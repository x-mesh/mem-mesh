# MCP API Design Analysis Report

## 1. API Consistency Issues

### 1.1 Inconsistent Response Format Parameters (CONSISTENCY ISSUE)
**Files:** schemas.py, dispatcher.py, tools.py

**Issue:** Similar tools have inconsistent response format control:

- `search()` (schemas.py:109-114): 4 format options (minimal/compact/standard/full)
- `context()` (schemas.py:174-178): 3 format options (compact/standard/full) - MISSING "minimal"
- `batch_operations()`: NO response_format parameter at all

**Impact:** Users cannot control response verbosity in batch operations, unlike individual calls.

**Line References:**
- schemas.py:109-114 (search format options)
- schemas.py:174-178 (context format options, missing "minimal")
- schemas.py:418-495 (batch_operations schema lacks format control)

**Recommendation:** Add `response_format` parameter to batch_operations schema with same options as search.

---

### 1.2 Inconsistent Error Response Structures (CONSISTENCY ISSUE)
**Files:** dispatcher.py, transport.py, batch_tools.py

**Issue:** Different error response formats across tools:

1. **Standard tool error** (transport.py:35-45):
   ```json
   {
     "content": [{"type": "text", "text": "{\"success\": false, \"error\": \"message\"}"}],
     "isError": true
   }
   ```

2. **Batch operation failure** (batch_tools.py:108-112):
   ```json
   {
     "status": "failed",
     "error": "Batch embedding generation failed",
     "message": "Batch embedding generation failed"
   }
   ```

3. **Individual op error in batch** (batch_tools.py:296-303):
   ```json
   {"index": 0, "type": "add", "success": false, "error": "..."}
   ```

**Impact:** LLMs and clients see inconsistent error structures, complicating error handling logic.

**Line References:**
- transport.py:35-45 (standard error format)
- batch_tools.py:108-112 (batch failure format)
- batch_tools.py:296-303 (operation-level error format)

**Recommendation:** Standardize all errors to use `isError: true` with optional `error_code` field for machine-readable classification.

---

### 1.3 Inconsistent Tool Description Accuracy (CONSISTENCY ISSUE)
**File:** descriptions.py

**Issue:** Tool descriptions don't match actual capabilities:

