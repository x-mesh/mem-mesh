# Design Document: MCP Direct SQLite & Architecture Refactoring

## Overview

이 설계 문서는 mem-mesh 시스템의 아키텍처를 개선하여 MCP 서버가 직접 SQLite에 접근할 수 있도록 하고, FastMCP 라이브러리를 사용한 새로운 MCP 구현을 제공하며, 디렉토리 구조를 재구성하는 방안을 설명합니다.

### 핵심 목표
1. MCP 서버가 FastAPI 없이 독립적으로 동작 가능
2. FastMCP 라이브러리를 사용한 간결한 MCP 구현
3. 명확한 디렉토리 구조로 모듈 분리
4. SQLite WAL 모드를 통한 동시 접근 안정성
5. Docker 및 Makefile을 통한 배포 자동화

## Architecture

### 현재 아키텍처

```
┌─────────────────┐     ┌─────────────────┐
│   AI Agent      │     │   Web Browser   │
└────────┬────────┘     └────────┬────────┘
         │ stdio                 │ HTTP
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│   MCP Server    │     │ FastAPI Server  │
│   (src/mcp/)    │     │   (src/main)    │
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     ▼
         ┌─────────────────────┐
         │   SQLite + WAL      │
         │   (data/memories.db)│
         └─────────────────────┘
```

### 새로운 아키텍처

```
┌─────────────────┐     ┌─────────────────┐
│   AI Agent      │     │   Web Browser   │
└────────┬────────┘     └────────┬────────┘
         │ stdio                 │ HTTP
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│  FastMCP Server │     │ FastAPI Dashboard│
│  (app/mcp/)     │     │ (app/dashboard/) │
└────────┬────────┘     └────────┬────────┘
         │                       │
         │  ┌─────────────────┐  │
         │  │  Storage Mode   │  │
         │  │  Abstraction    │  │
         │  └────────┬────────┘  │
         │           │           │
         ▼           ▼           ▼
┌─────────────────────────────────────────┐
│              app/core/                   │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐  │
│  │Database │ │Embeddings│ │ Services │  │
│  └────┬────┘ └──────────┘ └──────────┘  │
└───────┼─────────────────────────────────┘
        ▼
┌─────────────────────┐
│   SQLite + WAL      │
│   (data/memories.db)│
└─────────────────────┘
```

### 디렉토리 구조

```
mem-mesh/
├── app/                          # 새로운 애플리케이션 디렉토리
│   ├── __init__.py
│   ├── mcp/                      # FastMCP 기반 MCP 서버
│   │   ├── __init__.py
│   │   ├── __main__.py           # python -m app.mcp 진입점
│   │   ├── server.py             # FastMCP 서버 구현
│   │   └── tools.py              # MCP 도구 정의
│   ├── dashboard/                # FastAPI 대시보드
│   │   ├── __init__.py
│   │   ├── __main__.py           # python -m app.dashboard 진입점
│   │   ├── main.py               # FastAPI 앱
│   │   └── routes.py             # API 라우트
│   └── core/                     # 공통 모듈
│       ├── __init__.py
│       ├── config.py             # 설정 관리
│       ├── database/             # 데이터베이스 레이어
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── models.py
│       ├── embeddings/           # 임베딩 서비스
│       │   ├── __init__.py
│       │   └── service.py
│       ├── services/             # 비즈니스 로직
│       │   ├── __init__.py
│       │   ├── memory.py
│       │   ├── search.py
│       │   ├── context.py
│       │   └── stats.py
│       ├── schemas/              # Pydantic 스키마
│       │   ├── __init__.py
│       │   ├── requests.py
│       │   └── responses.py
│       └── storage/              # 스토리지 추상화
│           ├── __init__.py
│           ├── base.py           # 추상 인터페이스
│           ├── direct.py         # Direct SQLite 구현
│           └── api.py            # API 클라이언트 구현
├── src/                          # 기존 코드 (하위 호환성)
├── static/                       # 웹 UI 정적 파일
├── data/                         # 데이터베이스 파일
├── docker/                       # Docker 관련 파일
│   ├── Dockerfile.mcp
│   ├── Dockerfile.dashboard
│   └── docker-compose.yml
├── Makefile                      # 빌드 자동화
├── pyproject.toml
└── .env.example
```

## Components and Interfaces

### 1. Storage Abstraction Layer

