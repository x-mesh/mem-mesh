# Web Dashboard & API

> Golden Rules, 세션 관리, 보안 정책, Anti-Patterns 등 프로젝트 공통 표준은 root [AGENTS.md](../../../AGENTS.md) 참조.

## Module Context

FastAPI 기반 웹 대시보드와 REST API. 메모리 관리를 위한 웹 인터페이스와 HTTP 엔드포인트 제공.

**Components:**
- Dashboard routes - Memory CRUD, search, statistics endpoints
- SSE MCP - Server-Sent Events transport for MCP protocol
- Static files - Web UI assets

## Tech Stack & Constraints

**Framework:**
- FastAPI for REST API and routing
- Uvicorn as ASGI server
- SSE (Server-Sent Events) for real-time updates

**Route Organization** (v2.1+):
Modular route structure for better maintainability:
- `route_modules/__init__.py` - Router aggregation (19 lines)
- `route_modules/memories.py` - Memory CRUD endpoints (188 lines)
  - POST /api/memories - Create memory
  - GET /api/memories/{id} - Get memory
  - PUT /api/memories/{id} - Update memory
  - DELETE /api/memories/{id} - Delete memory
- `route_modules/relay.py` - Relay endpoints
  - GET /api/relay/v1/admin/overview - dashboard relay queue/digest overview
  - GET /api/relay/v1/admin/settings - relay setup and identity registry state
  - PUT /api/relay/v1/admin/settings - update relay share defaults
  - POST /api/relay/v1/admin/hub/check - check configured team hub reachability
  - POST /api/relay/v1/admin/identities - register or generate hub identity token
  - PUT /api/relay/v1/admin/identities/{token_hash_prefix} - update hub identity metadata/scopes/revocation
  - POST /api/relay/v1/admin/materialize - backfill received relay rows into ordinary memories
  - GET /api/relay/v1/health - relay hub health probe for personal nodes
  - POST /api/relay/v1/ingest - S2S relay ingest
  - POST /api/relay/v1/search - team relay view search
  - GET /api/relay/v1/projects/{team_project_id}/digest - latest relay digest
  - POST /api/relay/v1/outbox/share/{memory_id} - enqueue local memory for relay
  - POST /api/relay/v1/outbox/share-project/{project_id} - enqueue shareable local project memories for relay
- `route_modules/search.py` - Search endpoints (63 lines)
  - GET /api/memories/search - Search memories
  - POST /api/memories/search - Advanced search
- `route_modules/stats.py` - Statistics endpoints (65 lines)
  - GET /api/memories/stats - Overall statistics
  - GET /api/memories/stats/projects - Project statistics

## Implementation Patterns

**Router Composition:**
```python
from fastapi import APIRouter
from .route_modules import router as api_router

app = FastAPI()
app.include_router(api_router)
```

**Dependency Injection:**
```python
from fastapi import Depends
from ...core.services.memory import MemoryService

async def get_memory_service() -> MemoryService:
    # Get service from app state
    return app.state.memory_service

@router.post("/memories")
async def create_memory(
    params: AddParams,
    service: MemoryService = Depends(get_memory_service)
):
    return await service.add(**params.model_dump())
```

## Testing Strategy

**API Tests:**
```bash
python -m pytest tests/test_fastapi_app.py -v
```

**SSE MCP Tests:**
```bash
python -m pytest tests/test_sse_mcp.py -v
```

## Local Golden Rules

**Do's:**
- Use FastAPI dependency injection for services
- Return Pydantic models from endpoints
- Use proper HTTP status codes
- Add OpenAPI documentation to all endpoints

**Don'ts:**
- Do NOT access database directly from routes
- Do NOT bypass service layer
- Do NOT return raw database objects
- Do NOT add authentication without design review

**API Design:**
- RESTful endpoint naming
- Consistent error response format
- Proper HTTP method usage (GET, POST, PUT, DELETE)
