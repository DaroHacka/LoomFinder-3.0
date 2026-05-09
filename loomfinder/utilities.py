import json
import asyncio
import os
import random
import sys
import tomllib
from pathlib import Path

from diskcache import Cache

CACHE_DIR = os.path.expanduser("~/.cache/loomfinder")
cache = Cache(CACHE_DIR)


class TimeoutExpired(Exception):
    pass

def load_login_cookies():
    path = Path.home() / ".loomfinder" / "cookies.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}

def load_config(config_path=None):
    if config_path:
        paths = [Path(config_path)]
    else:
        _pkg = Path(__file__).resolve().parent.parent
        paths = [
            Path.cwd() / "config.toml",
            Path.home() / ".config" / "loomfinder" / "config.toml",
            _pkg / "config.toml",
        ]

    for path in paths:
        if path.exists():
            with open(path, "rb") as f:
                return tomllib.load(f)
    return {}


def get_s3_keys(config):
    ia_config = config.get("internet_archive", {})

    access = ia_config.get("s3_access") or ia_config.get("access")
    secret = ia_config.get("s3_secret") or ia_config.get("secret")
    if access and secret:
        return access, secret, {}

    email = ia_config.get("email")
    password = ia_config.get("password")
    if email and password:
        from internetarchive.config import get_auth_config

        auth = get_auth_config(email, password)
        return (
            auth["s3"]["access"],
            auth["s3"]["secret"],
            auth.get("cookies", {}),
        )

    ini = os.path.expanduser("~/.config/ia.ini")
    if os.path.exists(ini):
        import configparser

        cfg = configparser.ConfigParser()
        cfg.read(ini)
        if cfg.has_section("s3"):
            access = cfg.get("s3", "access", fallback=None)
            secret = cfg.get("s3", "secret", fallback=None)
        else:
            access = secret = None

        cookies = {}
        if cfg.has_section("cookies"):
            cookies = {
                "logged-in-user": cfg.get("cookies", "logged-in-user", fallback=None),
                "logged-in-sig": cfg.get("cookies", "logged-in-sig", fallback=None),
            }

        if access and secret:
            return access, secret, cookies

    return None, None, {}


def configure_ia(config):
    access, secret, _ = get_s3_keys(config)
    return bool(access and secret)


async def input_with_timeout(prompt, timeout=10):
    print(prompt, end="", flush=True)
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(None, lambda: sys.stdin.readline().strip())
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        future.cancel()
        raise TimeoutExpired


def save_to_file(content, filename="loomfinder_samples.txt"):
    with open(filename, "a") as f:
        f.write(content + "\n\n")


def save_author(author, filename="Authors_list.txt"):
    try:
        with open(filename, "r") as f:
            authors = f.readlines()
        author_names = {name.strip().lower() for name in authors}
        variations = {" ".join(a.split()[::-1]).lower() for a in author_names}
        if author.lower() not in author_names and author.lower() not in variations:
            with open(filename, "a") as f:
                f.write(author + "\n")
    except FileNotFoundError:
        with open(filename, "w") as f:
            f.write(author + "\n")


def get_random_saved_author(filename="Authors_list.txt"):
    try:
        with open(filename) as f:
            authors = f.readlines()
        return random.choice(authors).strip() if authors else None
    except FileNotFoundError:
        return None


def get_cached_metadata(identifier):
    key = f"metadata:{identifier}"
    return cache.get(key)


def set_cached_metadata(identifier, metadata):
    key = f"metadata:{identifier}"
    cache.set(key, metadata, expire=3600)
