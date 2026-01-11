# Design Document: mem-mesh

## Overview

mem-mesh는 AI 개발 도구들 간의 작업 맥락을 중앙화하는 메모리 시스템입니다. FastAPI 기반 서버가 MCP 프로토콜을 통해 클라이언트(Cursor, Kiro, Claude CLI)와 통신하며, SQLite + sqlite-vec를 사용하여 메타데이터와 벡터를 단일 파일에 저장합니다.

### Key Design Decisions

1. **단일 파일 저장소**: SQLite + sqlite-vec로 메타데이터와 벡터를 하나의 DB 파일에 저장하여 배포/백업 단순화
2. **로컬 임베딩**: sentence-transformers MiniLM-L6-v2 (384dim)로 외부 API 의존성 제거
3. **하이브리드 검색**: SQL 필터링 + 벡터 유사도 + 최신성 가중치 조합
4. **MCP 프로토콜**: stdio 기반 통신으로 다양한 AI 도구와 호환

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Layer                            │
├──────────┬──────────┬──────────┬────────────────────────────┤
│  Cursor  │   Kiro   │CLI/uv    │ Claude Desktop             │
└────┬─────┴────┬─────┴────┬─────┴────────────────────────────┘
     │          │          │
     └──────────┼──────────┘
                │ (MCP Protocol over stdio)
     ┌──────────▼──────────────────────────────────────────────┐
     │   mem-mesh Server (FastAPI + MCP)                       │
     ├─────────────────────────────────────────────────────────┤
     │  ┌─────────────────────────────────────────────────────┐│
     │  │  MCP Handler Layer                                  ││
     │  │  - Tool Registration (add, search, context, etc.)   ││
     │  │  - Input Validation                                 ││
     │  │  - Response Formatting                              ││
     │  └─────────────────────────────────────────────────────┘│
     │                       ↓                                 │
     │  ┌─────────────────────────────────────────────────────┐│
     │  │  Service Layer                                      ││
     │  │  ├─ MemoryService (CRUD operations)                 ││
     │  │  ├─ SearchService (Hybrid search)                   ││
     │  │  ├─ ContextService (Related memory retrieval)       ││
     │  │  └─ EmbeddingService (Text vectorization)           ││
     │  └─────────────────────────────────────────────────────┘│
     │                       ↓                                 │
     │  ┌─────────────────────────────────────────────────────┐│
     │  │  Data Access Layer                                  ││
     │  │  ├─ SQLite (metadata storage)                       ││
     │  │  └─ sqlite-vec (vector index)                       ││
     │  └─────────────────────────────────────────────────────┘│
     └─────────────────────────────────────────────────────────┘
                       ↓
     ┌─────────────────────────────────────────────────────────┐
     │  mem_mesh.db (SQLite + sqlite-vec)                      │
     │  - memories table (metadata + embedding blob)           │
     │  - memories_vec virtual table (vector index)            │
     └─────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### 1. MCP Handler (`src/mcp/`)

MCP 프로토콜 요청을 처리하고 적절한 서비스로 라우팅합니다.

```python
class MCPServer:
    """MCP 서버 메인 클래스"""
    
    def __init__(self, memory_service: MemoryService, 
                 search_service: SearchService,
                 context_service: ContextService):
        self.memory_service = memory_service
        self.search_service = search_service
        self.context_service = context_service
    
    async def handle_add(self, params: AddParams) -> AddResponse:
        """mem-mesh.add 도구 핸들러"""
        pass
    
    async def handle_search(self, params: SearchParams) -> SearchResponse:
        """mem-mesh.search 도구 핸들러"""
        pass
    
    async def handle_context(self, params: ContextParams) -> ContextResponse:
        """mem-mesh.context 도구 핸들러"""
        pass
    
    async def handle_delete(self, params: DeleteParams) -> DeleteResponse:
        """mem-mesh.delete 도구 핸들러"""
        pass
    
    async def handle_update(self, params: UpdateParams) -> UpdateResponse:
        """mem-mesh.update 도구 핸들러"""
        pass
```

### 2. Memory Service (`src/services/memory.py`)

메모리 CRUD 작업을 담당합니다.

