"""Acceptance tests for M6 — Cron / watch ops.

Mapped to contract criteria 1–20 in START-PROMPT.md §5.

Test isolation strategy:
- PATH is scrubbed to a tmpdir containing only stable POSIX tools.
- 'crontab' is replaced by a stub that reads/writes a per-test temp file
  (pointed to by the CRONTAB_FILE env var).
- 'install_wiki_bin.sh' uses LLMWIKI_SRC_DIR to point at the real src/wiki/.
- Interactive confirmation is injected via subprocess stdin (b"y\\n" or b"n\\n").
- Read-only upstream guard: sha256-tree equality before/after for legacy dirs.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
sys.path.insert(0, str(SRC))

from wiki.init import init  # noqa: E402

INSTALL_CRON = REPO_ROOT / "src" / "wiki" / "install_cron.sh"
UNINSTALL_CRON = REPO_ROOT / "src" / "wiki" / "uninstall_cron.sh"
INSTALL_BIN = REPO_ROOT / "src" / "wiki" / "install_wiki_bin.sh"
LINT_CRON = REPO_ROOT / "src" / "wiki" / "lint_cron.sh"
SRC_WIKI = REPO_ROOT / "src" / "wiki"

_REQUIRED_TOOLS = (
    "bash", "python3", "diff", "grep", "awk", "sed", "date", "find",
    "mkdir", "cat", "cp", "mv", "rm", "chmod", "printf", "touch",
    "basename", "dirname", "head", "wc", "sort", "tee", "env", "id",
    "true", "false", "test", "[", "uname", "readlink", "cut", "tail",
    "ln", "ls", "stat",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def scrubbed_bin(tmp_path: Path) -> Path:
    """Directory with stable POSIX tools + a crontab stub."""
    bindir = tmp_path / "scrubbed-bin"
    bindir.mkdir()
    for tool in _REQUIRED_TOOLS:
        src = shutil.which(tool)
        if src:
            try:
                os.symlink(src, bindir / tool)
            except FileExistsError:
                pass
    return bindir


@pytest.fixture
def crontab_file(tmp_path: Path) -> Path:
    """Path to the file the crontab stub uses as its backing store."""
    return tmp_path / "crontab.txt"


@pytest.fixture
def scrubbed_env(scrubbed_bin: Path, crontab_file: Path) -> dict:
    """Environment with scrubbed PATH + crontab stub + LLMWIKI_SRC_DIR."""
    # Write the crontab stub script.
    stub = scrubbed_bin / "crontab"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'CRONTAB_FILE="${CRONTAB_FILE:-/tmp/stub-crontab.txt}"\n'
        'case "${1:-}" in\n'
        "  -l)\n"
        '    cat "$CRONTAB_FILE" 2>/dev/null || true\n'
        "    ;;\n"
        "  -)\n"
        '    cat > "$CRONTAB_FILE"\n'
        "    ;;\n"
        "  *)\n"
        '    echo "crontab stub: unknown args: $*" >&2\n'
        "    exit 1\n"
        "    ;;\n"
        "esac\n"
    )
    stub.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = str(scrubbed_bin)
    env["CRONTAB_FILE"] = str(crontab_file)
    env["LLMWIKI_SRC_DIR"] = str(SRC_WIKI)
    return env


@pytest.fixture
def no_crontab_env(scrubbed_bin: Path, crontab_file: Path) -> dict:
    """Scrubbed PATH with NO crontab stub — simulates crontab absent."""
    # Remove the crontab stub if it somehow exists.
    stub = scrubbed_bin / "crontab"
    if stub.exists():
        stub.unlink()
    env = os.environ.copy()
    env["PATH"] = str(scrubbed_bin)
    env["CRONTAB_FILE"] = str(crontab_file)
    env["LLMWIKI_SRC_DIR"] = str(SRC_WIKI)
    return env


@pytest.fixture
def wiki(tmp_path: Path) -> Path:
    target = tmp_path / "wiki-test"
    return init("Test Domain", "A unit-test wiki.", str(target))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_install(wiki_root: Path | str | None, env: dict,
                 answer: bytes = b"y\n",
                 timeout: int = 15) -> subprocess.CompletedProcess:
    args = ["bash", str(INSTALL_CRON)]
    if wiki_root is not None:
        args.append(str(wiki_root))
    return subprocess.run(
        args, env=env, capture_output=True, input=answer, timeout=timeout,
    )


def _run_uninstall(wiki_root: Path | str | None, env: dict,
                   answer: bytes = b"y\n",
                   timeout: int = 15) -> subprocess.CompletedProcess:
    args = ["bash", str(UNINSTALL_CRON)]
    if wiki_root is not None:
        args.append(str(wiki_root))
    return subprocess.run(
        args, env=env, capture_output=True, input=answer, timeout=timeout,
    )


def _run_install_bin(wiki_root: Path | str | None, env: dict,
                     timeout: int = 15) -> subprocess.CompletedProcess:
    args = ["bash", str(INSTALL_BIN)]
    if wiki_root is not None:
        args.append(str(wiki_root))
    return subprocess.run(
        args, env=env, capture_output=True, timeout=timeout,
    )


def _sha256_tree(root: Path) -> dict[str, str]:
    """Return {relative_path: sha256_hex} for every file under root."""
    result: dict[str, str] = {}
    for f in sorted(root.rglob("*")):
        if f.is_file():
            h = hashlib.sha256(f.read_bytes()).hexdigest()
            result[str(f.relative_to(root))] = h
    return result


def _read_crontab(env: dict) -> str:
    cf = env.get("CRONTAB_FILE", "")
    if cf and Path(cf).exists():
        return Path(cf).read_text()
    return ""


# ---------------------------------------------------------------------------
# AC 1 — walk-up acceptance
# ---------------------------------------------------------------------------

def test_walkup_acceptance(wiki: Path, scrubbed_env: dict):
    sub = wiki / "deep" / "nested"
    sub.mkdir(parents=True)
    r = _run_install(sub, scrubbed_env)
    assert r.returncode == 0, r.stderr.decode()
    crontab = _read_crontab(scrubbed_env)
    assert "llm-wiki-builder" in crontab


# ---------------------------------------------------------------------------
# AC 2 — non-wiki arg rejection
# ---------------------------------------------------------------------------

def test_rejects_non_wiki_arg(tmp_path: Path, scrubbed_env: dict):
    not_wiki = tmp_path / "empty-dir"
    not_wiki.mkdir()
    r = _run_install(not_wiki, scrubbed_env)
    assert r.returncode != 0
    assert b"SCHEMA.md" in r.stderr
    # Nothing written anywhere under not_wiki
    for leaked in ("entry", "raw", ".wiki", "log.md"):
        assert not (not_wiki / leaked).exists()


# ---------------------------------------------------------------------------
# AC 3 — symlink wiki-root rejection → exit 4
# ---------------------------------------------------------------------------

def test_symlink_wiki_root_rejected(wiki: Path, tmp_path: Path, scrubbed_env: dict):
    link = tmp_path / "wiki-link"
    os.symlink(wiki, link)
    r = _run_install(link, scrubbed_env)
    assert r.returncode == 4
    assert b"ERR_SECURITY" in r.stderr
    # crontab untouched
    assert _read_crontab(scrubbed_env) == ""


def test_symlink_wiki_root_rejected_uninstall(wiki: Path, tmp_path: Path,
                                              scrubbed_env: dict):
    link = tmp_path / "wiki-link"
    os.symlink(wiki, link)
    r = _run_uninstall(link, scrubbed_env)
    assert r.returncode == 4
    assert b"ERR_SECURITY" in r.stderr


# ---------------------------------------------------------------------------
# AC 4 — user abort
# ---------------------------------------------------------------------------

def test_user_abort_leaves_crontab_unchanged(wiki: Path, scrubbed_env: dict,
                                             crontab_file: Path):
    # Seed an unrelated crontab entry.
    crontab_file.write_text("*/5 * * * * /usr/bin/echo hello\n")
    before_ct = crontab_file.read_text()
    before_log = (wiki / "log.md").read_text()
    r = _run_install(wiki, scrubbed_env, answer=b"n\n")
    assert r.returncode == 0
    assert crontab_file.read_text() == before_ct
    assert (wiki / "log.md").read_text() == before_log


def test_uninstall_abort_leaves_crontab_unchanged(wiki: Path, scrubbed_env: dict,
                                                  crontab_file: Path):
    _run_install(wiki, scrubbed_env, answer=b"y\n")
    before_ct = crontab_file.read_text()
    before_log = (wiki / "log.md").read_text()
    r = _run_uninstall(wiki, scrubbed_env, answer=b"n\n")
    assert r.returncode == 0
    assert crontab_file.read_text() == before_ct
    assert (wiki / "log.md").read_text() == before_log


# ---------------------------------------------------------------------------
# AC 5 — diff shown before confirmation
# ---------------------------------------------------------------------------

def test_diff_shown_before_install(wiki: Path, scrubbed_env: dict):
    r = _run_install(wiki, scrubbed_env, answer=b"y\n")
    combined = r.stdout.decode() + r.stderr.decode()
    assert "===" in combined, "Expected diff header not found"


def test_diff_shown_before_uninstall(wiki: Path, scrubbed_env: dict):
    _run_install(wiki, scrubbed_env, answer=b"y\n")
    r = _run_uninstall(wiki, scrubbed_env, answer=b"n\n")
    combined = r.stdout.decode() + r.stderr.decode()
    assert "===" in combined


# ---------------------------------------------------------------------------
# AC 6 — idempotent install
# ---------------------------------------------------------------------------

def test_idempotent_install_one_block_two_log_lines(wiki: Path, scrubbed_env: dict):
    _run_install(wiki, scrubbed_env, answer=b"y\n")
    _run_install(wiki, scrubbed_env, answer=b"y\n")
    crontab = _read_crontab(scrubbed_env)
    name = wiki.name
    tag = f"# llm-wiki-builder:{name}"
    # Exactly one start tag and one end tag.
    assert crontab.count(tag + "\n") == 1, crontab
    assert crontab.count(f"{tag}-end") == 1, crontab
    # Exactly two install log lines.
    log = (wiki / "log.md").read_text()
    install_lines = [l for l in log.splitlines()
                     if re.match(r"^## \[\d{4}-\d{2}-\d{2}\] cron \| install \|", l)]
    assert len(install_lines) == 2


# ---------------------------------------------------------------------------
# AC 7 — scheduled jobs correct
# ---------------------------------------------------------------------------

def test_scheduled_jobs_in_crontab(wiki: Path, scrubbed_env: dict):
    _run_install(wiki, scrubbed_env, answer=b"y\n")
    crontab = _read_crontab(scrubbed_env)
    # autoconvert.sh every 15 minutes
    assert re.search(r"\*/15\s+\*\s+\*\s+\*\s+\*.*autoconvert\.sh", crontab), crontab
    # lint_cron.sh on Monday 06:23
    assert re.search(r"23\s+6\s+\*\s+\*\s+1.*lint_cron\.sh", crontab), crontab
    # sync.sh must NOT appear as a scheduled entry (comment is allowed)
    cron_lines = [l for l in crontab.splitlines()
                  if not l.strip().startswith("#") and "sync.sh" in l]
    assert cron_lines == [], f"sync.sh scheduled unexpectedly: {cron_lines}"


# ---------------------------------------------------------------------------
# AC 8 — crontab absent → graceful degrade → exit 2
# ---------------------------------------------------------------------------

def test_no_crontab_graceful_degrade(wiki: Path, no_crontab_env: dict):
    r = _run_install(wiki, no_crontab_env, answer=b"y\n")
    assert r.returncode == 2
    combined = r.stdout.decode() + r.stderr.decode()
    assert "WARNING" in combined or "warning" in combined.lower()
    # log.md still gets the install line
    log = (wiki / "log.md").read_text()
    assert re.search(r"^## \[\d{4}-\d{2}-\d{2}\] cron \| install \|", log, re.M)
    # cron.log created
    assert (wiki / ".wiki" / "cron.log").exists()


# ---------------------------------------------------------------------------
# AC 9 — log line format (install)
# ---------------------------------------------------------------------------

def test_install_log_line_format(wiki: Path, scrubbed_env: dict):
    _run_install(wiki, scrubbed_env, answer=b"y\n")
    log = (wiki / "log.md").read_text()
    matches = [l for l in log.splitlines()
               if re.match(r"^## \[\d{4}-\d{2}-\d{2}\] cron \| install \| .+$", l)]
    assert len(matches) == 1, f"Expected 1 install log line, found: {matches}"


# ---------------------------------------------------------------------------
# AC 10 — uninstall no-op when no block present
# ---------------------------------------------------------------------------

def test_uninstall_noop_no_block(wiki: Path, scrubbed_env: dict, crontab_file: Path):
    # Give the crontab stub some unrelated content.
    crontab_file.write_text("*/5 * * * * /usr/bin/echo hi\n")
    before_log = (wiki / "log.md").read_text()
    r = _run_uninstall(wiki, scrubbed_env)
    assert r.returncode == 0
    combined = r.stdout.decode() + r.stderr.decode()
    assert "Nothing to do" in combined or "nothing" in combined.lower() or "No cron" in combined
    # log.md unchanged
    assert (wiki / "log.md").read_text() == before_log


# ---------------------------------------------------------------------------
# AC 11 — uninstall removes block
# ---------------------------------------------------------------------------

def test_uninstall_removes_block(wiki: Path, scrubbed_env: dict):
    _run_install(wiki, scrubbed_env, answer=b"y\n")
    name = wiki.name
    assert f"llm-wiki-builder:{name}" in _read_crontab(scrubbed_env)

    _run_uninstall(wiki, scrubbed_env, answer=b"y\n")
    crontab_after = _read_crontab(scrubbed_env)
    assert f"llm-wiki-builder:{name}" not in crontab_after
    # One uninstall log line added
    log = (wiki / "log.md").read_text()
    assert re.search(r"^## \[\d{4}-\d{2}-\d{2}\] cron \| uninstall \|", log, re.M)


# ---------------------------------------------------------------------------
# AC 12 — log line format (uninstall)
# ---------------------------------------------------------------------------

def test_uninstall_log_line_format(wiki: Path, scrubbed_env: dict):
    _run_install(wiki, scrubbed_env, answer=b"y\n")
    _run_uninstall(wiki, scrubbed_env, answer=b"y\n")
    log = (wiki / "log.md").read_text()
    matches = [l for l in log.splitlines()
               if re.match(r"^## \[\d{4}-\d{2}-\d{2}\] cron \| uninstall \| .+$", l)]
    assert len(matches) == 1, f"Expected 1 uninstall log line, found: {matches}"


# ---------------------------------------------------------------------------
# AC 13 — install_wiki_bin populates bin/
# ---------------------------------------------------------------------------

def test_install_wiki_bin_populates_bin(wiki: Path, scrubbed_env: dict):
    r = _run_install_bin(wiki, scrubbed_env)
    assert r.returncode == 0, r.stderr.decode()
    bin_dir = wiki / ".wiki" / "bin"
    assert bin_dir.is_dir()
    # Every .sh and .py in src/wiki/ should be present.
    for f in SRC_WIKI.glob("*.sh"):
        assert (bin_dir / f.name).exists(), f"Missing {f.name} in bin/"
        assert os.access(bin_dir / f.name, os.X_OK), f"{f.name} not executable"
    for f in SRC_WIKI.glob("*.py"):
        assert (bin_dir / f.name).exists(), f"Missing {f.name} in bin/"


# ---------------------------------------------------------------------------
# AC 14 — install_wiki_bin idempotent
# ---------------------------------------------------------------------------

def test_install_wiki_bin_idempotent(wiki: Path, scrubbed_env: dict):
    _run_install_bin(wiki, scrubbed_env)
    hashes_first = {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest()
        for f in (wiki / ".wiki" / "bin").glob("*")
        if f.is_file()
    }
    _run_install_bin(wiki, scrubbed_env)
    hashes_second = {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest()
        for f in (wiki / ".wiki" / "bin").glob("*")
        if f.is_file()
    }
    assert hashes_first == hashes_second
    # sha256 of each copied file == source
    for f in SRC_WIKI.glob("*.sh"):
        src_h = hashlib.sha256(f.read_bytes()).hexdigest()
        dst_h = hashes_second[f.name]
        assert src_h == dst_h, f"Hash mismatch for {f.name}"


# ---------------------------------------------------------------------------
# AC 15 — install_cron.sh calls install_wiki_bin (bin/ populated)
# ---------------------------------------------------------------------------

def test_install_cron_populates_bin(wiki: Path, scrubbed_env: dict):
    bin_dir = wiki / ".wiki" / "bin"
    assert not bin_dir.exists() or not list(bin_dir.glob("*.sh"))
    _run_install(wiki, scrubbed_env, answer=b"y\n")
    assert bin_dir.is_dir()
    assert (bin_dir / "autoconvert.sh").exists()


# ---------------------------------------------------------------------------
# AC 16 — install_wiki_bin path safety (symlink root → exit 4)
# ---------------------------------------------------------------------------

def test_install_wiki_bin_rejects_symlink_root(wiki: Path, tmp_path: Path,
                                               scrubbed_env: dict):
    link = tmp_path / "wiki-link"
    os.symlink(wiki, link)
    r = _run_install_bin(link, scrubbed_env)
    assert r.returncode == 4
    assert b"ERR_SECURITY" in r.stderr


# ---------------------------------------------------------------------------
# AC 17 — lint_cron.sh invokes graph_lint.py with --log
# ---------------------------------------------------------------------------

def test_lint_cron_invokes_graph_lint(wiki: Path, tmp_path: Path,
                                      scrubbed_env: dict):
    # Populate .wiki/bin/ with real scripts.
    _run_install_bin(wiki, scrubbed_env)

    # Replace python3 in scrubbed bin with a stub that records argv.
    record_file = tmp_path / "py3-calls.txt"
    py3_stub = Path(scrubbed_env["PATH"]) / "python3"
    # Rewrite the python3 symlink as a recording shim.
    py3_stub.unlink(missing_ok=True)
    real_py3 = shutil.which("python3")
    assert real_py3
    py3_stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> {record_file}\n'
        # Actually run the real python3 so graph_lint.py works.
        f'exec {real_py3} "$@"\n'
    )
    py3_stub.chmod(0o755)

    r = subprocess.run(
        ["bash", str(LINT_CRON), str(wiki)],
        env=scrubbed_env, capture_output=True, timeout=30,
    )
    # We don't gate on exit code (graph_lint may return non-0 for empty wiki).
    # Check that graph_lint.py was called with --log.
    assert record_file.exists(), "python3 stub never called"
    calls = record_file.read_text()
    assert "graph_lint.py" in calls, calls
    assert "--log" in calls, calls


# ---------------------------------------------------------------------------
# AC 18 — read-only upstream guard
# ---------------------------------------------------------------------------

def test_read_only_upstream_guard(wiki: Path, scrubbed_env: dict):
    UPSTREAM_DIRS = ["LLM_Wiki", "RAG-Wiki", "Local_MCP_Server"]
    workspace_root = REPO_ROOT.parent

    snapshots_before = {}
    for d in UPSTREAM_DIRS:
        p = workspace_root / d
        if p.exists():
            snapshots_before[d] = _sha256_tree(p)

    _run_install(wiki, scrubbed_env, answer=b"y\n")
    _run_uninstall(wiki, scrubbed_env, answer=b"y\n")

    for d, before in snapshots_before.items():
        after = _sha256_tree(workspace_root / d)
        assert before == after, f"Upstream {d} was modified!"

    # Also check raw/ and entry/ within wiki.
    for protected in ("raw", "entry"):
        p = wiki / protected
        if p.exists():
            for f in p.rglob("*"):
                assert f.is_dir() or f.stat().st_mtime < os.stat(INSTALL_CRON).st_mtime + 0.1


# ---------------------------------------------------------------------------
# AC 19 — no *.tmp files after any run
# ---------------------------------------------------------------------------

def test_no_tmp_files_after_install(wiki: Path, scrubbed_env: dict):
    _run_install(wiki, scrubbed_env, answer=b"y\n")
    tmp_files = list(wiki.rglob("*.tmp"))
    assert tmp_files == [], f"Unexpected .tmp files: {tmp_files}"


def test_no_tmp_files_after_install_bin(wiki: Path, scrubbed_env: dict):
    _run_install_bin(wiki, scrubbed_env)
    tmp_files = list(wiki.rglob("*.tmp"))
    assert tmp_files == [], f"Unexpected .tmp files: {tmp_files}"


def test_no_tmp_files_after_abort(wiki: Path, scrubbed_env: dict):
    _run_install(wiki, scrubbed_env, answer=b"n\n")
    tmp_files = list(wiki.rglob("*.tmp"))
    assert tmp_files == [], f"Unexpected .tmp files: {tmp_files}"