스토리지 모드에 따라 다른 구현을 사용할 수 있도록 추상화 레이어를 제공합니다.

```python
# app/core/storage/base.py
from abc import ABC, abstractmethod
from typing import Optional, List
from ..schemas.requests import AddParams, SearchParams, UpdateParams
from ..schemas.responses import AddResponse, SearchResponse, ContextResponse

class StorageBackend(ABC):
    """스토리지 백엔드 추상 인터페이스"""
    
    @abstractmethod
    async def initialize(self) -> None:
        """스토리지 초기화"""
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """스토리지 종료"""
        pass
    
    @abstractmethod
    async def add_memory(self, params: AddParams) -> AddResponse:
        """메모리 추가"""
        pass
    
    @abstractmethod
    async def search_memories(self, params: SearchParams) -> SearchResponse:
        """메모리 검색"""
        pass
    
    @abstractmethod
    async def get_context(self, memory_id: str, depth: int, project_id: Optional[str]) -> ContextResponse:
        """컨텍스트 조회"""
        pass
    
    @abstractmethod
    async def update_memory(self, memory_id: str, params: UpdateParams) -> UpdateResponse:
        """메모리 업데이트"""
        pass
    
    @abstractmethod
    async def delete_memory(self, memory_id: str) -> DeleteResponse:
        """메모리 삭제"""
        pass
    
    @abstractmethod
    async def get_stats(self, project_id: Optional[str], start_date: Optional[str], end_date: Optional[str]) -> StatsResponse:
        """통계 조회"""
        pass
```

### 2. Direct Storage Implementation

```python
# app/core/storage/direct.py
from .base import StorageBackend
from ..database.base import Database
from ..embeddings.service import EmbeddingService
from ..services.memory import MemoryService
from ..services.search import SearchService
from ..services.context import ContextService
from ..services.stats import StatsService

class DirectStorageBackend(StorageBackend):
    """SQLite 직접 접근 스토리지 백엔드"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db: Optional[Database] = None
        self.embedding_service: Optional[EmbeddingService] = None
        self.memory_service: Optional[MemoryService] = None
        self.search_service: Optional[SearchService] = None
        self.context_service: Optional[ContextService] = None
        self.stats_service: Optional[StatsService] = None
    
    async def initialize(self) -> None:
        self.db = Database(self.db_path)
        await self.db.connect()
        
        self.embedding_service = EmbeddingService()
        self.memory_service = MemoryService(self.db, self.embedding_service)
        self.search_service = SearchService(self.db, self.embedding_service)
        self.context_service = ContextService(self.db, self.embedding_service)
        self.stats_service = StatsService(self.db)
    
    async def add_memory(self, params: AddParams) -> AddResponse:
        return await self.memory_service.create(
            content=params.content,
            project_id=params.project_id,
            category=params.category,
            source=params.source or "mcp",
            tags=params.tags
        )
    
    # ... 나머지 메서드 구현
```

### 3. API Storage Implementation

```python
# app/core/storage/api.py
import httpx
from .base import StorageBackend

class APIStorageBackend(StorageBackend):
    """FastAPI REST API를 통한 스토리지 백엔드"""
    
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client: Optional[httpx.AsyncClient] = None
    
    async def initialize(self) -> None:
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout
        )
    
    async def shutdown(self) -> None:
        if self.client:
            await self.client.aclose()
    
    async def add_memory(self, params: AddParams) -> AddResponse:
        response = await self.client.post(
            "/api/memories",
            json=params.model_dump(exclude_none=True)
        )
        response.raise_for_status()
        return AddResponse(**response.json())
    
    # ... 나머지 메서드 구현
```

### 4. FastMCP Server Implementation