```python
class MemoryService:
    """메모리 저장/조회/삭제/업데이트 서비스"""
    
    def __init__(self, db: Database, embedding_service: EmbeddingService):
        self.db = db
        self.embedding_service = embedding_service
    
    async def create(self, content: str, project_id: str | None,
                     category: str, source: str, tags: list[str] | None) -> Memory:
        """새 메모리 생성 (중복 감지 포함)"""
        # 1. content_hash 계산
        # 2. 중복 체크
        # 3. 임베딩 생성
        # 4. DB 저장
        pass
    
    async def get(self, memory_id: str) -> Memory | None:
        """ID로 메모리 조회"""
        pass
    
    async def update(self, memory_id: str, content: str | None,
                     category: str | None, tags: list[str] | None) -> Memory:
        """메모리 업데이트 (content 변경 시 재임베딩)"""
        pass
    
    async def delete(self, memory_id: str) -> bool:
        """메모리 삭제"""
        pass
```

### 3. Search Service (`src/services/search.py`)

하이브리드 검색을 수행합니다.

```python
class SearchService:
    """하이브리드 검색 서비스"""
    
    def __init__(self, db: Database, embedding_service: EmbeddingService):
        self.db = db
        self.embedding_service = embedding_service
    
    async def search(self, query: str, project_id: str | None,
                     category: str | None, limit: int,
                     recency_weight: float) -> list[SearchResult]:
        """
        하이브리드 검색 수행
        1. query 임베딩 생성
        2. SQL 필터 적용 (project_id, category)
        3. 벡터 유사도 계산 (cosine similarity)
        4. 최신성 가중치 적용: score = (1-α)*sim + α*recency
        5. 정렬 및 limit 적용
        """
        pass
    
    def _calculate_recency_score(self, created_at: datetime, 
                                  oldest: datetime, newest: datetime) -> float:
        """최신성 점수 계산 (0.0 ~ 1.0)"""
        pass
```

### 4. Context Service (`src/services/context.py`)

특정 메모리의 맥락을 조회합니다.

```python
class ContextService:
    """맥락 조회 서비스"""
    
    def __init__(self, db: Database, search_service: SearchService):
        self.db = db
        self.search_service = search_service
    
    async def get_context(self, memory_id: str, project_id: str | None,
                          depth: int) -> ContextResult:
        """
        메모리 맥락 조회
        1. primary memory 로드
        2. 유사 메모리 검색
        3. 시간순 정렬 및 관계 분류 (before/after/similar)
        4. depth만큼 확장 검색
        5. 타임라인 생성
        """
        pass
    
    def _classify_relationship(self, primary_time: datetime,
                                related_time: datetime) -> str:
        """관계 분류: before, after, similar"""
        pass
```

### 5. Stats Service (`src/services/stats.py`)

메모리 통계 정보를 제공합니다.

```python
class StatsService:
    """메모리 통계 서비스"""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def get_overall_stats(self, project_id: str | None = None,
                               start_date: str | None = None,
                               end_date: str | None = None) -> StatsResult:
        """
        전체 통계 조회
        1. 총 메모리 수
        2. 프로젝트별 분포
        3. 카테고리별 분포
        4. 소스별 분포
        5. 날짜 범위 정보
        """
        pass
    
    async def get_project_stats(self, project_id: str | None = None) -> dict[str, int]:
        """프로젝트별 메모리 수 조회"""
        pass
    
    async def get_category_stats(self, project_id: str | None = None) -> dict[str, int]:
        """카테고리별 메모리 수 조회"""
        pass
    
    async def get_source_stats(self, project_id: str | None = None) -> dict[str, int]:
        """소스별 메모리 수 조회"""
        pass
    
    async def get_date_range_stats(self, start_date: str, end_date: str,
                                  project_id: str | None = None) -> dict[str, int]:
        """날짜 범위별 메모리 수 조회"""
        pass
```

### 6. Embedding Service (`src/embeddings/service.py`)

텍스트를 벡터로 변환합니다.

```python
class EmbeddingService:
    """임베딩 생성 서비스"""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = None
        self.model_name = model_name
        self.dimension = 384
    
    def load_model(self) -> None:
        """모델 로드 (lazy loading)"""
        pass
    
    def embed(self, text: str) -> list[float]:
        """단일 텍스트 임베딩"""
        pass
    
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """배치 임베딩"""
        pass
    
    def to_bytes(self, embedding: list[float]) -> bytes:
        """임베딩을 bytes로 변환 (SQLite 저장용)"""
        pass
    
    def from_bytes(self, data: bytes) -> list[float]:
        """bytes를 임베딩으로 변환"""
        pass
```

### 7. Database Layer (`src/database/`)

SQLite + sqlite-vec 연결을 관리합니다.

```python
class Database:
    """데이터베이스 연결 및 쿼리 관리"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection = None
    
    async def connect(self) -> None:
        """DB 연결 및 sqlite-vec 초기화"""
        pass
    
    async def init_tables(self) -> None:
        """테이블 및 인덱스 생성"""
        pass
    
    async def execute(self, query: str, params: tuple = ()) -> Any:
        """쿼리 실행"""
        pass
    
    async def vector_search(self, embedding: bytes, limit: int,
                            filters: dict | None) -> list[tuple]:
        """벡터 유사도 검색"""
        pass
```

