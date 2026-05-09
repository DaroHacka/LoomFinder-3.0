import asyncio
import base64
import io
import random
import re
import sys
import urllib.parse

import aiohttp

from .ocr import ocr_image
from .random_selection import extract_segment

def debug(msg):
    print(f"[debug tiers] {msg}", file=sys.stderr)


def _meta(d):
    inner = d.get("metadata")
    return inner if isinstance(inner, dict) else d


def _make_pages(metadata):
    m = _meta(metadata)
    image_count = int(m.get("imagecount", 0))
    if image_count <= 30:
        return None, 0
    max_page = image_count - 1
    num = min(15, max_page - 20)
    if num < 1:
        return None, 0
    pages = sorted(random.sample(range(20, max_page + 1), num))
    return pages, image_count


def _ocr_all(image_data_list):
    texts = []
    for data in image_data_list:
        text = ocr_image(data)
        if text:
            texts.append(text)
    if not texts:
        return None
    combined = "\n\n".join(texts)
    return extract_segment(combined)


# ─── Tier G: IIIF Manifest ──────────────────────────────────────────────

async def tier_g(identifier, pages, session):
    """Try IIIF manifest for direct page image URLs."""
    url = f"https://iiif.archivelab.org/iiif/{identifier}/manifest.json"
    try:
        async with session.get(url, ssl=False, timeout=15) as resp:
            if resp.status != 200:
                debug(f"tier-g {identifier}: IIIF HTTP {resp.status}")
                return None
            manifest = await resp.json()
    except Exception as e:
        debug(f"tier-g {identifier}: IIIF error {e}")
        return None

    canvases = manifest.get("sequences", [{}])[0].get("canvases", [])
    if not canvases:
        debug(f"tier-g {identifier}: no canvases in manifest")
        return None

    image_data = []
    for p in pages:
        if p >= len(canvases):
            continue
        img_info = canvases[p].get("images", [{}])[0].get("resource", {})
        service_id = img_info.get("service", {}).get("@id", "")
        if not service_id:
            continue
        img_url = f"{service_id}/full/full/0/default.jpg"
        try:
            async with session.get(img_url, ssl=False, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 500:
                        image_data.append(data)
        except:
            pass

    if image_data:
        debug(f"tier-g {identifier}: got {len(image_data)} pages")
        return _ocr_all(image_data)
    return None


# ─── Tier F: Direct Page JPEGs ─────────────────────────────────────────

async def tier_f(identifier, pages, session):
    """Try direct page JPEGs from archive.org/download."""
    image_data = []
    for p in pages:
        url = f"https://archive.org/download/{identifier}/page/n{p}.jpg"
        try:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 500:
                        image_data.append(data)
                    else:
                        debug(f"tier-f {identifier}: page {p} too small ({len(data)} bytes)")
                else:
                    debug(f"tier-f {identifier}: page {p} HTTP {resp.status}")
        except Exception as e:
            debug(f"tier-f {identifier}: page {p} error {e}")
            break

    if image_data:
        debug(f"tier-f {identifier}: got {len(image_data)} pages from direct JPEG")
        return _ocr_all(image_data)
    return None


# ─── Tier E: Playwright canvas data extraction ──────────────────────────

async def tier_e(identifier, pages, cookies):
    """Open BookReader in Playwright, extract canvas.toDataURL() pixels."""
    from playwright.async_api import async_playwright

    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items() if v)

    image_data = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            extra_http_headers={"Cookie": cookie_str} if cookie_str else {},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        )
        p = await context.new_page()

        url = f"https://archive.org/details/{identifier}?view=theater"
        debug(f"tier-e {identifier}: opening {url}")
        await p.goto(url, wait_until="domcontentloaded", timeout=60000)

        try:
            await p.wait_for_selector("#BookReader", timeout=30000)
        except Exception:
            debug("tier-e: BookReader element not found")
            await browser.close()
            return None

        await p.wait_for_timeout(3000)

        for idx in pages:
            try:
                await p.evaluate(f"br && br.jumpToPage({idx})")
                await p.wait_for_timeout(2000)

                canvas_data = await p.evaluate("""() => {
                    const canvas = document.querySelector('canvas.BRpage');
                    if (!canvas) return null;
                    return canvas.toDataURL('image/png');
                }""")

                if canvas_data:
                    _, encoded = canvas_data.split(",", 1)
                    png = base64.b64decode(encoded)
                    if len(png) > 500:
                        image_data.append(png)
                        debug(f"tier-e {identifier}: page {idx} {len(png)} bytes")
            except Exception as e:
                debug(f"tier-e {identifier}: page {idx} error {e}")

        await browser.close()

    if image_data:
        debug(f"tier-e {identifier}: extracted {len(image_data)} pages from canvas")
        return _ocr_all(image_data)
    return None


# ─── Tier D: Playwright canvas screenshot ───────────────────────────────

