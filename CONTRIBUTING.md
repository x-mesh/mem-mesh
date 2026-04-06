# Contributing to mem-mesh

Thank you for your interest in contributing to mem-mesh — a centralized AI memory management server built on SQLite + sqlite-vec.

## Table of Contents

- [Development Environment Setup](#development-environment-setup)
- [Code Style](#code-style)
- [Running Tests](#running-tests)
- [Pull Request Guidelines](#pull-request-guidelines)
- [Commit Message Format](#commit-message-format)
- [Issue Reporting](#issue-reporting)
- [Code of Conduct](#code-of-conduct)

---

## Development Environment Setup

### Prerequisites

- Python 3.9 or higher
- `pip` (latest recommended)
- Git

### Installation

```bash
git clone https://github.com/your-org/mem-mesh.git
cd mem-mesh

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install all dependencies (server + dev extras)
pip install -e ".[server,dev]"

# Or use the Makefile shortcut
make install-dev
```

### Environment Configuration

```bash
cp .env.example .env   # if available, or create .env manually
```

Key environment variables:

| Variable | Description | Default |
|---|---|---|
| `MEM_MESH_DB_PATH` | SQLite database file path | `./data/memories.db` |
| `MEM_MESH_CLIENT` | Client identifier (stdio mode) | — |
| `MCP_LOG_FORMAT` | Log format (`text` or `json`) | `text` |

### Running the Development Server

```bash
# FastAPI web server + dashboard (hot reload)
make run-api
# -> http://localhost:8000
# -> API docs: http://localhost:8000/docs

# MCP stdio server (FastMCP)
make run-mcp

# Pure MCP stdio server
make run-mcp-pure
```

If port 8000 is already in use, the server is already running — do not restart it.

### Pre-commit Hooks (optional but recommended)

```bash
pre-commit install
```

---

## Code Style

mem-mesh enforces consistent style across all Python source files.

### Formatter: Black

Line length is 88 characters. Format all code before committing:

```bash
make format
# equivalent: black app/ tests/ scripts/
```

### Linter: Ruff

```bash
make lint          # check only
make lint-fix      # check and auto-fix
```

### Import Order: isort (Black-compatible profile)

Maintain the following import order in every file:

```python
# 1. Standard library
import os
import asyncio

# 2. Third-party
from fastapi import FastAPI
from pydantic import BaseModel

# 3. Local (absolute imports only)
from app.core.errors import NotFoundError
from app.core.version import get_version
```

Never use relative imports (`from .module import ...`).

### Type Hints

All public functions and methods must have complete type annotations. The `Any` type is prohibited.

```python
# correct
async def search(query: str, limit: int = 10) -> list[SearchResult]:
    ...

# wrong — missing return type, uses Any
def search(query, limit=10):
    ...
```

### Async/Await

All database and vector operations must be `async`. Never perform database work from synchronous functions or directly from route handlers.

```python
# correct
async def get_memory(memory_id: str) -> Memory:
    return await db.fetch_one(memory_id)

# wrong — synchronous DB call
def get_memory(memory_id: str) -> Memory:
    return db.fetch_one_sync(memory_id)
```

### Input Validation

All external input must pass through a Pydantic schema before reaching service or storage layers.

### Error Handling

Import error classes exclusively from `app.core.errors`. Do not define inline exception classes inside services.

```python
# correct
from app.core.errors import NotFoundError, ValidationError

# wrong
class MyServiceError(Exception): ...
```

### sqlite-vec Constraint

Never use `INSERT OR REPLACE` with sqlite-vec virtual tables. Use `DELETE` followed by `INSERT`.

```python
# correct
await db.execute("DELETE FROM vec_items WHERE id = ?", [id])
await db.execute("INSERT INTO vec_items VALUES (?, ?)", [id, embedding])

# wrong
await db.execute("INSERT OR REPLACE INTO vec_items VALUES (?, ?)", [id, embedding])
```

### Centralized Metadata

- Version information: `app.core.version` only
- Error classes: `app.core.errors` only

---

## Running Tests

### Unit Tests (no server required)

```bash
make test
# equivalent: pytest tests/ --ignore=tests/integration -v
```

### Integration Tests (requires running server at localhost:8000)

```bash
make test-live
# or target specific suites:
make test-live-api
make test-live-mcp
```

### All Tests

```bash
make test-all
```

### Coverage Report

```bash
make test-cov
# HTML report generated at htmlcov/index.html
```

### Test Markers

Use pytest markers to categorize tests:

```python
@pytest.mark.unit
async def test_search_returns_results(): ...

@pytest.mark.integration
async def test_api_add_and_retrieve(): ...

@pytest.mark.property
def test_embedding_roundtrip(hypothesis_input): ...
```

Run evaluation tests (Tier 3) with:

```bash
RUN_EVALS=1 pytest tests/evals/ -v
```

### Import Check

After any structural change, verify the application still imports cleanly:

```bash
python -c "from app.web.app import app"
```

---

## Pull Request Guidelines

### Before Opening a PR

1. Fork the repository and create a feature branch from `main`.
2. Run `make format` and `make lint` — CI will reject unformatted code.
3. Add or update tests to cover your change.
4. Run `make test` and confirm all unit tests pass.
5. Verify the import check: `python -c "from app.web.app import app"`.

### Branch Naming

```
feat/short-description
fix/issue-number-description
refactor/module-name
docs/what-was-updated
```

### PR Description

Include the following in your PR body:

- **What** changed and **why**
- Which modules are affected (refer to [AGENTS.md](./AGENTS.md) Context Map for routing)
- How to test the change manually (if applicable)
- Any migration steps required

### Review Process

- At least one maintainer approval is required before merge.
- Address all review comments or explicitly explain why a suggestion is declined.
- Squash commits on merge to keep history clean.

### Architecture Changes

For changes that affect the MCP protocol layer, database schema, or embedding pipeline, open a discussion issue first before writing code. Consult the [AGENTS.md Golden Rules](./AGENTS.md#golden-rules) to ensure constraints are respected.

---

## Commit Message Format

Follow the `type: description` convention (Conventional Commits):

```
type: short imperative description
```

| Type | When to use |
|---|---|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `refactor` | Code restructuring without behavior change |
| `docs` | Documentation only |
| `test` | Adding or updating tests |
| `chore` | Build, tooling, dependency updates |

**Examples:**

```
feat: add recency_weight parameter to search
fix: use DELETE+INSERT for sqlite-vec updates
refactor: move error classes to app.core.errors
docs: add batch_operations usage example
test: add property tests for embedding roundtrip
chore: bump version to 1.3.0
```

Rules:
- Use the imperative mood: "add", not "added" or "adds"
- Keep the subject line under 72 characters
- Do not end the subject line with a period
- Separate subject from body with a blank line when additional context is needed

---

## Issue Reporting

### Bug Reports

When filing a bug, include:

- mem-mesh version (`make version`)
- Python version and OS
- Minimal reproduction steps
- Actual vs. expected behavior
- Relevant log output (with sensitive values redacted)

### Feature Requests

Describe:

- The problem you are trying to solve
- Your proposed solution or API shape
- Alternatives you considered

### Security Vulnerabilities

Do not file public issues for security vulnerabilities. Contact the maintainers directly with a description and reproduction steps.

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you agree to uphold a respectful and inclusive environment for all contributors.

Report unacceptable behavior to the project maintainers.