## Data Models

### Memory Model

```python
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from typing import Optional
import hashlib

class Memory(BaseModel):
    """메모리 데이터 모델"""
    id: UUID
    content: str = Field(min_length=10, max_length=10000)
    content_hash: str  # SHA256 hash
    project_id: Optional[str] = None
    category: str = "task"  # task, bug, idea, decision, incident, code_snippet
    source: str  # cursor, kiro, cli, etc.
    embedding: bytes  # float32 vector as bytes (384 * 4 = 1536 bytes)
    tags: Optional[list[str]] = None
    created_at: datetime
    updated_at: datetime
    
    @staticmethod
    def compute_hash(content: str) -> str:
        """content의 SHA256 해시 계산"""
        return hashlib.sha256(content.encode()).hexdigest()
```

### Request/Response Schemas

```python
# Add
class AddParams(BaseModel):
    content: str = Field(min_length=10, max_length=10000)
    project_id: Optional[str] = Field(None, pattern=r"^[a-z0-9_-]*$")
    category: str = "task"
    source: Optional[str] = None
    tags: Optional[list[str]] = None

class AddResponse(BaseModel):
    id: str
    status: str  # "saved" or "duplicate"
    created_at: str  # ISO8601

# Search
class SearchParams(BaseModel):
    query: str = Field(min_length=3)
    project_id: Optional[str] = Field(None, pattern=r"^[a-z0-9_-]*$")
    category: Optional[str] = None
    limit: int = Field(5, ge=1, le=20)
    recency_weight: float = Field(0.0, ge=0.0, le=1.0)

class SearchResult(BaseModel):
    id: str
    content: str
    similarity_score: float
    created_at: str
    project_id: Optional[str]
    category: str
    source: str

class SearchResponse(BaseModel):
    results: list[SearchResult]

# Context
class ContextParams(BaseModel):
    memory_id: str
    project_id: Optional[str] = Field(None, pattern=r"^[a-z0-9_-]*$")
    depth: int = Field(2, ge=1, le=5)

class RelatedMemory(BaseModel):
    id: str
    content: str
    similarity_score: float
    relationship: str  # "before", "after", "similar"
    created_at: str

class ContextResponse(BaseModel):
    primary_memory: SearchResult
    related_memories: list[RelatedMemory]
    timeline: list[str]  # memory IDs in chronological order

# Delete
class DeleteParams(BaseModel):
    memory_id: str

class DeleteResponse(BaseModel):
    id: str
    status: str  # "deleted"

# Update
class UpdateParams(BaseModel):
    memory_id: str
    content: Optional[str] = Field(None, min_length=10, max_length=10000)
    category: Optional[str] = None
    tags: Optional[list[str]] = None

class UpdateResponse(BaseModel):
    id: str
    status: str  # "updated"

# Stats
class StatsParams(BaseModel):
    project_id: Optional[str] = Field(None, pattern=r"^[a-z0-9_-]*$")
    start_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    group_by: Optional[str] = Field("overall", pattern=r"^(overall|project|category|source)$")

class StatsResponse(BaseModel):
    total_memories: int
    unique_projects: int
    categories_breakdown: dict[str, int]
    sources_breakdown: dict[str, int]
    projects_breakdown: dict[str, int]
    date_range: Optional[dict[str, str]] = None  # {"start": "2024-01-01", "end": "2024-12-31"}
    query_time_ms: float
```

### Database Schema (SQLite)

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
    tags TEXT,  -- JSON array
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_memories_project_id ON memories(project_id);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_content_hash ON memories(content_hash);

-- sqlite-vec 가상 테이블 (벡터 검색용)
CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec USING vec0(
    memory_id TEXT PRIMARY KEY,
    embedding FLOAT[384]
);
```

### Configuration

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """애플리케이션 설정"""
    database_path: str = "./mem_mesh.db"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    search_threshold: float = 0.5
    log_level: str = "INFO"
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    
    class Config:
        env_file = ".env"
        env_prefix = "MEM_MESH_"
```



## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Embedding Dimension Consistency

*For any* valid text input (10-10,000 characters), the Embedding_Service SHALL produce a vector of exactly 384 dimensions (float32 values).

**Validates: Requirements 1.1, 2.1, 8.4**

### Property 2: Content Length Validation

*For any* content string with length < 10 or length > 10,000, the Memory_Server SHALL reject the request with a 400 error and not create any memory.