async def tier_d(identifier, pages, cookies):
    """Open BookReader in Playwright, screenshot the canvas element."""
    from playwright.async_api import async_playwright

    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items() if v)

    image_data = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            extra_http_headers={"Cookie": cookie_str} if cookie_str else {},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        )
        p = await context.new_page()

        url = f"https://archive.org/details/{identifier}?view=theater"
        debug(f"tier-d {identifier}: opening {url}")
        await p.goto(url, wait_until="domcontentloaded", timeout=60000)

        try:
            await p.wait_for_selector("#BookReader", timeout=30000)
        except Exception:
            debug("tier-d: BookReader element not found")
            await browser.close()
            return None

        await p.wait_for_timeout(3000)

        for idx in pages:
            try:
                await p.evaluate(f"br && br.jumpToPage({idx})")
                await p.wait_for_timeout(2000)

                canvas = await p.query_selector("canvas.BRpage")
                if canvas:
                    data = await canvas.screenshot()
                    if len(data) > 500:
                        image_data.append(data)
                        debug(f"tier-d {identifier}: page {idx} {len(data)} bytes")
            except Exception as e:
                debug(f"tier-d {identifier}: page {idx} error {e}")

        await browser.close()

    if image_data:
        debug(f"tier-d {identifier}: got {len(image_data)} pages from screenshot")
        return _ocr_all(image_data)
    return None


# ─── Tier C: Playwright page image extraction ────────────────────────────


async def tier_c(identifier, pages, cookies):
    """Extract page images via Playwright from the BookReader IMG elements.

    The BookReader renders pages as IMG elements with blob: URLs.
    We take element screenshots after navigating with keyboard arrows.
    """
    from playwright.async_api import async_playwright

    sanitized = []
    for k, v in cookies.items():
        if not v:
            continue
        raw_value = v.split(";")[0].strip()
        if not raw_value:
            continue
        decoded = urllib.parse.unquote(raw_value)
        if not decoded:
            continue
        if any(c in decoded for c in '\r\n\t'):
            continue
        sanitized.append({"name": k, "value": decoded, "domain": "archive.org", "path": "/"})

    debug(f"tier-c {identifier}: {len(sanitized)} sanitized cookies")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        )
        if sanitized:
            await context.add_cookies(sanitized)

        page = await context.new_page()

        url = f"https://archive.org/details/{identifier}?view=theater"
        debug(f"tier-c {identifier}: opening {url}")
        await page.goto(url, wait_until="networkidle", timeout=60000)

        try:
            await page.wait_for_selector("#BookReader", timeout=30000)
        except Exception:
            debug(f"tier-c {identifier}: BookReader not found")
            await browser.close()
            return None

        await page.wait_for_timeout(5000)

        image_data = []
        seen_srcs = set()

        async def extract_visible_pages():
            nonlocal image_data, seen_srcs
            elements = await page.query_selector_all("img.BRpageimage")
            for el in elements:
                try:
                    src = await el.get_attribute("src") or ""
                    if src in seen_srcs:
                        continue
                    seen_srcs.add(src)
                    data = await el.screenshot()
                    if len(data) > 500:
                        image_data.append(data)
                        debug(f"tier-c {identifier}: extracted page ({len(data)} bytes)")
                except Exception:
                    pass

        target_count = min(len(pages), 10)

        for _ in range(80):
            if len(image_data) >= target_count:
                break
            await extract_visible_pages()
            await page.keyboard.press("ArrowRight")
            await page.wait_for_timeout(500)

        await extract_visible_pages()

        await browser.close()

    if image_data:
        debug(f"tier-c {identifier}: captured {len(image_data)} pages")
        return _ocr_all(image_data)
    return None


# ─── Runner ─────────────────────────────────────────────────────────────

async def run_tiers(identifier, metadata, config, tiers, cookies):
    """Run requested tiers in order. Returns segment string or None."""
    pages, _ = _make_pages(metadata)
    if not pages:
        debug(f"{identifier}: not enough pages")
        return None

    loop = asyncio.get_event_loop()
    for tier in tiers:
        debug(f"{identifier}: trying tier-{tier}...")
        try:
            if tier == "g":
                conn = aiohttp.TCPConnector(ssl=False)
                async with aiohttp.ClientSession(connector=conn) as s:
                    result = await tier_g(identifier, pages, s)

            elif tier == "f":
                async with aiohttp.ClientSession(
                    cookies={k: v for k, v in cookies.items() if v},
                ) as s:
                    result = await tier_f(identifier, pages, s)

            elif tier == "c":
                result = await tier_c(identifier, pages, cookies)

            elif tier == "e":
                # Playwright is sync-heavy, run in executor
                result = await loop.run_in_executor(
                    None, lambda: asyncio.run(tier_e(identifier, pages, cookies))
                )

            elif tier == "d":
                result = await loop.run_in_executor(
                    None, lambda: asyncio.run(tier_d(identifier, pages, cookies))
                )

            else:
                continue
        except Exception as e:
            debug(f"{identifier}: tier-{tier} exception: {e}")
            result = None

        if result:
            return result
        debug(f"{identifier}: tier-{tier} produced no result")

    return None