```python
# app/mcp/server.py
from fastmcp import FastMCP
from typing import Optional, List
from ..core.config import Settings
from ..core.storage.base import StorageBackend
from ..core.storage.direct import DirectStorageBackend
from ..core.storage.api import APIStorageBackend

# FastMCP 서버 인스턴스 생성
mcp = FastMCP("mem-mesh")

# 전역 스토리지 백엔드
storage: Optional[StorageBackend] = None

async def initialize_storage(settings: Settings) -> None:
    """스토리지 백엔드 초기화"""
    global storage
    
    if settings.storage_mode == "direct":
        storage = DirectStorageBackend(settings.database_path)
    else:
        storage = APIStorageBackend(settings.api_base_url)
    
    await storage.initialize()

@mcp.tool()
async def add(
    content: str,
    project_id: Optional[str] = None,
    category: str = "task",
    source: str = "mcp",
    tags: Optional[List[str]] = None
) -> dict:
    """Add a new memory to the memory store
    
    Args:
        content: Memory content (10-10000 characters)
        project_id: Project identifier (optional)
        category: Memory category (task, bug, idea, decision, incident, code_snippet)
        source: Memory source
        tags: Memory tags
    """
    from ..core.schemas.requests import AddParams
    
    params = AddParams(
        content=content,
        project_id=project_id,
        category=category,
        source=source,
        tags=tags
    )
    result = await storage.add_memory(params)
    return result.model_dump()

@mcp.tool()
async def search(
    query: str,
    project_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 5,
    recency_weight: float = 0.0
) -> dict:
    """Search memories using hybrid search (vector + metadata)
    
    Args:
        query: Search query (min 3 characters)
        project_id: Project filter
        category: Category filter
        limit: Maximum results (1-20)
        recency_weight: Recency weight (0.0-1.0)
    """
    from ..core.schemas.requests import SearchParams
    
    params = SearchParams(
        query=query,
        project_id=project_id,
        category=category,
        limit=limit,
        recency_weight=recency_weight
    )
    result = await storage.search_memories(params)
    return result.model_dump()

@mcp.tool()
async def context(
    memory_id: str,
    depth: int = 2,
    project_id: Optional[str] = None
) -> dict:
    """Get context around a specific memory
    
    Args:
        memory_id: Memory ID to get context for
        depth: Search depth (1-5)
        project_id: Project filter
    """
    result = await storage.get_context(memory_id, depth, project_id)
    return result.model_dump()

@mcp.tool()
async def update(
    memory_id: str,
    content: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> dict:
    """Update an existing memory
    
    Args:
        memory_id: Memory ID to update
        content: New content
        category: New category
        tags: New tags
    """
    from ..core.schemas.requests import UpdateParams
    
    params = UpdateParams(content=content, category=category, tags=tags)
    result = await storage.update_memory(memory_id, params)
    return result.model_dump()

@mcp.tool()
async def delete(memory_id: str) -> dict:
    """Delete a memory from the store
    
    Args:
        memory_id: Memory ID to delete
    """
    result = await storage.delete_memory(memory_id)
    return result.model_dump()

@mcp.tool()
async def stats(
    project_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> dict:
    """Get statistics about stored memories
    
    Args:
        project_id: Project filter
        start_date: Start date filter (YYYY-MM-DD)
        end_date: End date filter (YYYY-MM-DD)
    """
    result = await storage.get_stats(project_id, start_date, end_date)
    return result.model_dump()
```

### 5. Enhanced Configuration

```python
# app/core/config.py
from typing import Literal, Optional
from pydantic import Field, validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """애플리케이션 설정"""
    
    # Storage mode
    storage_mode: Literal["direct", "api"] = Field(
        default="direct",
        description="Storage mode: 'direct' for SQLite, 'api' for FastAPI"
    )
    
    # API settings (for api mode)
    api_base_url: str = Field(
        default="http://localhost:8000",
        description="FastAPI server base URL"
    )
    
    # Database settings
    database_path: str = Field(
        default="./data/memories.db",
        description="Path to SQLite database file"
    )
    
    # SQLite WAL settings
    busy_timeout: int = Field(
        default=5000,
        ge=1000,
        description="SQLite busy timeout in milliseconds"
    )
    
    # Embedding settings
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence-transformers model name"
    )
    embedding_dim: int = Field(default=384)
    
    # Server settings
    server_host: str = Field(default="127.0.0.1")
    server_port: int = Field(default=8000, ge=1, le=65535)
    
    # Logging
    log_level: str = Field(default="INFO")
    
    @validator("storage_mode")
    def validate_storage_mode(cls, v: str) -> str:
        if v not in ("direct", "api"):
            raise ValueError("storage_mode must be 'direct' or 'api'")
        return v
    
    class Config:
        env_file = ".env"
        env_prefix = "MEM_MESH_"
        case_sensitive = False
```

## Data Models

기존 데이터 모델을 유지하며, 스토리지 추상화 레이어에서 사용합니다.

### Memory Model

