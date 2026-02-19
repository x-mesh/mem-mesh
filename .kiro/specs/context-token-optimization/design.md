# 설계 문서 (Design Document)

## 개요 (Overview)

context-token-optimization 기능은 mem-mesh 시스템의 핵심 토큰 효율화 메커니즘입니다. 기존의 Pin/Session 시스템을 확장하여 지능적인 맥락 관리, 중요도 기반 메모리 승격, 의도 기반 검색 조정을 통해 AI 도구 사용 시 토큰 사용량을 최대 95%까지 절감하면서도 검색 품질을 향상시킵니다.

### 핵심 목표

1. **토큰 절감**: 세션당 평균 맥락 토큰 사용량 80% 이상 감소
2. **검색 정확도 향상**: 중요 데이터 위주 저장으로 검색 관련성 향상
3. **시스템 성능**: SQLite WAL 모드와 검색 캐싱을 결합한 고속 맥락 전환

### 기존 시스템 활용

현재 mem-mesh는 이미 다음 컴포넌트를 보유하고 있습니다:
- `PinService`: 단기 작업 추적 (app/core/services/pin.py)
- `SessionService`: 세션 관리 (app/core/services/session.py)
- `UnifiedSearchService`: 통합 검색 (app/core/services/unified_search.py)
- `ContextService`: 맥락 조회 (app/core/services/context.py)

이 설계는 기존 서비스를 확장하고 새로운 최적화 레이어를 추가합니다.

## 아키텍처 (Architecture)

### 시스템 구조

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP Tool Layer                            │
│  (session_resume, pin_add, pin_complete, pin_promote, etc)  │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│              Token Optimization Layer (NEW)                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  TokenTracker: 토큰 사용량 추적 및 예측              │  │
│  │  ImportanceAnalyzer: 자동 중요도 분석                │  │
│  │  ContextOptimizer: 맥락 로딩 최적화                  │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│              Enhanced Service Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │ PinService   │  │SessionService│  │UnifiedSearch     │ │
│  │ (Enhanced)   │  │ (Enhanced)   │  │Service(Enhanced) │ │
│  └──────────────┘  └──────────────┘  └──────────────────┘ │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│                  Database Layer                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  SQLite + sqlite-vec                                  │  │
│  │  - pins 테이블 (확장)                                 │  │
│  │  - sessions 테이블 (확장)                             │  │
│  │  - session_stats 테이블 (신규)                        │  │
│  │  - token_usage 테이블 (신규)                          │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 데이터 흐름

1. **세션 시작 (Session Resume)**
   ```
   User → session_resume(expand=false) 
        → SessionService.resume_last_session()
        → TokenTracker.estimate_tokens()
        → Return: 요약 정보 (~100 tokens)
   ```

2. **작업 추가 (Pin Add)**
   ```
   User → pin_add(content, importance)
        → ImportanceAnalyzer.analyze() (if importance=None)
        → PinService.create_pin()
        → TokenTracker.record_pin_tokens()
   ```

3. **검색 (Search with Intent)**
   ```
   User → search(query)
        → SearchIntentAnalyzer.analyze()
        → ContextOptimizer.adjust_depth()
        → UnifiedSearchService.search()
        → TokenTracker.record_search_tokens()
   ```

4. **세션 종료 (Session End)**
   ```
   User → session_end()
        → SessionService.end_session()
        → Auto-promote pins (importance >= 4)
        → TokenTracker.calculate_savings()
        → Return: 통계 및 절감률
   ```

## 컴포넌트 및 인터페이스 (Components and Interfaces)

### 1. TokenTracker (신규)

토큰 사용량을 추적하고 예측하는 서비스입니다.