- `"add"` (line 30-33): Lists "decision, bug, idea, code_snippet, incident" but MISSING `git-history` (it's in schemas.py:12-21)
- `"search"` (line 24-28): Says "hybrid search (vector + FTS5)" but doesn't mention semantic, fuzzy, or exact modes available in schemas.py:24
- `"batch_operations"` (line 54-56): Says "Execute multiple add/search operations" but also supports `pin_add` (schemas.py:436)

**Impact:** LLMs receive incomplete tool descriptions and miss available capabilities.

**Line References:**
- descriptions.py:30-33 (add missing categories)
- descriptions.py:24-28 (search mode clarity)
- descriptions.py:54-56 (batch_operations pin_add support)

**Recommendation:** Update descriptions to match full capability list in schemas.

---

## 2. Error Handling Issues

### 2.1 Overly Broad Exception Catching (DESIGN ISSUE)
**File:** dispatcher.py:77-82

**Code:**
```python
except ValidationError as ve:
    logger.error(f"Validation error in tool {tool_name}: {ve}")
    return format_tool_error(f"Validation error: {str(ve)}")
except Exception as e:  # <- TOO BROAD
    logger.error(f"Error in tool {tool_name}", error=str(e))
    return format_tool_error(str(e))
```

**Problem:**
- Catches ALL exceptions including SystemExit, KeyboardInterrupt, etc.
- No distinction between client errors (bad input) and server errors (database failure)
- Lost context about error type for proper HTTP status code mapping
- Same handling for expected vs unexpected errors

**Missing:** Specific exception types like:
- `ValueError` (validation failure)
- `NotFoundError` (resource not found)
- `PermissionError` (authorization failure)
- `DatabaseError` (infrastructure issue)

**Line References:**
- dispatcher.py:77-82
- tools.py:77-123 (similar broad exception handling in add())
- batch_tools.py:93-104 (catches Exception without classification)

**Recommendation:** Create typed exception hierarchy (`MemoryException`, `ValidationException`, etc.) and catch specifically.

---

### 2.2 Inconsistent Batch Operation Status Reporting (DESIGN ISSUE)
**File:** batch_tools.py:400-411

**Code:**
```python
return {
    "status": "success",  # <- ALWAYS "success" even if some ops failed
    "total_operations": len(operations),
    "results": results,  # contains failures in results[x]["success"]=False
    ...
}
```

**Problem:**
- Top-level `"status": "success"` is misleading when individual operations fail
- Clients expecting all-or-nothing semantics get partial failures silently
- No summary of failed operations count

**Missing:**
- Overall status like "partial_success" when some ops fail
- `failed_count` field for quick failure assessment
- All-or-nothing rollback option for atomic batch operations

**Line References:**
- batch_tools.py:400-411
- batch_tools.py:275-303 (operation results with mixed success)

**Recommendation:** Return `"status": "partial_success"` when any operation fails, add `failed_count` field.

---

## 3. Validation Issues

### 3.1 Missing Pre-dispatch Argument Validation (DESIGN ISSUE)
**File:** dispatcher.py (all _dispatch_* methods)

**Issue:** Each dispatcher method manually validates required arguments:

```python
async def _dispatch_add(self, args: Dict[str, Any]) -> Dict[str, Any]:
    if "content" not in args:
        return format_tool_error("Missing required argument: content")
```

**Problem:**
- Duplicate validation: manual checks + Pydantic schemas in tools.py both validate
- Pydantic schema validators (AddParams) never get invoked
- Schema enums (VALID_CATEGORIES) ignored in dispatcher

**Missing:**
- Centralized argument validation before tool dispatch
- Leverage existing Pydantic validators

**Line References:**
- dispatcher.py:84-95 (_dispatch_add manual validation)
- dispatcher.py:97-113 (_dispatch_search manual validation)
- dispatcher.py:154-164 (_dispatch_pin_add manual validation)
- All other _dispatch_* methods follow same pattern

**Recommendation:** Create `validate_arguments(tool_name, args)` function that runs Pydantic validators before dispatch.

---

### 3.2 Incomplete Batch Operation Validation (DESIGN ISSUE)
**Files:** schemas.py:418-495, batch_tools.py:226-250

**Issue:** Batch operation schema doesn't enforce per-operation constraints:

```json
"items": {
  "type": "object",
  "properties": {...},
  "required": ["type"],  // <- ONLY type required!
}
```

**Problem:**
- `add` operation requires `content` but schema doesn't enforce it
- `search` operation requires `query` but schema doesn't enforce it
- `pin_add` requires `project_id` but schema doesn't enforce it
- Dispatcher applies shared defaults from first operation to all: `category=add_operations[0].get("category")` (batch_tools.py:265)

**Missing:**
- Conditional schema validation (oneOf with different required sets per operation type)
- Per-operation default isolation

**Example Bug:**
```python
# Line 262-268: applies first op's project_id to ALL adds
batch_add_result = await self.batch_add_memories(
    contents=contents,
    project_id=add_operations[0].get("project_id"),  # <- WRONG!
    category=add_operations[0].get("category", "task"),
    ...
)
```

**Line References:**
- schemas.py:430-493 (batch items schema)
- batch_tools.py:262-268 (applies first op's defaults to all)

**Recommendation:** Use JSON Schema `oneOf` with different required fields per operation type, validate each operation independently.

---

### 3.3 Date Parameter Validation Incomplete (DESIGN ISSUE)
**Files:** schemas.py:128-137, requests.py:98-130

**Issue:** Date parameters lack semantic validation:

**Current:**
```python
"date_from": {
    "type": "string",
    "description": "Start date (YYYY-MM-DD)",
    "pattern": r"^\d{4}-\d{2}-\d{2}$",  # Only format validation
}
```

**Problem:**
- Regex only validates format, not date validity: "2026-02-30" passes regex but is invalid
- No logical validation: `date_from` can be after `date_to`
- No bounds checking: dates before 1970 or after year 3000 technically allowed

**Missing:**
- Pydantic `@field_validator` for date parsing and bounds
- Cross-field validation (date_from ≤ date_to)

**Line References:**
- schemas.py:128-137 (date schema patterns)
- requests.py:98-130 (SearchParams date handling)

**Recommendation:** Use `datetime.date` fields instead of strings for automatic validation.

---

## 4. Missing Features

### 4.1 No Rate Limiting or Abuse Prevention (MISSING FEATURE)
**Issue:** No rate limiting or quota enforcement across any tools

**Missing:**
- Per-project daily memory addition limits
- Per-user request rate limits (e.g., 100 requests/minute)
- Batch operation size enforcement (schema has maxItems:50 but no server-side check)
- Large batch operation warnings (> 10 ops)

**Impact:** Malicious users could:
- Spam millions of memories to the database
- Perform millions of searches to exhaust resources
- Send 50-operation batches repeatedly without throttling

**Current State:**
- schemas.py:488 defines `maxItems: 50` but no middleware enforces it
- No rate limiting middleware in dispatcher.py or tools.py
- No quota tracking per project_id

**Recommendation:** Implement rate limiting middleware + quota tracking per project.

---

### 4.2 No API Versioning (MISSING FEATURE)
**Issue:** Tools have no version support for backward compatibility

**Missing:**
- Version parameter in tool schemas (e.g., `api_version: "v1"`)
- Version-specific response formats
- Deprecation warnings for old APIs

**Impact:** Breaking changes require ALL clients to update simultaneously. Cannot phase out features.

**Recommendation:** Add optional `api_version` parameter (default "v1") for future compatibility.

---

### 4.3 No Cursor-based Pagination (MISSING FEATURE)
**Files:** schemas.py:95-101, responses.py:54-85

**Issue:** Search results limited to 20 items max, no pagination support

**Current:**
```python
"limit": {
    "type": "integer",
    "default": 5,
    "minimum": 1,
    "maximum": 20,  # <- Can't get more than 20 results
}
```

**Problem:**
- Large projects with thousands of memories can't paginate results
- No way to get second page of results
- Total count provided but no cursor/offset for retrieval

**Missing:**
- `cursor` parameter for cursor-based pagination
- Or `offset` parameter for offset-based pagination
- Response should include `next_cursor` or `has_more` flag

**Line References:**
- schemas.py:95-101 (limit constraints)
- responses.py:54-85 (SearchResponse structure)

**Recommendation:** Add cursor-based pagination with 1000+ result retrieval capability.

---

## 5. Usability Issues

### 5.1 Batch Operations Misleading Overall Status (USABILITY ISSUE)
**File:** batch_tools.py:400-411

**Code:**
```python
return {
    "status": "success",  # <- Misleading when results contain failures
    "total_operations": 4,
    "results": [
        {"index": 0, "success": true, ...},
        {"index": 1, "success": false, "error": "..."},  # <- Some fail
        ...
    ],
}
```

**Problem:** Top-level `"status"` doesn't reflect actual outcome

**LLM Confusion:**
- Tool says "status: success"
- But reading results reveals some failed
- LLM can't determine if operation succeeded overall

**Missing:**
- `failed_count` at top level
- Status should be "partial_success" not "success" when failures occur

**Line References:**
- batch_tools.py:400-411

**Recommendation:** Return `"status": "partial_success"` when any operation fails, add `successful_count` and `failed_count` fields.

---

### 5.2 Batch Add Operations Apply Wrong Defaults (USABILITY ISSUE)
**File:** batch_tools.py:262-268

**Code:**
```python
batch_add_result = await self.batch_add_memories(
    contents=contents,
    project_id=add_operations[0].get("project_id"),  # <- Uses FIRST op's project
    category=add_operations[0].get("category", "task"),  # <- Applies to ALL ops
    source=add_operations[0].get("source", "mcp_batch"),  # <- Same source for all
    tags=add_operations[0].get("tags"),  # <- Same tags for all
)
```

**Problem:**
- Applies first operation's defaults to ALL operations
- If operations have different project_id, category, or tags, they get silently overridden
- No error or warning about overridden fields

**Example Bug:**
```python
# User sends:
operations = [
    {"type": "add", "content": "...", "project_id": "proj-a", "category": "bug"},
    {"type": "add", "content": "...", "project_id": "proj-b", "category": "task"},
]

# But both get:
# project_id="proj-a", category="bug"  <- Second op is overridden!
```

**Line References:**
- batch_tools.py:262-268

**Recommendation:** Validate each add operation independently, require explicit project_id/category per op or make them truly shared.

---

### 5.3 Inconsistent Search Mode Documentation (USABILITY ISSUE)
**Files:** schemas.py:24, descriptions.py:24-28

**Issue:** Search schema defines 4 modes but descriptions don't list them

**Schema lists** (schemas.py:24):
```python
VALID_SEARCH_MODES = ["hybrid", "exact", "semantic", "fuzzy"]
```

**But description** (descriptions.py:24-28):
```
"Search memories using hybrid search (vector + FTS5).
Use query="" for recent memories sorted by date..."
```

**Problem:** Doesn't mention that exact, semantic, or fuzzy modes exist

**Impact:** LLMs won't know they can use fuzzy search for typo tolerance or semantic for concept search

**Line References:**
- schemas.py:24 (defines 4 modes)
- descriptions.py:24-28 (only mentions hybrid)
- Note: search_mode parameter appears in SearchParams (requests.py:94-96) but NOT in tool schema (schemas.py:74-147)

**Recommendation:** Update description to list all 4 search modes, add search_mode to tool schema.

---

## 6. Response Structure Issues

### 6.1 Double JSON Encoding in Responses (DESIGN ISSUE)
**File:** transport.py:10-32

**Code:**
```python
def format_tool_response(
    result: Dict[str, Any], include_meta: bool = None
) -> Dict[str, Any]:
    if include_meta is None:
        include_meta = get_settings().enable_token_metadata

    if include_meta:
        result = add_token_metadata(result)

    return {
        "content": [{"type": "text", "text": json.dumps(result)}],  # <- Double encoding
        "isError": False,
    }
```

**Problem:**
- Result is dict, then json.dumps() makes it string, then it's wrapped in text field
- If result has error info, it's buried in double-encoded JSON string
- Clients must parse nested JSON to access actual data

**Better Approach:**
- Put errors/metadata at top level if needed
- Use structured content type instead of text

**Line References:**
- transport.py:29-32

**Impact:** Adds parsing complexity for clients, harder for LLMs to extract structured error information

---

## Summary by Issue Category

### Critical Issues (Fix First)
1. **Inconsistent error response formats** - confuses clients
2. **Overly broad exception catching** - can hide real issues
3. **Batch operation status misleading** - clients can't determine success
4. **Batch operation default application** - silently overrides user intent
5. **Missing pre-dispatch validation** - duplicate validation logic

### High Priority (Should Fix)
6. Inconsistent response format parameters across tools
7. Date parameter validation incomplete
8. Inconsistent tool descriptions (LLM confusion)
9. Batch operation per-op validation incomplete

### Medium Priority (Nice to Have)
10. No rate limiting / abuse prevention
11. No cursor-based pagination
12. Double JSON encoding complexity
13. Batch operation status accuracy (partial_success)

### Low Priority (Future)
14. API versioning
15. Search mode parameter documentation

## Specific File Locations (Reference)

| Issue | File | Lines | Type |
|-------|------|-------|------|
| Response format inconsistency | schemas.py | 109-114, 174-178, 418-495 | Consistency |
| Error response formats | dispatcher.py, transport.py, batch_tools.py | 77-82, 35-45, 108-112 | Consistency |
| Tool descriptions inaccurate | descriptions.py | 30-33, 24-28, 54-56 | Consistency |
| Broad exception catching | dispatcher.py | 77-82 | Design |
| Batch status misleading | batch_tools.py | 400-411 | Design |
| Duplicate validation | dispatcher.py | 84-95, 97-113, 154-164 | Design |
| Incomplete batch validation | schemas.py, batch_tools.py | 430-493, 262-268 | Design |
| Date validation | schemas.py, requests.py | 128-137, 98-130 | Design |
| Rate limiting missing | dispatcher.py, tools.py | All | Missing |
| Pagination missing | schemas.py, responses.py | 95-101, 54-85 | Missing |
| Double JSON encoding | transport.py | 29-32 | Design |
| Batch add defaults | batch_tools.py | 262-268 | Usability |
| Search modes undocumented | descriptions.py, schemas.py | 24-28, 24 | Usability |

---

## Recommendations Summary

### Immediate Actions
1. Standardize error response format across all tools (use isError field consistently)
2. Add specific exception types instead of bare `Exception` catching
3. Fix batch operations status to return "partial_success" when any op fails
4. Validate batch operation parameters independently instead of using first-op defaults

### Short-term Refactoring
5. Consolidate validation logic: move dispatcher manual checks to Pydantic validators
6. Add response_format parameter to batch_operations schema
7. Update tool descriptions to match actual capabilities
8. Implement date validation with datetime objects

### Medium-term Enhancements
9. Add rate limiting middleware per project_id
10. Implement cursor-based pagination for large result sets
11. Create typed exception hierarchy for better error handling
12. Add search_mode parameter to tool schemas

### Design Improvements
13. Consider removing double JSON encoding, use structured response format
14. Add "failed_count" and "successful_count" to batch operation responses
15. Implement all-or-nothing batch operation option with rollback
16. Add API versioning support for backward compatibility
