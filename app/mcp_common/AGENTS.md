# MCP Common: Shared Protocol Implementation

## Module Context

MCP (Model Context Protocol) 서버 구현체들이 공유하는 핵심 로직. 비즈니스 로직과 스키마 정의를 중앙 집중화하여 일관성 보장.

**Shared Components:**
- MCPToolHandlers: 6개 MCP tool의 비즈니스 로직
- StorageManager: 스토리지 초기화/종료 관리
- JSON Schema 정의: tools/list 응답용

## Tech Stack & Constraints

**MCP Protocol:**
- Version: 2024-11-05 (app.core.version에서 관리)
- Transport: stdio, SSE 지원
- JSON-RPC 2.0 기반 통신

**Tool Implementation:**
- 6개 표준 도구: add, search, context, update, delete, stats
- 모든 도구는 storage backend 의존성 주입 방식
- 동일한 Pydantic 스키마 사용

## Implementation Patterns

**Tool Handler Pattern:**
```python
class MCPToolHandlers:
    def __init__(self, storage: StorageBackend):
        self._storage = storage
    
    async def tool_name(self, **kwargs) -> Dict[str, Any]:
        # 1. 파라미터 검증 (Pydantic)
        # 2. 스토리지 백엔드 호출
        # 3. 결과 직렬화
        return result.model_dump()
```

**Storage Manager Pattern:**
```python
storage_manager = StorageManager()
await storage_manager.initialize(settings)
handlers = MCPToolHandlers(storage_manager.storage)
```

**Schema Definition:**
- JSON Schema는 schemas.py에서 중앙 관리
- Pure MCP 구현에서 tools/list 응답에 사용
- FastMCP는 자동 스키마 생성하지만 일관성을 위해 동일 스키마 참조

## Testing Strategy

**Tool Logic Tests:**
```bash
python -m pytest tests/test_mcp_tools.py -v
```

**Integration Tests:**
- 각 MCP 서버 구현체와의 통합 테스트
- 스토리지 백엔드 모킹을 통한 단위 테스트

## Local Golden Rules

**Do's:**
- 모든 tool 함수는 storage 의존성 주입 방식 사용
- 에러 처리는 JSON-RPC 표준 준수
- 로깅은 구조화된 형태로 수행
- 버전 정보는 app.core.version에서 import

**Don'ts:**
- Tool 함수에서 직접 데이터베이스 접근 금지
- 하드코딩된 스키마 정의 금지
- MCP 프로토콜 버전 하드코딩 금지
- 동기 함수로 tool 구현 금지

**Protocol Compliance:**
- JSON-RPC 2.0 메시지 형식 엄격 준수
- 에러 코드는 표준 JSON-RPC 코드 사용
- 모든 응답은 올바른 content 형식으로 반환