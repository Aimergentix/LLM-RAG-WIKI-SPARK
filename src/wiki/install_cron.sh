#!/usr/bin/env bash
# install_cron.sh — interactive, idempotent installer for wiki cron jobs.
#
# Shows a unified diff against the current crontab and asks before writing.
# Calls install_wiki_bin.sh first (populates .wiki/bin/ for stable cron paths).
# Idempotent: strips any existing block tagged for this wiki before re-inserting.
#
# Scheduled jobs:
#   */15 * * * *   autoconvert.sh    (every 15 minutes)
#   23   6 * * 1   lint_cron.sh      (Mondays 06:23)
#   */30 * * * *   sync.sh           (every 30 minutes)
#
# Usage:  install_cron.sh [WIKI_ROOT]   (default: walk up from cwd)
#
# All cron entries are tagged:
#   # llm-wiki-builder:{wiki-name}
#   # llm-wiki-builder:{wiki-name}-end
#
# Exit codes:
#   0  success (including user abort)
#   1  wiki root not found
#   2  crontab binary absent (degrades gracefully — log line written)
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
    # Reject symlinks before any resolution.
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

# ---- 3. Resolve names and paths ---------------------------------------------

NAME="$(basename "$WIKI_ROOT")"
TAG="# llm-wiki-builder:$NAME"
TAG_END="# llm-wiki-builder:$NAME-end"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$WIKI_ROOT/.wiki/bin"
STATE_DIR="$WIKI_ROOT/.wiki"
CRON_LOG="$STATE_DIR/cron.log"
LOG_FILE="$WIKI_ROOT/log.md"

AUTOCONVERT="$BIN_DIR/autoconvert.sh"
LINT_CRON="$BIN_DIR/lint_cron.sh"
SYNC_CRON="$BIN_DIR/sync.sh"

# ---- 4. Populate .wiki/bin/ (adj. D) ----------------------------------------

INSTALL_BIN="$SCRIPT_DIR/install_wiki_bin.sh"
if [[ -x "$INSTALL_BIN" ]]; then
    LLMWIKI_SRC_DIR="${LLMWIKI_SRC_DIR:-$SCRIPT_DIR}" "$INSTALL_BIN" "$WIKI_ROOT"
fi

# ---- 5. Check for crontab ---------------------------------------------------

HAVE_CRONTAB=1
command -v crontab >/dev/null 2>&1 || HAVE_CRONTAB=0

if (( HAVE_CRONTAB == 0 )); then
    echo "WARNING: 'crontab' not found on PATH. Cannot write crontab." >&2
    echo "         Recording install attempt in log only." >&2
    mkdir -p "$STATE_DIR"
    : >> "$CRON_LOG"
    [[ -f "$LOG_FILE" ]] || echo "# Log" > "$LOG_FILE"
    echo "## [$(date +%Y-%m-%d)] cron | install | $NAME" >> "$LOG_FILE"
    exit 2
fi

# ---- 6. Build the new cron block --------------------------------------------

NEW_BLOCK="${TAG}
*/15 * * * * ${AUTOCONVERT} ${WIKI_ROOT} >> ${CRON_LOG} 2>&1 # Every 15 minutes
23   6 * * 1 ${LINT_CRON}   ${WIKI_ROOT} >> ${CRON_LOG} 2>&1 # Mondays 06:23
*/30 * * * * ${SYNC_CRON}    ${WIKI_ROOT} >> ${CRON_LOG} 2>&1 # Every 30 minutes
${TAG_END}"

# ---- 7. Strip existing block (idempotent) + build proposed crontab ----------

CURRENT="$(crontab -l 2>/dev/null || true)"

STRIPPED="$(printf '%s\n' "$CURRENT" | awk -v tag="$TAG" -v tag_end="$TAG_END" '
    $0 == tag     { skip = 1; next }
    $0 == tag_end { skip = 0; next }
    !skip
')"

# Trim leading/trailing blank lines from the stripped portion before appending.
# Append the new block with a blank separator.
if [[ -n "$STRIPPED" ]]; then
    NEW_CRON="$(printf '%s\n\n%s\n' "$STRIPPED" "$NEW_BLOCK")"
else
    NEW_CRON="$(printf '%s\n' "$NEW_BLOCK")"
fi

# ---- 8. Show diff and confirm -----------------------------------------------

echo
echo "=== Proposed crontab diff for wiki '$NAME' ==="
diff <(printf '%s\n' "$CURRENT") <(printf '%s\n' "$NEW_CRON") || true
echo "=============================================="
echo

read -r -p "Install this crontab? [y/N] " ans
case "${ans:-N}" in
    y|Y|yes|YES)
        ;;
    *)
        echo "Aborted; crontab unchanged."
        exit 0
        ;;
esac

# ---- 9. Write crontab + post-install housekeeping ---------------------------

printf '%s\n' "$NEW_CRON" | crontab -
mkdir -p "$STATE_DIR"
: >> "$CRON_LOG"
[[ -f "$LOG_FILE" ]] || echo "# Log" > "$LOG_FILE"
echo "## [$(date +%Y-%m-%d)] cron | install | $NAME" >> "$LOG_FILE"
echo "Installed. Logs: $CRON_LOG"
