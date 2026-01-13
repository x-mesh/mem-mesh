# Core Services & Database Layer

## Module Context

핵심 비즈니스 로직과 데이터 계층을 담당하는 모듈. 데이터베이스 연결, 임베딩 생성, 메모리 관리 서비스의 중앙 집중식 구현.

**Dependencies:**
- pysqlite3 (SQLite with extension loading)
- sqlite-vec (vector operations)
- sentence-transformers (embedding generation)
- pydantic (data validation)

## Tech Stack & Constraints

**Database Layer:**
- SQLite only - NO PostgreSQL, MySQL, or external vector DBs
- sqlite-vec virtual table for vector operations
- Connection pooling through Database class singleton
- WAL mode enabled for concurrent access

**Embedding Strategy:**
- sentence-transformers models only
- Default: `all-MiniLM-L6-v2` (384 dimensions)
- Model metadata stored in `embedding_metadata` table
- Migration required when model changes

## Implementation Patterns

**Service Layer Pattern:**
```python
# Service 클래스 구조
class ServiceName:
    def __init__(self, db: Database, embedding_service: EmbeddingService):
        self.db = db
        self.embedding_service = embedding_service
    
    async def operation(self, params: ParamsSchema) -> ResponseSchema:
        # 비즈니스 로직 구현
        pass
```

**Database Operations:**
```python
# 올바른 벡터 업데이트 패턴
await self.db.execute("DELETE FROM memory_vectors WHERE memory_id = ?", (memory_id,))
await self.db.execute("INSERT INTO memory_vectors VALUES (?, ?)", (memory_id, vector))

# 잘못된 패턴 (sqlite-vec에서 지원하지 않음)
# await self.db.execute("INSERT OR REPLACE INTO memory_vectors VALUES (?, ?)", (memory_id, vector))
```

**Configuration Management:**
- Settings 클래스를 통한 중앙 집중식 설정
- 환경변수 prefix: `MEM_MESH_`
- .env 파일 지원

## Testing Strategy

**Unit Tests:**
```bash
python -m pytest tests/test_*_service.py -v
python -m pytest tests/test_database/ -v
```

**Integration Tests:**
```bash
python -m pytest tests/test_integration.py -v
```

**Database Tests:**
- 각 테스트는 독립적인 임시 데이터베이스 사용
- 테스트 후 자동 정리
- sqlite-vec 확장 로딩 테스트 포함

## Local Golden Rules

**Do's:**
- 모든 데이터베이스 작업에 async/await 사용
- Pydantic 스키마를 통한 입력 검증 필수
- 임베딩 생성 시 배치 처리 적용
- 데이터베이스 연결은 Database 클래스를 통해서만

**Don'ts:**
- sqlite-vec 테이블에 INSERT OR REPLACE 사용 금지
- 직접적인 sqlite3 연결 생성 금지
- 임베딩 모델 변경 시 마이그레이션 없이 진행 금지
- 동기 함수에서 데이터베이스 작업 수행 금지

**Error Handling:**
- 모든 서비스 메서드는 적절한 예외 타입 정의
- 데이터베이스 오류는 DatabaseError로 래핑
- 로깅을 통한 오류 추적 필수