```python
class TokenTracker:
    """토큰 사용량 추적 및 최적화 서비스"""
    
    def __init__(self, db: Database):
        self.db = db
        self.token_estimator = TokenEstimator()
    
    async def estimate_tokens(self, content: str) -> int:
        """
        컨텐츠의 예상 토큰 수 계산
        
        Args:
            content: 분석할 텍스트
            
        Returns:
            예상 토큰 수
        """
        pass
    
    async def record_session_tokens(
        self,
        session_id: str,
        loaded_tokens: int,
        unloaded_tokens: int
    ) -> None:
        """
        세션의 토큰 사용량 기록
        
        Args:
            session_id: 세션 ID
            loaded_tokens: 실제 로드된 토큰 수
            unloaded_tokens: 지연 로딩으로 절감된 토큰 수
        """
        pass
    
    async def calculate_savings(self, session_id: str) -> Dict[str, Any]:
        """
        세션의 토큰 절감률 계산
        
        Returns:
            {
                "total_tokens": int,
                "loaded_tokens": int,
                "saved_tokens": int,
                "savings_rate": float  # 0.0-1.0
            }
        """
        pass
    
    async def check_threshold(
        self,
        session_id: str,
        threshold: int = 10000
    ) -> bool:
        """
        토큰 사용량이 임계값을 초과했는지 확인
        
        Returns:
            True if exceeded, False otherwise
        """
        pass
```

### 2. ImportanceAnalyzer (신규)

핀의 중요도를 자동으로 분석하는 서비스입니다.

```python
class ImportanceAnalyzer:
    """핀 중요도 자동 분석 서비스"""
    
    def __init__(self):
        self.keywords = self._load_importance_keywords()
    
    def analyze(self, content: str, tags: Optional[List[str]] = None) -> int:
        """
        컨텐츠와 태그를 분석하여 중요도 추정
        
        Args:
            content: 핀 내용
            tags: 태그 목록
            
        Returns:
            중요도 (1-5)
            
        분석 기준:
        - 5: architecture, design, critical, breaking
        - 4: feature, implement, refactor, optimize
        - 3: fix, update, improve (기본값)
        - 2: test, doc, comment
        - 1: typo, format, style
        """
        pass
    
    def _load_importance_keywords(self) -> Dict[int, List[str]]:
        """중요도별 키워드 사전 로드"""
        return {
            5: ["architecture", "design", "critical", "breaking", "아키텍처", "설계", "중대"],
            4: ["feature", "implement", "refactor", "optimize", "기능", "구현", "최적화"],
            3: ["fix", "update", "improve", "수정", "업데이트", "개선"],
            2: ["test", "doc", "comment", "테스트", "문서", "주석"],
            1: ["typo", "format", "style", "오타", "포맷", "스타일"]
        }
```

### 3. ContextOptimizer (신규)

검색 의도에 따라 맥락 로딩 깊이를 조정하는 서비스입니다.

```python
class ContextOptimizer:
    """맥락 로딩 최적화 서비스"""
    
    def __init__(self, session_service: SessionService):
        self.session_service = session_service
    
    async def adjust_for_intent(
        self,
        intent: SearchIntent,
        project_id: str,
        base_limit: int = 10
    ) -> Tuple[bool, int, int]:
        """
        검색 의도에 따라 맥락 로딩 파라미터 조정
        
        Args:
            intent: 검색 의도 분석 결과
            project_id: 프로젝트 ID
            base_limit: 기본 제한 수
            
        Returns:
            (expand, limit, min_importance)
            - expand: 상세 로딩 여부
            - limit: 로드할 핀 개수
            - min_importance: 최소 중요도 필터
        """
        pass
    
    async def load_context_for_search(
        self,
        query: str,
        project_id: str,
        intent: SearchIntent
    ) -> SessionContext:
        """
        검색 의도에 최적화된 맥락 로드
        
        Args:
            query: 검색 쿼리
            project_id: 프로젝트 ID
            intent: 검색 의도
            
        Returns:
            최적화된 세션 맥락
        """
        pass
```

### 4. Enhanced PinService

기존 PinService에 필터링 및 통계 기능을 추가합니다.

