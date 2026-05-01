#!/usr/bin/env bash
# uninstall_cron.sh — remove the cron block for a given wiki.
# Symmetric with install_cron.sh; identifies the block by the
# # llm-wiki-builder:{name} / # llm-wiki-builder:{name}-end tag pair.
#
# Usage:  uninstall_cron.sh [WIKI_ROOT]   (default: walk up from cwd)
#
# Exit codes:
#   0  success (including user abort or no-op)
#   1  wiki root not found
#   2  crontab binary absent
#   4  [ERR_SECURITY] symlink wiki root

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

ARG="${1:-}"
if [[ -z "$ARG" ]]; then
    WIKI_ROOT="$(find_wiki_root "$PWD")" || {
        echo "ERROR: No SCHEMA.md found walking up from $PWD" >&2
        exit 1
    }
else
    if [[ ! -d "$ARG" ]]; then
        echo "ERROR: $ARG is not a directory" >&2
        exit 1
    fi
    if [[ -L "$ARG" ]]; then
        echo "[ERR_SECURITY] Wiki root '$ARG' is a symlink. Refusing." >&2
        exit 4
    fi
    WIKI_ROOT="$(cd "$ARG" && pwd)"
    while [[ "$WIKI_ROOT" != "/" && ! -f "$WIKI_ROOT/SCHEMA.md" && ! -d "$WIKI_ROOT/.git" ]]; do
        WIKI_ROOT="$(dirname "$WIKI_ROOT")"
    done
    if [[ -d "$WIKI_ROOT/.git" && ! -f "$WIKI_ROOT/SCHEMA.md" ]]; then
        echo "ERROR: reached git repository root without finding SCHEMA.md." >&2
        exit 1
    fi
    if [[ ! -f "$WIKI_ROOT/SCHEMA.md" ]]; then
        echo "ERROR: $ARG is not inside a wiki (no SCHEMA.md found walking up)." >&2
        exit 1
    fi
fi
WIKI_ROOT="$(cd "$WIKI_ROOT" && pwd)"

# ---- 2. Security: reject symlink wiki root ----------------------------------

if [[ -L "$WIKI_ROOT" ]]; then
    echo "[ERR_SECURITY] Wiki root '$WIKI_ROOT' resolves through a symlink. Refusing." >&2
    exit 4
fi

# ---- 3. Names and paths -----------------------------------------------------

NAME="$(basename "$WIKI_ROOT")"
TAG="# llm-wiki-builder:$NAME"
TAG_END="# llm-wiki-builder:$NAME-end"
LOG_FILE="$WIKI_ROOT/log.md"

# ---- 4. Check for crontab ---------------------------------------------------

HAVE_CRONTAB=1
command -v crontab >/dev/null 2>&1 || HAVE_CRONTAB=0

if (( HAVE_CRONTAB == 0 )); then
    echo "WARNING: 'crontab' not found on PATH. Cannot read/write crontab." >&2
    exit 2
fi

# ---- 5. Check whether a tagged block exists ---------------------------------

CURRENT="$(crontab -l 2>/dev/null || true)"
if ! printf '%s\n' "$CURRENT" | grep -qF "$TAG"; then
    echo "No cron block tagged '$TAG' found. Nothing to do."
    exit 0
fi

# ---- 6. Compute the stripped crontab ----------------------------------------

STRIPPED="$(printf '%s\n' "$CURRENT" | awk -v tag="$TAG" -v tag_end="$TAG_END" '
    $0 == tag     { skip = 1; next }
    $0 == tag_end { skip = 0; next }
    !skip
')"

# ---- 7. Show diff and confirm -----------------------------------------------

echo
echo "=== Diff (will REMOVE '$TAG' block) ==="
diff <(printf '%s\n' "$CURRENT") <(printf '%s\n' "$STRIPPED") || true
echo "======================================="
echo

read -r -p "Remove? [y/N] " ans
case "${ans:-N}" in
    y|Y|yes|YES)
        ;;
    *)
        echo "Aborted; crontab unchanged."
        exit 0
        ;;
esac

# ---- 8. Write stripped crontab + log ----------------------------------------

printf '%s\n' "$STRIPPED" | crontab -
[[ -f "$LOG_FILE" ]] || echo "# Log" > "$LOG_FILE"
echo "## [$(date +%Y-%m-%d)] cron | uninstall | $NAME" >> "$LOG_FILE"
echo "Removed."
