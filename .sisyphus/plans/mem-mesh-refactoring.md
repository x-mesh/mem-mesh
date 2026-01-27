# mem-mesh Comprehensive Refactoring Plan

## Context

### Original Request
Create a detailed, prioritized refactoring plan for mem-mesh based on comprehensive codebase analysis covering:
- DRY violations in search implementations
- Missing tests for critical modules
- Code quality issues (bare except, missing type hints)
- Large file refactoring
- MCP implementation duplication

### Interview Summary

**Key Discussions**:
- **Legacy Search Strategy**: User chose to move 5 legacy search files to `legacy/` folder for reference
- **Test Priority**: MCP Servers first (external interfaces, critical for client integrations)
- **File Splitting**: By responsibility pattern (DatabaseConnection, DatabaseInitializer, DatabaseMigrator)
- **Test Strategy**: TDD approach - write tests first, then refactor

**Research Findings**:
- 6 search implementations with UnifiedSearchService as active (~2,500+ lines duplication)
- 6 bare except clauses masking errors
- MCP stdio servers have 0% test coverage
- ~388 lines duplicated between Pure MCP and SSE MCP
- 10 files exceed 500 lines
- 17 sleep() calls in tests causing flakiness
- Tests import from old `src/` architecture instead of new `app/`

### Metis Review (Self-Analysis)

**Identified Gaps** (addressed in plan):
- Added rollback verification steps to each phase
- Specified test count targets for each module
- Added CI/CD integration considerations
- Locked down scope creep boundaries

---

## Work Objectives

### Core Objective
Eliminate technical debt and improve maintainability of mem-mesh through systematic refactoring: consolidate duplicated code, add comprehensive test coverage, fix code quality issues, and split oversized files.

### Concrete Deliverables
- 5 legacy search files moved to `app/core/services/legacy/`
- 6 bare except clauses replaced with specific exception handling
- Test suites for MCP servers (>80% coverage target)
- Type hints added to 23 functions
- Dispatcher abstraction for MCP implementations
- Large files split by responsibility

### Definition of Done
- [ ] All pytest tests pass: `python -m pytest tests/ -v`
- [ ] No bare except clauses: `grep -r "except:" app/ | wc -l` = 0
- [ ] Type check passes: `mypy app/ --ignore-missing-imports`
- [ ] MCP servers tested: `pytest tests/test_mcp_stdio*.py` shows >10 tests
- [ ] Legacy files archived: `ls app/core/services/legacy/` shows 5 files

### Must Have
- Zero breaking changes to MCP tool interfaces
- All existing tests continue to pass
- UnifiedSearchService remains the active implementation
- MCP Protocol 2024-11-05 compliance maintained

### Must NOT Have (Guardrails)
- NO changes to database schema
- NO modifications to MCP tool schemas or method signatures
- NO new feature development (refactoring only)
- NO frontend changes
- NO external vector database integrations
- NO changes to embedding model configuration

---

## Verification Strategy (MANDATORY)

### Test Decision
- **Infrastructure exists**: YES (pytest, 74 test files)
- **User wants tests**: TDD (Test-Driven Development)
- **Framework**: pytest with asyncio

### TDD Workflow
Each refactoring task follows RED-GREEN-REFACTOR:
1. **RED**: Write failing test that validates new behavior
2. **GREEN**: Implement minimum code to pass
3. **REFACTOR**: Clean up while keeping green

### Existing Test Baseline
Before any changes, verify baseline:
```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: All existing tests pass (baseline for regression detection)

---

## Task Flow

```
Phase 1: Critical Fixes (Foundation)
├── 1.1 Archive legacy search files
├── 1.2 Fix bare except clauses
└── 1.3 Verify baseline tests still pass

Phase 2: Test Coverage (TDD Foundation)
├── 2.1 MCP Stdio server tests
├── 2.2 MCP Pure server tests  
├── 2.3 Session/Pin service tests
└── 2.4 Add missing type hints

Phase 3: Code Consolidation
├── 3.1 Create MCP dispatcher abstraction
├── 3.2 Split database/base.py
├── 3.3 Split dashboard/routes.py
└── 3.4 Fix flaky tests

