# **LoomFinder 3.0 — *Discover random snippets from books on the Internet Archive***

Discover random snippets from books on the Internet Archive directly in your terminal — including modern, in‑copyright books — by borrowing them through your own Internet Archive account exactly as a normal user would. LoomFinder 3.0 doesn't bypass restrictions or access anything you aren't entitled to; it simply automates the same borrow‑and‑read workflow you already perform manually, making exploration faster, smoother, and more fun.

LoomFinder 2.0 was a fun experiment: it scraped open‑access texts, mostly classics. But the moment you searched for Stephen King, Cormac McCarthy, or any modern author, you hit a wall. The Archive would show the book, but the text was locked behind its borrowing system.

LoomFinder 3.0 breaks through that wall.

It uses a real browser (via Playwright) to log into your Internet Archive account, borrow the book exactly as a human would, render the pages, and OCR them into text — all in a perfectly legal way through your own subscription and borrowing rights. And because Playwright runs in headless mode, you don't need a graphical Linux environment at all; the entire pipeline works from a terminal‑only server just as smoothly as on a desktop. Suddenly, the Archive's modern library becomes searchable, explorable, and alive.

```
log in to your Internet Archive profile
→ fetch a random book based on your search
→ borrow the book if borrowing is required
→ open the BookReader and skip the front matter
→ screenshot a few interior pages
→ send the images to OCR
→ print a clean text snippet directly in your terminal
```

---

> **⚠️ Pay attention if you are an active subscriber:**  
> Don't use this tool if you don't want your account to be temporarily blocked from loaning new books. Internet Archive appears to impose a lending limit — likely 5–10 books per day per account. If you don't care about the limit, LoomFinder auto-returns each book once the snippet is captured.  
>
> I didn't know about this restriction when I started the project, and it changes things. With a hard cap on daily borrows, the tool can't fully deliver on its promise of being a freely explorable library. That said, I still like the concept — building the screenshot-and-OCR pipeline, reverse-engineering the BookReader, and getting it working end-to-end was genuinely fun. It works, just for a limited number of loans per day.  
>
> Use `--keep` to hold onto a book for the full 1-hour loan period and generate multiple snippets.
> Use `--borrowed N` to reference a previously kept book by index.

---

## Two Modes of Operation

LoomFinder has two independent extraction paths:

| Mode | Flag | Source | Content type |
|------|------|--------|-------------|
| **Open-access** (default) | *(no flag)* | `.txt` download | Public-domain / free texts |
| **Borrow** | `--borrow` | Playwright screenshot + OCR | Any borrowable book |

Without `--borrow`, LoomFinder **only searches open-access books** — borrow-only books are automatically excluded from search results. This preserves your IA lending quota for when you really need it.

With `--borrow`, you opt into the lending system explicitly.

---

## Improvements to the Open-Access (2.0) Path

The core functionality — searching and extracting snippets from open-access books — has been significantly upgraded in 3.0:

### Smarter Snippet Selection
Instead of picking one random text chunk and hoping for the best, LoomFinder now **samples 15 random regions** across the entire text, scores each one for quality (ratio of real words to OCR noise/symbols), and returns the **best one** that passes the quality threshold. This means cleaner, more readable snippets every time — truck manuals and table-heavy texts are reliably filtered out.

### More Accurate Author Matching
Author names with middle initials (`Howard R. Garis`, `T. S. Eliot`) now match correctly, while still rejecting false positives (`Stephen King` vs `Stephen F. King`). The tokenizer normalizes periods consistently on both the search term and the book metadata.

### Faster Failure on Locked Books
If a book's `.txt` file requires authentication (401/403), LoomFinder breaks immediately instead of retrying 3 times with backoff. Combined with the search filter that excludes borrow-only books by default, this means no more wasted time on inaccessible texts.

### Borrow-Only Books Filtered from Search
Without `--borrow`, the search query automatically excludes collections `printdisabled`, `lendinglibrary`, and `inlibrary` — the collections where IA stores borrow-only books. Only genuine open-access books appear in results.

### Authenticated Downloads
When you're logged into your IA account (via cookies), those session cookies are passed to the txt downloader. Some restricted `.txt` files become accessible.

## Borrow Path Upgrades

