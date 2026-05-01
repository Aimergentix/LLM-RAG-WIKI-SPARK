# Changelog

All notable changes to LLM-RAG-WIKI are recorded here.

## [1.1.0-dev] — 2026-05-01
### Added
- **P5 — Snapshot Backups.** Implemented `src/rag/snapshot.py` to backup ChromaDB index and manifest before reindexing operations. Configurable via `config.yaml`.
- **P5 — Hybrid Retrieval.** Implemented BM25 lexical search layer and Reciprocal Rank Fusion (RRF) to combine semantic and keyword relevance.
- **P5 — Re-ranking.** Added `src/rag/reranker.py` using `CrossEncoder` to refine hybrid result sets. Updated `config.yaml` with reranking parameters.

## [1.0.0] — 2026-05-01

### Added
- **M14 — Integration + system test.** Completion of the modular rebuild.
  Editor shims (`AGENTS.md`, `GEMINI.md`, `SKILL.md`, etc.) created.
  Integration test suite `tests/test_integration.py` implemented to verify
  cross-layer handoff. System signed off for alpha release.

## [0.13.0] — 2026-05-01

### Added
- **M13 — MCP server.** `src/mcp/server.py` implementation using FastMCP.
  Exposes persona resources (`persona://current`, `persona://list`,
  `persona://summary`) and management tools (`activate_persona`,
  `activate_domain`, `add_persona_rule`). Extends `PersonaStore` with
  `active.yaml` persistence to track runtime state across sessions.
  Supports stdio transport for Cursor/Claude integration.
  8/8 M13 acceptance tests pass.

## [0.12.0] — 2026-05-01

### Added
- **M12 — Persona compiler.** `src/mcp/compiler.py` implementation.
  Provides "The Crusher" logic for deterministic profile generation.
  Supports ultra-dense text, structured JSON, and debug YAML outputs.
  Implements rule deduplication, priority-based merging, and 
  token-optimized symbol packing per MASTER §15.
  10/10 M12 acceptance tests pass.

## [0.11.0] — 2026-05-01

### Added
- **M11 — Persona store.** `src/mcp/store.py` implementation.
  Provides atomic, deterministic storage for character and domain personas.
  Enforces append-only audit logs and versioning. Implements path safety
  boundaries (`[ERR_SECURITY]`) and canonical YAML serialization.
  Includes `AuditEntry`, `Persona`, and `MetaDirective` dataclasses.
  12/12 M11 acceptance tests pass.

## [0.10.0] — 2026-05-01

### Added
- **M10 — Evals.** `src/rag/eval_runner.py` and `tests/eval_cases.yaml`.
  Implements the RAG evaluation framework (MASTER §11). Supports metrics
  for Precision@K, Recall@K, and Null Response Accuracy. Case matrix
  covers positive, negative_ood, borderline, adversarial, and security
  categories. 8/8 evaluation cases pass on current wiki index.

## [0.9.0] — 2026-05-01

### Added
- **M9 — Retrieval CLI.** `src/rag/retrieve.py` — implementation of the
  RAG query interface (MASTER §6 P3). Supports top-k retrieval with
  cosine distance, scoring thresholds (`min_score`, `ood_threshold`),
  and graceful degradation. Outputs schema-compliant YAML. Implements
  exit codes 0 (Success) and 1 (Degradation) as per MASTER §9.
  Handles `[ERR_CONFIG]`, `[ERR_INDEX_MISSING]`, and `[ERR_RUNTIME]`.
  12/12 M9 acceptance tests pass; 231/231 total.

## [0.8.0] — 2026-05-01