```python
# app/core/database/models.py
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

@dataclass
class Memory:
    id: str
    content: str
    content_hash: str
    project_id: Optional[str]
    category: str
    source: str
    embedding: bytes
    tags: Optional[List[str]]
    created_at: datetime
    updated_at: datetime
```

### Database Schema

```sql
-- memories 테이블
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    project_id TEXT,
    category TEXT NOT NULL DEFAULT 'task',
    source TEXT NOT NULL,
    embedding BLOB NOT NULL,
    tags TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_memories_project_id ON memories(project_id);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_content_hash ON memories(content_hash);

-- sqlite-vec 벡터 테이블
CREATE VIRTUAL TABLE IF NOT EXISTS memory_embeddings USING vec0(
    memory_id TEXT PRIMARY KEY,
    embedding FLOAT[384]
);
```


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Settings Configuration Round-Trip

*For any* valid settings configuration (storage_mode, api_base_url, database_path, busy_timeout), loading settings from environment variables and then reading them back SHALL produce the same values.

**Validates: Requirements 1.1, 7.1, 7.2, 7.3, 7.4**

### Property 2: Invalid Storage Mode Rejection

*For any* storage_mode value that is not "direct" or "api", the Settings validation SHALL raise a ValueError with a descriptive message.

**Validates: Requirements 1.5**

### Property 3: Direct Mode Tool Operations

*For any* valid memory data (content, project_id, category, tags), when storage_mode is "direct":
- Adding a memory SHALL persist it to SQLite and return a valid memory ID
- Searching for the added memory SHALL return it in results
- Updating the memory SHALL modify the stored data
- Deleting the memory SHALL remove it from the database

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**

### Property 4: API Mode Error Handling

*For any* API request that fails (network error, timeout, server error), the APIStorageBackend SHALL:
- Return an appropriate error response
- Retry the request up to the configured retry limit
- Not crash or hang indefinitely

**Validates: Requirements 3.2**

### Property 5: Concurrent Database Access Stability

*For any* set of concurrent read and write operations on the same database:
- Read operations SHALL not be blocked by write operations (WAL mode)
- Write conflicts SHALL be handled with retry logic
- No data corruption SHALL occur

**Validates: Requirements 4.2, 4.3**

### Property 6: Storage Backend Interface Consistency

*For any* StorageBackend implementation (DirectStorageBackend or APIStorageBackend), calling the same method with the same parameters SHALL produce equivalent results (given the same underlying data state).

**Validates: Requirements 2.1-2.6, 3.1**

## Error Handling

### Storage Mode Errors

| Error Condition | Handling Strategy |
|----------------|-------------------|
| Invalid storage_mode value | Raise ValueError with valid options |
| Database connection failure (direct mode) | Raise ConnectionError with details |
| API server unreachable (api mode) | Retry with exponential backoff, then raise |

### Database Errors

| Error Condition | Handling Strategy |
|----------------|-------------------|
| SQLITE_BUSY | Retry with busy_timeout, then raise |
| SQLITE_LOCKED | Wait and retry up to 3 times |
| Constraint violation | Raise with descriptive message |
| Embedding generation failure | Retry up to 3 times, then raise |

### API Client Errors

| Error Condition | Handling Strategy |
|----------------|-------------------|
| Connection timeout | Retry up to 3 times with backoff |
| HTTP 4xx errors | Return error response immediately |
| HTTP 5xx errors | Retry up to 3 times with backoff |
| Invalid response format | Raise parsing error |

### Error Response Format

```python
class ErrorResponse(BaseModel):
    error: str  # Error code (e.g., "STORAGE_ERROR", "VALIDATION_ERROR")
    message: str  # Human-readable error message
    details: Optional[dict] = None  # Additional error context
```

## Testing Strategy

### Dual Testing Approach

이 프로젝트는 단위 테스트와 속성 기반 테스트를 모두 사용합니다:

- **단위 테스트**: 특정 예제, 엣지 케이스, 에러 조건 검증
- **속성 기반 테스트**: 모든 유효한 입력에 대해 보편적 속성 검증

### Property-Based Testing Configuration

- **라이브러리**: Hypothesis (Python)
- **최소 반복 횟수**: 100회 per property
- **태그 형식**: `Feature: mcp-direct-sqlite, Property {number}: {property_text}`

### Test Categories

#### 1. Unit Tests