```python
# app/core/services/pin.py에 추가할 메서드

class PinService:
    # ... 기존 메서드들 ...
    
    async def get_pins_filtered(
        self,
        session_id: str,
        min_importance: Optional[int] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[PinResponse]:
        """
        필터링된 핀 목록 조회
        
        Args:
            session_id: 세션 ID
            min_importance: 최소 중요도
            status: 상태 필터
            tags: 태그 필터 (AND 조건)
            limit: 결과 개수
            
        Returns:
            필터링된 핀 목록
        """
        pass
    
    async def get_pin_statistics(
        self,
        session_id: str
    ) -> Dict[str, Any]:
        """
        세션의 핀 통계 조회
        
        Returns:
            {
                "total": int,
                "by_status": {"open": int, "in_progress": int, "completed": int},
                "by_importance": {1: int, 2: int, 3: int, 4: int, 5: int},
                "avg_lead_time_hours": float,
                "promotion_candidates": int  # importance >= 4인 완료된 핀
            }
        """
        pass
```

### 5. Enhanced SessionService

기존 SessionService에 토큰 추적 및 자동 승격 기능을 추가합니다.

```python
# app/core/services/session.py에 추가할 메서드

class SessionService:
    # ... 기존 메서드들 ...
    
    async def resume_with_token_tracking(
        self,
        project_id: str,
        user_id: Optional[str] = None,
        expand: bool = False,
        limit: int = 10
    ) -> Tuple[SessionContext, Dict[str, int]]:
        """
        토큰 추적과 함께 세션 재개
        
        Returns:
            (session_context, token_info)
            token_info = {
                "loaded_tokens": int,
                "unloaded_tokens": int,
                "estimated_total": int
            }
        """
        pass
    
    async def end_with_auto_promotion(
        self,
        session_id: str,
        summary: Optional[str] = None,
        auto_promote_threshold: int = 4
    ) -> Dict[str, Any]:
        """
        자동 승격과 함께 세션 종료
        
        Args:
            session_id: 세션 ID
            summary: 세션 요약
            auto_promote_threshold: 자동 승격 중요도 임계값
            
        Returns:
            {
                "session": SessionResponse,
                "promoted_pins": List[str],  # 승격된 핀 ID 목록
                "token_savings": Dict[str, Any]
            }
        """
        pass
    
    async def get_session_statistics(
        self,
        project_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        세션 통계 조회
        
        Returns:
            {
                "total_sessions": int,
                "avg_duration_hours": float,
                "avg_pins_per_session": float,
                "importance_distribution": Dict[int, int],
                "avg_token_savings_rate": float
            }
        """
        pass
```

### 6. Enhanced UnifiedSearchService

기존 UnifiedSearchService에 의도 기반 맥락 조정 기능을 통합합니다.

```python
# app/core/services/unified_search.py에 추가할 메서드

class UnifiedSearchService:
    # ... 기존 메서드들 ...
    
    async def search_with_context_optimization(
        self,
        query: str,
        project_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 25,
        optimize_context: bool = True
    ) -> Tuple[SearchResponse, Optional[SessionContext]]:
        """
        맥락 최적화와 함께 검색 수행
        
        Args:
            query: 검색 쿼리
            project_id: 프로젝트 ID
            category: 카테고리 필터
            limit: 결과 개수
            optimize_context: 맥락 최적화 활성화
            
        Returns:
            (search_response, optimized_context)
        """
        pass
```

## 데이터 모델 (Data Models)

### 1. 기존 테이블 확장

#### pins 테이블 (확장)
```sql
-- 기존 컬럼 유지
-- 새로운 컬럼 추가
ALTER TABLE pins ADD COLUMN estimated_tokens INTEGER DEFAULT 0;
ALTER TABLE pins ADD COLUMN promoted_to_memory_id TEXT;
ALTER TABLE pins ADD COLUMN auto_importance BOOLEAN DEFAULT FALSE;
```

