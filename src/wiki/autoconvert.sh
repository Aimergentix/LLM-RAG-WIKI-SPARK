#!/usr/bin/env bash
# autoconvert.sh — entry/ → raw/ tiered Markdown converter (M2).
#
# Reads .wiki/.converted.json, finds new files in entry/, converts each via
# the best available tier, writes raw/{slug}.md with frontmatter, updates
# the manifest atomically, appends one log line per file. Idempotent — never
# re-processes a file whose sha256 already appears in the manifest.
#
# Usage:
#   autoconvert.sh                 # auto-detect wiki root from cwd
#   autoconvert.sh /path/to/wiki   # explicit root (must be inside a wiki)
#
# Exit codes:
#   0 success
#   1 wiki root not found / explicit arg not inside a wiki
#   2 no converters available AND non-trivial input present
#   4 [ERR_SECURITY] path escape / prohibited write
#
# Concurrency: serialized via flock(1) on .wiki/.converted.json.lock.
# A Python fcntl fallback is used if flock(1) is missing.
#
# Spec: MASTER §6 W2, §7 (autoconvert manifest + log format), §8 (path safety),
#       Appendix B (tier table).

set -euo pipefail

# ---- 1. Locate wiki root ----------------------------------------------------
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
    WIKI_ROOT="$(cd "$WIKI_ROOT" && pwd)"
    while [[ "$WIKI_ROOT" != "/" && ! -f "$WIKI_ROOT/SCHEMA.md" && ! -d "$WIKI_ROOT/.git" ]]; do
        WIKI_ROOT="$(dirname "$WIKI_ROOT")"
    done
    if [[ -d "$WIKI_ROOT/.git" && ! -f "$WIKI_ROOT/SCHEMA.md" ]]; then
        echo "ERROR: reached git repository root at '$WIKI_ROOT' without finding SCHEMA.md." >&2
        exit 1
    fi
    if [[ ! -f "$WIKI_ROOT/SCHEMA.md" ]]; then
        echo "ERROR: $1 is not inside a wiki (no SCHEMA.md found walking up)." >&2
        exit 1
    fi
fi
WIKI_ROOT="$(cd "$WIKI_ROOT" && pwd)"

ENTRY_DIR="$WIKI_ROOT/entry"
RAW_DIR="$WIKI_ROOT/raw"
STATE_DIR="$WIKI_ROOT/.wiki"
MANIFEST="$STATE_DIR/.converted.json"
STATUS_FILE="$STATE_DIR/.status.json"
LOCK_FILE="$STATE_DIR/.converted.json.lock"
LOG_FILE="$WIKI_ROOT/log.md"

mkdir -p "$ENTRY_DIR" "$RAW_DIR/assets" "$STATE_DIR"
[[ -f "$MANIFEST" ]] || echo '{}' > "$MANIFEST"
[[ -f "$STATUS_FILE" ]] || echo '{}' > "$STATUS_FILE"
[[ -f "$LOG_FILE" ]] || echo "# Log" > "$LOG_FILE"

# ---- 2. Acquire lock (serialize concurrent runs) ----------------------------
# flock(1) is preferred; fall back to a Python fcntl wrapper when missing.
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    flock 9
    LOCK_HELD=1
elif command -v python3 >/dev/null 2>&1; then
    # Re-exec under a Python wrapper that holds an fcntl.flock for our PID.
    if [[ "${_AUTOCONVERT_LOCKED:-}" != "1" ]]; then
        export _AUTOCONVERT_LOCKED=1
        exec python3 - "$LOCK_FILE" "$0" "$WIKI_ROOT" <<'PY'
import fcntl, os, sys
lock_path, script, wiki = sys.argv[1], sys.argv[2], sys.argv[3]
fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
fcntl.flock(fd, fcntl.LOCK_EX)
os.execvp("bash", ["bash", script, wiki])
PY
    fi
    LOCK_HELD=1
else
    LOCK_HELD=0
fi

# ---- 3. Detect available converters -----------------------------------------
HAVE_PANDOC=0;     command -v pandoc     >/dev/null 2>&1 && HAVE_PANDOC=1
HAVE_PDFTOTEXT=0;  command -v pdftotext  >/dev/null 2>&1 && HAVE_PDFTOTEXT=1
HAVE_MARKITDOWN=0; command -v markitdown >/dev/null 2>&1 && HAVE_MARKITDOWN=1

NO_CONVERTERS=0
if (( HAVE_PANDOC == 0 && HAVE_PDFTOTEXT == 0 && HAVE_MARKITDOWN == 0 )); then
    NO_CONVERTERS=1
    echo "WARNING: No converters installed; only .txt and .md will be copied." >&2
fi

# ---- 4. Helpers -------------------------------------------------------------
slugify() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
        | sed 's/[^a-z0-9]/-/g; s/--*/-/g; s/^-//; s/-$//'
}