```python
# tests/test_config.py
def test_default_storage_mode():
    """기본 storage_mode가 'direct'인지 확인"""
    settings = Settings()
    assert settings.storage_mode == "direct"

def test_default_api_base_url():
    """기본 api_base_url이 'http://localhost:8000'인지 확인"""
    settings = Settings()
    assert settings.api_base_url == "http://localhost:8000"

def test_wal_mode_enabled():
    """WAL 모드가 활성화되어 있는지 확인"""
    db = Database("./test.db")
    await db.connect()
    result = await db.execute("PRAGMA journal_mode")
    assert result.fetchone()[0] == "wal"

def test_fastmcp_tools_available():
    """FastMCP 서버에 6개 도구가 등록되어 있는지 확인"""
    from app.mcp.server import mcp
    tools = mcp.list_tools()
    assert len(tools) == 6
    tool_names = {t.name for t in tools}
    assert tool_names == {"add", "search", "context", "update", "delete", "stats"}
```

#### 2. Property-Based Tests

```python
# tests/test_properties.py
from hypothesis import given, strategies as st, settings as hyp_settings

# Property 1: Settings Configuration Round-Trip
@given(
    storage_mode=st.sampled_from(["direct", "api"]),
    api_base_url=st.text(min_size=1).filter(lambda x: x.startswith("http")),
    database_path=st.text(min_size=1),
    busy_timeout=st.integers(min_value=1000, max_value=60000)
)
@hyp_settings(max_examples=100)
def test_settings_round_trip(storage_mode, api_base_url, database_path, busy_timeout):
    """Feature: mcp-direct-sqlite, Property 1: Settings Configuration Round-Trip"""
    import os
    os.environ["MEM_MESH_STORAGE_MODE"] = storage_mode
    os.environ["MEM_MESH_API_BASE_URL"] = api_base_url
    os.environ["MEM_MESH_DATABASE_PATH"] = database_path
    os.environ["MEM_MESH_BUSY_TIMEOUT"] = str(busy_timeout)
    
    settings = Settings()
    
    assert settings.storage_mode == storage_mode
    assert settings.api_base_url == api_base_url
    assert settings.database_path == database_path
    assert settings.busy_timeout == busy_timeout

# Property 2: Invalid Storage Mode Rejection
@given(
    invalid_mode=st.text().filter(lambda x: x not in ("direct", "api"))
)
@hyp_settings(max_examples=100)
def test_invalid_storage_mode_rejected(invalid_mode):
    """Feature: mcp-direct-sqlite, Property 2: Invalid Storage Mode Rejection"""
    import os
    os.environ["MEM_MESH_STORAGE_MODE"] = invalid_mode
    
    with pytest.raises(ValueError) as exc_info:
        Settings()
    
    assert "storage_mode" in str(exc_info.value).lower()

# Property 3: Direct Mode Tool Operations
@given(
    content=st.text(min_size=10, max_size=1000),
    project_id=st.one_of(st.none(), st.text(min_size=1, max_size=50).filter(str.isalnum)),
    category=st.sampled_from(["task", "bug", "idea", "decision", "incident", "code_snippet"]),
    tags=st.lists(st.text(min_size=1, max_size=20), max_size=5)
)
@hyp_settings(max_examples=100)
async def test_direct_mode_crud_operations(content, project_id, category, tags):
    """Feature: mcp-direct-sqlite, Property 3: Direct Mode Tool Operations"""
    storage = DirectStorageBackend("./test.db")
    await storage.initialize()
    
    # Add
    add_result = await storage.add_memory(AddParams(
        content=content,
        project_id=project_id,
        category=category,
        tags=tags
    ))
    assert add_result.memory_id is not None
    
    # Search
    search_result = await storage.search_memories(SearchParams(query=content[:20]))
    assert any(m.id == add_result.memory_id for m in search_result.results)
    
    # Update
    new_content = content + " updated"
    update_result = await storage.update_memory(
        add_result.memory_id,
        UpdateParams(content=new_content)
    )
    assert update_result.success
    
    # Delete
    delete_result = await storage.delete_memory(add_result.memory_id)
    assert delete_result.success
    
    await storage.shutdown()

# Property 5: Concurrent Database Access Stability
@given(
    num_readers=st.integers(min_value=1, max_value=10),
    num_writers=st.integers(min_value=1, max_value=5)
)
@hyp_settings(max_examples=50)
async def test_concurrent_access_stability(num_readers, num_writers):
    """Feature: mcp-direct-sqlite, Property 5: Concurrent Database Access Stability"""
    import asyncio
    
    db = Database("./test_concurrent.db")
    await db.connect()
    
    async def reader():
        for _ in range(10):
            await db.fetchall("SELECT * FROM memories LIMIT 10")
            await asyncio.sleep(0.01)
    
    async def writer():
        for i in range(5):
            await db.execute(
                "INSERT INTO memories (id, content, ...) VALUES (?, ?, ...)",
                (f"test_{i}", f"content_{i}", ...)
            )
            await asyncio.sleep(0.02)
    
    tasks = [reader() for _ in range(num_readers)] + [writer() for _ in range(num_writers)]
    
    # 모든 작업이 에러 없이 완료되어야 함
    await asyncio.gather(*tasks)
    
    await db.close()
```