Phase 4: Cleanup (Ongoing)
├── 4.1 Migrate test imports to app/
├── 4.2 Remove empty function bodies
└── 4.3 Documentation updates
```

## Parallelization

| Group | Tasks | Reason |
|-------|-------|--------|
| A | 1.1, 1.2 | Independent file modifications |
| B | 2.1, 2.2 | Independent test files |
| C | 2.3, 2.4 | Can run in parallel with B |
| D | 3.2, 3.3 | Independent file splits |

| Task | Depends On | Reason |
|------|------------|--------|
| 1.3 | 1.1, 1.2 | Verify after changes |
| 2.* | 1.3 | Need stable baseline |
| 3.1 | 2.1, 2.2 | Need tests before refactoring |
| 3.2 | 2.* | Need tests before splitting |
| 4.* | 3.* | Final cleanup after major work |

---

## TODOs

### Phase 1: Critical Fixes (Immediate - 1-2 days)

---

- [ ] 1.1 Archive Legacy Search Implementations

  **What to do**:
  - Create `app/core/services/legacy/` directory
  - Move 5 legacy files: `search.py`, `enhanced_search.py`, `improved_search.py`, `final_improved_search.py`, `simple_improved_search.py`
  - Create `app/core/services/legacy/__init__.py` with deprecation notice
  - Update any imports that reference these files (should be none since UnifiedSearchService is active)
  - Verify `use_unified_search=True` is the default in config

  **Must NOT do**:
  - Do NOT delete the files (preserve for reference)
  - Do NOT modify UnifiedSearchService
  - Do NOT change config defaults

  **Parallelizable**: YES (with 1.2)

  **References**:
  - `app/core/services/search.py` - Legacy base search (872 lines)
  - `app/core/services/enhanced_search.py` - Quality optimization extension
  - `app/core/services/improved_search.py` - Korean optimization extension
  - `app/core/services/final_improved_search.py` - Standalone translation
  - `app/core/services/simple_improved_search.py` - Lightweight standalone
  - `app/core/services/unified_search.py` - ACTIVE implementation (keep in place)
  - `app/core/config.py:use_unified_search` - Config flag (verify default=True)
  - `app/core/storage/direct.py` - Check import usage

  **Acceptance Criteria**:
  - [ ] Directory exists: `ls app/core/services/legacy/` shows directory
  - [ ] Files moved: `ls app/core/services/legacy/*.py | wc -l` = 6 (5 files + __init__.py)
  - [ ] Original location clean: `ls app/core/services/*search*.py` shows only `unified_search.py`, `search_quality.py`, `search_warmup.py`
  - [ ] No import errors: `python -c "from app.core.storage.direct import DirectStorage"` succeeds
  - [ ] Tests pass: `python -m pytest tests/ -v --tb=short -q` shows no failures

  **Commit**: YES
  - Message: `refactor: archive legacy search implementations to legacy/`
  - Files: `app/core/services/legacy/`
  - Pre-commit: `python -m pytest tests/test_search_service.py -v`

---

- [ ] 1.2 Fix Bare Except Clauses

  **What to do**:
  - Replace all 6 bare `except:` with specific exception types
  - Add logging for caught exceptions
  - Use `except Exception as e:` as minimum, or more specific types where applicable

  **Files to modify**:
  1. `app/core/database/base.py:122` - Change to `except Exception as e:` with logging
  2. `app/core/services/enhanced_search.py:381` - Change to `except Exception as e:`
  3. `app/core/services/search_quality.py:397` - Change to `except Exception as e:`
  4. `app/core/services/search_quality.py:534` - Change to `except Exception as e:`
  5. `app/core/services/noise_filter.py:259` - Change to `except Exception as e:`
  6. `app/web/dashboard/routes.py:393` - Change to `except Exception as e:`

  **Must NOT do**:
  - Do NOT change the logic flow (catch and continue as before)
  - Do NOT add new exception types without understanding context
  - Do NOT suppress SystemExit or KeyboardInterrupt

  **Parallelizable**: YES (with 1.1)

  **References**:
  - `app/core/database/base.py:120-125` - Extension loading fallback
  - `app/core/services/enhanced_search.py:378-382` - Explanation generation
  - `app/core/services/search_quality.py:394-398` - Scoring calculation
  - `app/core/services/search_quality.py:531-535` - Feedback recording
  - `app/core/services/noise_filter.py:256-260` - Recency filtering
  - `app/web/dashboard/routes.py:390-394` - Delete endpoint
  - `app/core/utils/logger.py` - Logging pattern to follow

  **Acceptance Criteria**:
  - [ ] No bare excepts: `grep -rn "except:" app/ | grep -v "except Exception" | grep -v "except.*Error" | wc -l` = 0
  - [ ] All exceptions logged: Each modified except block includes `logger.warning()` or `logger.error()`
  - [ ] Tests pass: `python -m pytest tests/ -v --tb=short -q` shows no failures
  - [ ] Manual verification: `grep -n "except Exception" app/core/database/base.py` shows line ~122

  **Commit**: YES
  - Message: `fix: replace bare except clauses with specific exception handling`
  - Files: 5 files listed above
  - Pre-commit: `python -m pytest tests/ -v --tb=short -q`

---

- [ ] 1.3 Verify Baseline After Phase 1

  **What to do**:
  - Run full test suite to confirm no regressions
  - Verify all imports work correctly
  - Confirm MCP servers still functional

  **Must NOT do**:
  - Do NOT proceed to Phase 2 if any tests fail

  **Parallelizable**: NO (depends on 1.1, 1.2)

  **References**:
  - `tests/` - Full test directory
  - `app/core/storage/direct.py` - Primary import point for services

  **Acceptance Criteria**:
  - [ ] Full test pass: `python -m pytest tests/ -v --tb=short` shows 0 failures
  - [ ] Import test: `python -c "from app.core.storage.direct import DirectStorage; print('OK')"` prints OK
  - [ ] MCP import test: `python -c "from app.mcp_stdio.server import mcp; print('OK')"` prints OK
  - [ ] Quick MCP test: `echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | timeout 5 python -m app.mcp_stdio_pure 2>/dev/null | head -1` returns valid JSON

  **Commit**: NO (verification only)

---

### Phase 2: Test Coverage (1-2 weeks)

---

- [ ] 2.1 Create MCP Stdio Server Tests (TDD)

  **What to do**:
  - Create `tests/test_mcp_stdio.py` with comprehensive tests
  - Test tool registration, initialization, tool calls
  - Test error handling for invalid requests
  - Target: 10+ test functions, >80% coverage

  **TDD Workflow**:
  1. RED: Write test for tool listing → Verify it fails (no mock setup)
  2. GREEN: Add proper test infrastructure
  3. REFACTOR: Extract common fixtures

  **Must NOT do**:
  - Do NOT modify the MCP server code (test as-is first)
  - Do NOT test internal implementation details (test public interface)

  **Parallelizable**: YES (with 2.2)

  **References**:
  - `app/mcp_stdio/server.py` - FastMCP-based implementation (306 lines)
  - `app/mcp_common/tools.py` - Shared tool handlers
  - `tests/test_mcp_tools.py` - Existing MCP tool tests (12 tests) - pattern to follow
  - `tests/test_mcp.py` - Basic MCP tests - pattern reference

  **Acceptance Criteria**:
  - [ ] Test file exists: `ls tests/test_mcp_stdio.py`
  - [ ] Test count: `grep -c "async def test_" tests/test_mcp_stdio.py` >= 10
  - [ ] Tests pass: `python -m pytest tests/test_mcp_stdio.py -v` shows all pass
  - [ ] Coverage check: Tests cover initialize, tools/list, tools/call for all 11 tools

  **Commit**: YES
  - Message: `test: add comprehensive tests for FastMCP stdio server`
  - Files: `tests/test_mcp_stdio.py`
  - Pre-commit: `python -m pytest tests/test_mcp_stdio.py -v`

---

- [ ] 2.2 Create MCP Pure Server Tests (TDD)

  **What to do**:
  - Create `tests/test_mcp_stdio_pure.py` with comprehensive tests
  - Test JSON-RPC message handling, tool dispatch
  - Test error responses for malformed requests
  - Target: 10+ test functions, >80% coverage

  **TDD Workflow**:
  1. RED: Write test for JSON-RPC parsing → Verify current behavior
  2. GREEN: Ensure tests validate expected behavior
  3. REFACTOR: Extract test utilities

  **Must NOT do**:
  - Do NOT modify the Pure MCP server code (test as-is first)
  - Do NOT duplicate tests from 2.1 (test unique behaviors)

  **Parallelizable**: YES (with 2.1)

  **References**:
  - `app/mcp_stdio_pure/server.py` - Pure MCP implementation (424 lines)
  - `app/mcp_stdio_pure/server.py:147-286` - Tool dispatch branches to test
  - `app/mcp_stdio_pure/server.py:385-401` - Method dispatch to test
  - `tests/test_mcp_stdio.py` - Pattern from 2.1 (if completed first)

  **Acceptance Criteria**:
  - [ ] Test file exists: `ls tests/test_mcp_stdio_pure.py`
  - [ ] Test count: `grep -c "async def test_\|def test_" tests/test_mcp_stdio_pure.py` >= 10
  - [ ] Tests pass: `python -m pytest tests/test_mcp_stdio_pure.py -v` shows all pass
  - [ ] Edge cases covered: Tests for malformed JSON, unknown methods, missing parameters

  **Commit**: YES
  - Message: `test: add comprehensive tests for Pure MCP stdio server`
  - Files: `tests/test_mcp_stdio_pure.py`
  - Pre-commit: `python -m pytest tests/test_mcp_stdio_pure.py -v`

---

- [ ] 2.3 Create Session and Pin Service Tests (TDD)

  **What to do**:
  - Create `tests/test_session_service.py` with unit tests
  - Create `tests/test_pin_service.py` with unit tests
  - Convert manual tests from `tests/manual/` to automated tests
  - Target: 8+ tests per service

  **TDD Workflow**:
  1. RED: Write test for session_resume → Define expected behavior
  2. GREEN: Verify service meets expectations
  3. REFACTOR: Extract database fixtures

  **Must NOT do**:
  - Do NOT modify service implementation (test first)
  - Do NOT use time.sleep() in new tests

  **Parallelizable**: YES (with 2.1, 2.2, 2.4)

  **References**:
  - `app/core/services/session.py` - Session service (355 lines)
  - `app/core/services/pin.py` - Pin service (398 lines)
  - `tests/manual/test_pin_promotion.py` - Manual test to convert
  - `tests/manual/test_work_tracking_integration.py` - Manual test to convert
  - `tests/test_memory_service.py` - Pattern for service tests

  **Acceptance Criteria**:
  - [ ] Test files exist: `ls tests/test_session_service.py tests/test_pin_service.py`
  - [ ] Test count session: `grep -c "async def test_" tests/test_session_service.py` >= 8
  - [ ] Test count pin: `grep -c "async def test_" tests/test_pin_service.py` >= 8
  - [ ] No sleep calls: `grep -c "sleep" tests/test_session_service.py tests/test_pin_service.py` = 0
  - [ ] Tests pass: `python -m pytest tests/test_session_service.py tests/test_pin_service.py -v`

  **Commit**: YES
  - Message: `test: add automated tests for Session and Pin services`
  - Files: `tests/test_session_service.py`, `tests/test_pin_service.py`
  - Pre-commit: `python -m pytest tests/test_session_service.py tests/test_pin_service.py -v`

---

- [x] 2.4 Add Missing Return Type Hints

  **What to do**:
  - Add return type hints to 23 identified functions
  - Run mypy to verify type correctness
  - Focus on high-priority files first

  **Files to modify** (priority order):
  1. `app/core/schemas/requests.py` - 10 validator functions
  2. `app/core/services/search_quality.py` - 2 functions (lines 541, 561)
  3. `app/core/utils/logger.py` - log_duration (line 269)
  4. `app/web/lifespan.py` - get_services (line 204)
  5. `app/core/services/pin.py` - session_service property (line 48)
  6. `app/core/services/alert.py` - update_thresholds (line 381)
  7. Other utility functions

  **Must NOT do**:
  - Do NOT change function behavior
  - Do NOT add overly complex generic types

  **Parallelizable**: YES (with 2.1, 2.2, 2.3)

  **References**:
  - `app/core/schemas/requests.py:18,28,46,54,64,80,102,124,134,142` - Validator functions
  - Python typing module documentation
  - Existing type hints in codebase for patterns

  **Acceptance Criteria**:
  - [ ] Type hints added: `grep -c "-> " app/core/schemas/requests.py` increased by 10
  - [ ] mypy passes: `mypy app/core/schemas/requests.py --ignore-missing-imports` shows 0 errors
  - [ ] Tests pass: `python -m pytest tests/ -v --tb=short -q` shows no failures

  **Commit**: YES
  - Message: `refactor: add missing return type hints to 23 functions`
  - Files: Multiple files as listed
  - Pre-commit: `mypy app/ --ignore-missing-imports --no-error-summary`

---

### Phase 3: Code Consolidation (2-3 weeks)

---

- [x] 3.1 Create MCP Dispatcher Abstraction

  **What to do**:
  - Create `app/mcp_common/dispatcher.py` with unified dispatch logic
  - Extract 11 tool dispatch branches into a single dispatcher class
  - Create `app/mcp_common/transport.py` for JSON-RPC formatting
  - Refactor Pure MCP and SSE MCP to use new abstractions
  - Reduce ~388 lines of duplication

  **TDD Workflow**:
  1. RED: Write tests for new Dispatcher class
  2. GREEN: Implement Dispatcher with same behavior as existing code
  3. REFACTOR: Update Pure MCP and SSE MCP to use Dispatcher

  **Must NOT do**:
  - Do NOT change MCP tool behavior
  - Do NOT modify tool schemas
  - Do NOT break FastMCP implementation

  **Parallelizable**: NO (depends on 2.1, 2.2)

  **References**:
  - `app/mcp_stdio_pure/server.py:147-286` - Tool dispatch to extract
  - `app/web/mcp/sse.py:112-237` - Tool dispatch to extract
  - `app/mcp_common/tools.py` - Existing shared handlers
  - `app/mcp_common/schemas.py` - Tool schemas

  **Acceptance Criteria**:
  - [ ] Files created: `ls app/mcp_common/dispatcher.py app/mcp_common/transport.py`
  - [ ] Dispatcher tests: `python -m pytest tests/test_mcp_dispatcher.py -v` (new test file)
  - [ ] Pure MCP updated: `wc -l app/mcp_stdio_pure/server.py` < 350 lines (was 424)
  - [ ] SSE MCP updated: `wc -l app/web/mcp/sse.py` < 400 lines (was 480)
  - [ ] All MCP tests pass: `python -m pytest tests/test_mcp*.py -v`

  **Commit**: YES
  - Message: `refactor: extract MCP dispatcher and transport abstractions`
  - Files: `app/mcp_common/dispatcher.py`, `app/mcp_common/transport.py`, `app/mcp_stdio_pure/server.py`, `app/web/mcp/sse.py`
  - Pre-commit: `python -m pytest tests/test_mcp*.py -v`

---

- [x] 3.2 Split database/base.py by Responsibility

  **What to do**:
  - Split 768-line `app/core/database/base.py` into:
    - `app/core/database/connection.py` - DatabaseConnection class
    - `app/core/database/initializer.py` - DatabaseInitializer class
    - `app/core/database/migrator.py` - DatabaseMigrator class
    - `app/core/database/base.py` - Re-export facade (backward compatible)
  - Each file should be <300 lines
  - Maintain backward compatibility via re-exports

  **TDD Workflow**:
  1. RED: Write tests for each new class before splitting
  2. GREEN: Extract classes maintaining existing behavior
  3. REFACTOR: Clean up imports across codebase

  **Must NOT do**:
  - Do NOT change database schema
  - Do NOT break existing imports from base.py
  - Do NOT modify query logic

  **Parallelizable**: YES (with 3.3)

  **References**:
  - `app/core/database/base.py` - Current monolithic file (768 lines)
  - `app/core/database/base.py:1-150` - Connection management section
  - `app/core/database/base.py:150-400` - Table initialization section
  - `app/core/database/base.py:400-768` - Query and migration section
  - `app/core/AGENTS.md` - Database layer patterns

  **Acceptance Criteria**:
  - [ ] Files created: `ls app/core/database/connection.py app/core/database/initializer.py app/core/database/migrator.py`
  - [ ] Each file small: `wc -l app/core/database/*.py | grep -v total | awk '$1 > 300 {print}'` shows nothing
  - [ ] Backward compatible: `python -c "from app.core.database.base import Database; print('OK')"`
  - [ ] All tests pass: `python -m pytest tests/ -v --tb=short -q`

  **Commit**: YES
  - Message: `refactor: split database/base.py into connection, initializer, migrator modules`
  - Files: `app/core/database/`
  - Pre-commit: `python -m pytest tests/ -v --tb=short -q`

---

- [x] 3.3 Split dashboard/routes.py

  **What to do**:
  - Split 819-line `app/web/dashboard/routes.py` into:
    - `app/web/dashboard/routes/memories.py` - Memory CRUD endpoints
    - `app/web/dashboard/routes/search.py` - Search endpoints
    - `app/web/dashboard/routes/stats.py` - Statistics endpoints
    - `app/web/dashboard/routes/__init__.py` - Router aggregation
  - Each file should be <250 lines
  - Use FastAPI router composition

  **TDD Workflow**:
  1. RED: Ensure existing API tests cover all endpoints
  2. GREEN: Split maintaining same endpoint behavior
  3. REFACTOR: Clean up router organization

  **Must NOT do**:
  - Do NOT change API endpoints or response schemas
  - Do NOT break existing API clients
  - Do NOT modify authentication (none exists currently)

  **Parallelizable**: YES (with 3.2)

  **References**:
  - `app/web/dashboard/routes.py` - Current monolithic file (819 lines)
  - `tests/test_fastapi_app.py` - API endpoint tests
  - FastAPI router documentation

  **Acceptance Criteria**:
  - [ ] Directory created: `ls app/web/dashboard/routes/`
  - [ ] Router files: `ls app/web/dashboard/routes/*.py | wc -l` >= 4
  - [ ] Each file small: `wc -l app/web/dashboard/routes/*.py | grep -v total | awk '$1 > 250 {print}'` shows nothing
  - [ ] API tests pass: `python -m pytest tests/test_fastapi_app.py -v`

  **Commit**: YES
  - Message: `refactor: split dashboard routes into modular route files`
  - Files: `app/web/dashboard/routes/`
  - Pre-commit: `python -m pytest tests/test_fastapi_app.py -v`

---

- [x] 3.4 Fix Flaky Test Patterns

  **What to do**:
  - Replace 17 sleep() calls with proper async patterns
  - Use asyncio.Event, asyncio.Condition, or mock time
  - Focus on tests in `tests/` directory (not demos)

  **Files to fix**:
  1. `tests/test_context_service.py:152,190` - Replace asyncio.sleep with proper sync
  2. `tests/test_properties.py:146,166` - Replace tiny sleeps with await patterns
  3. `tests/test_integration.py:69,361` - Replace with event-based waiting
  4. `tests/test_search_service.py:185` - Replace with proper async handling
  5. `tests/test_api_mode.py:57,88,126,166` - Replace time.sleep with process readiness checks

  **Must NOT do**:
  - Do NOT break test behavior
  - Do NOT remove necessary waits for real async operations
  - Do NOT touch demo files (they're not in CI)

  **Parallelizable**: NO (after other Phase 3 tasks)

  **References**:
  - `tests/test_context_service.py` - Context service tests
  - `tests/test_integration.py` - Integration tests
  - asyncio.Event, asyncio.wait_for documentation

  **Acceptance Criteria**:
  - [ ] No time.sleep in main tests: `grep -r "time.sleep" tests/test_*.py | wc -l` = 0
  - [ ] Minimal asyncio.sleep: `grep -r "asyncio.sleep" tests/test_*.py | wc -l` <= 3
  - [ ] Tests still pass: `python -m pytest tests/ -v --tb=short -q`
  - [ ] Tests run faster: Measure test suite time before/after

  **Commit**: YES
  - Message: `test: replace sleep calls with proper async patterns to fix flaky tests`
  - Files: Test files as listed
  - Pre-commit: `python -m pytest tests/ -v --tb=short -q`

---

### Phase 4: Cleanup (Ongoing)

---

- [x] 4.1 Migrate Test Imports to app/ Architecture

  **What to do**:
  - Update test files to import from `app/` instead of `src/`
  - Focus on main test files that currently import from src
  - Verify tests work with new imports

  **Files to update**:
  - `tests/test_memory_service.py` - Change `from src.services.memory` to `from app.core.services.memory`
  - `tests/test_search_service.py` - Change `from src.services.search` to `from app.core.services.unified_search`
  - `tests/test_context_service.py` - Change `from src.services.context` to `from app.core.services.context`
  - `tests/test_mcp_tools.py` - Change `from src.mcp.tools` to `from app.mcp_common.tools`

  **Must NOT do**:
  - Do NOT break tests
  - Do NOT remove src/ directory (may still be needed for compatibility)

  **Parallelizable**: YES (independent cleanup)

  **References**:
  - `tests/test_memory_service.py` - Current src imports
  - `app/core/services/` - New module locations
  - `app/mcp_common/` - New MCP module location

  **Acceptance Criteria**:
  - [ ] No src imports in main tests: `grep -r "from src\." tests/test_*.py | wc -l` = 0
  - [ ] Tests pass: `python -m pytest tests/test_memory_service.py tests/test_search_service.py tests/test_context_service.py tests/test_mcp_tools.py -v`

  **Commit**: YES
  - Message: `refactor: migrate test imports from src/ to app/ architecture`
  - Files: Test files as listed
  - Pre-commit: `python -m pytest tests/ -v --tb=short -q`

---

- [x] 4.2 Clean Up Empty Function Bodies

  **What to do**:
  - Review 31 instances of `pass` placeholders
  - Add proper implementations or NotImplementedError where appropriate
  - Remove truly unnecessary empty bodies

  **Priority targets**:
  - `app/mcp_stdio_pure/server.py:424` - Exception handler pass
  - `app/core/services/alert.py:76` - stop_background_check
  - `app/core/services/metrics_collector.py:61` - stop method

  **Must NOT do**:
  - Do NOT modify abstract base class methods (pass is intentional)
  - Do NOT break exception handling patterns

  **Parallelizable**: YES (independent cleanup)

  **References**:
  - `app/core/storage/base.py` - Abstract methods (keep pass)
  - `app/core/services/pin.py:18,23,28,379` - Exception handlers (review)
  - `app/core/services/memory.py:22,27,32` - Exception handlers (review)

  **Acceptance Criteria**:
  - [ ] Questionable passes addressed: Review and document each remaining pass
  - [ ] No unnecessary empty bodies: Each `pass` has documented reason
  - [ ] Tests pass: `python -m pytest tests/ -v --tb=short -q`

  **Commit**: YES
  - Message: `refactor: clean up unnecessary empty function bodies`
  - Files: Various as identified
  - Pre-commit: `python -m pytest tests/ -v --tb=short -q`

---

- [x] 4.3 Update Documentation

  **What to do**:
  - Update AGENTS.md files to reflect new structure
  - Add deprecation notices to legacy search docs
  - Document new MCP dispatcher pattern
  - Update test coverage documentation

  **Must NOT do**:
  - Do NOT remove existing documentation
  - Do NOT document features that don't exist

  **Parallelizable**: YES (independent cleanup)

  **References**:
  - `AGENTS.md` - Root documentation
  - `app/core/AGENTS.md` - Core module documentation
  - `app/mcp_common/AGENTS.md` - MCP documentation
  - `docs/` - Additional documentation

  **Acceptance Criteria**:
  - [ ] Legacy search documented: `grep -l "legacy" app/core/services/legacy/` includes README or docs
  - [ ] Dispatcher documented: `grep "dispatcher" app/mcp_common/AGENTS.md` shows content
  - [ ] Test docs updated: Documentation mentions new test files

  **Commit**: YES
  - Message: `docs: update documentation for refactored architecture`
  - Files: Documentation files
  - Pre-commit: None (documentation only)

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 1.1 | `refactor: archive legacy search implementations` | app/core/services/legacy/ | pytest tests/ |
| 1.2 | `fix: replace bare except clauses` | 5 service files | pytest tests/ |
| 2.1 | `test: add MCP stdio server tests` | tests/test_mcp_stdio.py | pytest tests/test_mcp_stdio.py |
| 2.2 | `test: add Pure MCP server tests` | tests/test_mcp_stdio_pure.py | pytest tests/test_mcp_stdio_pure.py |
| 2.3 | `test: add Session/Pin service tests` | tests/test_session_service.py, tests/test_pin_service.py | pytest tests/test_*_service.py |
| 2.4 | `refactor: add missing type hints` | Multiple | mypy app/ |
| 3.1 | `refactor: extract MCP dispatcher` | app/mcp_common/, app/mcp_stdio_pure/, app/web/mcp/ | pytest tests/test_mcp*.py |
| 3.2 | `refactor: split database/base.py` | app/core/database/ | pytest tests/ |
| 3.3 | `refactor: split dashboard routes` | app/web/dashboard/routes/ | pytest tests/test_fastapi_app.py |
| 3.4 | `test: fix flaky test patterns` | tests/*.py | pytest tests/ (faster) |
| 4.1 | `refactor: migrate test imports` | tests/*.py | pytest tests/ |
| 4.2 | `refactor: clean up empty bodies` | Various | pytest tests/ |
| 4.3 | `docs: update documentation` | *.md files | None |

---

## Success Criteria

### Verification Commands
```bash
# All tests pass
python -m pytest tests/ -v --tb=short

# No bare excepts
grep -rn "except:" app/ | grep -v "except Exception" | grep -v "except.*Error" | wc -l
# Expected: 0

# Type hints complete
mypy app/ --ignore-missing-imports --no-error-summary

# MCP tests exist and pass
python -m pytest tests/test_mcp_stdio*.py -v
# Expected: 20+ tests pass

# Legacy files archived
ls app/core/services/legacy/
# Expected: 6 files (5 search + __init__.py)

# Large files split
wc -l app/core/database/*.py app/web/dashboard/routes/*.py | grep -v total
# Expected: All files < 350 lines
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent (no schema changes, no new features)
- [ ] All tests pass (existing + new)
- [ ] Zero bare except clauses
- [ ] Type hints on all 23 identified functions
- [ ] MCP servers have >80% test coverage
- [ ] Legacy search files archived
- [ ] Large files split appropriately
- [ ] No flaky tests (minimal sleep calls)
- [ ] Documentation updated

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Breaking MCP protocol | Low | High | TDD approach, test before refactor |
| Breaking existing tests | Medium | Medium | Run full test suite after each commit |
| Incomplete legacy search archive | Low | Low | Verify imports after move |
| Type hint errors | Medium | Low | Use mypy incrementally |
| Flaky test fix breaks timing | Medium | Medium | Keep fallback sleeps, reduce duration |

---

## Estimated Timeline

| Phase | Duration | Effort |
|-------|----------|--------|
| Phase 1 | 1-2 days | 4-8 hours |
| Phase 2 | 1-2 weeks | 20-40 hours |
| Phase 3 | 2-3 weeks | 30-50 hours |
| Phase 4 | Ongoing | 10-20 hours |
| **Total** | **4-6 weeks** | **64-118 hours** |

