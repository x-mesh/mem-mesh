# mem-mesh MCP 사용 예제

실제 사용 가능한 mem-mesh MCP 도구 예제 모음

## 📋 목차

1. [기본 메모리 관리](#기본-메모리-관리)
2. [검색 및 컨텍스트](#검색-및-컨텍스트)
3. [Work Tracking (Pins & Sessions)](#work-tracking-pins--sessions)
4. [토큰 최적화 패턴](#토큰-최적화-패턴)

---

## 기본 메모리 관리

### 메모리 추가

```json
{
  "tool": "add",
  "arguments": {
    "content": "Implemented user authentication with JWT tokens",
    "project_id": "my-app",
    "category": "task",
    "tags": ["auth", "jwt", "security"]
  }
}
```

**응답 예시:**
```json
{
  "id": "abc123...",
  "content": "Implemented user authentication with JWT tokens",
  "project_id": "my-app",
  "category": "task",
  "tags": ["auth", "jwt", "security"],
  "created_at": "2026-01-20T10:30:00Z"
}
```

### 메모리 검색

```json
{
  "tool": "search",
  "arguments": {
    "query": "authentication JWT",
    "project_id": "my-app",
    "limit": 3
  }
}
```

**응답 예시:**
```json
{
  "results": [
    {
      "id": "abc123...",
      "content": "Implemented user authentication with JWT tokens",
      "similarity_score": 0.95,
      "category": "task",
      "created_at": "2026-01-20T10:30:00Z"
    }
  ],
  "total": 1
}
```

### 메모리 업데이트

```json
{
  "tool": "update",
  "arguments": {
    "memory_id": "abc123...",
    "content": "Updated: Implemented user authentication with JWT tokens and refresh tokens",
    "tags": ["auth", "jwt", "security", "refresh-token"]
  }
}
```

### 메모리 삭제

```json
{
  "tool": "delete",
  "arguments": {
    "memory_id": "abc123..."
  }
}
```

---

## 검색 및 컨텍스트

### 카테고리별 검색

```json
{
  "tool": "search",
  "arguments": {
    "query": "login bug",
    "category": "bug",
    "limit": 5
  }
}
```

### 최신성 가중치 적용

```json
{
  "tool": "search",
  "arguments": {
    "query": "deployment",
    "recency_weight": 0.3,
    "limit": 5
  }
}
```

**recency_weight 설명:**
- `0.0`: 유사도만 고려 (기본값)
- `0.3`: 최신성 30% 반영
- `1.0`: 최신성 100% 반영 (최신 순 정렬)

### 컨텍스트 조회

```json
{
  "tool": "context",
  "arguments": {
    "memory_id": "abc123...",
    "depth": 1,
    "project_id": "my-app"
  }
}
```

**depth 설명:**
- `1`: 직접 연관된 메모리만 (빠름, 토큰 절약)
- `2`: 2단계 연관 메모리 (기본값)
- `3-5`: 더 넓은 컨텍스트 (느림, 토큰 많이 사용)

**응답 예시:**
```json
{
  "memory": {
    "id": "abc123...",
    "content": "Implemented user authentication with JWT tokens",
    "category": "task"
  },
  "related_memories": [
    {
      "id": "def456...",
      "content": "Added JWT token validation middleware",
      "similarity_score": 0.85
    }
  ]
}
```

### 통계 조회

```json
{
  "tool": "stats",
  "arguments": {
    "project_id": "my-app",
    "start_date": "2026-01-01",
    "end_date": "2026-01-31"
  }
}
```

**응답 예시:**
```json
{
  "total_memories": 150,
  "by_category": {
    "task": 80,
    "bug": 30,
    "decision": 20,
    "idea": 15,
    "code_snippet": 5
  },
  "by_project": {
    "my-app": 100,
    "other-project": 50
  }
}
```

---

## Work Tracking (Pins & Sessions)

### 세션 재개 (토큰 최적화)

```json
{
  "tool": "session_resume",
  "arguments": {
    "project_id": "my-app",
    "expand": false,
    "limit": 10
  }
}
```

**expand 설명:**
- `false`: 요약만 반환 (~100 tokens) ✅ 권장
- `true`: 전체 Pin 내용 반환 (~1000+ tokens)

**응답 예시 (expand=false):**
```json
{
  "session_id": "session-123",
  "project_id": "my-app",
  "status": "active",
  "pins_count": 5,
  "open_pins": 2,
  "completed_pins": 3,
  "started_at": "2026-01-20T09:00:00Z"
}
```

### Pin 추가 (작업 추적)

```json
{
  "tool": "pin_add",
  "arguments": {
    "content": "Fix login validation bug",
    "project_id": "my-app",
    "importance": 4,
    "tags": ["bug", "login", "validation"]
  }
}
```

**importance 가이드:**
- `5`: 긴급/중요 (아키텍처 결정, 중대 버그)
- `4`: 중요 (주요 기능, 중요 버그) → Memory 승격 권장
- `3`: 일반 작업 (기본값)
- `2`: 사소한 개선
- `1`: 매우 사소한 작업

**응답 예시:**
```json
{
  "id": "pin-abc123",
  "content": "Fix login validation bug",
  "project_id": "my-app",
  "importance": 4,
  "status": "open",
  "created_at": "2026-01-20T10:00:00Z"
}
```

### Pin 완료

```json
{
  "tool": "pin_complete",
  "arguments": {
    "pin_id": "pin-abc123"
  }
}
```

**응답 예시 (importance >= 4):**
```json
{
  "id": "pin-abc123",
  "status": "completed",
  "completed_at": "2026-01-20T11:30:00Z",
  "lead_time_hours": 1.5,
  "suggest_promotion": true,
  "promotion_message": "이 Pin의 중요도가 4점입니다. Memory로 승격하시겠습니까?"
}
```

### Pin을 Memory로 승격

```json
{
  "tool": "pin_promote",
  "arguments": {
    "pin_id": "pin-abc123"
  }
}
```

**응답 예시:**
```json
{
  "pin_id": "pin-abc123",
  "memory_id": "mem-xyz789",
  "message": "Pin이 영구 Memory로 승격되었습니다"
}
```

### 세션 종료

```json
{
  "tool": "session_end",
  "arguments": {
    "project_id": "my-app",
    "summary": "Fixed login bug and improved validation"
  }
}
```

**응답 예시:**
```json
{
  "session_id": "session-123",
  "project_id": "my-app",
  "status": "completed",
  "summary": "Fixed login bug and improved validation",
  "ended_at": "2026-01-20T12:00:00Z"
}
```

---

## 토큰 최적화 패턴

### 패턴 1: 세션 시작 (최소 토큰)

```json
// 1. 세션 요약만 로드 (~100 tokens)
{
  "tool": "session_resume",
  "arguments": {
    "project_id": "my-app",
    "expand": false
  }
}

// 2. 필요시에만 검색 (~200 tokens)
{
  "tool": "search",
  "arguments": {
    "query": "login bug",
    "limit": 3,
    "response_format": "compact"
  }
}
```

**총 토큰: ~300 tokens (vs 2000+ tokens 기존 방식)**

### 패턴 2: 작업 추적 (증분 저장)

```json
// 1. 작업 시작 시 Pin 생성
{
  "tool": "pin_add",
  "arguments": {
    "content": "Implement payment webhook",
    "project_id": "my-app",
    "importance": 4
  }
}

// 2. 작업 완료 시
{
  "tool": "pin_complete",
  "arguments": {
    "pin_id": "pin-abc123"
  }
}

// 3. 중요한 작업만 승격
{
  "tool": "pin_promote",
  "arguments": {
    "pin_id": "pin-abc123"
  }
}
```

**장점:**
- 실시간 작업 추적
- 중요한 것만 영구 저장
- 토큰 사용량 최소화

### 패턴 3: 점진적 컨텍스트 로딩

```json
// 1. 얕은 검색으로 시작
{
  "tool": "search",
  "arguments": {
    "query": "authentication",
    "limit": 2,
    "response_format": "compact"
  }
}

// 2. 관련성 있으면 컨텍스트 확장
{
  "tool": "context",
  "arguments": {
    "memory_id": "best-match-id",
    "depth": 1,
    "response_format": "compact"
  }
}

// 3. 필요시에만 depth 증가
{
  "tool": "context",
  "arguments": {
    "memory_id": "best-match-id",
    "depth": 2
  }
}
```

**토큰 절약: 60-70%**

### 패턴 4: 배치 작업

```json
{
  "tool": "batch_operations",
  "arguments": {
    "operations": [
      {
        "type": "add",
        "content": "Implemented user authentication",
        "category": "task",
        "tags": ["auth", "security"]
      },
      {
        "type": "add",
        "content": "Fixed login validation bug",
        "category": "bug",
        "tags": ["login", "validation"]
      },
      {
        "type": "search",
        "query": "authentication",
        "limit": 3
      }
    ]
  }
}
```

**장점:**
- 단일 요청으로 여러 작업 처리
- 임베딩 배치 생성으로 30-50% 토큰 절감
- 네트워크 오버헤드 감소

**토큰 절약: 30-50%**

### 패턴 5: 필터 활용

```json
// ❌ 나쁜 예: 필터 없음
{
  "tool": "search",
  "arguments": {
    "query": "bug"
  }
}
// → 모든 프로젝트의 모든 버그 반환 (1000+ results)

// ✅ 좋은 예: 필터 적용
{
  "tool": "search",
  "arguments": {
    "query": "login bug",
    "project_id": "my-app",
    "category": "bug",
    "limit": 3
  }
}
// → 관련 버그 3개만 반환
```

**토큰 절약: 80-90%**

---

## 실전 워크플로우 예제

### 예제 1: 버그 수정 세션

```json
// 1. 세션 시작
{"tool": "session_resume", "arguments": {"project_id": "my-app", "expand": false}}

// 2. 작업 시작
{"tool": "pin_add", "arguments": {
  "content": "Fix login validation bug",
  "project_id": "my-app",
  "importance": 4
}}

// 3. 관련 정보 검색
{"tool": "search", "arguments": {
  "query": "login validation",
  "category": "bug",
  "limit": 3
}}

// 4. 작업 완료
{"tool": "pin_complete", "arguments": {"pin_id": "pin-abc123"}}

// 5. Memory로 승격
{"tool": "pin_promote", "arguments": {"pin_id": "pin-abc123"}}

// 6. 세션 종료
{"tool": "session_end", "arguments": {
  "project_id": "my-app",
  "summary": "Fixed login validation bug"
}}
```

**총 토큰: ~500 tokens (vs 3000+ tokens 기존 방식)**

### 예제 2: 기능 개발 세션

```json
// 1. 세션 재개
{"tool": "session_resume", "arguments": {"project_id": "my-app", "expand": false}}

// 2. 이전 결정사항 확인
{"tool": "search", "arguments": {
  "query": "payment architecture",
  "category": "decision",
  "limit": 2
}}

// 3. 작업 시작
{"tool": "pin_add", "arguments": {
  "content": "Implement Stripe webhook handler",
  "project_id": "my-app",
  "importance": 4,
  "tags": ["payment", "stripe", "webhook"]
}}

// 4. 작업 완료 및 승격
{"tool": "pin_complete", "arguments": {"pin_id": "pin-xyz"}}
{"tool": "pin_promote", "arguments": {"pin_id": "pin-xyz"}}
```

---

## 성능 비교

| 방식 | 토큰 사용량 | 응답 시간 |
|------|------------|----------|
| 기존 (전체 로드) | ~5000 tokens | ~2초 |
| 최적화 (요약 + 필터) | ~500 tokens | ~0.3초 |
| **절감률** | **90%** | **85%** |

---

## 추가 팁

### 1. 캐시 활용
- 같은 쿼리는 재사용
- 세션 내에서 검색 결과 캐싱

### 2. 배치 작업
- 여러 메모리 추가 시 batch 사용 (구현 예정)

### 3. 카테고리 선택 가이드
- `task`: 일반 작업, TODO
- `bug`: 버그, 이슈
- `decision`: 아키텍처 결정, 중요 선택
- `idea`: 아이디어, 제안
- `code_snippet`: 코드 조각, 예제
- `incident`: 장애, 사고
- `git-history`: Git 커밋 히스토리

### 4. 태그 전략
- 구체적인 기술 스택: `["react", "typescript", "api"]`
- 기능 영역: `["auth", "payment", "notification"]`
- 우선순위: `["urgent", "important", "nice-to-have"]`

---

## 문제 해결

### Q: 검색 결과가 너무 많아요
**A:** `limit`를 줄이고 `project_id`, `category` 필터를 사용하세요.

### Q: 토큰을 더 절약하고 싶어요
**A:** 
1. `session_resume`에서 `expand=false` 사용
2. `context`에서 `depth=1`로 시작
3. `search`에서 `limit=3` 이하 사용

### Q: Pin과 Memory의 차이는?
**A:**
- **Pin**: 임시 작업 추적 (세션 단위)
- **Memory**: 영구 저장 (프로젝트 전체)
- importance >= 4인 Pin만 Memory로 승격 권장

### Q: 세션은 언제 종료하나요?
**A:** 
- 작업 완료 시
- 하루 작업 마무리 시
- 컨텍스트 전환 시 (다른 프로젝트로 이동)

---

**더 많은 정보:**
- [효율적인 MCP 프롬프트](./efficient-mcp-prompts.md)
- [컨텍스트 최적화](./context-optimization-prompt-compact.md)