#### sessions 테이블 (확장)
```sql
-- 기존 컬럼 유지
-- 새로운 컬럼 추가
ALTER TABLE sessions ADD COLUMN initial_context_tokens INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN total_loaded_tokens INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN total_saved_tokens INTEGER DEFAULT 0;
```

### 2. 신규 테이블

#### session_stats 테이블
```sql
CREATE TABLE IF NOT EXISTS session_stats (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- 'resume', 'search', 'pin_add', 'end'
    tokens_loaded INTEGER NOT NULL,
    tokens_saved INTEGER NOT NULL,
    context_depth INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX idx_session_stats_session ON session_stats(session_id);
CREATE INDEX idx_session_stats_timestamp ON session_stats(timestamp);
```

#### token_usage 테이블
```sql
CREATE TABLE IF NOT EXISTS token_usage (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT,
    operation_type TEXT NOT NULL,  -- 'session_resume', 'search', 'context_load'
    query TEXT,
    tokens_used INTEGER NOT NULL,
    tokens_saved INTEGER DEFAULT 0,
    optimization_applied BOOLEAN DEFAULT FALSE,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
);

CREATE INDEX idx_token_usage_project ON token_usage(project_id);
CREATE INDEX idx_token_usage_session ON token_usage(session_id);
CREATE INDEX idx_token_usage_created ON token_usage(created_at);
```

### 3. Pydantic 스키마

```python
# app/core/schemas/optimization.py (신규)

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class TokenInfo(BaseModel):
    """토큰 정보"""
    loaded_tokens: int = Field(..., description="실제 로드된 토큰 수")
    unloaded_tokens: int = Field(..., description="지연 로딩으로 절감된 토큰 수")
    estimated_total: int = Field(..., description="예상 총 토큰 수")
    savings_rate: float = Field(..., ge=0.0, le=1.0, description="절감률")

class SessionStatistics(BaseModel):
    """세션 통계"""
    total_sessions: int
    avg_duration_hours: float
    avg_pins_per_session: float
    importance_distribution: Dict[int, int]
    avg_token_savings_rate: float

class PinStatistics(BaseModel):
    """핀 통계"""
    total: int
    by_status: Dict[str, int]
    by_importance: Dict[int, int]
    avg_lead_time_hours: Optional[float]
    promotion_candidates: int

class OptimizedSessionContext(BaseModel):
    """최적화된 세션 맥락"""
    session_context: Any  # SessionContext
    token_info: TokenInfo
    optimization_applied: bool
    recommendations: List[str] = Field(default_factory=list)
```

## 정확성 속성 (Correctness Properties)

*속성(Property)은 시스템의 모든 유효한 실행에서 참이어야 하는 특성 또는 동작입니다. 속성은 사람이 읽을 수 있는 명세와 기계가 검증 가능한 정확성 보장 사이의 다리 역할을 합니다.*


### Property Reflection (속성 반영)

Prework 분석 결과, 50개의 acceptance criteria 중 47개가 property로, 3개가 example로 테스트 가능합니다. 이제 중복성을 제거하고 통합 가능한 속성들을 식별합니다:

**중복 제거 및 통합:**

1. **세션 재개 관련 (1.1-1.5)**: 5개 속성 → 3개로 통합
   - 1.1 (토큰 제한)과 1.2 (상세 로딩)는 expand 파라미터의 양면이므로 하나의 속성으로 통합 가능
   - 1.3 (limit), 1.5 (필수 필드)는 독립적 유지
   - 1.4는 example로 유지

2. **핀 생성 관련 (2.1-2.5)**: 5개 속성 → 3개로 통합
   - 2.1 (필수 필드)과 2.4 (ID 생성), 2.5 (자동 설정)는 핀 생성의 기본 불변성으로 통합 가능
   - 2.2 (자동 중요도), 2.3 (범위 검증)은 독립적 유지

