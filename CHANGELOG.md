# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `RelationService.auto_link_similar` — vector similarity-based automatic memory linking (replaces prior TODO stub)
- `auto_complete_pins` strategy parameter on `session_end` — 3-state enum (`none`/`in_progress`/`all`), backwards compatible with boolean
- `tests/test_auto_complete_strategy.py` covering all strategies + backwards compatibility

### Changed
- `pin_list` optimization: when client-side filters (`min_importance`, `tags`) apply, fetch up to 200 records then trim to `limit` (prevents fewer-than-requested results); stats calculation merged into the pin iteration loop

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
