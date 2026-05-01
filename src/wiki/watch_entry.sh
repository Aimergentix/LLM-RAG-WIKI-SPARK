#!/usr/bin/env bash
# watch_entry.sh — long-running watcher that runs autoconvert.sh whenever
# a file appears in entry/. Falls back to a polling loop if inotifywait is
# unavailable.
#
# Usage:
#   watch_entry.sh                 # auto-detect wiki root from cwd
#   watch_entry.sh /path/to/wiki   # explicit root
#
# Exits cleanly on SIGINT/SIGTERM.

set -euo pipefail

WIKI_ROOT="${1:-$PWD}"
if [[ ! -d "$WIKI_ROOT" ]]; then
    echo "ERROR: $WIKI_ROOT is not a directory" >&2
    exit 1
fi
WIKI_ROOT="$(cd "$WIKI_ROOT" && pwd)"
while [[ "$WIKI_ROOT" != "/" && ! -f "$WIKI_ROOT/SCHEMA.md" && ! -d "$WIKI_ROOT/.git" ]]; do
    WIKI_ROOT="$(dirname "$WIKI_ROOT")"
done
if [[ -d "$WIKI_ROOT/.git" && ! -f "$WIKI_ROOT/SCHEMA.md" ]]; then
    echo "ERROR: reached git repository root at '$WIKI_ROOT' without finding SCHEMA.md." >&2
    exit 1
fi
[[ -f "$WIKI_ROOT/SCHEMA.md" ]] || { echo "ERROR: No SCHEMA.md found." >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUTOCONVERT="$SCRIPT_DIR/autoconvert.sh"
ENTRY_DIR="$WIKI_ROOT/entry"
mkdir -p "$ENTRY_DIR"

trap 'echo "[watch] stop"; exit 0' INT TERM

run_convert() {
    echo "[watch] $(date +%H:%M:%S) running autoconvert"
    bash "$AUTOCONVERT" "$WIKI_ROOT" || echo "[watch] autoconvert failed"
}

# Initial pass.
run_convert

if command -v inotifywait >/dev/null 2>&1; then
    echo "[watch] using inotifywait on $ENTRY_DIR"
    while inotifywait -qq -r -e close_write,create,moved_to "$ENTRY_DIR"; do
        sleep 1   # debounce burst writes
        run_convert
    done
else
    echo "[watch] inotifywait not found; polling every 30s"
    last_state=""
    while true; do
        state="$(find "$ENTRY_DIR" -type f -printf '%p %T@\n' 2>/dev/null | sort)"
        if [[ "$state" != "$last_state" ]]; then
            last_state="$state"
            run_convert
        fi
        sleep 30
    done
fi