#### 3. Integration Tests

```python
# tests/test_integration.py
async def test_mcp_server_direct_mode():
    """MCP 서버가 direct 모드에서 올바르게 동작하는지 확인"""
    os.environ["MEM_MESH_STORAGE_MODE"] = "direct"
    
    from app.mcp.server import mcp, initialize_storage
    await initialize_storage(Settings())
    
    # 도구 호출 테스트
    result = await mcp.call_tool("add", {
        "content": "Test memory content for integration test",
        "category": "task"
    })
    assert "memory_id" in result

async def test_mcp_server_api_mode():
    """MCP 서버가 api 모드에서 올바르게 동작하는지 확인"""
    # FastAPI 서버가 실행 중이어야 함
    os.environ["MEM_MESH_STORAGE_MODE"] = "api"
    os.environ["MEM_MESH_API_BASE_URL"] = "http://localhost:8000"
    
    from app.mcp.server import mcp, initialize_storage
    await initialize_storage(Settings())
    
    result = await mcp.call_tool("stats", {})
    assert "total_memories" in result
```

### Test File Structure

```
tests/
├── __init__.py
├── conftest.py                    # pytest fixtures
├── test_config.py                 # 설정 관련 테스트
├── test_storage_direct.py         # Direct 스토리지 테스트
├── test_storage_api.py            # API 스토리지 테스트
├── test_properties.py             # 속성 기반 테스트
├── test_mcp_server.py             # FastMCP 서버 테스트
├── test_dashboard.py              # FastAPI 대시보드 테스트
└── test_integration.py            # 통합 테스트
```


## Docker Configuration

### Dockerfile.mcp

```dockerfile
# docker/Dockerfile.mcp
FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 설치
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# 애플리케이션 코드 복사
COPY app/ ./app/

# 환경변수 기본값
ENV MEM_MESH_STORAGE_MODE=direct
ENV MEM_MESH_DATABASE_PATH=/data/memories.db

# 데이터 볼륨
VOLUME ["/data"]

# MCP 서버 실행 (stdio transport)
CMD ["python", "-m", "app.mcp"]
```

### Dockerfile.dashboard

```dockerfile
# docker/Dockerfile.dashboard
FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 설치
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# 애플리케이션 코드 복사
COPY app/ ./app/
COPY static/ ./static/

# 환경변수 기본값
ENV MEM_MESH_DATABASE_PATH=/data/memories.db
ENV MEM_MESH_SERVER_HOST=0.0.0.0
ENV MEM_MESH_SERVER_PORT=8000

# 데이터 볼륨
VOLUME ["/data"]

# 포트 노출
EXPOSE 8000

# FastAPI 서버 실행
CMD ["python", "-m", "app.dashboard"]
```

### docker-compose.yml

```yaml
# docker/docker-compose.yml
version: '3.8'

services:
  dashboard:
    build:
      context: ..
      dockerfile: docker/Dockerfile.dashboard
    ports:
      - "8000:8000"
    volumes:
      - mem-mesh-data:/data
    environment:
      - MEM_MESH_DATABASE_PATH=/data/memories.db
      - MEM_MESH_SERVER_HOST=0.0.0.0
      - MEM_MESH_SERVER_PORT=8000
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  mcp:
    build:
      context: ..
      dockerfile: docker/Dockerfile.mcp
    volumes:
      - mem-mesh-data:/data
    environment:
      - MEM_MESH_STORAGE_MODE=direct
      - MEM_MESH_DATABASE_PATH=/data/memories.db
    depends_on:
      - dashboard
    stdin_open: true
    tty: true

volumes:
  mem-mesh-data:
    driver: local
```