sha256_of() { sha256sum "$1" | awk '{print $1}'; }
today() { date +%Y-%m-%d; }

write_frontmatter() {
    # $1=outfile $2=title $3=slug $4=converter $5=status
    local outfile="$1" title="$2" slug="$3" converter="$4" status="$5"
    local body
    body="$(cat "$outfile" 2>/dev/null || true)"
    {
        echo "---"
        echo "type: raw_source"
        echo "title: '${title//\'/}'"
        echo "slug: $slug"
        echo "converter: $converter"
        echo "converted_at: $(today)"
        echo "status: $status"
        echo "---"
        echo
        printf '%s\n' "$body"
    } > "$outfile.tmp"
    mv "$outfile.tmp" "$outfile"
}

manifest_has() {
    # $1=relpath $2=sha256 → exit 0 iff already converted with this sha.
    python3 - "$MANIFEST" "$1" "$2" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
e = m.get(sys.argv[2])
sys.exit(0 if e and e.get("sha256") == sys.argv[3] else 1)
PY
}

manifest_slug_for() {
    # $1=relpath → prints recorded slug, if any.
    python3 - "$MANIFEST" "$1" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
e = m.get(sys.argv[2])
if e and "slug" in e:
    print(e["slug"])
PY
}

manifest_slug_taken() {
    # $1=slug $2=relpath → exit 0 iff slug owned by a DIFFERENT relpath.
    python3 - "$MANIFEST" "$1" "$2" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
slug, relpath = sys.argv[2], sys.argv[3]
for k, v in m.items():
    if k == relpath:
        continue
    if isinstance(v, dict) and v.get("slug") == slug:
        sys.exit(0)
sys.exit(1)
PY
}

manifest_add() {
    # $1=relpath $2=slug $3=converter $4=sha256 $5=status
    python3 - "$MANIFEST" "$1" "$2" "$3" "$4" "$5" <<'PY'
import json, os, sys, datetime
path = sys.argv[1]
with open(path) as f:
    m = json.load(f)
m[sys.argv[2]] = {
    "source": sys.argv[2],
    "slug": sys.argv[3],
    "converter": sys.argv[4],
    "sha256": sys.argv[5],
    "status": sys.argv[6],
    "converted_at": datetime.date.today().isoformat(),
}
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(m, f, indent=2, sort_keys=True)
os.replace(tmp, path)
PY
}

log_line() {
    # $1=relpath $2=slug $3=converter
    echo "## [$(today)] autoconvert | $1 → raw/$2.md ($3)" >> "$LOG_FILE"
}

# ---- 5. Convert one file ----------------------------------------------------
# Sets globals: STATUS, CONVERTER
convert_one() {
    local infile="$1" outfile="$2"
    local ext="${infile##*.}"
    ext="$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')"
    STATUS="ok"
    CONVERTER="unknown"

    case "$ext" in
        md|txt)
            cp "$infile" "$outfile"
            CONVERTER="copy"
            ;;
        html|htm|docx|odt|rtf|epub)
            if (( HAVE_PANDOC )); then
                pandoc -f "$ext" -t markdown --wrap=none "$infile" -o "$outfile" 2>/dev/null \
                    || pandoc "$infile" -o "$outfile" 2>/dev/null
                CONVERTER="pandoc"
            elif (( HAVE_MARKITDOWN )); then
                markitdown "$infile" > "$outfile"
                CONVERTER="markitdown"
            else
                STATUS="skipped_no_converter"
                : > "$outfile"
                echo "<!-- needs-converter: install pandoc or markitdown -->" >> "$outfile"
                CONVERTER="none"
            fi
            ;;
        pdf)
            if (( HAVE_PDFTOTEXT )) && pdftotext -layout "$infile" "$outfile" 2>/dev/null \
                && [[ -s "$outfile" ]]; then
                CONVERTER="pdftotext"
            elif (( HAVE_MARKITDOWN )) && markitdown "$infile" > "$outfile" 2>/dev/null \
                && [[ -s "$outfile" ]]; then
                CONVERTER="markitdown"
            elif (( HAVE_PANDOC )) && pandoc "$infile" -o "$outfile" 2>/dev/null \
                && [[ -s "$outfile" ]]; then
                CONVERTER="pandoc"
            else
                STATUS="needs_vision"
                CONVERTER="vision"
                cat > "$outfile" <<EOF
<!-- needs-vision: $infile -->

This PDF could not be converted with text-based tools (pdftotext, markitdown,
pandoc). It is likely scanned or image-heavy. The next ingest pass should
resolve this stub by viewing the source with a vision-capable model.

