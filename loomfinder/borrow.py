import sys

from .login import load_or_login, track_kept_book
from .random_selection import extract_segment

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


async def _press_arrow_right(page, count, delay_ms=500):
    for _ in range(count):
        await page.keyboard.press("ArrowRight")
        await page.wait_for_timeout(delay_ms)


async def _advance_batch(page, identifier, label, count, per_press_ms=500, drain_ms=2000):
    debug(f"{identifier}: {label} {count} presses at {per_press_ms}ms")
    await _press_arrow_right(page, count, per_press_ms)
    await page.wait_for_timeout(drain_ms)


async def _try_capture(page, identifier, image_sizes):
    CAPTURE_SELECTORS = [
        "img.BRpageimage", "img.br-page-image", "canvas.BRpage",
        "div.BRpageimage img", "#BookReader img",
    ]
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
                    if image_sizes and len(data) == image_sizes[-1]:
                        debug(f"{identifier}: duplicate, skipping")
                        return None
                    debug(f"{identifier}: captured via {sel} ({len(data)} bytes)")
                    return data
            except Exception:
                continue
    br = await page.query_selector("#BookReader")
    if br:
        try:
            data = await br.screenshot()
            if len(data) > 500:
                if image_sizes and len(data) == image_sizes[-1]:
                    debug(f"{identifier}: duplicate via #BookReader, skipping")
                    return None
                debug(f"{identifier}: captured via #BookReader ({len(data)} bytes)")
                return data
        except Exception:
            pass
    return None



async def _capture_and_ocr(page, identifier, pages):
    CAPTURE_COUNT = 3

    await _advance_batch(page, identifier, "initial advance", 12, 600, 2000)
    await page.wait_for_timeout(3000)

    image_data = []
    image_sizes = []

    for i in range(CAPTURE_COUNT):
        data = await _try_capture(page, identifier, image_sizes)
        if data:
            image_data.append(data)
            image_sizes.append(len(data))
        if i < CAPTURE_COUNT - 1:
            await _advance_batch(page, identifier, f"inter-capture advance {i + 1}", 6, 600, 2000)

    if not image_data:
        debug(f"{identifier}: no pages captured")
        return None

    texts = []
    from .ocr import ocr_image
    for data in image_data:
        text = ocr_image(data)
        if text:
            texts.append(text)
    if not texts:
        debug(f"{identifier}: OCR produced no text")
        return None

    combined = "\n\n".join(texts)
    return extract_segment(combined)


async def borrow_and_extract(identifier, metadata, config, tiers=None, keep=False):
    cookies = await load_or_login(config)
    if not cookies:
        debug(f"{identifier}: no auth cookies")
        return None

    pages = _make_pages_for(metadata)
    if not pages:
        debug(f"{identifier}: not enough pages")
        return None

    debug(f"{identifier}: borrowing and extracting")

    email = config.get("internet_archive", {}).get("email")
    password = config.get("internet_archive", {}).get("password")
    theater_url = f"https://archive.org/details/{identifier}?view=theater"

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

        async def load_theater():
            await page.goto(theater_url, wait_until="networkidle", timeout=60000)
            try:
                await page.wait_for_selector("#BookReader", timeout=30000)
            except Exception:
                debug(f"{identifier}: BookReader not found")
                return False
            await page.wait_for_timeout(5000)
            return True

        if not await load_theater():
            await browser.close()
            return None

        logout_btn = await page.query_selector("button:has-text('Log In and Borrow')")
        if logout_btn:
            debug(f"{identifier}: session expired, re-logging in")
            if not email or not password:
                debug(f"{identifier}: no credentials for re-login")
                await browser.close()
                return None
            try:
                await page.goto("https://archive.org/login", wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)
                await page.fill("#email-input", email)
                await page.fill("#password-input", password)
                await page.check("#remember-input")
                await page.keyboard.press("Enter")
                await page.wait_for_url("https://archive.org/", timeout=20000)
                debug(f"{identifier}: re-login successful")
                from .login import save_cookies
                fresh_cookies = await context.cookies()
                save_cookies({c["name"]: c["value"] for c in fresh_cookies})
            except Exception as e:
                debug(f"{identifier}: re-login failed: {e}")
                await browser.close()
                return None
            if not await load_theater():
                await browser.close()
                return None

        borrow_btn = await page.query_selector("button:has-text('borrow')")
        if borrow_btn:
            debug(f"{identifier}: clicking Borrow in BookReader toolbar")
            try:
                await borrow_btn.click(timeout=10000)
                await page.wait_for_timeout(5000)
            except Exception as e:
                debug(f"{identifier}: borrow click failed: {e}")
            body_text = await page.text_content("body") or ""
            if "lending limit" in body_text.lower() or "lending error" in body_text.lower():
                debug(f"{identifier}: borrowing limit reached")
                await browser.close()
                return "__LENDING_LIMIT__"
            debug(f"{identifier}: borrow click done")
        else:
            debug(f"{identifier}: no borrow button found, may be open access or already borrowed")

        preview = await page.evaluate("""(() => {
            try { return typeof br !== 'undefined' && br !== null && br.brPreview === true; }
            catch(e) { return null; }
        })()""")
        debug(f"{identifier}: BookReader preview mode: {preview}")

        result = await _capture_and_ocr(page, identifier, pages)

        if result and not keep:
            try:
                return_btn = await page.query_selector("button:has-text('Return')")
                if return_btn:
                    await return_btn.click(timeout=10000)
                    await page.wait_for_timeout(2000)
                    debug(f"{identifier}: returned book")
            except Exception as e:
                debug(f"{identifier}: return click failed: {e}")

        await browser.close()

    if result and keep:
        m = _meta(metadata)
        title_str = m.get("title", identifier)
        track_kept_book(identifier, title_str)

    return result


async def extract_from_borrowed(identifier, metadata, config):
    cookies = await load_or_login(config)
    if not cookies:
        debug(f"{identifier}: no auth cookies")
        return None

    pages = _make_pages_for(metadata)
    if not pages:
        debug(f"{identifier}: not enough pages")
        return None

    debug(f"{identifier}: extracting from already-borrowed book")

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

        result = await _capture_and_ocr(page, identifier, pages)
        await browser.close()

    return result
