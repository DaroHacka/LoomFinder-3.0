import json
import sys
from pathlib import Path

COOKIE_PATH = Path.home() / ".loomfinder" / "cookies.json"


def debug(msg):
    print(f"[debug login] {msg}", file=sys.stderr)


async def login(email: str, password: str) -> dict:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        debug("navigating to login page")
        await page.goto(
            "https://archive.org/login",
            wait_until="networkidle",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        await page.fill("#email-input", email)
        await page.fill("#password-input", password)
        await page.check("#remember-input")
        await page.keyboard.press("Enter")

        try:
            await page.wait_for_url("https://archive.org/", timeout=20000)
            debug("login successful")
        except Exception as e:
            debug(f"login failed: {e}")
            await browser.close()
            return {}

        cookies = await context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}

        COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_PATH.write_text(json.dumps(cookie_dict, indent=2))
        debug(f"saved {len(cookie_dict)} cookies to {COOKIE_PATH}")

        await browser.close()
        return cookie_dict


def _normalise_cookies(data):
    if isinstance(data, list):
        return {c["name"]: c["value"] for c in data if "name" in c and "value" in c}
    if isinstance(data, dict):
        return data
    return {}


async def load_or_login(config) -> dict:
    email = config.get("internet_archive", {}).get("email")
    password = config.get("internet_archive", {}).get("password")

    # Check saved cookies first — works regardless of config credentials
    if COOKIE_PATH.exists():
        try:
            raw = json.loads(COOKIE_PATH.read_text())
            cookies = _normalise_cookies(raw)
            if "logged-in-sig" in cookies and "logged-in-user" in cookies:
                debug(f"loaded {len(cookies)} saved cookies")
                return cookies
        except Exception as e:
            debug(f"error loading cookies: {e}")

    if not email or not password:
        debug("no credentials in config and no valid cookies")
        return {}

    return await login(email, password)
