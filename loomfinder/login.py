import json
from datetime import datetime, timedelta
import sys
from pathlib import Path

COOKIE_PATH = Path.home() / ".loomfinder" / "cookies.json"
KEPT_PATH = Path.home() / ".loomfinder" / "kept_books.json"


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


async def load_or_login(config) -> dict:
    email = config.get("internet_archive", {}).get("email")
    password = config.get("internet_archive", {}).get("password")

    if not email or not password:
        debug("no credentials in config")
        return {}

    if COOKIE_PATH.exists():
        try:
            cookies = json.loads(COOKIE_PATH.read_text())
            if "logged-in-sig" in cookies and "logged-in-user" in cookies:
                debug(f"loaded {len(cookies)} saved cookies")
                return cookies
        except Exception as e:
            debug(f"error loading cookies: {e}")

    return await login(email, password)


def get_kept_books():
    if not KEPT_PATH.exists():
        return []
    try:
        data = json.loads(KEPT_PATH.read_text())
        now = datetime.now()
        return [b for b in data if datetime.fromisoformat(b["expires_at"]) > now]
    except Exception:
        return []


def track_kept_book(identifier, title):
    books = get_kept_books()
    books.append({
        "identifier": identifier,
        "title": title,
        "borrowed_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),
    })
    KEPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEPT_PATH.write_text(json.dumps(books, indent=2))


def remove_kept_book(identifier):
    books = get_kept_books()
    books = [b for b in books if b["identifier"] != identifier]
    KEPT_PATH.write_text(json.dumps(books, indent=2))


LENDING_LIMIT_PATH = Path.home() / ".loomfinder" / "lending_limit.txt"


def is_lending_blocked():
    if not LENDING_LIMIT_PATH.exists():
        return False
    try:
        blocked_at = datetime.fromisoformat(LENDING_LIMIT_PATH.read_text().strip())
        return datetime.now() - blocked_at < timedelta(hours=12)
    except Exception:
        return False


def mark_lending_limit():
    LENDING_LIMIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    LENDING_LIMIT_PATH.write_text(datetime.now().isoformat())


def clear_lending_limit():
    if LENDING_LIMIT_PATH.exists():
        LENDING_LIMIT_PATH.unlink()