Original file: \`$infile\`
EOF
            fi
            ;;
        pptx|xlsx)
            if (( HAVE_MARKITDOWN )); then
                markitdown "$infile" > "$outfile"
                CONVERTER="markitdown"
            elif (( HAVE_PANDOC )); then
                pandoc "$infile" -o "$outfile" 2>/dev/null \
                    || { STATUS="failed"; : > "$outfile"; }
                CONVERTER="pandoc"
            else
                STATUS="skipped_no_converter"
                : > "$outfile"
                CONVERTER="none"
            fi
            ;;
        png|jpg|jpeg|gif|webp|svg)
            local asset_name
            asset_name="$(basename "$infile")"
            cp "$infile" "$RAW_DIR/assets/$asset_name"
            cat > "$outfile" <<EOF
<!-- needs-vision: raw/assets/$asset_name -->

Image asset. The next ingest pass should resolve this stub by viewing the
asset with a vision-capable model.

![${asset_name}](assets/${asset_name})
EOF
            STATUS="needs_vision"
            CONVERTER="vision"
            ;;
        *)
            if (( HAVE_PANDOC )) && pandoc "$infile" -o "$outfile" 2>/dev/null \
                && [[ -s "$outfile" ]]; then
                CONVERTER="pandoc"
            else
                STATUS="failed_unknown_format"
                CONVERTER="none"
                : > "$outfile"
                echo "<!-- failed: unknown format .$ext -->" >> "$outfile"
            fi
            ;;
    esac
}

# ---- 6. Main loop -----------------------------------------------------------
NEW=0
SKIPPED=0
FAILED=0
NEEDS_VISION=0
NON_TEXT_INPUT=0

shopt -s nullglob globstar
for infile in "$ENTRY_DIR"/**/*; do
    [[ -f "$infile" ]] || continue
    # Symlink safety (MASTER §8): never follow symlinks out of entry/.
    if [[ -L "$infile" ]]; then
        echo "WARNING: skipping symlink $infile" >&2
        continue
    fi
    relpath="${infile#"$ENTRY_DIR"/}"
    base="$(basename "$infile")"
    sha="$(sha256_of "$infile")"

    if manifest_has "$relpath" "$sha"; then
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    ext_lc="$(printf '%s' "${base##*.}" | tr '[:upper:]' '[:lower:]')"
    case "$ext_lc" in
        md|txt) ;;
        *) NON_TEXT_INPUT=1 ;;
    esac

    name="${base%.*}"
    relname="${relpath%.*}"
    slug="$(slugify "$relname")"
    [[ -z "$slug" ]] && slug="file-$(printf '%s' "$sha" | cut -c1-12)"

    existing_slug="$(manifest_slug_for "$relpath")"
    if [[ -n "$existing_slug" ]]; then
        slug="$existing_slug"
    else
        if manifest_slug_taken "$slug" "$relpath"; then
            slug="${slug}-$(printf '%s' "$sha" | cut -c1-8)"
            if manifest_slug_taken "$slug" "$relpath"; then
                echo "ERROR: slug collision unresolvable for $relpath ($slug)" >&2
                FAILED=$((FAILED + 1))
                continue
            fi
        fi
    fi

    outfile="$RAW_DIR/$slug.md"

    convert_one "$infile" "$outfile"
    write_frontmatter "$outfile" "$name" "$slug" "$CONVERTER" "$STATUS"
    manifest_add "$relpath" "$slug" "$CONVERTER" "$sha" "$STATUS"
    log_line "$relpath" "$slug" "$CONVERTER"

    case "$STATUS" in
        ok)            NEW=$((NEW + 1)) ;;
        needs_vision)  NEEDS_VISION=$((NEEDS_VISION + 1)); NEW=$((NEW + 1)) ;;
        *)             FAILED=$((FAILED + 1)) ;;
    esac
done

# ---- 7. Status summary (one-shot, parseable) -------------------------------
cat <<EOF
AUTOCONVERT COMPLETE
  wiki:         $WIKI_ROOT
  new:          $NEW
  skipped:      $SKIPPED
  failed:       $FAILED
  needs-vision: $NEEDS_VISION
EOF

# Atomic write of .status.json.
python3 - "$STATUS_FILE" "$NEW" "$SKIPPED" "$FAILED" "$NEEDS_VISION" <<'PY'
import json, os, sys, datetime
path = sys.argv[1]
try:
    with open(path) as f:
        s = json.load(f)
except Exception:
    s = {}
s["last_autoconvert"] = {
    "at": datetime.datetime.now().isoformat(timespec="seconds"),
    "new": int(sys.argv[2]),
    "skipped": int(sys.argv[3]),
    "failed": int(sys.argv[4]),
    "needs_vision": int(sys.argv[5]),
}
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(s, f, indent=2, sort_keys=True)
os.replace(tmp, path)
PY

# Hard exit 2 reserved for "no converters available AND non-trivial input"
# is documented in the contract but never reached in practice — per
# acceptance #10, such files are recorded as status=skipped_no_converter
# and the run still exits 0. Kept as a single exit point below.
exit 0
