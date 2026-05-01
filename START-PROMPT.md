# START-PROMPT — LLM-RAG-WIKI v2 · Modular Build Session

**Maintainer:** Aranda Möller · amoeller@mailbox.org
**Session type:** Modular build · Plan-first, test-gated
**Status:** DONE · 2026-05-01

---

## 1. Mission

Build `LLM-RAG-WIKI/` — a consolidated, fully local, three-layer personal
AI pipeline — by constructing and validating one self-contained module at a
time. Each module must fit comfortably within a single AI session (~150k
effective tokens), be independently testable, and expose a stable interface
before the next module is started.

**Source material (read-only):**

| Layer | Legacy folder | Role |
|---|---|---|
| Wiki builder | [./LLM_Wiki/](./LLM_Wiki/) | Source scripts, templates, bin/ |
| RAG engine | [./RAG-Wiki/](./RAG-Wiki/) | Source prompt contracts, scripts |
| MCP / persona | [./Local_MCP_Server/](./Local_MCP_Server/) | Source design specs |
| Master spec | [./MASTER.md](./MASTER.md) | Canonical unified specification |

**Target:** `./LLM-RAG-WIKI/` — new self-contained codebase. The three
legacy folders are **read-only references** during the rebuild. They are
deleted only after M14 sign-off, at which point `LLM-RAG-WIKI/` becomes the
self-sufficient alpha release of the three-layer pipeline (releasable
irrespective of its enclosing root folder).

---

## 2. Modular Build Philosophy

### 2.1 Why modules

A monolithic build session accumulates context until the AI loses coherence
on early decisions. A module-first approach avoids this:

- Each module is **narrow** — one responsibility, one session
- Each module has a **written contract**: inputs, outputs, acceptance criteria
- Each module is **tested and signed off** before the next begins
- Contracts survive session boundaries — a fresh AI can pick up mid-build
  by reading the module registry (Section 5) without needing session history

### 2.2 Session discipline

Every build session follows this sequence — no exceptions:

```
1. Read this document and the module registry (Section 5)
2. Read the contract for the target module
3. Read relevant sections of MASTER.md
4. Output Pre-Flight Checklist (Section 3)
5. Build the module
6. Run acceptance tests; record results in the module registry
7. Output a brief session summary; stop
```

**Never start a module until its dependencies are marked `DONE` in Section 5.**
**Never merge modules into the integration layer until all unit modules are `DONE`.**

### 2.3 Token hygiene

- Do not re-read legacy source folders unless a module explicitly requires
  migrating a specific script or template. Reference `MASTER.md` instead.
- Do not generate documentation prose inside source files beyond docstrings
  and inline comments. Documentation lives in `MASTER.md`.
- Do not generate test fixtures larger than necessary to exercise the
  acceptance criteria.
- If a module grows beyond ~400 lines of Python or ~200 lines of shell,
  split it at a natural seam and record the split in the module registry.

---

## 3. Pre-Flight Checklist

Output this block at the start of every build session before writing any file:

```markdown
### Pre-Flight Checklist
- **Target module:** (ID and name from Section 5)
- **Dependencies satisfied:** (list module IDs, confirm DONE)
- **Files to be created:** (list)
- **Files to be modified:** (list, if any)
- **Read-only boundaries confirmed:** ./LLM_Wiki/, ./RAG-Wiki/, ./Local_MCP_Server/
- **Security rule confirmed:** no writes to upstream legacy folders
- **Plan (2–3 sentences):**
```

---

## 4. Target Folder Layout