### Lending Limit Detection
If IA rejects the borrow (daily limit exceeded, account blocked), LoomFinder detects the error message on the page and reports "borrowing limit reached" instead of silently extracting preview-mode garbage.

### 12-Hour Cooldown
When the lending limit is hit, a timestamp is saved. LoomFinder won't attempt to borrow again for 12 hours — it falls back to open-access downloads during that period.

### Keep Books Borrowed (`--keep`)
Instead of returning the book immediately after extracting one snippet, `--keep` holds onto it for the full 1-hour loan period. The book is tracked in `~/.loomfinder/kept_books.json` so you can generate more snippets.

### Extract from Kept Books (`--borrowed N`)
Once a book is kept, reference it by index:
```bash
loomfinder --borrowed 1
```
This opens the already-borrowed book directly (no borrow click needed), captures a new random page, and returns another snippet. You can do this unlimited times during the 1-hour loan window.

### Configurable Borrow Limit
Set `max_borrows` in `config.toml` (default: 5) to cap borrow attempts per run and avoid hitting IA's daily limit.

---

## Technical Details of the Screenshot Capture

LoomFinder 3.0 captures page images using Playwright's element‑level screenshot API:

- **`el.screenshot()`** — captures the rendered `<img.BRpageimage>` DOM element exactly as the browser displays it
- **Format**: PNG (Playwright default), returned as Python bytes in memory
- **Resolution**:
  - Viewport: 1920×1080
  - `device_scale_factor=2` → effective buffer ~3840×2160
  - Each page image ends up around 2400×3600px effective resolution
- The images are never written to disk. They flow directly:

```
el.screenshot() → ocr_image() → Tesseract → text snippet
```

This is necessary because the BookReaderPreview API does not serve real images. It returns encrypted/obfuscated binary blobs that only the browser's JavaScript can decrypt and render. LoomFinder screenshots the final rendered `<img>` element — the only point where the page exists in a usable visual form.

---

## Why 3.0 Exists — The Story

The Internet Archive doesn't serve book pages in a single format. It uses different methods:

So I had to test with different new tiers but with very low success until I came up with the idea of screenshotting the page and OCR them.

- **Tier G** — IIIF manifests (open-access only)
- **Tier F** — direct JPEGs (open-access only)
- **Tier C/E/D** — BookReaderPreview (borrow‑only, encrypted, browser‑only)

LoomFinder 2.0 lived entirely in Tier G/F.
Modern books live entirely in Tier C/E/D.

We tried everything to break into those tiers:

- Direct loan API calls → **400/401 errors**
- Reverse‑engineering BookReaderPreview → **encrypted blobs**
- Canvas extraction → **BookReader no longer uses `<canvas>`**
- Response interception → **useless, data is obfuscated**

The only thing that worked?

**Let the browser do the work.**
Borrow the book.
Render the page.
Screenshot the `<img.BRpageimage>` element.
OCR it.
Extract a snippet.

That's LoomFinder 3.0.

---

## What You Get Now

- **LoomFinder 2.0:** Only public‑domain classics
- **LoomFinder 3.0:** Anything you can borrow on the Internet Archive
  - Modern fiction
  - Academic texts
  - Niche publications
  - Out‑of‑print books
  - Anything behind the "Borrow for 1 hour / 14 days" button

If the Archive has it and you can borrow it, LoomFinder can extract a snippet.

---

## Authentication

LoomFinder supports two ways to authenticate.
You only need one.

---

### Method A — Auto‑Login (Recommended)

Add your IA credentials to `config.toml`:

```toml
[internet_archive]
email = "your.email@example.com"
password = "your_password"
```

On first run, LoomFinder:

1. Opens a real browser
2. Logs into archive.org
3. Saves your session cookies to `~/.loomfinder/cookies.json`
4. Reuses them automatically

No manual steps. No repeated logins.

---

### Method B — Manual Cookie Export (More Robust)

If you prefer not to store your password:

1. Log into archive.org in your browser
2. Export cookies using a browser extension
3. Paste them into:

```
~/.loomfinder/cookies.json
```

4. Convert them:

```bash
python3 -m loomfinder.convert_cookies
```

This transforms the raw cookie array into LoomFinder's `{name: value}` format.

You only need to re-export when your IA session expires.

---

## Installation

### Requirements

- Python 3.11+
- Tesseract OCR
- Playwright Chromium (installed automatically)