**Validates: Requirements 1.4, 1.5**

### Property 3: Memory Save Response Completeness

*For any* valid memory save request, the response SHALL contain a non-empty id (UUID format), status ("saved" or "duplicate"), and created_at (ISO8601 format).

**Validates: Requirements 1.6**

### Property 4: Duplicate Detection via Content Hash

*For any* two save requests with identical content and project_id, the Memory_Server SHALL return the same memory ID for both requests (idempotency).

**Validates: Requirements 1.7**

### Property 5: Memory Persistence Round-Trip

*For any* successfully saved memory, immediately querying the database by ID SHALL return a memory with equivalent content, project_id, category, and source.

**Validates: Requirements 1.10**

### Property 6: Search Filter Correctness

*For any* search with project_id filter, all returned results SHALL have matching project_id. *For any* search with category filter, all returned results SHALL have matching category.

**Validates: Requirements 2.3, 2.4**

### Property 7: Search Results Field Completeness

*For any* search result, the result SHALL contain id, content, similarity_score (0.0-1.0), created_at, project_id, category, and source fields.

**Validates: Requirements 2.10**

### Property 8: Search Similarity Threshold

*For any* search result returned, the similarity_score SHALL be greater than or equal to the configured threshold (default 0.5).

**Validates: Requirements 2.5**

### Property 9: Search Limit Enforcement

*For any* search with specified limit N (1-20), the number of returned results SHALL be at most N.

**Validates: Requirements 2.8**

### Property 10: Recency Weight Scoring

*For any* search with recency_weight α > 0, the final score SHALL equal (1 - α) * similarity_score + α * recency_score, where recency_score is normalized to [0.0, 1.0].

**Validates: Requirements 2.6**

### Property 11: Context Response Structure

*For any* valid context request, the response SHALL contain primary_memory (with all SearchResult fields), related_memories (array), and timeline (array of memory IDs in chronological order).

**Validates: Requirements 3.7**

### Property 12: Context Relationship Classification

*For any* related memory in context response, if its created_at < primary_memory.created_at, relationship SHALL be "before"; if created_at > primary_memory.created_at, relationship SHALL be "after"; otherwise "similar".

**Validates: Requirements 3.3**

### Property 13: Deletion Completeness

*For any* successfully deleted memory, querying by ID SHALL return null/404, AND vector search SHALL not return that memory.

**Validates: Requirements 4.2**

### Property 14: Update Conditional Embedding Regeneration

*For any* update that changes content, the embedding SHALL be regenerated (different bytes). *For any* update that only changes category or tags, the embedding SHALL remain unchanged.

**Validates: Requirements 5.1, 5.2**

### Property 15: Memory Serialization Round-Trip

*For any* valid Memory object, serializing to database format then deserializing SHALL produce an equivalent Memory object (all fields equal).

**Validates: Requirements 8.7**

### Property 16: Content Hash Computation

*For any* content string, the computed content_hash SHALL equal SHA256(content.encode('utf-8')).hexdigest().

**Validates: Requirements 8.3**

### Property 17: UUID Generation

*For any* newly created memory, the id field SHALL be a valid UUID (version 4 format).

**Validates: Requirements 8.2**

## Error Handling

### Error Response Format

모든 에러는 일관된 JSON 형식으로 반환됩니다:

```python
class ErrorResponse(BaseModel):
    error: str  # 에러 코드
    message: str  # 사람이 읽을 수 있는 메시지
    details: Optional[dict] = None  # 추가 정보
```

### Error Codes

| HTTP Status | Error Code | Description |
|-------------|------------|-------------|
| 400 | `INVALID_CONTENT_LENGTH` | content가 10-10,000자 범위를 벗어남 |
| 400 | `INVALID_PROJECT_ID` | project_id 형식이 올바르지 않음 |
| 400 | `INVALID_CATEGORY` | 허용되지 않는 category 값 |
| 400 | `INVALID_QUERY` | query가 3자 미만 |
| 404 | `MEMORY_NOT_FOUND` | 요청한 memory_id가 존재하지 않음 |
| 500 | `EMBEDDING_FAILED` | 임베딩 생성 실패 (3회 재시도 후) |
| 500 | `DATABASE_ERROR` | 데이터베이스 작업 실패 |

### Retry Strategy

```python
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 0.1  # seconds
    max_delay: float = 1.0
    exponential_base: float = 2.0
```

임베딩 생성 실패 시:
1. 첫 번째 재시도: 0.1초 후
2. 두 번째 재시도: 0.2초 후
3. 세 번째 재시도: 0.4초 후
4. 모두 실패 시: 500 에러 반환

