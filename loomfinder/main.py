import argparse
import asyncio
import math
import os
import random
import re
import sys

import aiohttp
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .borrow import borrow_and_extract, extract_from_borrowed
from .categories import literature_genres, other_subjects, old_journals_and_magazines
from .login import get_kept_books, is_lending_blocked, mark_lending_limit, load_or_login
from .parsing import parse_parameters
from .queries import build_query_string, fetch_books, fetch_metadata
from .random_selection import extract_segment
from .utilities import (
    TimeoutExpired,
    get_random_saved_author,
    input_with_timeout,
    load_config,
    save_author,
    save_to_file,
)

console = Console()


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "LoomFinder: Discover random snippets from books "
            "on the Internet Archive."
        )
    )
    parser.add_argument(
        "params", nargs="*",
        help="Search parameters: [t:title] [g:genre] [x:anything] "
             "[a:author] [s:subject] [d:date]",
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Save the output to a file",
    )
    parser.add_argument(
        "--borrow", action="store_true",
        help="Borrow-only mode: skip txt download fallback",
    )
    parser.add_argument(
        "--keep", action="store_true",
        help="Keep book borrowed after extraction (don't return)",
    )
    parser.add_argument(
        "--borrowed", type=int, choices=range(1, 11), metavar="N",
        help="Extract from N-th kept book (1-10)",
    )
    parser.add_argument(
        "--list-genres", action="store_true",
        help="List available genres",
    )
    parser.add_argument(
        "--list-subjects", action="store_true",
        help="List available subjects",
    )
    parser.add_argument(
        "--list-journals", action="store_true",
        help="List available journals and magazines",
    )
    parser.add_argument(
        "--config", type=str,
        help="Path to config file",
    )
    parser.add_argument(
        "--lang", type=str, default=None,
        help="Language filter (ISO 639-2/B code, e.g. eng, fre, ger)",
    )
    parser.add_argument(
        "--tier-g", action="store_true",
        help="Only use Tier G (IIIF manifest)",
    )
    parser.add_argument(
        "--tier-f", action="store_true",
        help="Only use Tier F (direct page JPEGs)",
    )
    parser.add_argument(
        "--tier-c", action="store_true",
        help="Only use Tier C (BookReaderPreview direct fetch)",
    )
    parser.add_argument(
        "--tier-e", action="store_true",
        help="Only use Tier E (Playwright canvas extraction)",
    )
    parser.add_argument(
        "--tier-d", action="store_true",
        help="Only use Tier D (Playwright screenshot)",
    )
    return parser.parse_args()


_common_particles = {"de", "la", "von", "van", "di", "da", "del", "den", "der", "el", "le"}


def author_match_score(book, search_author):
    """Score how well a book's creator matches the search author.

    Treats the entire creator field as one entity. Rejects middle
    initials (single-letter extra tokens). Lower score = better match.

    Returns (match: bool, score: int).
    """
    if not search_author:
        return True, 0

    search_tokens = set(re.findall(r"\w+", search_author.lower()))
    creator = book.get("creator", "Unknown Author")

    if isinstance(creator, list):
        creator = ", ".join(creator)

    tokens = set(re.findall(r"\w+", creator.lower()))

    if not search_tokens.issubset(tokens):
        return False, 99

    extra = tokens - search_tokens
    extra_single = {t for t in extra if len(t) == 1}
    extra_multi = extra - extra_single

    if extra_single and not extra_multi:
        return False, 99

    score = 0
    if extra_multi:
        score += 20

    return True, score


def debug(msg):
    print(f"[debug main] {msg}", file=sys.stderr)


