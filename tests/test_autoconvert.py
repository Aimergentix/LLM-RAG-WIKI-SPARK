"""Acceptance tests for M2 — Converter pipeline.

Mapped to contract criteria 1–16 in START-PROMPT.md §5 (filed inline).

Test isolation: PATH is scrubbed to a tmpdir containing only stable POSIX
tools so degradation paths execute deterministically regardless of which
optional converters (pandoc, pdftotext, markitdown, inotifywait, flock) are
installed on the developer machine. Real-converter happy paths are gated
behind LLMWIKI_TEST_REAL_CONVERTERS=1.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
SRC = REPO_ROOT / "src"
sys.path.insert(0, str(SRC))

from wiki.init import init  # noqa: E402

AUTOCONVERT = REPO_ROOT / "src" / "wiki" / "autoconvert.sh"
WATCH = REPO_ROOT / "src" / "wiki" / "watch_entry.sh"
SESSION_CHECK = REPO_ROOT / "src" / "wiki" / "session_check.sh"

# Tools the scripts genuinely need.  flock is included when present so
# concurrency tests can exercise the flock(1) path; if absent the script
# uses its Python fcntl fallback.
_REQUIRED_TOOLS = (
    "bash", "python3", "sha256sum", "date", "find", "awk", "sed", "tr",
    "cat", "cp", "mv", "rm", "mkdir", "basename", "dirname", "head",
    "wc", "grep", "sort", "tee", "printf", "ls", "chmod", "stat",
    "env", "id", "true", "false", "test", "[", "uname", "readlink",
    "cut", "tail", "xargs", "touch", "ln",
)
_OPTIONAL_TOOLS = ("flock",)


@pytest.fixture
def scrubbed_path(tmp_path: Path) -> str:
    """Build a PATH containing only the required POSIX tools (symlinks
    into a tmpdir). Optional converters are deliberately omitted to force
    degradation paths."""
    bindir = tmp_path / "scrubbed-bin"
    bindir.mkdir()
    for tool in _REQUIRED_TOOLS + _OPTIONAL_TOOLS:
        src = shutil.which(tool)
        if src:
            try:
                os.symlink(src, bindir / tool)
            except FileExistsError:
                pass
    return str(bindir)


@pytest.fixture
def env_scrubbed(scrubbed_path: str) -> dict:
    env = os.environ.copy()
    env["PATH"] = scrubbed_path
    return env


@pytest.fixture
def wiki(tmp_path: Path) -> Path:
    """Build a real M1-scaffolded wiki for the test."""
    target = tmp_path / "wiki-test"
    return init("Test Domain", "A unit-test wiki.", str(target))


def _run(*args: str, env: dict | None = None,
         cwd: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(AUTOCONVERT), *args],
        env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )


# ---- Acceptance #1: path safety / non-wiki arg --------------------------

def test_rejects_non_wiki_explicit_arg(tmp_path: Path, env_scrubbed):
    target = tmp_path / "not-a-wiki"
    target.mkdir()
    result = _run(str(target), env=env_scrubbed)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "SCHEMA.md" in result.stderr
    for leaked in ("entry", "raw", ".wiki", "log.md"):
        assert not (target / leaked).exists(), f"leaked {leaked}"


def test_rejects_nonexistent_path(tmp_path: Path, env_scrubbed):
    result = _run(str(tmp_path / "does-not-exist"), env=env_scrubbed)
    assert result.returncode != 0


# ---- Acceptance #2: walk-up acceptance -----------------------------------

def test_accepts_subdir_of_wiki(wiki: Path, env_scrubbed):
    sub = wiki / "deep" / "nested"
    sub.mkdir(parents=True)
    result = _run(str(sub), env=env_scrubbed)
    assert result.returncode == 0, result.stderr


# ---- Acceptance #3: idempotency -----------------------------------------

def test_idempotent_no_new_on_second_run(wiki: Path, env_scrubbed):
    (wiki / "entry" / "note.txt").write_text("hello\n")
    r1 = _run(str(wiki), env=env_scrubbed)
    assert r1.returncode == 0, r1.stderr
    m1 = json.loads((wiki / ".wiki" / ".converted.json").read_text())
    r2 = _run(str(wiki), env=env_scrubbed)
    assert r2.returncode == 0
    m2 = json.loads((wiki / ".wiki" / ".converted.json").read_text())
    assert m1 == m2
    assert "new:          0" in r2.stdout
    assert "skipped:      1" in r2.stdout


# ---- Acceptance #4: re-conversion stability -----------------------------

def test_reconversion_reuses_slug(wiki: Path, env_scrubbed):
    f = wiki / "entry" / "note.txt"
    f.write_text("hello\n")
    _run(str(wiki), env=env_scrubbed)
    m1 = json.loads((wiki / ".wiki" / ".converted.json").read_text())
    slug1 = m1["note.txt"]["slug"]
    f.write_text("hello world\n")  # change content -> new sha
    _run(str(wiki), env=env_scrubbed)
    m2 = json.loads((wiki / ".wiki" / ".converted.json").read_text())
    assert m2["note.txt"]["slug"] == slug1
    assert m2["note.txt"]["sha256"] != m1["note.txt"]["sha256"]
    # raw/{slug}.md exists exactly once
    raw_files = list((wiki / "raw").glob("*.md"))
    assert len(raw_files) == 1


# ---- Acceptance #5: slug collision --------------------------------------

def test_slug_collision_disambiguated(wiki: Path, env_scrubbed):
    # Two paths slugifying to the same base ("foo-bar"): "foo bar.txt" and "foo_bar.txt".
    (wiki / "entry" / "foo bar.txt").write_text("a\n")
    (wiki / "entry" / "foo_bar.txt").write_text("b\n")
    r = _run(str(wiki), env=env_scrubbed)
    assert r.returncode == 0, r.stderr
    m = json.loads((wiki / ".wiki" / ".converted.json").read_text())
    slugs = sorted(v["slug"] for v in m.values())
    assert len(slugs) == 2
    assert slugs[0] != slugs[1]
    # one of them should match the suffix pattern
    assert any(re.fullmatch(r"foo-bar-[0-9a-f]{8}", s) for s in slugs)


# ---- Acceptance #6: atomic manifest writes ------------------------------

def test_no_tmp_leftovers_and_valid_json(wiki: Path, env_scrubbed):
    (wiki / "entry" / "a.txt").write_text("a\n")
    r = _run(str(wiki), env=env_scrubbed)
    assert r.returncode == 0
    state_dir = wiki / ".wiki"
    leftovers = [p.name for p in state_dir.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    json.loads((state_dir / ".converted.json").read_text())
    json.loads((state_dir / ".status.json").read_text())


def test_atomic_write_crash_leaves_manifest_intact(
        wiki: Path, env_scrubbed, tmp_path: Path):
    """Stub `python3` to exit 1 immediately after writing a `.tmp`; the
    real on-disk manifest must remain its previous value (here: empty {})."""
    # First baseline run: empty entry, manifest stays {}.
    _run(str(wiki), env=env_scrubbed)
    manifest = wiki / ".wiki" / ".converted.json"
    before = manifest.read_text()

    # Build a python3 shim that mimics manifest_add but exits before os.replace.
    shim_dir = tmp_path / "shim-bin"
    shim_dir.mkdir()
    real_python = shutil.which("python3", path=env_scrubbed["PATH"])
    assert real_python
    shim = shim_dir / "python3"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        # Detect a manifest_add call by sniffing argv: it's the only one with
        # 6 positional args after the script (path, relpath, slug, conv, sha, status).
        # All other python3 heredocs have <= 4 args. If 6, write tmp then die.
        f'REAL={real_python}\n'
        'if [ "$#" -eq 7 ]; then\n'  # script + 6 args = 7
        '  PATH_ARG="$1"\n'
        '  printf "{}" > "$PATH_ARG.tmp"\n'
        '  exit 1\n'
        'fi\n'
        'exec "$REAL" "$@"\n'
    )
    shim.chmod(0o755)

    env2 = dict(env_scrubbed)
    env2["PATH"] = f"{shim_dir}:{env_scrubbed['PATH']}"
    (wiki / "entry" / "crash.txt").write_text("boom\n")
    # Run; we don't care about the rc, only about manifest preservation.
    subprocess.run(
        ["bash", str(AUTOCONVERT), str(wiki)],
        env=env2, capture_output=True, text=True, timeout=30,
    )
    after = manifest.read_text()
    assert after == before, "manifest mutated despite simulated crash"


# ---- Acceptance #7: concurrent runs serialize ---------------------------

def test_concurrent_runs_serialize(wiki: Path, env_scrubbed):
    # Seed disjoint files; race two autoconverts.
    for i in range(8):
        (wiki / "entry" / f"f{i}.txt").write_text(f"{i}\n")
    p1 = subprocess.Popen(
        ["bash", str(AUTOCONVERT), str(wiki)],
        env=env_scrubbed, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    p2 = subprocess.Popen(
        ["bash", str(AUTOCONVERT), str(wiki)],
        env=env_scrubbed, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    p1.wait(timeout=60); p2.wait(timeout=60)
    assert p1.returncode == 0 and p2.returncode == 0
    m = json.loads((wiki / ".wiki" / ".converted.json").read_text())
    for i in range(8):
        assert f"f{i}.txt" in m, f"lost entry f{i}.txt under concurrent run"


# ---- Acceptance #8 / #10: tier fallback / no converters -----------------

def test_pdf_with_no_converters_yields_needs_vision(wiki: Path, env_scrubbed):
    (wiki / "entry" / "scan.pdf").write_bytes(b"%PDF-1.4\nfake\n")
    r = _run(str(wiki), env=env_scrubbed)
    assert r.returncode == 0, r.stderr
    m = json.loads((wiki / ".wiki" / ".converted.json").read_text())
    assert m["scan.pdf"]["status"] == "needs_vision"
    assert m["scan.pdf"]["converter"] == "vision"
    raw = (wiki / "raw" / f"{m['scan.pdf']['slug']}.md").read_text()
    body = raw.split("---", 2)[2].lstrip()
    assert body.startswith("<!-- needs-vision:")


def test_text_only_no_converters_succeeds(wiki: Path, env_scrubbed):
    (wiki / "entry" / "n.txt").write_text("plain\n")
    (wiki / "entry" / "n.md").write_text("# md\n")
    r = _run(str(wiki), env=env_scrubbed)
    assert r.returncode == 0
    m = json.loads((wiki / ".wiki" / ".converted.json").read_text())
    for k in ("n.txt", "n.md"):
        assert m[k]["status"] == "ok"
        assert m[k]["converter"] == "copy"


def test_non_text_no_converters_skipped(wiki: Path, env_scrubbed):
    # .docx with no pandoc/markitdown -> skipped_no_converter, exit 0.
    (wiki / "entry" / "doc.docx").write_bytes(b"PK\x03\x04fake\n")
    r = _run(str(wiki), env=env_scrubbed)
    assert r.returncode == 0
    m = json.loads((wiki / ".wiki" / ".converted.json").read_text())
    assert m["doc.docx"]["status"] == "skipped_no_converter"


# ---- Acceptance #9: image input -----------------------------------------

def test_image_emits_needs_vision_stub(wiki: Path, env_scrubbed):
    (wiki / "entry" / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\nfake\n")
    r = _run(str(wiki), env=env_scrubbed)
    assert r.returncode == 0
    m = json.loads((wiki / ".wiki" / ".converted.json").read_text())
    assert m["pic.png"]["status"] == "needs_vision"
    assert (wiki / "raw" / "assets" / "pic.png").exists()
    raw = (wiki / "raw" / f"{m['pic.png']['slug']}.md").read_text()
    assert "needs-vision: raw/assets/pic.png" in raw
    assert "![pic.png](assets/pic.png)" in raw


# ---- Acceptance #11: manifest schema ------------------------------------

def test_manifest_schema_keys(wiki: Path, env_scrubbed):
    (wiki / "entry" / "x.txt").write_text("x\n")
    _run(str(wiki), env=env_scrubbed)
    m = json.loads((wiki / ".wiki" / ".converted.json").read_text())
    entry = m["x.txt"]
    assert set(entry.keys()) == {
        "source", "slug", "converter", "sha256", "status", "converted_at"
    }
    assert entry["converter"] in {"pandoc", "markitdown", "pdftotext", "vision", "copy", "none"}
    assert entry["status"] in {"ok", "needs_vision", "skipped_no_converter",
                                "failed", "failed_unknown_format"}
    assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["converted_at"])


# ---- Acceptance #12: log format -----------------------------------------

LOG_RE = re.compile(
    r"^## \[\d{4}-\d{2}-\d{2}\] autoconvert \| .+ → raw/.+\.md \(.+\)$"
)


def test_log_line_format(wiki: Path, env_scrubbed):
    (wiki / "entry" / "log1.txt").write_text("a\n")
    _run(str(wiki), env=env_scrubbed)
    log = (wiki / "log.md").read_text().splitlines()
    autoconvert_lines = [ln for ln in log if ln.startswith("## [") and "autoconvert" in ln]
    assert autoconvert_lines, log
    for ln in autoconvert_lines:
        assert LOG_RE.match(ln), f"bad log line: {ln!r}"


# ---- Acceptance #13/14: session_check.sh --------------------------------

def _session_check(wiki: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SESSION_CHECK), str(wiki)],
        env=env, capture_output=True, text=True, timeout=10,
    )


def test_session_check_silent_when_idle(wiki: Path, env_scrubbed):
    r = _session_check(wiki, env_scrubbed)
    assert r.returncode == 0
    assert r.stdout == "" and r.stderr == ""


def test_session_check_reports_pending_ingest(wiki: Path, env_scrubbed):
    (wiki / "raw" / "abc.md").write_text("---\ntype: raw_source\n---\nx\n")
    r = _session_check(wiki, env_scrubbed)
    assert r.returncode == 0
    assert "WIKI:" in r.stdout
    assert "raw/ awaiting ingest:" in r.stdout
    assert "1" in r.stdout


# ---- Acceptance #15: watch_entry.sh initial pass ------------------------

def test_watch_entry_runs_initial_pass(wiki: Path, env_scrubbed):
    (wiki / "entry" / "seed.txt").write_text("seed\n")
    proc = subprocess.Popen(
        ["bash", str(WATCH), str(wiki)],
        env=env_scrubbed, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        # Give it time to do the initial autoconvert pass and start watching.
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                m = json.loads((wiki / ".wiki" / ".converted.json").read_text())
            except Exception:
                m = {}
            if "seed.txt" in m:
                break
            time.sleep(0.2)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    m = json.loads((wiki / ".wiki" / ".converted.json").read_text())
    assert "seed.txt" in m, "watcher did not run initial pass"


# ---- Acceptance #16: read-only upstream ---------------------------------

LEGACY_DIRS = ("LLM_Wiki", "RAG-Wiki", "Local_MCP_Server")


def test_no_writes_to_legacy_folders(wiki: Path, env_scrubbed):
    """End-of-suite guard: snapshot legacy dirs before/after a run; no
    new files allowed."""
    snaps = {}
    for d in LEGACY_DIRS:
        p = WORKSPACE_ROOT / d
        if p.exists():
            snaps[d] = {q.relative_to(p) for q in p.rglob("*")}
    (wiki / "entry" / "z.txt").write_text("z\n")
    _run(str(wiki), env=env_scrubbed)
    for d, before in snaps.items():
        p = WORKSPACE_ROOT / d
        after = {q.relative_to(p) for q in p.rglob("*")}
        new = after - before
        assert not new, f"M2 wrote into read-only upstream {d}: {new}"
