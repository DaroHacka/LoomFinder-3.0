import asyncio
import math
import random
from urllib.parse import quote

import aiohttp

from .random_selection import get_weighted_random_choice
from .utilities import get_cached_metadata, set_cached_metadata, cache

ROWS_PER_PAGE = 1000


def build_query_string(title=None, genre=None, anything=None, author=None,
                       subject=None, start_date=None, end_date=None,
                        language="eng", page=1):
    query = [f"mediatype:texts", f"language:({language})"]

    if not any([title, genre, anything, author, subject, start_date, end_date]):
        subject = get_weighted_random_choice()
        query.append(f"subject:({subject})")
    else:
        if title:
            query.append(f"title:({title})")
        if genre:
            query.append(f"subject:({genre})")
        if anything:
            query.append(f"({anything})")
        if author:
            query.append(f"creator:({author})")
        if subject:
            query.append(f"subject:({subject})")
        if start_date and end_date:
            query.append(f"date:[{start_date}-01-01 TO {end_date}-12-31]")

    query_string = " AND ".join(query)
    encoded_qs = quote(query_string, safe="():[]")
    return (
        f"https://archive.org/advancedsearch.php"
        f"?q={encoded_qs}&fl[]=identifier&fl[]=title&fl[]=creator"
        f"&rows={ROWS_PER_PAGE}&page={page}&output=json"
    )


async def fetch_books(session, query_url, semaphore, max_retries=3):
    for attempt in range(max_retries):
        try:
            async with semaphore:
                async with session.get(query_url, timeout=30) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        response = data.get("response", {})
                        books = response.get("docs", [])
                        num_found = response.get("numFound", 0)
                        return books, num_found
                    elif resp.status == 403:
                        pass
                    elif resp.status == 429:
                        pass
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass

        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt)

    return None, 0


async def fetch_metadata(session, identifier, semaphore):
    cached = get_cached_metadata(identifier)
    if cached:
        return cached

    url = f"https://archive.org/metadata/{identifier}"
    for attempt in range(3):
        try:
            async with semaphore:
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        metadata = await resp.json()
                        set_cached_metadata(identifier, metadata)
                        return metadata
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        if attempt < 2:
            await asyncio.sleep(2 ** attempt)

    return None