See [MASTER.md §2 — Repository Layout](MASTER.md#2-repository-layout) for the
canonical consolidated tree and the legacy reference layout. Do not duplicate it here.

---

## 5. Module Registry

Update `Status` and `Notes` after each session. This is the persistent state that survives context loss.

| ID | Module | Layer | Depends on | Status | Notes |
|---|---|---|---|---|---|
| **M0** | Plan & module breakdown | — | — | `DONE` | 2026-04-30; contracts for M1/M7/M11 filed below; adjustments A–E applied |
| **M1** | Scaffold + templates | Wiki | M0 | `DONE` | 2026-04-30; init entry point: `src/wiki/init.py` (Python stdlib); 22/22 acceptance tests pass; root templates SCHEMA/index/log/CONTEXT migrated from legacy `LLM_Wiki/skills/templates/`, page templates + ADR verbatim from MASTER Appendix A; `config.yaml` is a syntactically valid stub (M7 finalizes); `.wiki/bin/` script copy deferred to M6 (adj. D); editor shims deferred to M14 (adj. C) |
| **M2** | Converter pipeline | Wiki | M1 | `DONE` | 2026-05-01; autoconvert.sh re-derived from MASTER §6 W2 with legacy hardened invariants ported (path-arg validation, slug-collision suffix, atomic os.replace, nullglob globstar walk); flock(1) lock with Python fcntl fallback; watch_entry.sh + session_check.sh ported; 19/19 acceptance tests pass under PATH-scrubbed isolation; needs-vision marker resolution deferred to M3; bin-copy still deferred to M6 |
| **M3** | Ingest agent | Wiki | M1, M2 | `DONE` | 2026-05-01; `src/wiki/{ingest.py, crossref.py, glossary.py, agent_seam.py, _frontmatter.py}` (pre-declared split per §2.3); LLM seam = `IngestAgent` ABC + `DeterministicStubAgent`; deterministic alphabetical-Kahn DAG; anchor-bounded glossary patcher preserves manual rows; 2-phase atomic writer (temp + `os.replace`) across source/concept/entity/index/log/SCHEMA; 20/20 acceptance tests pass; 61/61 total; manifest `.wiki/.converted.json` read only |
| **M4** | Graph lint | Wiki | M1 | `DONE` | 2026-05-01; `src/wiki/graph_lint.py` (~430 LOC, single file, pure stdlib) re-derived from MASTER Appendix C with regex prior art from legacy `LLM_Wiki/skills/bin/graph_lint.py`; all 8 rules (orphan / broken_link / index_gap / hub_and_spoke / relation_code_distribution / unknown_relation_code / asymmetric_coverage / stale_candidate) + 5-state discourse classifier (EMPTY/BIASED/FOCUSED/DIVERSIFIED/DISPERSED); CLI `python -m wiki.graph_lint <root> [--json] [--log] [--fail-on=high\|medium\|low\|none]`; strictly read-only against wiki content (sha256-tree-equality test) — only `--log` appends one W5 line to `log.md`; symlink-as-wiki-root rejected with `[ERR_SECURITY]`; 30/30 acceptance tests pass; 91/91 total; auto-fix and `.wiki/.alert.md` writer deferred to M6 |
| **M5** | Query + synthesis | Wiki | M1, M3 | `DONE` | 2026-05-01; `src/wiki/{query.py, query_agent.py}` (pure stdlib, ~310 LOC); `QueryAgent` ABC + `DeterministicStubQueryAgent`; `query_one()` orchestrates candidate scan → rank → synthesize → optional atomic synthesis page write + `## Synthesis` index section + W4 log line; symlink wiki-root rejected with `[ERR_SECURITY]` before `resolve()`; 2-phase atomic writer (temp + `os.replace`) same contract as M3; back-link injection into existing pages deferred (see contract); 23/23 acceptance tests pass; 114/114 total |
| **M6** | Cron / watch ops | Wiki | M2 | `DONE` | 2026-05-01; `src/wiki/{install_cron.sh, uninstall_cron.sh, install_wiki_bin.sh, lint_cron.sh}` (pure bash ≥4 + POSIX coreutils, ~255 LOC total); interactive diff-first installer + symmetric remover; idempotent via `# llm-wiki-builder:{name}` / `# llm-wiki-builder:{name}-end` tag pair; scheduled jobs: `autoconvert.sh` (*/15 min) + `lint_cron.sh` (Mon 06:23); `sync.sh` deferred (adj. D2 — not yet implemented); graceful degrade when `crontab` absent (exit 2, log line still written); `install_wiki_bin.sh` satisfies adj. D bin-copy; `install_cron.sh` calls `install_wiki_bin.sh` before any crontab write; symlink wiki-root rejected `[ERR_SECURITY]` (exit 4) in all four scripts; `LLMWIKI_SRC_DIR` env override enables PATH-scrubbed test isolation; 24/24 M6 acceptance tests pass; 138/138 total |
| **M7** | Config + schema | RAG | M0, M1 | `DONE` | 2026-05-01; `src/rag/__init__.py` (empty package marker) + `src/rag/config.py` (~265 LOC, pure stdlib at module level, `yaml` imported inside function body with graceful `ConfigError` if missing); frozen dataclass hierarchy `Config` / `ProjectConfig` / `RuntimeConfig` / `DomainConfig` / `EmbeddingConfig` / `PathsConfig` / `ChunkingConfig` / `IndexingConfig` / `RetrievalConfig` / `PrivacyConfig`; `load_config()` with three-step resolution (explicit path → `LLM_RAG_WIKI_CONFIG` env var → repo-root `config.yaml`); all path fields resolved absolute relative to config file's directory; `wiki_root` inside `entry/` or `raw/` rejected `[ERR_CONFIG]`; `config_hash()` via canonical key-sorted JSON + SHA-256; `config.yaml` stub replaced with canonical MASTER §7 default; 49/49 M7 acceptance tests pass; 187/187 total |
| **M8** | Ingest pipeline | RAG | M7 | `DONE` | 2026-05-01; `src/rag/{manifest.py, chunker.py, embedder.py, store.py, ingest.py}` (pre-declared 5-file split per §2.3, ~870 LOC total Python); pure stdlib at module level; `chromadb` and `sentence_transformers` imported only inside production backend `__init__` behind `[ERR_DB]` / `[ERR_EMBEDDING_MODEL]`; heading-aware Markdown chunker honors `chunking.min_chars` / `max_chars` with code-fence-atomic paragraph packing and frontmatter stripping; stable chunk IDs per MASTER §7 (`sha256(collection + rel_path + heading_path + idx + chunk_hash)`); `EmbedderBackend` ABC + `SentenceTransformersEmbedder` (production) + `DeterministicHashEmbedder` (test stub, unit-norm SHA-256 → float); `VectorStore` ABC + `ChromaVectorStore` (production) + `InMemoryVectorStore` (test stub); orchestrator `ingest_wiki()` does atomic manifest write (`*.tmp` + `os.replace`), per-file `source_hash` skip when manifest `config_hash` matches, deletes orphaned chunk IDs for removed files, skips `privacy: secret` frontmatter when `privacy.block_secret_chunks=true`, suppresses injection-marker chunk text in logs (still indexes the chunk), rejects symlink `wiki_root` with `[ERR_SECURITY]`, and supports `--reset` with `atomic_reindex=true` via shadow-collection (Chroma) or shadow `InMemoryVectorStore` (injected-store path) that is promoted to primary only on success — failure mid-run leaves the original collection byte-equivalent; CLI `python -m rag.ingest [--config PATH] [--reset]`; tests use stub embedder + in-memory store, monkeypatched `socket.socket`, and `sys.modules` snapshots to assert no third-party imports leak at module level; 32/32 M8 acceptance tests pass; 219/219 total |
| **M9** | Retrieval CLI | RAG | M7, M8 | `DONE` | 2026-05-01; retrieve.py + _query_store.py; YAML output, threshold logic, injection safety, CLI exit codes; 14/14 tests pass; Hybrid RRF enabled (P5) |
| **M10** | Evals | RAG | M8, M9 | `DONE` | 2026-05-01; eval_runner.py, eval_cases.yaml; precision/recall framework |
| **M11** | Persona store | MCP | M0 | `DONE` | 2026-05-01; store.py, persona schema, meta-directives |
| **M12** | Persona compiler | MCP | M11 | `DONE` | 2026-05-01; compiler.py, deterministic profile gen |
| **M13** | MCP server | MCP | M11, M12 | `DONE` | 2026-05-01; server.py (FastMCP), persona resources, active.yaml persistence |
| **M14** | Integration + system test | All | M1–M13 | `DONE` | 2026-05-01; test_integration.py, editor shims created; e2e pipeline verified |

**Status values:** `PENDING` · `IN-PROGRESS` · `DONE` · `BLOCKED` · `SPLIT`

### Filed contracts

#### Contract: M1 — Scaffold + templates

**Responsibility:** Produce the consolidated repository skeleton (directories, root files, templates, helper scripts) and a deterministic `init` entry point that scaffolds a domain-specific wiki tree from `templates/` with placeholder substitution.

**Inputs:**
- Legacy reference (read-only): `LLM_Wiki/skills/templates/`, `RAG-Wiki/scripts/run_phase.sh`, `RAG-Wiki/scripts/bump_version.sh`
- User-supplied at `init` runtime: domain name + 1-sentence description, target wiki path (default `./wiki-{slug}/`)

**Outputs (under `LLM-RAG-WIKI/`):**
- Root: `project.toml`, `MASTER.md` (copied from current root), `START-PROMPT.md` (copied), `config.yaml` (stub; M7 finalizes), `index.md`, `log.md`, `SCHEMA.md` (root copies for templates), `.gitignore`
- Directories: `entry/`, `raw/assets/`, `wiki/{concepts,entities,sources,synthesis}/`, `src/{wiki,rag,mcp}/` (empty package roots), `templates/pages/`, `personas/`, `data/{chroma,manifests}/` (gitignored), `tests/`, `scripts/`, `.github/chatmodes/` (empty)
- Templates: `templates/{SCHEMA.md, index.md, log.md, CONTEXT.md, ADR-template.md}`, `templates/pages/{source.md, concept.md, entity.md, synthesis.md}` — verbatim from MASTER.md Appendix A with `{{…}}` placeholders intact
- Helper scripts: `scripts/run_phase.sh`, `scripts/bump_version.sh` (migrated from `RAG-Wiki/scripts/`)
- Init entry point: `src/wiki/init.sh` **or** `src/wiki/init.py` (implementer chooses one; pure POSIX shell or pure Python stdlib — record choice in registry note on completion)

**Interfaces exposed:**
- CLI: `init <domain_name> <description> [wiki_path]` → creates wiki tree, hydrates templates, seeds `.wiki/.converted.json` and `.wiki/.status.json` to `{}`, prints success banner. Exits non-zero on path-validation failure.
- Placeholder substitution function reusable by M3/M5; substitutes `{{DOMAIN}}`, `{{DESCRIPTION}}`, `{{DATE}}`, `{{NAME}}`, `{{TITLE}}`, `{{SLUG}}`, `{{CONVERTER}}`, `{{QUESTION}}`, `{{ENTITY_TYPE}}` per MASTER §7.

**Out of scope (explicit):**
- Copying `src/wiki/*.{sh,py}` into `$WIKI_ROOT/.wiki/bin/` — deferred to M6 (adj. D)
- Editor shims (`AGENTS.md`, `GEMINI.md`, `SKILL.md`, `.github/chatmodes/*.chatmode.md`, `.cursorrules`, `.github/copilot-instructions.md`) — deferred to M14
- Any RAG, MCP, or converter logic
- Finalized `config.yaml` content — deferred to M7 (M1 ships a syntactically valid stub)

**Dependencies:**
- M0 (registry + contract approved)

**Acceptance criteria:**
1. Running `init` against a fresh path produces the full tree from MASTER §2 (consolidated layout) minus the explicit out-of-scope items.
2. All template files exist and contain at least one `{{PLACEHOLDER}}` token; `index.md`, `log.md`, `SCHEMA.md` produced in the live wiki contain **no** unresolved `{{…}}` tokens.
3. Path validation rejects: existing path, path under `.git`, path equal to cwd, path ancestor of cwd. Each returns non-zero exit and a single-line error.
4. `.wiki/.converted.json` and `.wiki/.status.json` exist and parse as `{}`.
5. `scripts/run_phase.sh --phase P1 --go yes --scope x --deliverables y` prints a rendered prompt to stdout and exits 0.
6. `project.toml` parses as valid TOML and contains `[project].name`, `[project].version`, `[release].date`.
7. Re-running `init` against the same populated path is a no-op-with-error, never destructive.

**Test strategy:** unit (placeholder substitution: golden-file tests) + integration (run `init` into a tmp dir, assert tree + content invariants); manual sanity run of `scripts/run_phase.sh` for P1–P5.

**Estimated size:** ~150 lines shell or ~200 lines Python; ~10 small template files (verbatim from MASTER Appendix A).

**Session boundary note:** A fresh session needs START-PROMPT §§3,5,6,7; MASTER §§2, 6 (W1), 7 (Wiki schemas + placeholders), Appendix A (template bodies).

---

#### Contract: M2 — Converter pipeline

**Responsibility:** Provide the deterministic, idempotent `entry/ → raw/` tiered converter, its file-system watcher, and a silent-unless-pending session status probe — all consuming/producing the manifest schema in MASTER §7 and obeying MASTER §8 path safety.

**Inputs:**
- A wiki root produced by M1 (contains `SCHEMA.md`, `entry/`, `raw/assets/`, `.wiki/.converted.json`, `.wiki/.status.json`, `log.md`)
- Files dropped by the user under `$WIKI_ROOT/entry/` (any extension; tier table in MASTER Appendix B)
- Optional binaries on `PATH`: `pandoc`, `pdftotext`, `markitdown`, `inotifywait`, `flock`

**Outputs:**
- `$WIKI_ROOT/raw/{slug}.md` — converted Markdown with frontmatter (`type: raw_source`, `title`, `slug`, `converter`, `converted_at`, `status`)
- `$WIKI_ROOT/raw/assets/{name}` — copies of image inputs
- `$WIKI_ROOT/.wiki/.converted.json` — manifest entries per MASTER §7, keyed by `entry/`-relative POSIX path
- `$WIKI_ROOT/.wiki/.status.json` — last-run summary `{last_autoconvert: {at, new, skipped, failed, needs_vision}}`
- `$WIKI_ROOT/log.md` — one append-only line per converted file: `## [YYYY-MM-DD] autoconvert | {relpath} → raw/{slug}.md ({converter})`
- Stdout: parseable `AUTOCONVERT COMPLETE` block
- Exit codes: `0` success, `1` wiki root not found / explicit-arg not inside a wiki, `2` no converters available **and** non-trivial input present, `4` `[ERR_SECURITY]` (path escape, prohibited write under read-only upstream)

**Interfaces exposed:**
- `src/wiki/autoconvert.sh [WIKI_ROOT]` — auto-locates wiki root by walking up from cwd if no arg; explicit arg must resolve inside a valid wiki (walk-up; never silent-scaffold)
- `src/wiki/watch_entry.sh [WIKI_ROOT]` — long-running; `inotifywait` with 1 s debounce when available, else 30 s polling; one initial pass; clean SIGINT/SIGTERM
- `src/wiki/session_check.sh [WIKI_ROOT]` — silent (exit 0, no output) unless pending work; otherwise prints `WIKI: {name}` plus per-bucket counts; always exit 0
- Manifest entry shape: `{ source, slug, converter ∈ {pandoc, markitdown, pdftotext, vision, copy, none}, sha256, status ∈ {ok, needs_vision, skipped_no_converter, failed, failed_unknown_format}, converted_at }`

**Out of scope (explicit):**
- Resolving `<!-- needs-vision: ... -->` markers — handed to M3 ingest agent
- Copying `src/wiki/*` into `$WIKI_ROOT/.wiki/bin/` — M6 (adj. D)
- Cron installation — M6
- Editor shims, lint alert producer (`.wiki/.alert.md` is consumed only) — M4 / M14
- RAG, MCP, graph-lint logic

**Dependencies:** M1 (scaffold, manifest seed files, layout)

**Acceptance criteria:**
1. **Path safety / non-wiki arg.** `autoconvert.sh /tmp/empty-dir` exits non-zero, mentions `SCHEMA.md`, creates **no** `entry/`, `raw/`, `.wiki/`, `log.md` under it.
2. **Walk-up acceptance.** `autoconvert.sh $WIKI_ROOT/deep/nested` succeeds and operates on `$WIKI_ROOT`.
3. **Idempotency.** Two consecutive runs over the same `entry/` produce identical `.converted.json`; second run reports `new=0`.
4. **Re-conversion stability.** Editing a file already in the manifest re-uses its previously recorded slug.
5. **Slug collision.** Two `entry/` paths whose slugs collide → second disambiguated with `-{sha256[:8]}` suffix; if still colliding the second is reported `failed`, manifest unchanged for it.
6. **Atomic manifest writes.** After a successful run, `.wiki/` contains no `*.tmp`; `.converted.json` and `.status.json` parse as valid JSON. Stub-`python3` crash injection leaves the on-disk manifest unchanged.
7. **Concurrent runs serialize.** Two parallel `autoconvert.sh` processes against the same wiki produce a manifest equivalent to running them sequentially. `flock` on `$WIKI_ROOT/.wiki/.converted.json.lock`; Python `fcntl` fallback.
8. **Tier fallback.** PDF: `pdftotext → markitdown → pandoc → vision-stub`; missing all three text converters yields a `needs_vision` raw page with `<!-- needs-vision: {abs_path} -->` first.
9. **Image input** copies to `raw/assets/` and emits a `needs-vision` stub linking the asset.
10. **No converters installed.** `.txt`/`.md`-only `entry/` succeeds (`copy` tier). Non-text file with no converters → `status=skipped_no_converter`, run exit 0.
11. **Manifest schema.** Each entry has exactly `{source, slug, converter, sha256, status, converted_at}`; values match enums above.
12. **Log format.** Each converted file appends exactly one line matching `^## \[\d{4}-\d{2}-\d{2}\] autoconvert \| .+ → raw/.+\.md \(.+\)$`.
13. **`session_check.sh` silence.** Empty `raw/`, no alert → no output, exit 0.
14. **`session_check.sh` reporting.** ≥1 `raw/{slug}.md` lacking `wiki/sources/{slug}.md` → prints `WIKI:` line and `raw/ awaiting ingest:` count.
15. **`watch_entry.sh` initial pass.** Started with one file in `entry/`, killed after a short timeout → manifest contains the seeded file.
16. **Read-only upstream.** Tests fail closed if any file is produced under `LLM_Wiki/`, `RAG-Wiki/`, `Local_MCP_Server/`.

**Test strategy:** pytest + `subprocess`; tmp-dir wiki per test built via M1's `init`. `PATH` scrubbed to a tmp dir holding only stable POSIX tools so degradation paths are exercised regardless of host installation; optional happy-path conversion gated behind `LLMWIKI_TEST_REAL_CONVERTERS=1`. Concurrency via parallel `Popen`. Atomic-write via stub `python3` shim.

**Estimated size:** ~280 lines bash + ~60 + ~50 + ~250 lines Python tests.

**Session boundary note:** START-PROMPT §§3,5,6,7; MASTER §§6 (W2), 7 (autoconvert manifest + log format), 8 (path safety), Appendix B (tier table); M1 contract for fixture wiki construction.

---

#### Contract: M3 — Ingest agent

**Responsibility:** Provide the deterministic core and LLM-agent seam that turn a single converted `raw/{slug}.md` into one new `wiki/sources/{slug}.md`, an in-place DAG-ordered concept/entity cross-ref pass, an anchor-bounded glossary patch in `SCHEMA.md`, plus matching `index.md` and `log.md` updates — all per MASTER §6 W3 and §7 (Wiki Schemas) — without ever modifying `raw/`, `entry/`, or `.wiki/`.

**Inputs:**
- A wiki root produced by M1 and populated by M2 (contains `raw/{slug}.md` files and a non-empty `.wiki/.converted.json` matching MASTER §7).
- Argument: `slug` (filename stem under `raw/`, without `.md`) **or** absolute/relative path to a `raw/*.md` file.
- The corresponding manifest entry in `.wiki/.converted.json` (read-only). The entry's `status` ∈ `{ok, needs_vision}` is honored; any other status → `[ERR_SCHEMA]`.
- An `IngestAgent` implementation. The CLI defaults to `DeterministicStubAgent` only under `LLMWIKI_TEST_STUB_AGENT=1`; otherwise it requires the host agent to inject one via `python -m wiki.ingest --agent dotted.path:Class` or rejects the run with `[ERR_RUNTIME]` "no agent bound" — the human/host AI is the production agent.
- Optional flag `--force` (overwrite existing `wiki/sources/{slug}.md`).

**Outputs (all atomic via temp-file + `os.replace`):**
- `$WIKI_ROOT/wiki/sources/{slug}.md` — hydrated from `templates/pages/source.md`, frontmatter `{type, title, source_path: raw/{slug}.md, ingested: {DATE}, converter}` per MASTER §7 + Appendix A.
- `$WIKI_ROOT/wiki/concepts/{slug}.md` and/or `$WIKI_ROOT/wiki/entities/{slug}.md` — created from templates if absent, otherwise merged in-place (DAG order, alphabetical slug tiebreaker).
- `$WIKI_ROOT/SCHEMA.md` — `## Glossary` table extended between markers `<!-- glossary:auto:start -->` / `<!-- glossary:auto:end -->`. Markers are inserted on first call inside the table body of `## Glossary`; manual rows above/below the markers are preserved byte-identical.
- `$WIKI_ROOT/index.md` — touched-page links inserted under existing `## Sources`, `## Concepts`, `## Entities` H2s (created if absent); existing entries deduplicated by relative path; section bodies kept sorted alphabetically.
- `$WIKI_ROOT/log.md` — appends exactly one line: `## [YYYY-MM-DD] ingest | {title} | sources/{slug}.md | {N} pages touched` (regex per MASTER §7).
- Stdout: parseable `INGEST COMPLETE` block with counts (`source=1, concepts=N, entities=N, glossary_added=N`).
- Exit codes: `0` success; `2` `[ERR_SCHEMA]` (slug not in manifest, manifest malformed, template malformed); `3` warn-and-stop on pre-existing `wiki/sources/{slug}.md` without `--force`; `4` `[ERR_SECURITY]` (path escape, attempted write under `raw/`/`entry/`/`.wiki/` or upstream legacy); `5` `[ERR_RUNTIME]`.

**Interfaces exposed:**
- CLI: `python -m wiki.ingest <slug-or-path> [--wiki-root DIR] [--force] [--agent dotted.path:Class]`. Wiki root auto-located by walk-up from cwd if not given (same convention as M2).
- Python:
  - `ingest_one(wiki_root: Path, slug: str, agent: IngestAgent, *, force: bool=False) -> IngestReport`
  - `class IngestReport(NamedTuple): source_path: Path; touched_pages: list[Path]; glossary_added: list[str]`
- LLM seam (`src/wiki/agent_seam.py`):
  ```python
  class TouchedPage(TypedDict):
      kind: Literal["concept", "entity"]
      slug: str
      title: str
      depends_on: list[str]
      merge_md: str

  class Contradiction(TypedDict):
      with_source_slug: str
      claim: str
      counter_claim: str

  class IngestAgent(ABC):
      def extract_takeaways(self, *, raw_md, schema_md, index_md) -> list[str]
      def plan_crossrefs(self, *, raw_md, takeaways, existing_pages) -> list[TouchedPage]
      def find_contradictions(self, *, page_slug, page_md, new_fragment) -> list[Contradiction]
      def detect_glossary_terms(self, *, raw_md, takeaways, existing_terms) -> list[tuple[str, str]]
      def resolve_vision(self, *, marker_path, asset_path) -> str
  ```
  `DeterministicStubAgent` returns canned, slug-derived results so all tests run offline.

**Out of scope (explicit):**
- Synthesis pages from queries (M5).
- Graph lint, orphan detection, relation-code enforcement (M4).
- Modifying `raw/`, `entry/`, or `.wiki/.converted.json` (manifest is read-only here).
- Cron / watcher / bin-copy (M6).
- `synthesis.md` template (M5); ADR creation (manual / M14).
- Real LLM calls — production seam binding is the host agent's responsibility.

**Dependencies:** M1 (templates, `substitute()` re-used from `wiki.init`), M2 (`.wiki/.converted.json` schema and `<!-- needs-vision: ... -->` marker contract).

**Acceptance criteria:**
1. **Manifest gate.** Ingesting a slug not present in `.wiki/.converted.json` exits `2` with `[ERR_SCHEMA]`, message naming the missing key; no files written.
2. **Source-page write.** Successful ingest produces `wiki/sources/{slug}.md` with valid YAML frontmatter containing exactly `{type, title, source_path, ingested, converter}`; no unresolved `{{…}}` tokens; `converter` matches the manifest entry.
3. **Pre-existing warn-and-stop.** If `wiki/sources/{slug}.md` already exists and `--force` is absent → exit `3`, single-line warning, no other files modified (sha256 of `index.md`/`log.md`/`SCHEMA.md` unchanged).
4. **`--force` overwrite.** With `--force`, the source page is rewritten atomically; no `*.tmp` left behind.
5. **DAG order is deterministic.** Plan with edges `A→B, A→C, B→D` and unrelated `E` updated in unique topo order with alphabetical slug tiebreaker (verified by spy agent recording call order). Cycles → `[ERR_SCHEMA]` exit `2`, no partial writes.
6. **Cross-ref merge — create.** Missing target `wiki/{kind}/{slug}.md` is created from `templates/pages/{kind}.md`, frontmatter populated, agent's `merge_md` appended under `## Cross-References`.
7. **Cross-ref merge — extend.** Existing target gets `merge_md` appended without duplicating identical lines; entity `source_count` increments by 1 once per `ingest_one`.
8. **Contradictions inline.** Each stub `Contradiction` produces exactly one line matching `^> ⚠️ Contradiction: \[.+\]\(\.\./sources/.+\.md\) says .+; \[.+\]\(\.\./sources/.+\.md\) says .+$`.
9. **Glossary patch is idempotent and non-destructive.** First run inserts `<!-- glossary:auto:start -->`/`<!-- glossary:auto:end -->` markers inside `## Glossary` table body; subsequent runs touch only rows between markers; manual rows above/below are byte-identical.
10. **Index updates.** Touched pages appear under their respective H2 alphabetically with relative links; `--force` rerun does not duplicate entries.
11. **Log append.** Exactly one line per W3 regex; counts `N = 1 source + created/extended concepts + created/extended entities` (glossary excluded).
12. **Atomicity.** `os.replace` injection raising mid-run leaves all five candidate target files byte-identical to pre-run state.
13. **needs-vision passthrough.** Manifest `status: needs_vision` triggers `agent.resolve_vision(...)`; result feeds `extract_takeaways`. `raw/{slug}.md` and manifest unchanged (sha256).
14. **Path safety.** Slug containing `/`, `..`, or resolving outside `$WIKI_ROOT/raw/` → `[ERR_SECURITY]` exit `4`. Symlinks under `raw/` not followed.
15. **Read-only upstreams.** Tests fail closed if any byte is written under `raw/`, `entry/`, `.wiki/`, `LLM_Wiki/`, `RAG-Wiki/`, or `Local_MCP_Server/`.
16. **No-network / no-model.** Suite passes with `LLMWIKI_TEST_STUB_AGENT=1` and `socket.socket` monkeypatched to raise.

**Test strategy:** pytest, tmp-dir wiki per test built via M1's `init` then seeded with hand-crafted `raw/{slug}.md` + manifest entries (no real M2 invocation needed for unit tests; one optional integration test chains `M2 → M3` end-to-end). All tests use `DeterministicStubAgent` or per-test spy subclass; no LLM, no network.

**Estimated size:** `ingest.py` ~180 LOC, `crossref.py` ~120 LOC, `glossary.py` ~80 LOC, `agent_seam.py` ~80 LOC, `_frontmatter.py` ~40 LOC = ~500 LOC Python total — pre-declared split per START-PROMPT §2.3. Tests ~350 LOC.

**Session boundary note:** START-PROMPT §§3,5,6,7; MASTER §6 (W3), §7 (Wiki Schemas + placeholders + `.converted.json` schema), §8 (path safety, read-only upstreams), §9 (`[ERR_SCHEMA]`, `[ERR_SECURITY]`, `[ERR_RUNTIME]`), Appendix A (source/concept/entity templates only — `synthesis.md` is M5); M1 contract for template hydration; M2 contract for manifest entry shape and `needs-vision` marker.

---

#### Contract: M4 — Graph lint

**Responsibility:** Provide a deterministic, pure-stdlib graph-aware linter that scans `$WIKI_ROOT/wiki/**/*.md` plus `index.md` and `SCHEMA.md`, builds the wiki link graph, applies the eight rules in MASTER Appendix C, classifies the discourse state, and emits a human-readable text report or `--json` for cron consumption — with **no writes** unless `--log` is passed (in which case it appends exactly one W5 line to `log.md`).

**Inputs:**
- A wiki root produced by M1 (must contain `wiki/`, `index.md`, `SCHEMA.md`); arbitrary M3 ingest state.
- CLI: `python -m wiki.graph_lint <wiki_root> [--json] [--log] [--fail-on {high,medium,low,none}]`. Default `--fail-on=high`.
- Python: `lint_wiki(wiki_root: Path) -> LintReport`.

**Outputs:**
- Stdout: text report grouped by severity (default) **or** canonical JSON (`--json`, `sort_keys=True`, `indent=2`).
- `$WIKI_ROOT/log.md` (only when `--log`): exactly one appended line matching `^## \[\d{4}-\d{2}-\d{2}\] lint \| \d+ issues \| state=(EMPTY|BIASED|FOCUSED|DIVERSIFIED|DISPERSED)$`.
- Exit codes: `0` no issues at-or-above `--fail-on` threshold; `1` issues at threshold; `2` `[ERR_SCHEMA]` (wiki root missing `wiki/`, `SCHEMA.md`, or `index.md`); `4` `[ERR_SECURITY]` (path escape, symlink leaving `wiki_root`); `5` `[ERR_RUNTIME]`.

**Interfaces exposed:**
- CLI: as above. No flags beyond those four; no auto-fix flag (auto-fix is host-agent / M3 territory).
- Python:
  ```python
  class Issue(TypedDict):
      severity: Literal["high", "medium", "low"]
      rule: str
      message: str
      page: NotRequired[str]
      target: NotRequired[str]

  @dataclass(frozen=True)
  class LintReport:
      wiki_root: Path
      pages: int
      edges: int
      components: int
      largest_component: int
      discourse_state: Literal["EMPTY","BIASED","FOCUSED","DIVERSIFIED","DISPERSED"]
      issues: list[Issue]

  def lint_wiki(wiki_root: Path) -> LintReport: ...
  def report_text(r: LintReport) -> str: ...
  def report_json(r: LintReport) -> str: ...
  ```
- Constants exposed (frozen): `RELATION_CODES`, `RELATEDTO_THRESHOLD = 0.70`, `RELATION_MIN_SAMPLE = 10`, `HUB_AND_SPOKE_THRESHOLD = 0.40`, `STALE_DAYS = 30`, `BIASED_INBOUND_SHARE = 0.50`.

**Rules implemented (all eight from MASTER Appendix C):**
1. `orphan` (HIGH) — wiki page with 0 inbound links; `wiki/sources/*` exempt.
2. `broken_link` (HIGH) — `[text](path.md)` whose resolved target under `wiki/` does not exist. Targets outside `wiki/` (e.g. `../../raw/...`) are not flagged.
3. `index_gap` (MEDIUM) — page basename absent from `index.md`.
4. `hub_and_spoke` (MEDIUM) — single page absorbs >40 % of all inbound edges; reports up to 3 worst.
5. `relation_code_distribution` (MEDIUM) — `relatedTo` >70 % of all parsed cross-ref codes when total ≥10.
6. `unknown_relation_code` (LOW) — per-page bullet codes not in `RELATION_CODES`.
7. `asymmetric_coverage` (LOW) — frontmatter `type`/`entity_type` distribution where the smallest non-empty bucket ≤ ⌊largest/5⌋ and largest ≥5.
8. `stale_candidate` (LOW) — frontmatter `updated` or `ingested` more than `STALE_DAYS` days ago.

**Discourse state classifier:** EMPTY (no pages) → BIASED (max-inbound share >0.5) → FOCUSED (largest-component ratio >0.85 AND <1.5 edges/node) → DIVERSIFIED (default mid case) → DISPERSED (≥n/3 components). Pure stdlib; no NetworkX.

**Out of scope (explicit):**
- Auto-fix (no writes to `index.md`, `SCHEMA.md`, or stub creation under `wiki/`).
- Cron installation (M6).
- InfraNodus or any external/MCP integration (Appendix C calls it optional; deferred indefinitely).
- The lint **alert** file `.wiki/.alert.md` referenced by M2's `session_check.sh` — produced by M6's cron wrapper, not by the linter itself.
- Any RAG/MCP logic.

**Dependencies:** M1 (scaffold + templates supply `wiki/`, `index.md`, `SCHEMA.md` shape). Runs against any wiki populated by M3, but does not require M3 output to be present.

**Acceptance criteria:**
1. **Empty wiki.** Linter against a fresh M1 scaffold reports `pages=0, edges=0, discourse_state=EMPTY`, zero issues, exit `0`.
2. **Pure stdlib.** `import wiki.graph_lint` triggers no third-party imports (asserted via source-grep for `networkx`/`yaml`/`requests`).
3. **Speed.** A synthetic wiki of 200 pages + 600 edges lints in < 1 s on the test runner (asserted with a 3 s soft cap to stay reliable).
4. **Read-only.** A full lint run (without `--log`) leaves every byte under `wiki_root` byte-identical (sha256 manifest of the entire tree before/after).
5. **`--log` append.** With `--log`, exactly one line is appended to `log.md` matching the W5 regex; the rest of the file is unchanged.
6. **Orphan rule.** A wiki with one concept page nobody links to → exactly one HIGH `orphan` issue naming that page; same page placed under `wiki/sources/` → 0 `orphan` issues.
7. **Broken link rule.** A page containing `[X](missing.md)` resolving inside `wiki/` → HIGH `broken_link` with `target` field populated; a link to `../../raw/x.md` → no issue.
8. **Index gap rule.** A page absent from `index.md` → MEDIUM `index_gap`; adding the basename to `index.md` clears it.
9. **Hub-and-spoke rule.** Star graph with one center receiving 5/5 inbound → MEDIUM `hub_and_spoke` flag on the hub; balanced 5-cycle → no issue.
10. **Relation-code rules.** A page whose `## Cross-References` bullets use 12 codes, 9 of which are `relatedTo` → MEDIUM `relation_code_distribution`. A page with code `kindaLike` → LOW `unknown_relation_code` listing that code. Sample size <10 → no `relation_code_distribution` issue.
11. **Stale candidate.** Frontmatter `updated: 2020-01-01` → LOW `stale_candidate` with day-count in message; `updated: <today>` → no issue.
12. **Asymmetric coverage.** 10 concept pages + 1 entity page → LOW `asymmetric_coverage`; balanced distribution → no issue.
13. **Discourse state.** Inputs constructed for each of EMPTY / BIASED / FOCUSED / DIVERSIFIED / DISPERSED produce the matching label.
14. **JSON output.** `--json` emits sorted-key, 2-space-indented JSON parseable by `json.loads`; same `LintReport` data as text mode.
15. **Exit codes.** `--fail-on=high`: 1 HIGH → exit 1; only LOW/MEDIUM → exit 0. `--fail-on=low` with any issue → exit 1. Wiki root missing `wiki/` → exit 2 with `[ERR_SCHEMA]`. Wiki root path that is a symlink → exit 4 with `[ERR_SECURITY]`.
16. **No-network.** Suite passes with `socket.socket` monkeypatched to raise.

**Test strategy:** pytest, tmp-dir wiki per test built via M1's `init` then seeded with hand-crafted page files (no real M3 ingest needed). 30 cases covering the 16 criteria. Synthetic 200-page wiki for the speed test. No LLM, no network.

**Estimated size:** `graph_lint.py` ~430 LOC Python (pure stdlib, single file — under §2.3 cap so no split). Tests ~430 LOC.

**Session boundary note:** START-PROMPT §§3, 5, 6, 7; MASTER §6 (W5), §7 (Wiki Schemas — frontmatter + linking conventions + log format), §8 (path safety, read-only upstreams), §9 (`[ERR_SCHEMA]`, `[ERR_SECURITY]`), Appendix C (rule table + discourse states). Legacy reference: `LLM_Wiki/skills/bin/graph_lint.py` for regex/threshold prior art only.

---

#### Contract: M5 — Query + synthesis

**Responsibility:** Provide the deterministic core and LLM-agent seam that accept a natural-language question against a populated wiki, select up to 7 relevant pages, synthesize an answer with inline citations and a confidence assessment, and — when requested — write one new `wiki/synthesis/{slug}.md`, an index entry under `## Synthesis`, and one W4-format log line. All on-disk mutations are 2-phase atomic (write `*.tmp`, then `os.replace`). The module is read-only against `raw/`, `entry/`, `.wiki/`, and all upstream legacy folders.

**Inputs:**
- A wiki root produced by M1 (must contain `index.md`, `SCHEMA.md`, `.wiki/.converted.json`; M3-produced pages optional).
- Argument: a natural-language question string.
- Optional flags: `--file` (write synthesis page), `--slug SLUG` (override derived slug), `--force` (overwrite existing synthesis page).
- A `QueryAgent` implementation. The CLI uses `DeterministicStubQueryAgent` only under `LLMWIKI_TEST_STUB_AGENT=1`; otherwise requires `--agent dotted.path:Class` or rejects with `[ERR_RUNTIME]`.

**Outputs (all atomic via temp + `os.replace` when written):**
- Stdout: parseable `QUERY COMPLETE` block with `sources_read` count and `synthesis_path`.
- `$WIKI_ROOT/wiki/synthesis/{slug}.md` (only with `--file`): hydrated from `templates/pages/synthesis.md`; frontmatter `{type, question, created: DATE, sources_read: [...]}` per MASTER §7; no unresolved `{{…}}` tokens.
- `$WIKI_ROOT/index.md` (only with `--file`): synthesis link inserted/deduplicated under `## Synthesis` H2 (created if absent); sorted alphabetically.
- `$WIKI_ROOT/log.md` (always): one line per query; filed: `## [YYYY-MM-DD] query | {question ≤80 chars} | filed as synthesis/{slug}.md`; unfiled: `## [YYYY-MM-DD] query | {question ≤80 chars} | not filed`.
- Exit codes: `0` success; `2` `[ERR_SCHEMA]` (wiki root invalid, template missing); `3` warn-and-stop (synthesis exists, no `--force`); `4` `[ERR_SECURITY]` (path escape, symlink wiki root, protected write); `5` `[ERR_RUNTIME]` (no agent bound).

**Interfaces exposed:**
- CLI: `python -m wiki.query "<question>" [--wiki-root DIR] [--file] [--slug SLUG] [--force] [--agent MOD:CLS]`. Wiki root auto-located by walk-up from cwd (same convention as M2/M3).
- Python (`wiki.query`):
  ```python
  class QueryReport(NamedTuple):
      answer: str
      sources_read: list[str]      # relative paths from wiki_root
      synthesis_path: Path | None  # set iff file_as_synthesis=True

  def query_one(
      wiki_root: Path, question: str, agent: QueryAgent,
      *, file_as_synthesis: bool = False, slug: str | None = None,
      force: bool = False, today: str | None = None,
  ) -> QueryReport
  ```
- LLM seam (`wiki.query_agent`):
  ```python
  class PageSummary(TypedDict):
      path: str; title: str; snippet: str   # first ≤300 chars of body

  class SynthesisResult(TypedDict):
      answer: str; sources_read: list[str]
      confidence: str; follow_up: list[str]

  class QueryAgent(ABC):
      def rank_pages(self, *, question, candidates) -> list[str]: ...
      def synthesize(self, *, question, pages) -> SynthesisResult: ...
      def propose_slug(self, *, question) -> str: ...

  class DeterministicStubQueryAgent(QueryAgent): ...
  ```

**Out of scope (explicit):**
- Back-link injection into existing source/concept/entity pages — deferred indefinitely (idempotency questions, write-surface conflicts with concurrent M3 ingests; graph discovery already covered by M4).
- RAG retrieval (M8/M9): M5 operates on `wiki/**/*.md` text only.
- Persona / MCP routing (M11–M13).
- Any modification of `raw/`, `entry/`, `.wiki/`.

**Dependencies:** M1 (scaffold, `init.substitute()`, `init.init()` fixture, wiki root layout); M3 (seam idiom mirrored — no runtime dependency).

**Acceptance criteria:**
1. **Wiki root gate.** `query_one` against a path missing `index.md` or `.wiki/.converted.json` raises `QueryError` `[ERR_SCHEMA]`; no files written.
2. **Empty wiki graceful.** `query_one` on a fresh M1 scaffold succeeds; `answer` non-empty; `sources_read = []`; `synthesis_path = None` unless `--file`.
3. **Answer without filing.** Without `--file`, `synthesis_path=None`; no file under `wiki/synthesis/`; log gets one "not filed" line; `index.md` sha256 unchanged.
4. **Valid synthesis page.** With `--file`, page has valid frontmatter `{type, question, created, sources_read}`; no `{{…}}` tokens; all four body sections present.
5. **`sources_read` frontmatter matches agent.** Frontmatter list equals `SynthesisResult.sources_read` in order.
6. **Warn-and-stop.** Pre-existing synthesis without `--force` → exit `3`; `index.md` and `log.md` sha256 unchanged.
7. **`--force` overwrite.** Atomically rewrites; no `*.tmp` left; `index.md` not duplicated.
8. **Index Synthesis section.** Filed slug appears under `## Synthesis`; re-run with `--force` adds no duplicate.
9. **Index section created if absent.** `## Synthesis` appended if missing; content before the new section byte-identical.
10. **Log format.** Filed matches `^## [\d-]+ query \| .{1,80} \| filed as synthesis/…$`; unfiled matches `^## [\d-]+ query \| .{1,80} \| not filed$`.
11. **Atomicity.** `os.replace` injection raises mid-run → all target files byte-identical to pre-run state; no `*.tmp` left.
12. **Slug auto-derivation.** Derived slug is lowercase, hyphens, ≤64 chars, matches `^[a-z0-9][a-z0-9_-]{0,127}$`; empty question → `"query"`.
13. **Custom slug validation.** Slug with `/` or `..` → `[ERR_SECURITY]` exit 4; no files written.
14. **Symlink wiki root.** Symlink wiki root → `[ERR_SECURITY]` exit 4 (checked before `resolve()`).
15. **Read-only upstreams.** After any run, `raw/`, `entry/`, `.wiki/` sha256-tree unchanged.
16. **No-network.** Suite passes with `socket.socket` monkeypatched to raise.
17. **`LLMWIKI_TEST_STUB_AGENT=1`.** CLI without `--agent` uses `DeterministicStubQueryAgent` under the env var.
18. **No-agent rejection.** CLI without env var and without `--agent` → exit 5 `[ERR_RUNTIME]`; no files written.

**Test strategy:** pytest, tmp-dir wiki per test via `wiki.init.init`, optionally seeded with hand-crafted pages. All tests use `DeterministicStubQueryAgent` or per-test subclass. `no_network` autouse fixture. One integration test chains `init → seed pages → query_one → file`. 23 test cases.

**Estimated size:** `query.py` ~310 LOC, `query_agent.py` ~75 LOC = ~385 LOC Python total. Tests ~260 LOC.

**Session boundary note:** START-PROMPT §§3,5,6,7; MASTER §6 (W4), §7 (synthesis frontmatter + log format + template placeholders), §8 (path safety, read-only upstreams), §9 (`[ERR_SCHEMA]`, `[ERR_SECURITY]`, `[ERR_RUNTIME]`), Appendix A (synthesis template); M1 contract for `substitute()` reuse and test fixture; M3 contract for `IngestAgent` seam idiom.

---

#### Contract: M6 — Cron / watch ops

**Responsibility:** Provide an interactive, idempotent crontab installer (`install_cron.sh`) and its symmetric remover (`uninstall_cron.sh`) that schedule the wiki background jobs; a thin lint wrapper (`lint_cron.sh`) that the cron schedule invokes; and a non-interactive bin-copy helper (`install_wiki_bin.sh`) that populates `$WIKI_ROOT/.wiki/bin/` with stable copies of all `src/wiki/` scripts (satisfying adj. D deferred from M1/M2). All four scripts are pure bash ≥4 + POSIX coreutils.

**Inputs:**
- A wiki root produced by M1 containing `SCHEMA.md` (detected by walk-up from argument or `$PWD`).
- Optional `WIKI_ROOT` positional argument; `install_cron.sh` and `uninstall_cron.sh` read interactive confirmation from stdin.
- `crontab` binary on `PATH` (optional; scripts degrade gracefully when absent).
- `src/wiki/*.{sh,py}` — copied by `install_wiki_bin.sh` to `.wiki/bin/`.
- `LLMWIKI_SRC_DIR` env var (test isolation override for `install_wiki_bin.sh`).

**Outputs:**
- `install_cron.sh`: calls `install_wiki_bin.sh`; shows unified diff; writes crontab after `y/Y/yes/YES`; schedules `autoconvert.sh` (*/15) and `lint_cron.sh` (Mon 06:23); `sync.sh` deferred (comment in block); creates `.wiki/cron.log`; appends `## [YYYY-MM-DD] cron | install | {name}` to `log.md`. Exit 0 success/abort; 1 wiki-root error; 2 crontab absent; 4 `[ERR_SECURITY]`.
- `uninstall_cron.sh`: symmetric; shows diff; no-op if block absent; appends `## [YYYY-MM-DD] cron | uninstall | {name}`.
- `install_wiki_bin.sh`: copies `src/wiki/*.sh` and `src/wiki/*.py` to `$WIKI_ROOT/.wiki/bin/` with execute bit; idempotent.
- `lint_cron.sh`: invokes `python3 $WIKI_ROOT/.wiki/bin/graph_lint.py $WIKI_ROOT --log --fail-on=medium`; appends a timestamped line to `.wiki/cron.log`.

**Interfaces exposed:**
- `src/wiki/install_cron.sh [WIKI_ROOT]`
- `src/wiki/uninstall_cron.sh [WIKI_ROOT]`
- `src/wiki/install_wiki_bin.sh [WIKI_ROOT]`
- `src/wiki/lint_cron.sh [WIKI_ROOT]`
- Tag format: `# llm-wiki-builder:{wiki-name}` / `# llm-wiki-builder:{wiki-name}-end`
- Log line (install): `## [YYYY-MM-DD] cron | install | {wiki-name}`
- Log line (uninstall): `## [YYYY-MM-DD] cron | uninstall | {wiki-name}`

**Out of scope (explicit):**
- `sync.sh` — not defined in this repo; deferral note in cron block (adj. D2).
- Modifications to `autoconvert.sh`, `watch_entry.sh`, `session_check.sh` (M2).
- `.wiki/.alert.md` producer (M4 deferred auto-fix, still deferred).
- RAG / MCP logic (M7–M13); editor shims (M14).
- Cron scheduling of `watch_entry.sh` (long-running daemon, not a cron job).

**Dependencies:** M2 (`DONE`) — wiki root layout, `autoconvert.sh` as primary scheduled job, `log.md` append convention, PATH-scrubbed test harness pattern.

**Acceptance criteria:**
1. **Walk-up acceptance.** `install_cron.sh $WIKI_ROOT/deep/nested` finds root by walk-up, exits 0.
2. **Non-wiki arg rejection.** Non-wiki explicit arg → exit 1, mentions `SCHEMA.md`, no files created.
3. **Symlink wiki-root rejection.** Symlink to valid wiki → exit 4 `[ERR_SECURITY]`, crontab untouched.
4. **User abort.** Sending `n` → crontab + `log.md` byte-identical; exit 0.
5. **Diff shown.** Stdout contains `===` diff header before any write.
6. **Idempotent install.** Two yes-runs → exactly one tag block in crontab; two install log lines in `log.md`.
7. **Scheduled jobs correct.** Crontab block has `*/15` entry for `autoconvert.sh` and `23 6 * * 1` entry for `lint_cron.sh`; `sync.sh` absent from scheduled entries.
8. **`crontab` absent — graceful degrade.** Exit 2; warning printed; log line and `cron.log` written.
9. **Log line format (install).** Matches `^## \[\d{4}-\d{2}-\d{2}\] cron \| install \| .+$`.
10. **Uninstall no-op.** No tagged block → reports and exits 0; `log.md` unchanged.
11. **Uninstall removes block.** After install+uninstall, crontab has no `llm-wiki-builder:{name}` tag; `log.md` gains uninstall line.
12. **Log line format (uninstall).** Matches `^## \[\d{4}-\d{2}-\d{2}\] cron \| uninstall \| .+$`.
13. **`install_wiki_bin` populates bin.** Every `src/wiki/*.sh` and `*.py` present in `.wiki/bin/` with execute bit.
14. **`install_wiki_bin` idempotent.** Re-run sha256 of each file equals source.
15. **`install_cron` calls `install_wiki_bin`.** After yes-run, `.wiki/bin/autoconvert.sh` exists.
16. **`install_wiki_bin` path safety.** Symlink root → exit 4 `[ERR_SECURITY]`.
17. **`lint_cron` invokes `graph_lint.py --log`.** Recording python3 stub captures the call.
18. **Read-only upstream guard.** Sha256-tree of `LLM_Wiki/`, `RAG-Wiki/`, `Local_MCP_Server/` unchanged after install + uninstall.
19. **No `*.tmp` files.** None left under `WIKI_ROOT` after any run.
20. **Full suite stays green.** 138/138 tests pass.

**Test strategy:** pytest + `subprocess`; tmp-dir wiki per test via `wiki.init.init`; PATH scrubbed to tmpdir with stable POSIX tools; `crontab` replaced by a bash stub reading/writing `$CRONTAB_FILE`; interactive confirmation injected via `input=b"y\n"` or `b"n\n"`; symlink tests via `os.symlink`; `LLMWIKI_SRC_DIR` override for `install_wiki_bin`; recording `python3` shim for `lint_cron` test. 24 test cases.

**Estimated size:** `install_cron.sh` ~100 LOC, `uninstall_cron.sh` ~70 LOC, `install_wiki_bin.sh` ~60 LOC, `lint_cron.sh` ~25 LOC = ~255 LOC shell. Tests ~280 LOC.

**Session boundary note:** START-PROMPT §§3, 5, 6, 7; MASTER §6 (W6), §7 (cron log format), §8 (path safety, read-only upstreams), §9 (`[ERR_SECURITY]`); M2 contract (PATH-scrubbed test harness, walk-up detection, log append); legacy `LLM_Wiki/skills/bin/install-cron.sh` and `uninstall-cron.sh` for porting reference.

---

#### Contract: M7 — Config + schema

**Responsibility:** Provide the canonical RAG configuration loader, validator, and typed accessor used by M8/M9/M10; ship a finalized default `config.yaml` matching MASTER §7 (RAG Schemas).

**Inputs:**
- `config.yaml` at repo root (M1 ships a stub; M7 finalizes; user may edit)
- Optional override path via env var `LLM_RAG_WIKI_CONFIG`

**Outputs:**
- `src/rag/__init__.py` — empty package marker
- `src/rag/config.py` — loader, validator, typed accessor
- `config.yaml` — authoritative default matching MASTER §7 schema (`schema_version: 1`)
- `tests/test_config.py`

**Interfaces exposed:**
- `load_config(path: str | Path | None = None) -> Config`
  - Resolution order: explicit `path` arg → `LLM_RAG_WIKI_CONFIG` env var → `config.yaml` at repo root (three parents above `config.py`)
  - All path fields resolved absolute via `Path.resolve()`, relative to the config file's directory
  - Raises `ConfigError` on any validation failure; message includes `[ERR_CONFIG]` and the offending field path
- `config_hash(cfg: Config) -> str` — SHA-256 of a canonical (key-sorted, normalized) JSON serialization; stable across YAML key-order and whitespace differences
- `ConfigError(Exception)` — carries `[ERR_CONFIG]`
- Frozen dataclass hierarchy: `Config`, `ProjectConfig`, `RuntimeConfig`, `DomainConfig`, `EmbeddingConfig`, `PathsConfig`, `ChunkingConfig`, `IndexingConfig`, `RetrievalConfig`, `PrivacyConfig`

**Validation rules (all raise `ConfigError`):**
1. `schema_version` must be integer `1` (bool rejected).
2. All required sections present; missing leaf → error naming the dotted path.
3. Type coercion errors (e.g. `top_k: "five"`) → error naming the field.
4. `paths.wiki_root` resolved path must not contain `entry` or `raw` as a path component.
5. `0.0 <= ood_threshold <= min_score <= 1.0`.
6. `min_chars >= 1` and `max_chars > min_chars`.

**Dependencies:**
- M0 (approval), M1 (ships stub `config.yaml` at default path)

**Acceptance criteria (12):**
1. `load_config()` against the shipped default returns a `Config` with every MASTER §7 RAG field present and correctly typed.
2. Missing any required field → `ConfigError [ERR_CONFIG]` naming the field path; no partial config returned.
3. `schema_version != 1` (wrong value, wrong type, or bool `True`) → `ConfigError`.
4. Wrong type for any leaf field → `ConfigError` naming the field.
5. Relative `wiki_root` resolves against config file's directory.
6. `wiki_root` inside `entry/` or `raw/` → `ConfigError`.
7. `ood_threshold > min_score` → `ConfigError`.
8. `config_hash()` stable across key-order-only differences (two `Config` objects with identical field values → same hash).
9. `config_hash()` changes when any field value changes.
10. `LLM_RAG_WIKI_CONFIG` env var overrides default path; explicit `path` arg overrides env var.
11. `import rag.config` has no network calls, no file writes, no log output.
12. `min_chars < 1` or `max_chars <= min_chars` → `ConfigError`.

**Test strategy:** 49 pytest cases: parametrized invalid configs for AC 2/3/4/6/12; hash stability for AC 8/9; env-var priority for AC 10; `no_network` autouse fixture blocking `socket.socket`; bonus test loading the shipped `config.yaml` directly. No integration tests, no ChromaDB/sentence-transformers imports.

**Estimated size:** `src/rag/config.py` ~265 LOC Python. `tests/test_config.py` ~290 LOC.

**Session boundary note:** MASTER §§4, 7 (RAG schemas), 8 (security — wiki_root rules), 9 (`[ERR_CONFIG]`).

---

#### Contract: M8 — RAG ingest pipeline

**Responsibility:** Scan the configured `wiki_root` for `*.md` pages, chunk them deterministically (heading-aware), embed each chunk, upsert to a vector store, and atomically rewrite a per-file ingest manifest — with privacy and prompt-injection boundaries enforced and an atomic-reindex mode that survives mid-run failures.

**Inputs:**
- M7 `Config` (typed `cfg.paths.wiki_root`, `cfg.chunking.{min_chars,max_chars}`, `cfg.embedding.{provider,model_id,normalize_embeddings}`, `cfg.indexing.atomic_reindex`, `cfg.retrieval.distance_metric`, `cfg.privacy.block_secret_chunks`, `cfg.domain.name` as the collection name).
- `wiki/**/*.md` content + YAML frontmatter (untrusted data per MASTER §8).
- Optional prior manifest at `cfg.paths.manifest_path` (MASTER §7 schema).

**Outputs:**
- `cfg.paths.manifest_path` — atomically written JSON manifest with `schema_version`, `config_hash`, `created_at`, `updated_at`, `files{rel_path: {source_hash, chunk_ids}}`.
- Vector store collection `cfg.domain.name` populated with one record per chunk: `id=chunk_id`, `embedding`, `metadata={rel_path, heading_path, chunk_index, chunk_hash}`, `document=chunk text`.
- `IngestStats` returned: `files_scanned, files_indexed, files_skipped, chunks_upserted, chunks_deleted, embedding_seconds`.
- Stdout banner `INGEST COMPLETE …` + per-file warning logs to `logging.getLogger("rag.ingest")` (injection-flagged chunk text suppressed).

**Interfaces exposed:**
- `manifest.py` — `FileEntry`, `Manifest` (frozen dataclasses), `load_manifest()`, `save_manifest()` (atomic), `ManifestError` carrying `[ERR_INDEX_MISSING]` / `[ERR_SCHEMA]`.
- `chunker.py` — `Chunk` (frozen dataclass), `chunk_markdown(text, *, rel_path, collection_name, min_chars, max_chars)`; deterministic IDs per MASTER §7; code fences atomic; frontmatter stripped; soft-cap of 1.25× `max_chars` only used when a single oversize paragraph cannot otherwise be packed.
- `embedder.py` — `EmbedderBackend` ABC; `SentenceTransformersEmbedder(model_id, *, normalize)` (lazy import; raises `EmbedderError` `[ERR_EMBEDDING_MODEL]` on import or load failure, never partially constructs); `DeterministicHashEmbedder(dim=16)` test stub producing unit-norm SHA-256-derived vectors.
- `store.py` — `VectorStore` ABC with `upsert / delete / count / reset`; `ChromaVectorStore(index_dir, collection_name, *, distance_metric)` (lazy `chromadb` import; raises `StoreError` `[ERR_DB]` on any failure); `InMemoryVectorStore` test stub with `ids() / get()` helpers.
- `ingest.py` — `IngestStats`, `ingest_wiki(cfg, *, embedder=None, store=None, today=None, reset=False)`; CLI `python -m rag.ingest [--config PATH] [--reset]`; production backends gated by `LLM_RAG_WIKI_TEST_STUB_EMBEDDER=1` (stub) for the embedder.

**Out of scope (explicit):**
- Retrieval CLI — M9.
- Eval framework — M10.
- MCP / persona delivery — M11–M13.
- Real `sentence-transformers` model downloads in tests (stub only).

**Dependencies:** M7 (`DONE`).

**Acceptance criteria (16):** as enumerated in the M8 launcher prompt — chunker determinism (1), min/max bounds (2), heading-path ancestry (3), MASTER §7 ID derivation (4), manifest `[ERR_INDEX_MISSING]` / `[ERR_SCHEMA]` (5), atomic manifest write (6), deterministic embedder unit-norm + stable (7), production embedder failure → `[ERR_EMBEDDING_MODEL]` no partial init (8), in-memory store upsert/overwrite/count/reset (9), fresh-wiki ingest manifests `config_hash` (10), unchanged-wiki no-op (11), single-file edit → only that file re-indexed and stale IDs dropped (12), file deletion drops chunks + manifest entry (13), atomic reindex mid-run failure preserves original (14), `privacy: secret` skip when `block_secret_chunks=true` (15), no module-level network/file-writes/`chromadb`/`sentence_transformers` imports (16).

**Validation / safety rules:**
1. Symlink `wiki_root` → `ConfigError` `[ERR_SECURITY]` (checked before `resolve()`).
2. Missing `wiki_root` directory → `ManifestError` `[ERR_INDEX_MISSING]`. Missing manifest at `cfg.paths.manifest_path` is tolerated by `ingest_wiki` (treated as empty); only `load_manifest` raises.
3. `*.md` files outside `wiki_root.resolve()` (symlink escape) skipped silently with a warning.
4. Markdown content is untrusted data — chunks containing prompt-injection markers (`"ignore rules"`, `"print secrets"`, `"disable guardrails"`, `"change system behavior"`) are still indexed (factual content); the ingest log records that they were indexed but never echoes their text.
5. Manifest writes are atomic (`*.tmp` + `os.replace` + `os.fsync`); a crash mid-write leaves the previous manifest byte-identical (or absent if first write).
6. `--reset` + `indexing.atomic_reindex=true`: writes go to a shadow store (Chroma collection rename, or fresh `InMemoryVectorStore` for injected stores) and only swap to primary on success; failure leaves the original collection untouched.

**Test strategy:** 32 pytest cases across `tests/test_chunker.py` (7), `tests/test_manifest.py` (8), `tests/test_ingest_rag.py` (17). All offline: `socket.socket` patched to raise; embedder = `DeterministicHashEmbedder`; store = `InMemoryVectorStore`. AC 8 forces lazy-import failure via `monkeypatch.setitem(sys.modules, "sentence_transformers", None)` and a fake module whose `SentenceTransformer.__init__` raises. AC 16 snapshots `sys.modules` before / after re-importing each `rag.*` module and asserts no `chromadb` or `sentence_transformers` leak. No real model downloads, no network, no Chroma persistence on disk.

**Estimated size:** ~870 LOC Python across the 5 source files (manifest 165 / chunker 250 / embedder 130 / store 175 / ingest 380), plus ~720 LOC of tests.

**Session boundary note:** MASTER §§6 (RAG P2 Ingest), §7 (manifest schema, stable chunk IDs), §8 (security: untrusted markdown, symlink rejection, prompt-injection boundary), §9 (`[ERR_INDEX_MISSING]`, `[ERR_SCHEMA]`, `[ERR_EMBEDDING_MODEL]`, `[ERR_DB]`, `[ERR_SECURITY]`).

---

#### Contract: M9 — Retrieval CLI

**Responsibility:** Provide the deterministic query orchestrator and CLI for the RAG layer, implementing graceful degradation and security boundaries.

**Inputs:**
- M7 `Config` (retrieval thresholds, top_k, distance metric).
- M8 Manifest and Vector Store.
- CLI argument: Query string.

**Outputs:**
- Schema-compliant YAML/JSON response to stdout.
- Exit codes 0–5 per MASTER §9.

**Interfaces exposed:**
- `retrieve.py`: `query_rag(...)`, `main(argv)`.
- `_query_store.py`: `QueryableStore` Protocol, `ChromaQueryAdapter`, `InMemoryQueryAdapter`.

**Acceptance criteria:**
1. `query_rag` returns `ok` for hits >= `min_score`.
2. `top_score < ood_threshold` returns `out_of_domain`.
3. `ood <= score < min_score` returns `insufficient_context` with `degradation_meta`.
4. CLI exit codes match MASTER §9 (0 ok, 1 deg, 3 system err, 4 security).
5. Missing/Empty manifest handled via `[ERR_INDEX_MISSING/EMPTY]`.
6. Config mismatch logs a single warning.
7. `render_yaml` produces canonical 6-key structure.
8. Excerpt formatting collapses newlines and truncates with `…`.
9. Injection markers trigger `[content withheld]` placeholder in excerpts.
10. `InMemoryQueryAdapter` supports cosine, l2, and ip metrics.
11. `ChromaQueryAdapter` uses lazy imports and raises `[ERR_DB]`.
12. CLI `--format json` matches YAML structure.
13. No module-level third-party imports (asserted via `sys.modules`).
14. 14/14 tests in `test_retrieve.py` pass.

**Test strategy:** unit (pytest, 14 cases covering thresholds, formatting, and security).

**Estimated size:** ~500 LOC Python total.

---

#### Contract: M11 — Persona store

**Responsibility:** Persist persona definitions and meta-directives as validated YAML files on disk; expose deterministic, side-effect-explicit read/write/list/audit primitives used by M12 (compiler) and M13 (server).

**Inputs:**
- Directory: `personas/` (per MASTER §2). One YAML file per persona; filename = `{persona.id}.yaml`.
- `personas/meta_directives.yaml` — separate file, single document.
- Persona schema: MASTER §7 (MCP / Persona Schema) — fields `id`, `kind`, `name`, `rules[]`, `style_weights{}`, `modes{}`, `version`, `audit_log[]`.

**Outputs:**
- `src/mcp/store.py`
- `personas/meta_directives.yaml` — initial empty document `{ meta_directives: [] }`
- `tests/test_persona_store.py`
- `tests/fixtures/personas/` — minimal fixtures (one `character`, one `domain`)

**Interfaces exposed:**
```
load_persona(persona_id: str) -> Persona
list_personas(kind: str | None = None) -> list[PersonaSummary]
save_persona(persona: Persona, *, change_note: str) -> None   # appends audit_log, atomic write
load_meta_directives() -> list[MetaDirective]
save_meta_directives(items: list[MetaDirective], *, change_note: str) -> None
```
- All writes atomic (temp file → fsync → `os.replace`).
- All writes append exactly one `audit_log[]` entry (timestamp, version delta, `change_note`). **Append-only**: writes that shrink/rewrite history are rejected.
- `kind` ∈ `{character, domain}`; `id` matches `^[a-z0-9][a-z0-9-]{1,63}$`.
- `version` semver; `save_persona` requires new version `>` on-disk version.

**Out of scope (explicit):**
- Compilation to runtime profile — M12
- Activation, routing, client-facing endpoint — M13
- Any network I/O

**Dependencies:**
- M0. (`personas/` directory created by M1 scaffold; `save_persona` may also create it lazily.)

**Acceptance criteria:**
1. `load_persona` rejects files missing any required field with a single-line error naming the missing field.
2. `save_persona` is atomic under simulated crash (test monkeypatches `os.replace` to raise after temp write — original file unchanged).
3. `audit_log[]` strictly append-only: a write whose input has shorter or modified history is rejected.
4. Two successive `save_persona` calls with identical content (other than the mandatory audit entry + version bump) produce byte-identical YAML serialization (canonical form: schema-ordered top-level keys, list order preserved, line endings `\n`).
5. `list_personas(kind="character")` and `list_personas(kind="domain")` return disjoint, complete summaries.
6. `meta_directives.yaml` round-trips: load → save unchanged → byte-identical.
7. `load_persona("../foo")` or any id failing the regex raises `[ERR_SECURITY]`-coded error; no path traversal.
8. No reads/writes outside `personas/`; symlinks inside `personas/` not followed.

**Test strategy:** unit (pytest, ~12 cases covering schema, atomicity, append-only, path safety, canonical serialization).

**Estimated size:** ~250 lines Python (split serialization into `src/mcp/persona_yaml.py` if exceeded).

**Session boundary note:** MASTER §§4, 6 (MCP Layer), 7 (MCP / Persona Schema), 8 (security — path safety, atomic writes). Legacy specs in `Local_MCP_Server/` are reference for *future* persona content, not for the storage contract.

---

## 6. Per-Module Contract Format

Before building any module, write its contract in this format and get
explicit user confirmation. The contract is filed inline below the module
entry in the registry once agreed.

```markdown
### Contract: M{N} — {Name}

**Responsibility:** one sentence.

**Inputs:**
- (file path, data format, or calling convention)

**Outputs:**
- (file path, data format, or exit code)

**Interfaces exposed:**
- (function signatures, CLI commands, or MCP endpoints)

**Dependencies:**
- (module IDs + specific files or functions consumed)

**Acceptance criteria:**
1. (concrete, testable statement)
2. …

**Test strategy:** (unit | integration | manual + what the test exercises)

**Estimated size:** ~N lines Python / ~N lines shell

**Session boundary note:** (what a fresh session needs to read to continue this module)
```

---

## 7. Build Rules

[MASTER.md §4 — Unified Rules](MASTER.md#4-unified-rules) is normative for
all sessions. The rules below are build-session additions specific to the
M0–M14 rebuild track and do not override MASTER.

1. **Plan first.** Phase-0 (this session) produces only the agreed module
   plan and contracts. No code is written in Phase-0.
2. **One module per session.** Do not start a second module in the same
   session unless the first is `DONE` and the second is trivially small.
3. **Test before advancing.** A module is `DONE` only when its acceptance
   criteria are met and recorded. "It looks right" is not a criterion.
4. **No speculative code.** Do not implement features not required by the
   current module's contract. Flag scope additions for a future module.
5. **Stable interfaces.** Once a module is `DONE`, its public interface
   (function signatures, CLI flags, YAML keys, MCP endpoints) is frozen.
   Changes require a new contract and explicit user Go.
6. **Read-only legacy.** Never write to `./LLM_Wiki/`, `./RAG-Wiki/`,
   or `./Local_MCP_Server/`. Reference only.
7. **Security boundaries always active.** MASTER.md §8 applies to
   every session without exception.
8. **Token discipline.** If context approaches ~130k tokens, summarize the
   session state, update the module registry, and stop cleanly. Do not
   continue into degraded context.

---

## 8. Phase-0 Task (This Session)

This START-PROMPT launches Phase-0. The deliverables for this session are:

1. **Review** the module registry (Section 5) against `MASTER.md` and the
   three legacy folders. Identify any missing modules, mis-ordered
   dependencies, or modules that should be split.
2. **Propose adjustments** to the module order or boundaries with reasoning.
3. **Write contracts** for M1, M7, and M11 — one from each layer — as
   representative samples. User reviews and approves or revises.
4. **Confirm the build order** explicitly. Record any user decisions as
   notes in the registry.
5. **Stop.** Do not write any code or create any files in `LLM-RAG-WIKI/`.

Output at the end of Phase-0:
- Updated module registry table (Sections 5) with any adjustments
- Three completed module contracts (M1, M7, M11)
- Confirmed build order
- Brief session summary (≤ 5 sentences)

---

## 9. Launching a Module Build Session

After Phase-0 is complete, each subsequent session is launched with:

```
Contract: START-PROMPT.md
Master spec: MASTER.md
Target module: M{N} — {Name}
Dependencies confirmed DONE: M{x}, M{y}

Task:
1. Read START-PROMPT.md Section 2, 3, 5, 7.
2. Read MASTER.md sections relevant to this module.
3. Output Pre-Flight Checklist (Section 3 of START-PROMPT).
4. Confirm the module contract (Section 5 of START-PROMPT).
5. Build the module.
6. Run and record acceptance tests.
7. Update module registry status to DONE.
8. Output session summary; stop.
```

---

## 10. Integration Session (M14)

Launched only when M1–M13 are all `DONE`. The integration session:

1. Wires the three layers into a single entry point (CLI or runner script)
2. Runs `tests/test_integration.py` against a minimal fixture wiki
3. Verifies the end-to-end pipeline: `entry/ → raw/ → wiki/ → chroma/ → MCP query`
4. Produces a `CHANGELOG.md` entry for v2.0.0
5. Confirms the legacy folders are safe to delete

After user sign-off on M14: delete `./LLM_Wiki/`, `./RAG-Wiki/`,
`./Local_MCP_Server/`. Update `README.md`. Tag `v2.0.0`.