## Makefile

```makefile
# Makefile
.PHONY: install run-api run-mcp test docker-build docker-up docker-down clean help

# 기본 변수
PYTHON := python
PIP := pip
DOCKER_COMPOSE := docker-compose -f docker/docker-compose.yml

# 도움말
help:
	@echo "mem-mesh Makefile"
	@echo ""
	@echo "사용 가능한 명령어:"
	@echo "  make install       - 의존성 설치"
	@echo "  make run-api       - FastAPI 대시보드 실행"
	@echo "  make run-mcp       - MCP 서버 실행"
	@echo "  make test          - 테스트 실행"
	@echo "  make docker-build  - Docker 이미지 빌드"
	@echo "  make docker-up     - Docker Compose 실행"
	@echo "  make docker-down   - Docker Compose 중지"
	@echo "  make clean         - 빌드 아티팩트 정리"

# 의존성 설치
install:
	$(PIP) install -e ".[dev]"

# FastAPI 대시보드 실행
run-api:
	$(PYTHON) -m app.dashboard

# MCP 서버 실행
run-mcp:
	$(PYTHON) -m app.mcp

# MCP 서버 실행 (API 모드)
run-mcp-api:
	MEM_MESH_STORAGE_MODE=api $(PYTHON) -m app.mcp

# 테스트 실행
test:
	pytest tests/ -v --cov=app --cov-report=term-missing

# 속성 기반 테스트만 실행
test-properties:
	pytest tests/test_properties.py -v --hypothesis-show-statistics

# Docker 이미지 빌드
docker-build:
	$(DOCKER_COMPOSE) build

# Docker Compose 실행
docker-up:
	$(DOCKER_COMPOSE) up -d

# Docker Compose 중지
docker-down:
	$(DOCKER_COMPOSE) down

# Docker 로그 확인
docker-logs:
	$(DOCKER_COMPOSE) logs -f

# 빌드 아티팩트 정리
clean:
	rm -rf __pycache__ .pytest_cache .coverage htmlcov
	rm -rf app/__pycache__ app/**/__pycache__
	rm -rf .eggs *.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# 데이터베이스 초기화 (주의: 모든 데이터 삭제)
reset-db:
	rm -f data/memories.db data/memories.db-wal data/memories.db-shm
```

## Entry Points

### app/mcp/__main__.py

```python
# app/mcp/__main__.py
"""MCP 서버 진입점"""
import asyncio
import logging
import sys

from ..core.config import Settings
from .server import mcp, initialize_storage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr  # MCP는 stdout을 사용하므로 로그는 stderr로
)

logger = logging.getLogger(__name__)

async def main():
    """MCP 서버 메인 함수"""
    settings = Settings()
    
    logger.info(f"Starting MCP server in {settings.storage_mode} mode")
    
    # 스토리지 초기화
    await initialize_storage(settings)
    
    # FastMCP 서버 실행
    await mcp.run_stdio()

if __name__ == "__main__":
    asyncio.run(main())
```

### app/dashboard/__main__.py

```python
# app/dashboard/__main__.py
"""FastAPI 대시보드 진입점"""
import uvicorn
from ..core.config import Settings

def main():
    """대시보드 서버 메인 함수"""
    settings = Settings()
    
    uvicorn.run(
        "app.dashboard.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=False,
        log_level=settings.log_level.lower()
    )

if __name__ == "__main__":
    main()
```

## Migration Guide

기존 `src/` 구조에서 새로운 `app/` 구조로의 마이그레이션:

1. **코드 복사**: `src/` 내용을 `app/core/`로 복사
2. **MCP 분리**: `src/mcp/`를 FastMCP 기반 `app/mcp/`로 재구현
3. **Dashboard 분리**: `src/main.py`를 `app/dashboard/`로 이동
4. **Import 경로 수정**: 모든 import를 `app.` 접두사로 변경
5. **pyproject.toml 업데이트**: 새로운 진입점 추가

### pyproject.toml 변경사항

```toml
[project.scripts]
mem-mesh-mcp = "app.mcp.__main__:main"
mem-mesh-dashboard = "app.dashboard.__main__:main"
# 기존 호환성 유지
mem-mesh = "src.main:main"
```
