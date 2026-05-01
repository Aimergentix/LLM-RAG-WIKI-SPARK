#!/usr/bin/env bash
# session_check.sh — silent unless wiki has pending work. Prints a compact
# status when invoked from a shell prompt or session-start hook.
#
# Usage:  session_check.sh [/path/to/wiki]   (default: cwd)
# Exits 0 always (informational only).

set -euo pipefail

WIKI_ROOT="${1:-$PWD}"
[[ -d "$WIKI_ROOT" ]] || exit 0
WIKI_ROOT="$(cd "$WIKI_ROOT" && pwd)"
while [[ "$WIKI_ROOT" != "/" && ! -f "$WIKI_ROOT/SCHEMA.md" && ! -d "$WIKI_ROOT/.git" ]]; do
    WIKI_ROOT="$(dirname "$WIKI_ROOT")"
done
if [[ -d "$WIKI_ROOT/.git" && ! -f "$WIKI_ROOT/SCHEMA.md" ]]; then
    exit 0  # silently skip non-wiki git repos
fi
[[ -f "$WIKI_ROOT/SCHEMA.md" ]] || exit 0

NAME="$(basename "$WIKI_ROOT")"

RAW_PENDING=0
if [[ -d "$WIKI_ROOT/raw" ]]; then
    shopt -s nullglob
    for f in "$WIKI_ROOT/raw"/*.md; do
        [[ -f "$f" ]] || continue
        slug="$(basename "$f" .md)"
        if ! [[ -f "$WIKI_ROOT/wiki/sources/$slug.md" ]]; then
            RAW_PENDING=$((RAW_PENDING + 1))
        fi
    done
fi

NEEDS_VISION=0
if [[ -d "$WIKI_ROOT/raw" ]]; then
    NEEDS_VISION="$( { grep -lR "<!-- needs-vision:" "$WIKI_ROOT/raw" 2>/dev/null || true; } | wc -l | tr -d ' ')"
fi

ALERT_FILE="$WIKI_ROOT/.wiki/.alert.md"
ALERT_LINE=""
if [[ -f "$ALERT_FILE" && -s "$ALERT_FILE" ]]; then
    ALERT_LINE="$(head -1 "$ALERT_FILE")"
fi

if (( RAW_PENDING == 0 && NEEDS_VISION == 0 )) && [[ -z "$ALERT_LINE" ]]; then
    exit 0
fi

echo "WIKI: $NAME"
(( RAW_PENDING > 0 ))  && echo "  raw/ awaiting ingest:  $RAW_PENDING"
(( NEEDS_VISION > 0 )) && echo "  needs-vision markers:  $NEEDS_VISION"
[[ -n "$ALERT_LINE" ]] && echo "  lint alert:            $ALERT_LINE"
echo "  Run: ingest    (or  lint  /  autoconvert)"
exit 0