### Automated Install

```bash
chmod +x install.sh
./install.sh
```

### Manual Install

```bash
git clone https://github.com/DaroHacka/LoomFinder-3.0.git
cd LoomFinder-3.0

sudo apt install tesseract-ocr libtesseract-dev
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium

pip install -e .

### Configuration

```bash
cp config.example.toml config.toml
```

Then edit `config.toml` with your IA credentials (or export cookies manually — see Authentication section). The file `.gitignore` excludes `config.toml` so your credentials can never be accidentally committed. The `config.example.toml` serves as a template for new users.

---

## Usage

```bash
loomfinder a:"Emily Bronte"
loomfinder g:poetry x:nature
loomfinder s:neuroscience d:2010-2024 --borrow
```

### Borrow‑Only Mode

```bash
loomfinder --borrow a:"Stephen King"
```

Without `--borrow`, LoomFinder **only searches open-access books** (borrow-only books are excluded from search results) and downloads `.txt` files directly via aiohttp.

With `--borrow`, it uses the Playwright screenshot + OCR path to capture pages from borrowable books. Use this only when you're willing to consume one of your daily IA lending slots.

---

## Flags

| Flag | Meaning |
|------|---------|
| `a:` | Author |
| `t:` | Title |
| `g:` | Genre |
| `s:` | Subject |
| `d:` | Date or range |
| `x:` | Keyword |
| `prose` | Random saved author |

## Options

| Option | Description |
|--------|-------------|
| `--borrow` | Borrow-only mode: skip txt download fallback |
| `--keep` | Keep book borrowed after extraction (don't return) |
| `--borrowed N` | Extract from N-th kept book (1-10) |
| `--save` | Save snippet to `loomfinder_samples.txt` |
| `--list-genres` | List available genres |
| `--list-subjects` | List available subjects |
| `--list-journals` | List available journals and magazines |
| `--config PATH` | Path to custom config file |
| `--lang CODE` | Language filter (ISO 639-2/B, e.g. `eng`, `fre`, `ger`) |
| `--tier-g` | Force Tier G (IIIF manifest) |
| `--tier-f` | Force Tier F (direct page JPEGs) |
| `--tier-c` | Force Tier C (BookReaderPreview direct fetch) |
| `--tier-e` | Force Tier E (Playwright canvas extraction) |
| `--tier-d` | Force Tier D (Playwright screenshot) |

---

## Examples

```bash
loomfinder a:"Virginia Woolf" --borrow
loomfinder g:fiction d:1990-2000
loomfinder s:neuroscience d:2010-2024 --borrow
loomfinder prose
loomfinder a:"Cormac McCarthy" --save
loomfinder a:"Howard R. Garis"       # open-access, txt download
loomfinder a:"Stephen King" --borrow --keep   # borrow + keep for 1 hour
loomfinder --borrowed 1                       # another snippet from kept book
```

---

## How It Works

LoomFinder has two independent extraction pipelines:

**Open-access path** (default, no `--borrow`):
1. **Search** — Builds an Archive query that excludes borrow-only books (`NOT collection:printdisabled AND NOT collection:lendinglibrary`)
2. **Fetch** — Gets book metadata and finds the `.txt` download URL
3. **Download** — Downloads the plain text file (with your IA session cookies for auth)
4. **Score + Extract** — Samples 15 random regions, scores each for quality, picks the best one
5. **Display** — Prints the snippet with title, author, year, and URL

**Borrow path** (`--borrow`):
1. **Search** — Builds an Archive query that includes all books (no collection filters)
2. **Borrow** — Playwright opens the book page and clicks "Borrow"
3. **Render** — The BookReader loads in theater mode
4. **Navigate** — Jumps to interior pages using keyboard events
5. **Capture** — Screenshots the `<img.BRpageimage>` element at 2× resolution
6. **OCR** — Tesseract converts the screenshot into text
7. **Extract** — A coherent snippet is selected from the OCR output
8. **Return or Keep** — Returns the book automatically, or keeps it if `--keep` is set

---

## Prose Mode

When LoomFinder finds an author you like, it asks if you want to save them.
Saved authors go into `Authors_list.txt`.
Then:

```bash
loomfinder prose
```

gives you a random snippet from your personal reading universe.