3. **핀 완료 관련 (3.1-3.5)**: 5개 속성 → 3개로 통합
   - 3.2 (importance >= 4 승격 제안)와 3.3 (importance <= 3 승격 없음)은 하나의 속성으로 통합 가능
   - 3.1 (상태 변경), 3.5 (lead_time 계산)은 독립적 유지
   - 3.4는 example로 유지

4. **핀 승격 관련 (4.1-4.5)**: 5개 속성 → 2개로 통합
   - 4.2 (importance), 4.3 (tags), 4.4 (project_id)는 모두 메타데이터 보존에 관한 것이므로 하나로 통합 가능
   - 4.1 (메모리 생성), 4.5 (중복 방지)는 독립적 유지

5. **세션 종료 관련 (5.1-5.5)**: 5개 속성 → 4개로 통합
   - 5.2 (커스텀 요약)와 5.3 (자동 요약)은 요약 생성의 양면이므로 하나로 통합 가능
   - 나머지는 독립적 유지

6. **의도 기반 맥락 조정 (6.1-6.5)**: 5개 속성 → 3개로 통합
   - 6.1 (Debug), 6.2 (Explore), 6.3 (Implement)은 의도별 맥락 조정의 구체적 케이스이므로 하나의 포괄적 속성으로 통합 가능
   - 6.4 (기본값), 6.5 (토큰 수 반환)은 독립적 유지

7. **토큰 추적 (7.1-7.5)**: 5개 속성 → 4개로 통합
   - 7.1 (초기 기록)과 7.2 (누적 업데이트)는 토큰 추적의 연속적 과정이므로 하나로 통합 가능
   - 나머지는 독립적 유지

8. **핀 검색 및 필터링 (8.1-8.5)**: 5개 속성 → 2개로 통합
   - 8.1 (importance), 8.2 (status), 8.3 (tags)는 모두 필터링 기능이므로 하나로 통합 가능
   - 8.4 (AND 조건)는 위와 통합
   - 8.5 (정렬)는 독립적 유지

9. **세션 통계 (9.1-9.5)**: 5개 속성 → 1개로 통합
   - 모든 통계 항목은 통계 조회의 완전성을 검증하는 하나의 속성으로 통합 가능

10. **데이터베이스 최적화 (10.1-10.5)**: 5개 속성 → 2개 property + 3개 example
    - 10.4 (자동 정리 표시), 10.5 (정리 실행)는 하나로 통합 가능
    - 10.1, 10.2, 10.3은 example로 유지

**최종 결과**: 50개 → 26개 속성 (23개 property + 3개 example)

### Correctness Properties (정확성 속성)

#### Property 1: 세션 재개 시 expand 파라미터에 따른 맥락 로딩

*For any* 유효한 세션과 expand 파라미터 값(true/false)에 대해, expand=false일 때는 반환된 맥락의 예상 토큰 수가 100 이하여야 하고, expand=true일 때는 활성 핀들의 상세 내용이 포함되어야 함

**Validates: Requirements 1.1, 1.2**

#### Property 2: 세션 재개 시 limit 파라미터 준수

*For any* 유효한 세션과 limit 값에 대해, 반환된 핀의 개수는 limit 이하여야 함

**Validates: Requirements 1.3**

#### Property 3: 세션 재개 시 필수 필드 포함

*For any* 유효한 세션에 대해, session_resume이 성공하면 반환된 데이터는 pins_count, open_pins, completed_pins를 포함해야 함

**Validates: Requirements 1.5**

#### Property 4: 핀 생성 시 기본 불변성

*For any* 유효한 핀 생성 요청에 대해, 생성된 핀은 고유한 pin_id와 session_id를 가지며, created_at이 설정되고, status가 'open'이어야 함

**Validates: Requirements 2.1, 2.4, 2.5**

#### Property 5: 핀 생성 시 자동 중요도 추정