async def extract_text(session, identifier, config, semaphore, borrow_only=False, tiers=None, keep=False, borrow_state=None):
    metadata = await fetch_metadata(session, identifier, semaphore)
    if not metadata:
        debug(f"{identifier}: no metadata")
        return None

    files = metadata.get("files", [])

    borrow_ok = True
    if not borrow_only:
        debug(f"{identifier}: --borrow not set, skipping borrow")
        borrow_ok = False
    elif borrow_state and borrow_state["limit_hit"]:
        debug(f"{identifier}: lending limit was hit earlier, skipping borrow")
        borrow_ok = False
    elif borrow_state and borrow_state["count"] >= borrow_state["max"]:
        debug(f"{identifier}: max_borrows ({borrow_state['max']}) reached, skipping borrow")
        borrow_ok = False
    elif is_lending_blocked():
        debug(f"{identifier}: lending is in 12h cooldown, skipping borrow")
        borrow_ok = False

    if borrow_ok:
        debug(f"{identifier}: trying borrow_and_extract...")
        segment = await borrow_and_extract(identifier, metadata, config, tiers=tiers, keep=keep)

        if segment == "__LENDING_LIMIT__":
            debug(f"{identifier}: borrowing limit reached")
            mark_lending_limit()
            if borrow_state:
                borrow_state["limit_hit"] = True
            if borrow_only:
                return None
            borrow_ok = False
        elif segment:
            debug(f"{identifier}: borrow_and_extract succeeded")
            if borrow_state:
                borrow_state["count"] += 1
            return segment

    if borrow_only:
        debug(f"{identifier}: borrow failed and --borrow is set, skipping")
        return None

    debug(f"{identifier}: borrow failed, trying txt download")

    txt_files = [f for f in files if f.get("name", "").endswith(".txt")]
    if not txt_files:
        debug(f"{identifier}: no txt files in metadata")
        return None

    text_url = f"https://archive.org/download/{identifier}/{txt_files[0]['name']}"
    debug(f"{identifier}: downloading {text_url}")

    for attempt in range(3):
        try:
            async with semaphore:
                async with session.get(text_url, timeout=30) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        segment = extract_segment(text)
                        if segment:
                            debug(f"{identifier}: txt download succeeded")
                            return segment
                        debug(f"{identifier}: txt downloaded but failed quality check")
                    else:
                        debug(f"{identifier}: txt download HTTP {resp.status}")
                        if resp.status in (401, 403):
                            break
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            debug(f"{identifier}: txt download error: {e}")
        if attempt < 2:
            await asyncio.sleep(2 ** attempt)

    debug(f"{identifier}: all attempts exhausted")
    return None


async def _display_result(book_title, book_author, segment, url, args, book, book_date=""):
    title_styled = Text(book_title, style="bold cyan")
    author_line = f"by {book_author}" + (f" ({book_date})" if book_date else "")
    author_styled = Text(author_line, style="italic yellow")
    snippet_styled = Text(segment, style="white")

    panel = Panel(
        f"{title_styled}\n{author_styled}\n\n"
        f"{snippet_styled}\n\n"
        f"[dim]{url}[/dim]",
        title="[bold green]LoomFinder[/bold green]",
        border_style="green",
    )
    console.print(panel)

    if args.save:
        output = (
            f"Book Title: {book_title}\n"
            f"Author: {book_author}" + (f" ({book_date})" if book_date else "") + "\n"
            f"URL: {url}\n\n{segment}"
        )
        save_to_file(output)
        console.print("[green]Output saved to loomfinder_samples.txt[/green]")