### Added
- **M8 — RAG ingest pipeline.** Five new modules under `src/rag/`
  (`manifest.py`, `chunker.py`, `embedder.py`, `store.py`, `ingest.py`,
  pre-declared 5-file split per §2.3, ~870 LOC Python total). Pure
  stdlib at module level; `chromadb` and `sentence_transformers` are
  imported only inside production-backend `__init__` methods, behind
  `[ERR_DB]` and `[ERR_EMBEDDING_MODEL]` with install-message
  conversion. The heading-aware Markdown chunker emits deterministic
  `Chunk` records honoring `chunking.min_chars` / `max_chars`, keeps
  fenced code blocks atomic, strips top-level YAML frontmatter, and
  derives stable IDs per MASTER §7 (`sha256(collection + rel_path +
  heading_path + chunk_index + chunk_hash)`). `EmbedderBackend` ABC
  ships with `SentenceTransformersEmbedder` (production) and
  `DeterministicHashEmbedder` (test stub producing unit-norm
  SHA-256-derived vectors). `VectorStore` ABC ships with
  `ChromaVectorStore` (production) and `InMemoryVectorStore` (test
  stub). The `ingest_wiki()` orchestrator scans `paths.wiki_root` for
  `*.md`, skips files outside `wiki_root.resolve()`, rejects symlink
  wiki roots with `[ERR_SECURITY]`, computes per-file `source_hash`,
  reuses prior manifest entries when both the file hash and
  `manifest.config_hash` match, deletes orphan chunk IDs for removed
  files, atomically rewrites the manifest (`*.tmp` + `os.replace` +
  `os.fsync`), and treats markdown as untrusted data: chunks
  containing prompt-injection markers are still indexed but their
  text is suppressed from the ingest log. `--reset` with
  `indexing.atomic_reindex=true` writes into a shadow store
  (Chroma collection or fresh `InMemoryVectorStore`) that is promoted
  to the primary only on success — failure mid-run leaves the
  original collection byte-equivalent. `privacy: secret` (or
  `private`) frontmatter pages are skipped when
  `privacy.block_secret_chunks=true`. CLI: `python -m rag.ingest
  [--config PATH] [--reset]`. Production embedder is bypassed in
  tests via `LLM_RAG_WIKI_TEST_STUB_EMBEDDER=1` (used by the M8 CLI
  fallback path; the test suite injects backends directly).
  32/32 M8 acceptance tests pass; 219/219 total.
- M8 contract filed inline in `START-PROMPT.md` §5.

## [0.7.0] — 2026-05-01

