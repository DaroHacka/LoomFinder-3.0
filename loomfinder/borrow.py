import sys

import aiohttp

from .login import load_or_login
from .random_selection import extract_segment

LOAN_URL = "https://archive.org/services/loans/loan/"
AVAILABILITY_URL = "https://archive.org/services/availability"


def debug(msg):
    print(f"[debug borrow] {msg}", file=sys.stderr)


def _meta(d):
    inner = d.get("metadata")
    return inner if isinstance(inner, dict) else d


def is_borrowable(metadata, identifier=""):
    if not metadata:
        debug(f"{identifier}: no metadata")
        return False
    m = _meta(metadata)
    if m.get("print-disabled-only") == "true":
        debug(f"{identifier}: print-disabled-only")
        return False
    if not m.get("borrow_url"):
        debug(f"{identifier}: no borrow_url")
        return False
    debug(f"{identifier}: is borrowable")
    return True


async def return_book(session, identifier):
    url = f"{LOAN_URL}?action=return_loan&identifier={identifier}"
    try:
        async with session.post(url, timeout=10) as resp:
            return resp.status == 200
    except:
        return False


def _make_pages_for(metadata):
    m = _meta(metadata)
    image_count = int(m.get("imagecount", 0))
    if image_count <= 30:
        return None
    max_page = image_count - 1
    num = min(15, max_page - 20)
    if num < 1:
        return None
    import random
    return sorted(random.sample(range(20, max_page + 1), num))


async def borrow_and_extract(identifier, metadata, config, tiers=None):
    cookies = await load_or_login(config)
    if not cookies:
        debug(f"{identifier}: no auth cookies")
        return None

    pages = _make_pages_for(metadata)
    if not pages:
        debug(f"{identifier}: not enough pages")
        return None

    debug(f"{identifier}: borrowing and extracting {len(pages)} target pages")

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=2,
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        )
        cookie_list = [
            {"name": k, "value": v, "domain": ".archive.org", "path": "/"}
            for k, v in cookies.items() if v
        ]
        await context.add_cookies(cookie_list)

        page = await context.new_page()

        # Step 1 — borrow the book if needed
        await page.goto(
            f"https://archive.org/details/{identifier}",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        borrow_btn = await page.query_selector("button:has-text('Borrow')")
        if borrow_btn:
            debug(f"{identifier}: clicking Borrow")
            try:
                await borrow_btn.click(force=True, timeout=10000)
            except Exception as e:
                debug(f"{identifier}: borrow click {e}, trying dispatchEvent")
                try:
                    await borrow_btn.dispatchEvent("click")
                except Exception:
                    pass
            await page.wait_for_timeout(3000)
            debug(f"{identifier}: borrow step done")
        else:
            debug(f"{identifier}: no borrow button, may be open access")

        # Step 2 — open theater view
        await page.goto(
            f"https://archive.org/details/{identifier}?view=theater",
            wait_until="networkidle",
            timeout=60000,
        )

        try:
            await page.wait_for_selector("#BookReader", timeout=30000)
        except Exception:
            debug(f"{identifier}: BookReader not found")
            await browser.close()
            return None

        await page.wait_for_timeout(5000)

        # Step 3 — hybrid capture: jumpToPage + ArrowRight + selector fallbacks
        image_data = []
        target_count = min(len(pages), 5)
        current_page = 0

        # Advance past front matter
        debug(f"{identifier}: advancing 25 pages past front matter")
        for _ in range(25):
            await page.keyboard.press("ArrowRight")
            await page.wait_for_timeout(200)
        current_page = 25
        await page.wait_for_timeout(1000)

        # Check if BookReader JS API is available
        has_api = await page.evaluate("typeof br !== 'undefined' && br !== null")
        debug(f"{identifier}: BookReader API available: {has_api}")

        CAPTURE_SELECTORS = [
            "img.BRpageimage",
            "img.br-page-image",
            "canvas.BRpage",
            "div.BRpageimage img",
            "#BookReader img",
        ]

        async def try_capture():
            for sel in CAPTURE_SELECTORS:
                els = await page.query_selector_all(sel)
                for el in els:
                    try:
                        src = ""
                        if sel.startswith("img") or "img" in sel:
                            src = await el.get_attribute("src") or ""
                            if src and not src.startswith("blob:"):
                                continue
                        box = await el.bounding_box()
                        if not box or box["width"] < 120 or box["height"] < 120:
                            continue
                        data = await el.screenshot()
                        if len(data) > 500:
                            return data, sel
                    except Exception:
                        continue
            return None, None

        for target in pages:
            if len(image_data) >= target_count:
                break

            # Try jumpToPage first
            jumped = False
            if has_api:
                try:
                    await page.evaluate(f"br && br.jumpToPage({target})")
                    await page.wait_for_timeout(3000)
                    current_page = target
                    jumped = True
                except Exception:
                    pass

            # Fallback: ArrowRight step
            if not jumped:
                steps = target - current_page
                if steps > 0:
                    for _ in range(min(steps, 50)):
                        await page.keyboard.press("ArrowRight")
                        await page.wait_for_timeout(150)
                    await page.wait_for_timeout(2000)
                    current_page = target

            # Try priority element selectors
            data, used_sel = await try_capture()
            if data:
                image_data.append(data)
                debug(f"{identifier}: page {target} via {used_sel} ({len(data)} bytes)")
                continue

            # Ultimate fallback: capture the entire BookReader container
            try:
                br = await page.query_selector("#BookReader")
                if br:
                    data = await br.screenshot()
                    if len(data) > 500:
                        image_data.append(data)
                        debug(f"{identifier}: page {target} via #BookReader fallback ({len(data)} bytes)")
                        continue
            except Exception:
                pass

            debug(f"{identifier}: page {target}: all capture methods failed")

        await browser.close()

    if not image_data:
        debug(f"{identifier}: no pages captured")
        return None

    # Step 3 — OCR
    from .ocr import ocr_image

    texts = []
    for data in image_data:
        text = ocr_image(data)
        if text:
            texts.append(text)
    if not texts:
        debug(f"{identifier}: OCR produced no text")
        return None

    combined = "\n\n".join(texts)
    result = extract_segment(combined)

    try:
        async with aiohttp.ClientSession() as session:
            await return_book(session, identifier)
    except:
        pass

    return result