*For any* importance가 명시되지 않은 핀 생성 요청에 대해, 생성된 핀의 importance는 1-5 범위 내의 값이어야 함

**Validates: Requirements 2.2**

#### Property 6: 핀 생성 시 importance 범위 검증

*For any* importance가 1-5 범위를 벗어난 핀 생성 요청에 대해, 시스템은 에러를 반환하고 핀을 생성하지 않아야 함

**Validates: Requirements 2.3**

#### Property 7: 핀 완료 시 상태 변경 및 시각 기록

*For any* 유효한 핀에 대해, pin_complete 호출 후 핀의 status는 'completed'이고 completed_at이 설정되어야 함

**Validates: Requirements 3.1**

#### Property 8: 핀 완료 시 중요도 기반 승격 제안

*For any* 완료된 핀에 대해, importance >= 4이면 promotion_suggested=true를 포함해야 하고, importance <= 3이면 승격 제안이 없어야 함

**Validates: Requirements 3.2, 3.3**

#### Property 9: 핀 완료 시 lead_time 자동 계산

*For any* 핀에 대해, 완료 후 lead_time_hours가 계산되어 있어야 하며, 이는 (completed_at - created_at)의 시간 차이여야 함

**Validates: Requirements 3.5**

#### Property 10: 핀 승격 시 메모리 생성 및 ID 반환

*For any* 유효한 핀에 대해, pin_promote 호출 후 memory_id가 반환되고, 해당 ID로 메모리를 조회할 수 있어야 함

**Validates: Requirements 4.1**

#### Property 11: 핀 승격 시 메타데이터 보존

*For any* 핀에 대해, 승격 후 생성된 메모리는 핀의 importance, tags, project_id를 모두 포함해야 함

**Validates: Requirements 4.2, 4.3, 4.4**

#### Property 12: 핀 중복 승격 방지

*For any* 이미 승격된 핀에 대해, pin_promote를 다시 호출하면 동일한 memory_id를 반환하고 중복 메모리를 생성하지 않아야 함

**Validates: Requirements 4.5**

#### Property 13: 세션 종료 시 요약 생성

*For any* 세션에 대해, session_end 호출 시 summary가 제공되면 그것을 사용하고, 제공되지 않으면 핀들의 내용을 기반으로 자동 생성해야 함

**Validates: Requirements 5.1, 5.2, 5.3**

#### Property 14: 세션 종료 시 자동 승격 제안

*For any* 세션에 대해, 종료 시 importance >= 4인 완료된 핀들에 대한 승격 제안이 포함되어야 함

**Validates: Requirements 5.4**

#### Property 15: 세션 종료 시 통계 반환

*For any* 세션에 대해, 종료 시 총 핀 수, 완료된 핀 수, 평균 lead_time을 포함한 통계가 반환되어야 함

**Validates: Requirements 5.5**

#### Property 16: 의도 기반 맥락 조정

*For any* 검색 의도(Debug/Explore/Implement)에 대해, 시스템은 의도에 맞는 맥락 로딩 전략(expand, limit, min_importance)을 적용해야 함

**Validates: Requirements 6.1, 6.2, 6.3**

#### Property 17: 의도 불명확 시 기본 모드 사용

*For any* 의도가 명확하지 않은 검색에 대해, 시스템은 요약 모드(expand=false)를 기본값으로 사용해야 함

**Validates: Requirements 6.4**

#### Property 18: 맥락 조정 시 토큰 수 반환

*For any* 의도 기반 맥락 조정에 대해, 로드된 맥락의 예상 토큰 수가 반환되어야 함

**Validates: Requirements 6.5**

#### Property 19: 세션 토큰 추적

*For any* 세션에 대해, 시작 시 초기 토큰 수가 기록되고, 맥락 로드 시마다 누적 토큰 수가 업데이트되어야 함

**Validates: Requirements 7.1, 7.2**

#### Property 20: 세션 종료 시 토큰 절감률 계산