### Added
- **M7 — Config + schema.** `src/rag/__init__.py` (empty package marker) +
  `src/rag/config.py` — pure-stdlib RAG configuration loader, validator, and
  typed accessor implementing MASTER §7 (RAG Schemas), §8 (security), and
  §9 (`[ERR_CONFIG]`). Frozen dataclass hierarchy: `Config` / `ProjectConfig`
  / `RuntimeConfig` / `DomainConfig` / `EmbeddingConfig` / `PathsConfig` /
  `ChunkingConfig` / `IndexingConfig` / `RetrievalConfig` / `PrivacyConfig`.
  `load_config()` resolves config via three-step priority: explicit path arg
  → `LLM_RAG_WIKI_CONFIG` env var → `config.yaml` at repo root (located
  relative to `config.py`'s own `__file__`). All path fields resolved
  absolute relative to the config file's directory. Validation enforces:
  `schema_version == 1` (bool rejected); all required sections and leaves
  present with correct types; `wiki_root` must not contain `entry` or `raw`
  as a path component (`[ERR_CONFIG]`); `0.0 <= ood_threshold <= min_score
  <= 1.0`; `min_chars >= 1` and `max_chars > min_chars`. `config_hash()`
  produces a stable SHA-256 over a canonical key-sorted JSON serialization,
  invariant to YAML key order and whitespace. `yaml` imported inside function
  body with a clear `ConfigError` install message if missing. `config.yaml`
  stub replaced with the canonical MASTER §7 default.
  49/49 M7 acceptance tests pass; 187/187 total.
- M7 contract filed inline in `START-PROMPT.md` §5.

## [0.6.0] — 2026-05-01

### Added
- **M6 — Cron / watch ops.** Four pure-bash scripts under `src/wiki/`:
  `install_cron.sh` — interactive diff-first crontab installer;
  `uninstall_cron.sh` — symmetric removal with diff preview;
  `install_wiki_bin.sh` — non-interactive bin-copy that populates
  `$WIKI_ROOT/.wiki/bin/` with stable copies of all `src/wiki/` scripts
  (satisfies adj. D deferred from M1/M2);
  `lint_cron.sh` — thin cron wrapper that invokes `graph_lint.py --log
  --fail-on=medium` and appends a timestamped line to `.wiki/cron.log`.
  Both install/uninstall scripts are idempotent via the
  `# llm-wiki-builder:{wiki-name}` / `# llm-wiki-builder:{wiki-name}-end`
  tag pair; show a unified diff before writing; require `y/Y/yes/YES`
  confirmation; degrade gracefully (exit 2, log line written) when
  `crontab` is absent. Scheduled jobs: `autoconvert.sh` every 15 minutes,
  `lint_cron.sh` Mondays at 06:23. `sync.sh` deferred (adj. D2 — not yet
  implemented; deferral note in cron block). Symlink-as-wiki-root rejected
  with `[ERR_SECURITY]` (exit 4) in all four scripts.
  `LLMWIKI_SRC_DIR` env override enables full PATH-scrubbed test isolation.
  24/24 M6 acceptance tests pass; 138/138 total.
- M6 contract filed inline in `START-PROMPT.md` §5.

## [0.5.0] — 2026-05-01

### Added
- **M5 — Query + synthesis.** `src/wiki/query.py` + `src/wiki/query_agent.py`
  — pure-stdlib query orchestrator and LLM-agent seam implementing MASTER
  §6 W4. `query_one()` scans `wiki/**/*.md` for candidate pages, delegates
  ranking and synthesis to a `QueryAgent`, and optionally writes an atomic
  `wiki/synthesis/{slug}.md` page (hydrated from `templates/pages/synthesis.md`),
  an index entry under `## Synthesis`, and one W4 log line. Symlink-as-wiki-root
  rejected with `[ERR_SECURITY]` before `Path.resolve()`. Two-phase atomic
  writer (temp + `os.replace`) covers synthesis page, `index.md`, and `log.md`.
  `QueryAgent` ABC + `DeterministicStubQueryAgent` keep the entire suite
  offline. `LLMWIKI_TEST_STUB_AGENT=1` gates stub in CLI; production
  requires `--agent dotted.path:Class`. Strictly read-only against
  `raw/`, `entry/`, `.wiki/`, and all upstream legacy folders.
  23/23 M5 acceptance tests pass; 114/114 total.
- M5 contract filed inline in `START-PROMPT.md` §5.

## [0.4.0] — 2026-05-01

### Added
- **M4 — Graph lint.** `src/wiki/graph_lint.py` — pure-stdlib graph-aware
  linter implementing all eight rules from MASTER Appendix C
  (`orphan`, `broken_link`, `index_gap`, `hub_and_spoke`,
  `relation_code_distribution`, `unknown_relation_code`,
  `asymmetric_coverage`, `stale_candidate`) plus the five-state
  discourse classifier (`EMPTY` / `BIASED` / `FOCUSED` /
  `DIVERSIFIED` / `DISPERSED`). CLI:
  `python -m wiki.graph_lint <root> [--json] [--log]
  [--fail-on={high,medium,low,none}]`. Strictly read-only against
  wiki content; only `--log` appends a single W5 line to `log.md`.
  Symlink-rooted lint targets rejected with `[ERR_SECURITY]`.
  30/30 M4 acceptance tests pass; 91/91 total.
- M4 contract filed inline in `START-PROMPT.md` §5.

## [0.3.0] — 2026-05-01

### Added
- **M3 — Ingest agent.** Single-source `raw/{slug}.md → wiki/sources/{slug}.md`
  writer with DAG-ordered concept/entity cross-ref pass, anchor-bounded
  glossary patch in `SCHEMA.md`, plus `index.md` and `log.md` updates.
  Split across `src/wiki/{ingest.py, crossref.py, glossary.py,
  agent_seam.py, _frontmatter.py}` per the §2.3 size cap. Two-phase
  atomic writer (temp + `os.replace`) covers all five candidate target
  files. LLM seam (`IngestAgent` ABC) plus `DeterministicStubAgent`
  keep the entire suite offline. Reads `.wiki/.converted.json` (M2)
  read-only; never modifies `raw/`, `entry/`, or `.wiki/`.
  20/20 M3 acceptance tests pass; 61/61 total.
- M3 contract filed inline in `START-PROMPT.md` §5.

## [0.2.0] — 2026-05-01

### Added
- **M2 — Converter pipeline.** `src/wiki/autoconvert.sh` (tiered
  `entry/ → raw/` converter), `src/wiki/watch_entry.sh` (inotify with
  polling fallback), `src/wiki/session_check.sh` (silent-unless-pending
  status probe). Atomic `os.replace` manifest writes; `flock(1)` lock
  with Python `fcntl` fallback for concurrent runs; slug-collision
  disambiguation; needs-vision stubs for PDFs without text converters
  and for image inputs. 19/19 acceptance tests pass under PATH-scrubbed
  isolation.
- M2 contract filed inline in `START-PROMPT.md` §5.

## [0.1.0] — 2026-04-30

### Added
- **M0 — Plan & module breakdown.** `MASTER.md`, `START-PROMPT.md`,
  module registry, and contracts for M1, M7, M11.
- **M1 — Scaffold + templates.** `src/wiki/init.py`, root templates
  (`SCHEMA.md`, `index.md`, `log.md`, `CONTEXT.md`, `ADR-template.md`),
  page templates (`source.md`, `concept.md`, `entity.md`,
  `synthesis.md`), `scripts/run_phase.sh`, `scripts/bump_version.sh`.
  22/22 acceptance tests pass.
