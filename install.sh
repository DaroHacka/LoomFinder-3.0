#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; }

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ──────────────────────────────────────────────
# 1. Check Python version
# ──────────────────────────────────────────────
info "Checking Python version..."
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+')
        major="${ver%.*}"
        if [ "$major" -ge 3 ] && [ "${ver#*.}" -ge 11 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    err "Python 3.11+ is required. Install it first."
    exit 1
fi
ok "Using $PYTHON $("$PYTHON" --version 2>&1)"

# ──────────────────────────────────────────────
# 2. Install Tesseract (system-level)
# ──────────────────────────────────────────────
info "Checking Tesseract OCR..."
if command -v tesseract &>/dev/null; then
    ok "tesseract already installed ($(tesseract --version 2>&1 | head -1))"
else
    warn "tesseract not found. Attempting to install..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq tesseract-ocr libtesseract-dev
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y tesseract tesseract-devel
    elif command -v brew &>/dev/null; then
        brew install tesseract
    else
        err "Could not install Tesseract automatically."
        err "Install it manually: https://github.com/tesseract-ocr/tesseract"
        exit 1
    fi
    ok "Tesseract installed"
fi

# Check English language data
TESSDATA=$(tesseract --print-parameters 2>/dev/null | grep tessdata || true)
if ! tesseract --list-langs 2>&1 | grep -q "eng"; then
    warn "English language data not found. Attempting to install..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y -qq tesseract-ocr-eng
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y tesseract-langpack-eng
    else
        err "Install English language data manually, then set TESSDATA_PREFIX"
        err "See: https://github.com/tesseract-ocr/tessdata"
        exit 1
    fi
fi
ok "Tesseract English language data available"

# ──────────────────────────────────────────────
# 3. Create virtual environment
# ──────────────────────────────────────────────
if [ -d "$PROJECT_DIR/.venv" ]; then
    warn "Virtual environment already exists at .venv"
    warn "Remove it first if you want a fresh install: rm -rf .venv"
else
    info "Creating virtual environment..."
    "$PYTHON" -m venv "$PROJECT_DIR/.venv"
    ok "Virtual environment created"
fi

source "$PROJECT_DIR/.venv/bin/activate"

# ──────────────────────────────────────────────
# 4. Install Python packages
# ──────────────────────────────────────────────
info "Installing Python dependencies (this may take a few minutes)..."
pip install --upgrade pip -q
pip install -r "$PROJECT_DIR/requirements.txt"
ok "Python dependencies installed"

# ──────────────────────────────────────────────
# 5. Install Playwright Chromium
# ──────────────────────────────────────────────
info "Installing Playwright Chromium browser..."
playwright install chromium 2>/dev/null || python3 -m playwright install chromium
ok "Playwright Chromium installed"

# ──────────────────────────────────────────────
# 6. Install LoomFinder in editable mode
# ──────────────────────────────────────────────
info "Installing LoomFinder..."
pip install -e "$PROJECT_DIR"
ok "LoomFinder installed"

# ──────────────────────────────────────────────
# 7. Create config from example if needed
# ──────────────────────────────────────────────
if [ ! -f "$PROJECT_DIR/config.toml" ]; then
    cp "$PROJECT_DIR/config.example.toml" "$PROJECT_DIR/config.toml"
    warn "Created config.toml from config.example.toml"
    warn "Edit it with your IA credentials: nano $PROJECT_DIR/config.toml"
else
    ok "config.toml already exists"
fi

# ──────────────────────────────────────────────
# 8. Set up loomfinder command
# ──────────────────────────────────────────────
info "Setting up loomfinder command..."
LOOMFINDER_WRAPPER="$PROJECT_DIR/loomfinder.sh"
cat > "$LOOMFINDER_WRAPPER" << 'WRAPPER'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/.venv/bin/activate"
exec python3 -m loomfinder "$@"
WRAPPER
chmod +x "$LOOMFINDER_WRAPPER"

BIN_PATH="/usr/local/bin/loomfinder"
if [ -w "$(dirname "$BIN_PATH")" ]; then
    cp "$LOOMFINDER_WRAPPER" "$BIN_PATH"
    ok "loomfinder command installed at $BIN_PATH"
elif command -v sudo &>/dev/null; then
    warn "Installing loomfinder to $BIN_PATH (requires sudo)..."
    sudo cp "$LOOMFINDER_WRAPPER" "$BIN_PATH"
    ok "loomfinder command installed at $BIN_PATH"
else
    warn "Could not install to $BIN_PATH (no sudo access)"
    warn "Add an alias to your shell profile:"
    warn "  alias loomfinder='$LOOMFINDER_WRAPPER'"
fi

# ──────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────
echo ""
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  LoomFinder 3.0 installation complete!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo ""
echo -e "  Activate the environment:  ${CYAN}source .venv/bin/activate${NC}"
echo -e "  Run LoomFinder:            ${CYAN}loomfinder s:literature${NC}"
echo -e "  Edit credentials:          ${CYAN}nano config.toml${NC}"
echo ""
echo -e "  ${YELLOW}Don't forget to add your IA credentials to config.toml!${NC}"
echo ""

