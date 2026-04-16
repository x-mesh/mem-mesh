# Contributing to mem-mesh

Thank you for your interest in contributing to mem-mesh! Whether you're fixing a bug, proposing a feature, or improving documentation, your effort makes this project better for everyone. Before getting started, please read through [README.md](./README.md) and [AGENTS.md](./AGENTS.md) to understand the architecture and design goals.

---

## Development Setup

```bash
# 1. Clone the repository
git clone https://github.com/x-mesh/mem-mesh.git
cd mem-mesh

# 2. Create and activate a virtual environment
python -m venv .venv && source .venv/bin/activate

# 3. Install in editable mode with dev dependencies
pip install -e ".[dev]"

# 4. Verify the install
python -c "from app.web.app import app"
```

If the import check exits cleanly with no output, your environment is ready.

---

## Running the Project

mem-mesh supports three run modes:

```bash
# FastAPI web server + dashboard (port 8000, hot-reload)
python -m app.web --reload

# FastMCP stdio server (for Cursor, Claude Desktop, Kiro)
python -m app.mcp_stdio

# Pure MCP stdio server (spec-compliant, no FastMCP dependency)
python -m app.mcp_stdio_pure

# Production web server
uvicorn app.web.app:app --host 0.0.0.0 --port 8000
```

---

## Tests

Run the full test suite with verbose output:

```bash
python -m pytest tests/ -v
```

Run a quick import smoke check before committing:

```bash
python -c "from app.web.app import app"
```

### Adding new tests

- Place test files under the `tests/` directory.
- Name files `test_<module>.py` so pytest auto-collects them.
- Mirror the source structure where possible (e.g., `app/services/foo.py` → `tests/test_foo.py`).
- Use `pytest.mark.asyncio` for async test functions.
- Keep tests isolated — avoid shared mutable state across test functions.

---

## Code Style

mem-mesh enforces consistent formatting and typing. The CI pipeline (`.github/workflows/ci.yml`) runs these checks on every PR.

| Tool | Purpose |
|------|---------|
| **Black** | Code formatting — no manual style decisions |
| **Ruff** | Fast linting — catches common errors and style issues |
| **isort** | Import sorting |
| **mypy** | Static type checking |

### Import order

Follow the stdlib → third-party → local (absolute paths) convention:

```python
# stdlib
import asyncio
from pathlib import Path

# third-party
from fastapi import FastAPI
from pydantic import BaseModel

# local
from app.core.errors import NotFoundError
from app.services.memory import MemoryService
```

Never use relative imports (`from .module import ...`).

### Type hints

- Type hints are **required** on all function signatures.
- Do **not** use `any` as a type — use specific types or `object` where truly generic.
- All DB and vector operations must be `async`/`await`.

### Error handling and centralized metadata

- Import error classes from `app.core.errors` — never define inline errors inside service modules.
- Version constants live in `app.core.version` — do not hardcode version strings elsewhere.
- For sqlite-vec tables, use `DELETE` followed by `INSERT` — `INSERT OR REPLACE` is prohibited.

---

## Commit Messages

Use the format `type: description` with a concise, imperative description.

| Type | When to use |
|------|-------------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `refactor` | Code restructure without behavior change |
| `docs` | Documentation only |
| `test` | Adding or updating tests |
| `chore` | Build, CI, dependency updates |

**Examples:**

```
feat: add batch_operations endpoint for multi-op round-trips
fix: use DELETE+INSERT for sqlite-vec updates
refactor: extract NLI pipeline into standalone module
docs: update MCP setup instructions for Kiro
test: add async tests for session_resume expand modes
chore: bump sqlite-vec to 0.1.6
```

Rules: use imperative mood ("add" not "added"), keep subject under 72 characters, no trailing period.

---

## Pull Requests

- **Feature branches** → base branch: `develop`
- **Release merges** → base branch: `main`

Before opening a PR, confirm the following:

- [ ] All existing tests pass (`python -m pytest tests/ -v`)
- [ ] New behavior is covered by tests
- [ ] Import smoke check passes (`python -c "from app.web.app import app"`)
- [ ] CHANGELOG.md is updated under the `[Unreleased]` section
- [ ] README.md or AGENTS.md updated if public behavior changed
- [ ] No secrets, API keys, or `.env` content is included

Include a clear description of **what** changed and **why** in the PR body. For changes that affect the MCP protocol layer, database schema, or embedding pipeline, open a discussion issue before writing code.

---

## Release Process

1. **Bump the version** in `pyproject.toml` (`app.core.version` reads from it — single source of truth).
2. **Update CHANGELOG.md** — move items from `[Unreleased]` to the new version heading with today's date.
3. **Merge** the release branch into `main` via PR.
4. **Tag the release** on `main`:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

5. Pushing the tag triggers `.github/workflows/release.yml`, which builds the package and publishes it to PyPI automatically.

---

## Security

- **Never** commit API keys, tokens, passwords, `.env` file contents, or personally identifiable information (PII).
- Sensitive values in code snippets must be replaced with `<REDACTED>`.
- Do not open public issues for security vulnerabilities. Report them via **GitHub private security advisory** (Security tab → "Report a vulnerability").

---

## Code of Conduct

Be respectful, constructive, and kind. We welcome contributors of all backgrounds and experience levels. Harassment, dismissiveness, or personal attacks will not be tolerated.
