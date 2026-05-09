# **LoomFinder 3.0 — Borrow the Internet Archive**

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
cp config.example.toml config.toml
```

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

Without `--borrow`, LoomFinder tries borrowing first, then falls back to open‑access `.txt` downloads.
With `--borrow`, it only uses the Playwright path.

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
| `--borrow` | Borrow-only mode |
| `--save` | Save snippet to file |
| `--tier-*` | Force a specific extraction tier |
| `--lang` | Language filter |

---

## Examples

```bash
loomfinder a:"Virginia Woolf" --borrow
loomfinder g:fiction d:1990-2000
loomfinder s:neuroscience d:2010-2024 --borrow
loomfinder prose
loomfinder a:"Cormac McCarthy" --save
```

---

## How It Works (Narrative Version)

1. **Search** — LoomFinder builds an Archive query and finds borrowable books.
2. **Borrow** — Playwright opens the book page and clicks "Borrow".
3. **Render** — The BookReader loads in theater mode.
4. **Navigate** — LoomFinder jumps to interior pages using keyboard events.
5. **Capture** — It screenshots the `<img.BRpageimage>` element at 2× resolution.
6. **OCR** — Tesseract converts the screenshot into text.
7. **Extract** — A coherent snippet is selected.
8. **Return** — The book is returned to the Archive.

It's the same flow a human follows — automated, fast, and reliable.

---

## Prose Mode

When LoomFinder finds an author you like, it asks if you want to save them.
Saved authors go into `Authors_list.txt`.
Then:

```bash
loomfinder prose
```

gives you a random snippet from your personal reading universe.