*For any* 세션에 대해, 종료 시 총 토큰 사용량과 절감률이 계산되어 반환되어야 함

**Validates: Requirements 7.3**

#### Property 21: 지연 로딩 시 미로드 토큰 추적

*For any* expand=false로 재개된 세션에 대해, 로드되지 않은 핀들의 예상 토큰 수가 별도로 추적되어야 함

**Validates: Requirements 7.4**

#### Property 22: 토큰 임계값 초과 시 경고

*For any* 세션에 대해, 누적 토큰 사용량이 임계값(10,000)을 초과하면 경고 메시지가 반환되어야 함

**Validates: Requirements 7.5**

#### Property 23: 핀 필터링 기능

*For any* 핀 검색 요청에 대해, importance, status, tags 필터가 제공되면 모든 반환된 핀은 해당 조건들을 AND 조건으로 만족해야 함

**Validates: Requirements 8.1, 8.2, 8.3, 8.4**

#### Property 24: 핀 검색 결과 정렬

*For any* 핀 검색에 대해, 결과는 created_at 기준 내림차순으로 정렬되어야 함

**Validates: Requirements 8.5**

#### Property 25: 세션 통계 완전성

*For any* 세션 통계 요청에 대해, 반환된 데이터는 총 세션 수, 평균 지속 시간, 세션당 평균 핀 수, 중요도별 분포, 평균 토큰 절감률을 모두 포함해야 함

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**

#### Property 26: 오래된 핀 자동 정리

*For any* 30일 이상 경과한 완료된 핀에 대해, 승격되지 않았다면 정리 실행 시 삭제되어야 하며, 삭제된 핀 수가 반환되어야 함

**Validates: Requirements 10.4, 10.5**

## 에러 처리 (Error Handling)

### 에러 유형 및 처리 전략

1. **TokenLimitExceededError**
   - 발생 조건: 세션의 누적 토큰 수가 임계값 초과
   - 처리: 경고 로그 + 사용자에게 경고 메시지 반환
   - 복구: 세션 종료 또는 맥락 정리 권장

2. **InvalidImportanceError**
   - 발생 조건: importance 값이 1-5 범위 외
   - 처리: 400 Bad Request + 상세 에러 메시지
   - 복구: 유효한 범위의 값으로 재시도

3. **PinNotFoundError**
   - 발생 조건: 존재하지 않는 pin_id로 작업 시도
   - 처리: 404 Not Found + 에러 메시지
   - 복구: 유효한 pin_id 확인 후 재시도

4. **SessionNotFoundError**
   - 발생 조건: 존재하지 않는 세션 접근
   - 처리: 404 Not Found + 새 세션 생성 안내
   - 복구: pin_add로 새 세션 시작

5. **DuplicatePromotionError**
   - 발생 조건: 이미 승격된 핀 재승격 시도
   - 처리: 200 OK + 기존 memory_id 반환 (에러 아님)
   - 복구: 불필요 (정상 동작)

6. **TokenEstimationError**
   - 발생 조건: 토큰 수 계산 실패
   - 처리: 경고 로그 + 기본값(0) 사용
   - 복구: 계속 진행 (비치명적)

### 에러 응답 형식

```python
{
    "error": {
        "type": "InvalidImportanceError",
        "message": "Importance must be between 1 and 5",
        "details": {
            "provided_value": 10,
            "valid_range": [1, 5]
        },
        "recovery_hint": "Please provide an importance value between 1 and 5"
    }
}
```

## 테스트 전략 (Testing Strategy)

### 이중 테스트 접근법

이 기능은 **단위 테스트**와 **속성 기반 테스트**를 모두 사용합니다:

- **단위 테스트**: 특정 예제, 엣지 케이스, 에러 조건 검증
- **속성 테스트**: 모든 입력에 대한 보편적 속성 검증

### 속성 기반 테스트 설정

**라이브러리**: Python의 `hypothesis` 사용