### Transaction Handling

```python
async def save_memory_with_transaction(self, memory: Memory) -> Memory:
    """트랜잭션으로 메모리 저장"""
    try:
        async with self.db.transaction():
            # 1. memories 테이블에 저장
            await self.db.execute(INSERT_MEMORY_SQL, memory.to_dict())
            # 2. memories_vec에 벡터 저장
            await self.db.execute(INSERT_VECTOR_SQL, (memory.id, memory.embedding))
        return memory
    except Exception as e:
        # 자동 롤백
        raise DatabaseError(f"Failed to save memory: {e}")
```

## Testing Strategy

### Testing Framework

- **Unit Tests**: pytest + pytest-asyncio
- **Property-Based Tests**: hypothesis
- **Integration Tests**: pytest with test database

### Test Configuration

```python
# pytest.ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_functions = test_*

# Property test configuration
hypothesis_settings = {
    "max_examples": 100,
    "deadline": 5000,  # 5 seconds
}
```

### Unit Tests

단위 테스트는 개별 컴포넌트의 특정 동작을 검증합니다:

1. **EmbeddingService**
   - 모델 로드 성공/실패
   - bytes 변환 정확성

2. **MemoryService**
   - CRUD 작업 기본 동작
   - 에러 케이스 (404, 400)

3. **SearchService**
   - 빈 결과 처리
   - 기본 limit 적용

4. **ContextService**
   - 존재하지 않는 memory_id 처리
   - 기본 depth 적용

### Property-Based Tests

각 correctness property는 hypothesis를 사용한 property-based test로 구현됩니다:

```python
from hypothesis import given, strategies as st

# Property 1: Embedding Dimension Consistency
@given(st.text(min_size=10, max_size=10000))
def test_embedding_dimension_consistency(content: str):
    """
    Feature: mem-mesh, Property 1: Embedding Dimension Consistency
    For any valid text input, embedding dimension should be 384.
    """
    embedding = embedding_service.embed(content)
    assert len(embedding) == 384
    assert all(isinstance(v, float) for v in embedding)

# Property 4: Duplicate Detection
@given(
    st.text(min_size=10, max_size=1000),
    st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('Ll', 'Nd'), whitelist_characters='-_'))
)
def test_duplicate_detection(content: str, project_id: str):
    """
    Feature: mem-mesh, Property 4: Duplicate Detection via Content Hash
    Saving same content twice should return same ID.
    """
    result1 = memory_service.create(content=content, project_id=project_id)
    result2 = memory_service.create(content=content, project_id=project_id)
    assert result1.id == result2.id

# Property 15: Serialization Round-Trip
@given(st.builds(Memory, ...))
def test_memory_serialization_roundtrip(memory: Memory):
    """
    Feature: mem-mesh, Property 15: Memory Serialization Round-Trip
    Serialize then deserialize should produce equivalent object.
    """
    serialized = memory.to_dict()
    deserialized = Memory.from_dict(serialized)
    assert memory == deserialized
```

### Integration Tests

통합 테스트는 전체 워크플로우를 검증합니다:

1. **Add → Search 워크플로우**
   - 메모리 저장 후 검색으로 찾기
   
2. **Add → Context 워크플로우**
   - 여러 메모리 저장 후 맥락 조회

3. **Add → Update → Search 워크플로우**
   - 메모리 업데이트 후 검색 결과 반영 확인

4. **Add → Delete → Search 워크플로우**
   - 메모리 삭제 후 검색에서 제외 확인

### Test Data Generators

```python
from hypothesis import strategies as st

# Valid content generator
valid_content = st.text(min_size=10, max_size=10000)

# Invalid content generators
too_short_content = st.text(max_size=9)
too_long_content = st.text(min_size=10001, max_size=20000)

# Project ID generator
project_id = st.from_regex(r'^[a-z0-9_-]{1,50}$')

# Category generator
category = st.sampled_from(['task', 'bug', 'idea', 'decision', 'incident', 'code_snippet'])

# Memory generator
memory_strategy = st.builds(
    Memory,
    id=st.uuids(),
    content=valid_content,
    project_id=st.one_of(st.none(), project_id),
    category=category,
    source=st.sampled_from(['cursor', 'kiro', 'cli']),
    tags=st.one_of(st.none(), st.lists(st.text(min_size=1, max_size=20), max_size=10))
)
```

### Test Coverage Goals

- 전체 코드 커버리지: ≥ 80%
- 서비스 레이어: ≥ 90%
- Property tests: 모든 17개 property 구현
- 각 property test: 최소 100회 실행
