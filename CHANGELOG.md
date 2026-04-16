# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.1] - 2026-04-16

### Added
- `.github/workflows/docker.yml` — publishes `docker.io/xmesh/mem-mesh` on `v*` tag / main push. Multi-arch (linux/amd64 + linux/arm64), GHA cache, provenance + SBOM. Requires `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` secrets.
- Makefile targets: `uvx-install`, `uvx-serve`, `uvx-hooks`, `uvx-refresh`, `docker-buildx-push`, `release V=x.y.z`, `release-tag`.

### Fixed
- **Docker compose env vars ignored**: all `DATABASE_PATH`, `EMBEDDING_MODEL`, `LOG_LEVEL`, `STORAGE_MODE` etc. in `docker-compose.yml` and `docker/docker-compose.yml` lacked the required `MEM_MESH_` prefix, so pydantic-settings silently dropped them. User overrides had no effect. Now properly prefixed.
- **Dockerfile dependency resolution**: `requirements.txt` upper bounds conflicted with `mcp>=1.13` (needs `uvicorn>=0.31.1`) and `fastmcp>=2.14.2` (needs `httpx>=0.28.1`). Bumped both to compatible ranges (`uvicorn>=0.31.1`, `httpx>=0.28.1`).
- `docker/docker-compose.yml` no longer mounts the removed `../static` and `../templates` directories (content lives under `app/web/` since 1.4.0 and is covered by the `/app/app` source mount).
- `.env.example`: commented out legacy `MEM_MESH_EMBEDDING_MODEL=all-MiniLM-L6-v2` / `DIM=384` so copying the template doesn't silently override the new KURE-v1 default.

### Docs
- Noted in CHANGELOG that existing DBs created with 1.3.x keep their persisted `embedding_model` metadata, overriding the new default. To adopt KURE-v1 on an existing install: delete the database volume or update `embedding_metadata` via `sqlite3` / dashboard.

## [1.4.0] - 2026-04-16

### Added
- **uvx-first install flow** — `uvx mem-mesh install` / `uvx mem-mesh serve` work out of the box. MCP config now emits a `uvx` command (`--from "mem-mesh[server]" mem-mesh-mcp-stdio`) so clients auto-spawn an isolated, cached mem-mesh per call
- `mem-mesh install` onboarding detects `uvx` and offers it as the recommended server option; warms the uv cache so the first MCP call is instant
- Packaging smoke-test suite (`tests/test_packaging.py`, 19 tests) — catches missing shell templates, web templates/static/rules, undeclared deps, and default-path CWD leaks before release
- Boot-time "Loading server modules…" message + 25%-step embedding-model progress logs so the banner → first-response gap is visible

### Changed
- **Default embedding model**: `intfloat/multilingual-e5-large` → `nlpai-lab/KURE-v1` (Korean-tuned BGE-M3, 1024-dim); onboarding model picker lists KURE-v1 first
- **Default database path**: uses XDG-compliant per-user directory (`~/Library/Application Support/mem-mesh/` on macOS, `$XDG_DATA_HOME/mem-mesh/` on Linux, `%APPDATA%/mem-mesh/` on Windows) instead of `./data/memories.db` relative to CWD. A legacy `./data/memories.db` in CWD is still detected with a one-line stderr warning for backwards compatibility
- Default access-log dir follows the same XDG convention
- `templates/`, `static/`, and `docs/rules/` moved under `app/web/` and resolved via `Path(__file__)` so they're packaged into the wheel
- `TemplateResponse` calls switched to the new Starlette API (`request, "index.html", {…}`) — fixes `TypeError: unhashable type: 'dict'` on recent starlette/jinja2

### Fixed
- **Packaging**: `pyproject.toml` now includes `app/cli/hooks/shell/*.sh`, `app/web/templates/*.html`, `app/web/static/**`, `app/web/rules/*` as package data. Previously `uvx` installs hit `FileNotFoundError` for shell templates and dashboard assets
- **Server deps**: `urllib3`, `sse-starlette`, `tiktoken`, `requests` added to `[project.optional-dependencies.server]` (were transitive-only in dev envs; missing in clean uvx installs)
- `pysqlite3-binary` moved to Linux-only (`sys_platform == 'linux'`) — no wheels exist for macOS arm64; uv's managed Python builds include SQLite extension loading so the binary is unnecessary on macOS
- Dead `/test` endpoint serving a non-existent `test_web_ui.html` removed
- `_model_embedding_dim()` helper with fallback — silences `FutureWarning` from sentence-transformers ≥3 (`get_sentence_embedding_dimension` → `get_embedding_dimension`)
- `release.yml` verify step: `app.core.version.VERSION` → `app.core.version.__VERSION__` (matched actual symbol)

## [1.3.0] - 2026-04-16

