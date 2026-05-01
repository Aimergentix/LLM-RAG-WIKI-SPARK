#!/usr/bin/env bash
# sync.sh — Handles external synchronization of the wiki via Git.
#
# Usage:
#   sync.sh [WIKI_ROOT]

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
    WIKI_ROOT="$(cd "$WIKI_ROOT" && pwd)"
fi

CRON_LOG="$WIKI_ROOT/.wiki/cron.log"
mkdir -p "$WIKI_ROOT/.wiki"

# ---- 2. Sync Logic (Git-First) -----------------------------------------------

if [[ -d "$WIKI_ROOT/.git" ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] sync starting" >> "$CRON_LOG"
    
    cd "$WIKI_ROOT"
    
    # 1. Capture local changes
    git add .
    # Commit only if there are changes
    if ! git diff-index --quiet HEAD --; then
        git commit -m "auto: wiki sync $(date -Iminutes)"
    fi
    
    # 2. Pull with rebase to keep history clean
    git pull --rebase
    
    # 3. Push to remote
    git push
    
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] sync complete" >> "$CRON_LOG"
else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] sync skipped: no .git directory found" >> "$CRON_LOG"
fi

exit 0