**설정**:
```python
from hypothesis import given, settings
import hypothesis.strategies as st

@settings(max_examples=100)  # 최소 100회 반복
@given(
    content=st.text(min_size=10, max_size=1000),
    importance=st.integers(min_value=1, max_value=5),
    tags=st.lists(st.text(min_size=1, max_size=20), max_size=5)
)
def test_pin_creation_invariants(content, importance, tags):
    """
    Feature: context-token-optimization, Property 4: 핀 생성 시 기본 불변성
    
    For any 유효한 핀 생성 요청에 대해, 생성된 핀은 고유한 pin_id와 
    session_id를 가지며, created_at이 설정되고, status가 'open'이어야 함
    """
    # 테스트 구현
    pass
```

### 단위 테스트 예제

```python
import pytest
from app.core.services.session import SessionService

async def test_session_resume_no_session():
    """
    세션이 없을 때 session_resume 호출 시 no_session 상태 반환
    Validates: Requirements 1.4
    """
    service = SessionService(db)
    result = await service.resume_last_session(
        project_id="nonexistent-project",
        expand=False
    )
    assert result is None or result.status == "no_session"

async def test_pin_complete_nonexistent():
    """
    존재하지 않는 핀 완료 시도 시 에러 반환
    Validates: Requirements 3.4
    """
    service = PinService(db)
    with pytest.raises(PinNotFoundError):
        await service.complete_pin("nonexistent-pin-id")

async def test_database_indexes_exist():
    """
    핀 및 세션 테이블에 필요한 인덱스 존재 확인
    Validates: Requirements 10.1, 10.2
    """
    indexes = await db.get_indexes("pins")
    assert "idx_pins_pin_id" in indexes
    assert "idx_pins_session_id" in indexes
    assert "idx_pins_project_id" in indexes
```

### 통합 테스트

```python
async def test_full_session_workflow_with_token_tracking():
    """
    전체 세션 워크플로우 통합 테스트:
    1. 세션 재개 (expand=false)
    2. 핀 추가 (여러 개, 다양한 중요도)
    3. 검색 수행 (의도 기반 맥락 조정)
    4. 핀 완료
    5. 세션 종료 (자동 승격 + 토큰 통계)
    """
    # 1. 세션 재개
    context, token_info = await session_service.resume_with_token_tracking(
        project_id="test-project",
        expand=False
    )
    assert token_info["loaded_tokens"] <= 100
    
    # 2. 핀 추가
    pin1 = await pin_service.create_pin(
        project_id="test-project",
        content="Implement feature X",
        importance=5
    )
    pin2 = await pin_service.create_pin(
        project_id="test-project",
        content="Fix typo in docs",
        importance=1
    )
    
    # 3. 검색 (Debug 의도)
    results, context = await search_service.search_with_context_optimization(
        query="feature X",
        project_id="test-project",
        optimize_context=True
    )
    
    # 4. 핀 완료
    completed = await pin_service.complete_pin(pin1.id)
    assert completed.suggest_promotion == True
    
    # 5. 세션 종료
    end_result = await session_service.end_with_auto_promotion(
        session_id=context.session_id
    )
    assert pin1.id in end_result["promoted_pins"]
    assert pin2.id not in end_result["promoted_pins"]
    assert end_result["token_savings"]["savings_rate"] > 0.5
```

### 테스트 커버리지 목표

- **코드 커버리지**: 최소 85%
- **속성 테스트**: 각 속성당 최소 100회 반복
- **통합 테스트**: 주요 워크플로우 5개 이상
- **성능 테스트**: 1000개 핀 세션에서 1초 이내 응답

### 테스트 태그 형식

모든 속성 기반 테스트는 다음 형식의 주석을 포함해야 합니다:

```python
"""
Feature: context-token-optimization, Property {번호}: {속성 제목}

{속성 설명}
"""
```

이를 통해 테스트와 설계 문서의 속성을 명확하게 연결할 수 있습니다.