### Added
- `RelationService.auto_link_similar` — vector similarity-based automatic memory linking (replaces prior TODO stub)
- `auto_complete_pins` strategy parameter on `session_end` — 3-state enum (`none`/`in_progress`/`all`), backwards compatible with boolean
- `tests/test_auto_complete_strategy.py` covering all strategies + backwards compatibility
- Public release tooling — `.github/workflows/release.yml` (PyPI publish automation via tag push)
- `CONTRIBUTING.md` with dev setup, PR workflow, tests, commit style, release process

### Changed
- `pin_list` optimization: when client-side filters (`min_importance`, `tags`) apply, fetch up to 200 records then trim to `limit` (prevents fewer-than-requested results); stats calculation merged into the pin iteration loop
- Repository ownership migrated from `JINWOO-J/mem-mesh` to `x-mesh/mem-mesh`; all URLs updated (`pyproject.toml`, `README*`, `Dockerfile`)
- `pyproject.toml`: authors email dropped (name-only), aligned with public-facing package metadata
- Renamed top-level `build.py` → `build_webui.py` to resolve module-name collision with PyPA's `build` (caused `python -m build` to import the local web UI script instead of the packaging frontend)

### Fixed
- `pyproject.toml`: moved `dependencies` out of `[project.urls]` table back into `[project]` (TOML scoping regression)
- Dockerfile `ENV MEM_MESH_SERVER_HOST=0.0.0.0` default — bare `docker run -p 8000:8000` now reachable from host (previously bound to `127.0.0.1` inside container, unreachable via published port)

### Security
- Bump `jinja2` pin `>=3.1.0` → `>=3.1.6` (CVE-2024-22195, CVE-2024-34064, CVE-2024-56326, CVE-2024-56201, CVE-2025-27516)
- Bump `fastmcp` pin `>=0.1.0,<1.0.0` → `>=2.14.2` (CVE-2025-62800, CVE-2025-62801, CVE-2025-64340, CVE-2025-69196, CVE-2026-27124, GHSA-rcfx-77hg-w2wv). `FastMCP(name)` API is source-compatible; MCP tests remain green.
- Reduces pip-audit findings from 46 CVEs (8 packages) to 1 CVE (transformers 4.57.6 → fix only available as 5.0.0rc3 pre-release; deferred pending sentence-transformers compatibility).

## [1.2.6] - 2026-04-14

### Fixed
- PreCompact hook JSON validation failure: switched output schema from `hookSpecificOutput` wrapper to `{continue, systemMessage}` format

## [Pre-1.2.x backlog]

### Fixed
- `MemoryService.create_with_embedding()` bug: replaced non-existent `db.add_memory()` with direct SQL INSERT + transaction
- CORS `allow_origins=["*"]` replaced with configurable `MEM_MESH_CORS_ORIGINS` environment variable
- Environment variable priority: `MEM_MESH_LOG_*` now takes precedence over deprecated `MCP_LOG_*`

### Added
- `MEM_MESH_CORS_ORIGINS` setting for configurable CORS origins
- `app/core/errors.py`: unified error codes, exception hierarchy, HTTP/JSON-RPC mappings
- `tests/conftest.py`: shared test fixtures (temp_db, mock services, MCP tool handlers)
- `.pre-commit-config.yaml` with Black, isort, Ruff, mypy hooks
- `CHANGELOG.md` (this file)
- `scripts/README.md`: categorized script documentation
- `docs/rfc-search-mode-simplification.md`: RFC for search mode consolidation
- Security warnings in `.env.example` for production deployment
- FastMCP stdio: pin/session/relations tools (pin_add, pin_complete, pin_promote, session_resume, session_end, link, unlink, get_links)
- CI: coverage reporting, Ruff linting, isort check, Codecov upload

### Changed
- Synced version in `pyproject.toml` to match `app/core/version.py` (1.0.4)

### Removed
- Legacy search files: `enhanced_search.py`, `improved_search.py`, `final_improved_search.py`, `simple_improved_search.py`

## [1.0.4] - 2026-02-15

### Added
- OAuth 2.1 authentication (Bearer token + Basic Auth)
- MCP Protocol 2025-03-26 Streamable HTTP transport
- UnifiedSearchService with hybrid/semantic/exact/fuzzy modes
- Work tracking system (projects, sessions, pins)
- Memory relations (link, unlink, get_links)
- Batch operations for MCP tools
- Token estimation and context optimization
- Web dashboard with SPA architecture
- WebSocket real-time notifications
- Monitoring API and search metrics

## [1.0.0] - 2026-01-01

### Added
- Initial release
- SQLite + sqlite-vec vector storage
- sentence-transformers embedding service
- MCP stdio server (FastMCP + Pure)
- FastAPI REST API
- Memory CRUD operations
- Vector search and FTS5 full-text search
- Project-based memory organization
