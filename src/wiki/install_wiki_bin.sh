#!/usr/bin/env bash
# install_wiki_bin.sh — copy all src/wiki/*.{sh,py} into $WIKI_ROOT/.wiki/bin/
# so cron entries can reference a stable path inside the wiki tree rather than
# the repo checkout. Non-interactive. Idempotent.
#
# Usage:
#   install_wiki_bin.sh [WIKI_ROOT]
#
# Environment overrides (test isolation):
#   LLMWIKI_SRC_DIR   — override the source directory (default: <script-dir>)
#
# Exit codes:
#   0 success
#   1 wiki root not found
#   4 [ERR_SECURITY] path escape / symlink wiki root

set -euo pipefail

# ---- 1. Locate wiki root -----------------------------------------------------

find_wiki_root() {
    local dir="${1:-$PWD}"
    while [[ "$dir" != "/" ]]; do
        if [[ -f "$dir/SCHEMA.md" ]]; then
            echo "$dir"
            return 0
        fi
        if [[ -d "$dir/.git" ]]; then
            echo "ERROR: reached git repository root at '$dir' without finding SCHEMA.md." >&2
            echo "       Run 'init' to scaffold a wiki in a subdirectory first." >&2
            return 1
        fi
        dir="$(dirname "$dir")"
    done
    return 1
}

WIKI_ROOT="${1:-}"
if [[ -z "$WIKI_ROOT" ]]; then
    WIKI_ROOT="$(find_wiki_root "$PWD")" || {
        echo "ERROR: No SCHEMA.md found walking up from $PWD" >&2
        exit 1
    }
else
    if [[ ! -d "$WIKI_ROOT" ]]; then
        echo "ERROR: $WIKI_ROOT is not a directory" >&2
        exit 1
    fi
    # Reject symlinks before resolution.
    if [[ -L "$WIKI_ROOT" ]]; then
        echo "[ERR_SECURITY] Wiki root '$WIKI_ROOT' is a symlink. Refusing." >&2
        exit 4
    fi
    WIKI_ROOT="$(cd "$WIKI_ROOT" && pwd)"
    while [[ "$WIKI_ROOT" != "/" && ! -f "$WIKI_ROOT/SCHEMA.md" && ! -d "$WIKI_ROOT/.git" ]]; do
        WIKI_ROOT="$(dirname "$WIKI_ROOT")"
    done
    if [[ -d "$WIKI_ROOT/.git" && ! -f "$WIKI_ROOT/SCHEMA.md" ]]; then
        echo "ERROR: reached git repository root without finding SCHEMA.md." >&2
        exit 1
    fi
    if [[ ! -f "$WIKI_ROOT/SCHEMA.md" ]]; then
        echo "ERROR: $1 is not inside a wiki (no SCHEMA.md found walking up)." >&2
        exit 1
    fi
fi
WIKI_ROOT="$(cd "$WIKI_ROOT" && pwd)"

# ---- 2. Security: reject symlink wiki root ----------------------------------

if [[ -L "$WIKI_ROOT" ]]; then
    echo "[ERR_SECURITY] Wiki root '$WIKI_ROOT' resolves through a symlink. Refusing." >&2
    exit 4
fi

# ---- 3. Locate source directory ---------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="${LLMWIKI_SRC_DIR:-$SCRIPT_DIR}"

if [[ ! -d "$SRC_DIR" ]]; then
    echo "ERROR: source directory '$SRC_DIR' not found." >&2
    exit 1
fi

# ---- 4. Copy scripts to .wiki/bin/ ------------------------------------------

BIN_DIR="$WIKI_ROOT/.wiki/bin"
mkdir -p "$BIN_DIR"

copied=0
for f in "$SRC_DIR"/*.sh "$SRC_DIR"/*.py; do
    [[ -f "$f" ]] || continue
    name="$(basename "$f")"
    dest="$BIN_DIR/$name"
    cp "$f" "$dest"
    chmod +x "$dest"
    copied=$((copied + 1))
done

echo "install_wiki_bin: copied $copied file(s) to $BIN_DIR"
exit 0
