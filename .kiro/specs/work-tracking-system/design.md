# Design Document: Work Tracking System

## Overview

Work Tracking System은 mem-mesh에 세션 기반 작업 추적 기능을 추가합니다. Steve Yegge의 "Beads" 컨셉과 work-memory-mcp의 세션 추적을 차용하여, 단기 작업(Pins)과 장기 지식(Memories)을 분리 관리합니다.

**핵심 설계 원칙:**
- 완전 분리된 테이블 구조 (projects, sessions, pins)
- 토큰 효율적인 컨텍스트 로드
- AI 자동 중요도 판단
- 기존 memories 테이블과 공존

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      MCP Tools Layer                        │
│  pin_add | pin_complete | pin_promote | session_resume/end  │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    Service Layer                            │
│  PinService | SessionService | ProjectService | StatsService│
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    Database Layer                           │
│     projects | sessions | pins | memories (기존)            │
└─────────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### 1. Database Schema

#### projects 테이블
```sql
CREATE TABLE projects (
    id TEXT PRIMARY KEY,           -- project_id (예: "mem-mesh")
    name TEXT NOT NULL,            -- 표시 이름
    description TEXT,              -- 프로젝트 설명
    tech_stack TEXT,               -- 예: "Python, FastAPI, SQLite"
    global_rules TEXT,             -- 프로젝트 전용 규칙 (Cursor Rule 등)
    global_context TEXT,           -- 프로젝트 전역 컨텍스트
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

#### sessions 테이블
```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    user_id TEXT NOT NULL DEFAULT 'default',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',  -- active, paused, completed
    summary TEXT,                            -- AI 생성 요약
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_sessions_project_status ON sessions(project_id, status);
CREATE INDEX idx_sessions_user ON sessions(user_id);
```

#### pins 테이블
```sql
CREATE TABLE pins (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    user_id TEXT NOT NULL DEFAULT 'default',
    content TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 3,  -- 1-5
    status TEXT NOT NULL DEFAULT 'open',    -- open, in_progress, completed
    tags TEXT,                              -- JSON array
    embedding BLOB,                         -- 벡터 검색용
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_pins_session ON pins(session_id);
CREATE INDEX idx_pins_project_status ON pins(project_id, status);
CREATE INDEX idx_pins_importance ON pins(importance DESC);
CREATE INDEX idx_pins_user ON pins(user_id);
```

### 2. Service Interfaces

#### PinService
```python
class PinService:
    async def create_pin(
        self, 
        project_id: str, 
        content: str, 
        importance: Optional[int] = None,  # None이면 AI 자동 판단
        tags: Optional[List[str]] = None,
        user_id: Optional[str] = None
    ) -> Pin
    
    async def complete_pin(self, pin_id: str) -> Pin
    
    async def promote_to_memory(self, pin_id: str) -> Memory
    
    async def get_pins_by_session(
        self, 
        session_id: str, 
        limit: int = 10,
        order_by_importance: bool = True
    ) -> List[Pin]
    
    async def delete_pin(self, pin_id: str) -> bool
```

#### SessionService
```python
class SessionService:
    async def get_or_create_active_session(
        self, 
        project_id: str,
        user_id: Optional[str] = None
    ) -> Session
    
    async def resume_last_session(
        self, 
        project_id: str,
        user_id: Optional[str] = None,
        expand: bool = False
    ) -> SessionContext
    
    async def end_session(
        self, 
        session_id: str, 
        summary: Optional[str] = None
    ) -> Session
    
    async def pause_inactive_sessions(
        self, 
        inactive_hours: int = 4
    ) -> int  # 일시정지된 세션 수
```

#### ProjectService
```python
class ProjectService:
    async def get_or_create_project(self, project_id: str) -> Project
    
    async def update_project(
        self, 
        project_id: str, 
        **kwargs
    ) -> Project
    
    async def list_projects_with_stats(self) -> List[ProjectWithStats]
```

### 3. MCP Tools

#### pin_add
```python
@tool
async def pin_add(
    content: str,
    project_id: str,
    importance: Optional[int] = None,
    tags: Optional[List[str]] = None
) -> dict:
    """
    새 Pin 생성. 세션 자동 관리.
    importance가 None이면 AI가 1-5 점수 자동 판단.
    """
```

#### pin_complete
```python
@tool
async def pin_complete(pin_id: str) -> dict:
    """
    Pin 완료 처리. completed_at 기록.
    importance >= 4면 Memory 승격 제안.
    """
```

#### pin_promote
```python
@tool
async def pin_promote(pin_id: str) -> dict:
    """
    Pin을 Memory로 승격.
    content, tags 복사 및 embedding 생성.
    """
```

#### session_resume
```python
@tool
async def session_resume(
    project_id: str,
    expand: bool = False,
    limit: int = 10  # 조회 시 제한, 저장은 무제한
) -> dict:
    """
    마지막 세션 컨텍스트 로드.
    expand=False: 압축된 요약만 반환 (토큰 절약)
    expand=True: 전체 pin 내용 반환
    limit: 반환할 pin 개수 (기본 10개, 저장은 무제한)
    """
```

#### session_end
```python
@tool
async def session_end(
    project_id: str,
    summary: Optional[str] = None
) -> dict:
    """
    현재 세션 종료.
    summary가 None이면 AI가 자동 생성.
    """
```

## Data Models

### Pydantic Schemas

```python
class PinCreate(BaseModel):
    content: str
    project_id: str
    importance: Optional[int] = Field(None, ge=1, le=5)
    tags: Optional[List[str]] = None
    user_id: Optional[str] = None

class PinResponse(BaseModel):
    id: str
    session_id: str
    project_id: str
    user_id: str
    content: str
    importance: int
    status: str
    tags: List[str]
    completed_at: Optional[str]
    lead_time_hours: Optional[float]  # 계산된 값
    created_at: str
    updated_at: str

class SessionContext(BaseModel):
    session_id: str
    project_id: str
    user_id: str
    status: str
    started_at: str
    summary: Optional[str]
    pins_count: int
    open_pins: int
    completed_pins: int
    pins: List[PinResponse]  # expand=True일 때만 전체 내용

class ProjectWithStats(BaseModel):
    id: str
    name: str
    description: Optional[str]
    tech_stack: str  # 예: "Python, FastAPI, SQLite"
    global_rules: Optional[str]  # 프로젝트 전용 규칙
    memory_count: int
    pin_count: int
    active_session: Optional[str]
    avg_lead_time_hours: Optional[float]
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Auto-creation Chain
*For any* new project_id used in pin creation, the system should auto-create both a project record and an active session before the pin is created.
**Validates: Requirements 1.1, 2.1, 3.1**

### Property 2: Session Reuse
*For any* project with an active session, creating multiple pins should assign them all to the same session.
**Validates: Requirements 2.1, 3.1**

### Property 3: Pin Completion Timestamps
*For any* pin marked as completed, completed_at should be set and lead_time should equal (completed_at - created_at).
**Validates: Requirements 3.5, 3.6**

### Property 4: Status Transitions
*For any* pin, status transitions should only follow: open → in_progress → completed. Invalid transitions should be rejected.
**Validates: Requirements 3.4**

### Property 5: Pin Promotion Round-trip
*For any* promoted pin, the resulting Memory should contain identical content and tags, with a valid embedding.
**Validates: Requirements 4.2**

### Property 6: Context Load Efficiency
*For any* session context load with expand=False, the response should contain summary and pin counts but not full pin contents. Pins should be ordered by importance (high first) and default limited to 10 (configurable via limit parameter). Total pin count is unlimited in storage.
**Validates: Requirements 5.1, 5.3, 5.4**

### Property 7: Lead Time Statistics
*For any* project with completed pins, average_lead_time should equal the mean of all individual pin lead_times.
**Validates: Requirements 6.1**

### Property 8: User Filtering
*For any* user_id filter, returned sessions and pins should only belong to that user. Default user_id should be "default" when not provided.
**Validates: Requirements 8.2, 8.4**

### Property 9: Importance-based Promotion Suggestion
*For any* completed pin with importance >= 4, the system should suggest promotion to Memory.
**Validates: Requirements 4.1**

## Error Handling

### Pin Operations
- `PinNotFoundError`: Pin ID가 존재하지 않을 때
- `InvalidStatusTransitionError`: 유효하지 않은 상태 전이 시도
- `PinAlreadyCompletedError`: 이미 완료된 Pin 재완료 시도

### Session Operations
- `SessionNotFoundError`: Session ID가 존재하지 않을 때
- `NoActiveSessionError`: 활성 세션이 없을 때 (resume 시)
- `SessionAlreadyEndedError`: 이미 종료된 세션 종료 시도

### Project Operations
- `ProjectNotFoundError`: Project ID가 존재하지 않을 때

## Testing Strategy

### Unit Tests
- 각 서비스 메서드의 기본 동작 검증
- 에러 케이스 검증 (존재하지 않는 ID, 유효하지 않은 상태 전이 등)
- 스키마 검증 (필수 필드, 타입, 범위)

### Property-Based Tests (Hypothesis)
- **Property 1-2**: 랜덤 project_id로 pin 생성 후 project/session 존재 확인
- **Property 3**: 랜덤 pin 생성 → 완료 → lead_time 계산 검증
- **Property 4**: 랜덤 상태 전이 시퀀스 생성 → 유효성 검증
- **Property 5**: 랜덤 pin 생성 → 승격 → Memory 내용 비교
- **Property 6**: 랜덤 세션에 다수 pin 생성 → 컨텍스트 로드 → 정렬/제한 검증
- **Property 7**: 랜덤 완료 pin들 → 평균 lead_time 계산 검증
- **Property 8**: 다중 사용자 데이터 생성 → 필터링 검증

### Integration Tests
- MCP Tool 전체 플로우 테스트
- 세션 자동 관리 테스트
- Dashboard 통계 연동 테스트

### Test Configuration
```python
# pytest.ini 또는 conftest.py
@settings(max_examples=100)  # 최소 100회 반복
```