async def main():
    args = parse_args()
    config = load_config(args.config)

    if args.lang is None:
        args.lang = config.get("loomfinder", {}).get("language", "eng")

    # Handle --borrowed N
    if args.borrowed is not None:
        kept = get_kept_books()
        if args.borrowed > len(kept):
            console.print(
                f"[red]No kept book #{args.borrowed}. "
                f"You have {len(kept)} kept book(s).[/red]"
            )
            return
        book = kept[args.borrowed - 1]
        identifier = book["identifier"]
        async with aiohttp.ClientSession() as session:
            metadata = await fetch_metadata(session, identifier, asyncio.Semaphore(1))
            if not metadata:
                console.print(f"[red]No metadata for kept book: {identifier}[/red]")
                return
            segment = await extract_from_borrowed(identifier, metadata, config)
            if segment:
                m = metadata.get("metadata", {})
                book_date = (m.get("date") or "")[:4] if m.get("date") else ""
                await _display_result(
                    book.get("title", identifier), "Unknown Author",
                    segment, f"https://archive.org/details/{identifier}",
                    args, None, book_date=book_date,
                )
            else:
                console.print("[red]Failed to extract from kept book.[/red]")
        return

    prose_mode = False
    if "prose" in args.params:
        prose_mode = True
        args.params.remove("prose")

    if args.list_genres:
        console.print("[bold]Available genres:[/bold]")
        for g in literature_genres:
            console.print(f"  {g}")
        return

    if args.list_subjects:
        console.print("[bold]Available subjects:[/bold]")
        for s in other_subjects:
            console.print(f"  {s}")
        return

    if args.list_journals:
        console.print("[bold]Available journals:[/bold]")
        for j in old_journals_and_magazines:
            console.print(f"  {j}")
        return

    params = args.params
    if prose_mode:
        author = get_random_saved_author()
        if not author:
            console.print(
                "[yellow]No saved authors found. Run without 'prose' "
                "to discover and save authors first.[/yellow]"
            )
            return
        params = [f"a:{author}"]

    title, genre, anything, author, subject, date = parse_parameters(params)
    start_date, end_date = None, None
    if date and "-" in date:
        start_date, end_date = date.split("-")

    # Build fallback plan: progressively relax the query
    query_plan = []
    base = (title, genre, anything, author, subject, start_date, end_date)
    query_plan.append(base)

    has_multi = sum(1 for x in [title, genre, anything, author, subject] if x) >= 2
    if has_multi:
        if genre:
            query_plan.append((title, None, anything, author, subject, start_date, end_date))
        if author and (genre or subject):
            query_plan.append((title, None, anything, author, None, None, None))
        if (genre or subject) and not author:
            query_plan.append((None, genre, None, None, subject, None, None))
        query_plan.append((None, None, None, None, None, None, None))

    tier_order = []
    for t in ["g", "f", "c", "e", "d"]:
        flag = getattr(args, f"tier_{t}", None)
        if flag:
            tier_order.append(t)
    if not tier_order:
        tier_order = ["g", "f", "c"]

    max_retries = config.get("loomfinder", {}).get("max_retries", 10)
    rate_limit = config.get("loomfinder", {}).get("rate_limit", 3)
    semaphore = asyncio.Semaphore(rate_limit)

    return_book = config.get("loomfinder", {}).get("return_book", True)
    keep = args.keep or not return_book
    borrow_only = args.borrow or args.keep
    max_borrows = config.get("loomfinder", {}).get("max_borrows", 5)
    borrow_state = {"count": 0, "max": max_borrows, "limit_hit": False}

    # Track total pages per level to avoid requesting empty pages
    total_pages_per_level = {}

    cookies = await load_or_login(config)
    connector = aiohttp.TCPConnector(limit=rate_limit + 2)
    async with aiohttp.ClientSession(connector=connector, cookies=cookies) as session:
        for attempt in range(max_retries):
            level = min(attempt // 2, len(query_plan) - 1)
            t, g, x, a, s, sd, ed = query_plan[level]
            is_random = not any([t, g, x, a, s, sd, ed])

            # Pick page: first attempt at each level = page 1, retries = random within bounds
            if level not in total_pages_per_level:
                page = 1
            else:
                max_page = total_pages_per_level[level]
                if max_page <= 1:
                    continue
                page = random.randint(2, min(max_page, 10 if is_random else 3))

            if attempt > 0:
                if level > 0 and attempt % 2 == 0:
                    labels = []
                    if a: labels.append(f"author:{a}")
                    if g: labels.append(f"genre:{g}")
                    if s: labels.append(f"subject:{s}")
                    if t: labels.append(f"title:{t}")
                    if not labels:
                        labels.append("random")
                    console.print(
                        f"[dim]Trying {', '.join(labels)}...[/dim]"
                    )
                else:
                    console.print(
                        f"[dim]Attempt {attempt + 1}/{max_retries}...[/dim]"
                    )

            query_url = build_query_string(
                title=t, genre=g, anything=x, author=a, subject=s,
                start_date=sd, end_date=ed,
                language=args.lang, page=page, borrow_only=borrow_only,
            )

            books, num_found = await fetch_books(session, query_url, semaphore)
            if num_found:
                total_pages_per_level[level] = math.ceil(num_found / 1000)
            if not books:
                continue

            valid = []
            for book in books:
                match, score = author_match_score(book, author)
                if match:
                    valid.append((score, random.random(), book))

            if not valid:
                continue

            valid.sort(key=lambda x: (x[0], x[1]))

            for _, _, book in valid[:20]:
                identifier = book.get("identifier")
                book_title = book.get("title", "Unknown Title")
                creator = book.get("creator", "Unknown Author")
                book_author = ", ".join(creator) if isinstance(creator, list) else creator

                if not identifier:
                    continue

                segment = await extract_text(
                    session, identifier, config, semaphore, borrow_only,
                    tiers=tier_order, keep=keep, borrow_state=borrow_state,
                )

                if segment:
                    url = f"https://archive.org/details/{identifier}"
                    book_date = book.get("date", "")[:4] if book.get("date") else ""
                    await _display_result(book_title, book_author, segment, url, args, book, book_date=book_date)

                    if (
                        not prose_mode
                        and book_author.lower() != "unknown author"
                    ):
                        save_timeout = config.get("loomfinder", {}).get(
                            "save_author_timeout", 10
                        )
                        try:
                            if save_timeout is None or save_timeout == 0:
                                choice = input(
                                    "Save author for 'prose' mode? (y/n): "
                                ).strip()
                            else:
                                choice = await input_with_timeout(
                                    "Save author for 'prose' mode? (y/n): ",
                                    timeout=save_timeout,
                                )
                        except TimeoutExpired:
                            console.print("\n[yellow]Timeout. Bye![/yellow]")
                            return

                        if choice and choice.lower() in ("yes", "y"):
                            save_author(book_author)
                            console.print("[green]Author saved[/green]")
                        elif choice and choice.lower() in ("no", "n"):
                            console.print("[dim]Author not saved[/dim]")

                    return

        console.print(
            "[red]Could not find a suitable book after "
            f"{max_retries} attempts.[/red]"
        )


def cli():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    cli()
