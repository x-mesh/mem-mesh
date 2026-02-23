# mem-mesh Project Rules

> AI 메모리 관리 MCP 서버 — SQLite + sqlite-vec 기반 하이브리드 검색(벡터 + FTS5)

## Quick Reference

```bash
# Dev
python -m app.web --reload              # FastAPI + Dashboard (port 8000)
python -m app.mcp_stdio                 # FastMCP stdio 서버
python -m app.mcp_stdio_pure            # Pure MCP stdio 서버

# Test & Lint
python -m pytest tests/ -v
python -c "from app.web.app import app" # import check

# Production
uvicorn app.web.app:app --host 0.0.0.0 --port 8000
```

아키텍처, Golden Rules, Context Map 등 상세 규칙은 **[AGENTS.md](./AGENTS.md)** 참조.

---

## mem-mesh 도구 활용 규칙

이 프로젝트에는 `mem-mesh` MCP 서버가 연결되어 있다. 아래 규칙에 따라 작업 맥락을 관리한다.

### 원칙 1: 코딩 응답 우선

사용자의 코딩 요청에는 **코드와 답변을 먼저 출력**한다. mem-mesh 도구 호출은 답변 완료 후 수행한다. 응답 서두에 "메모리를 검색하겠습니다" 같은 안내를 넣지 않는다.

### 원칙 2: 세션 자동 복원

새 대화의 첫 응답 직후, `session_resume`을 호출하여 이전 맥락을 확인한다.

```
session_resume(project_id="mem-mesh", expand="smart")
```

- `expand="smart"` (권장): status × importance 4-Tier 매트릭스로 핀 반환
  - Tier 1: active + 중요(≥4) → 전체 content + tags + created_at
  - Tier 2: active + 일반(<4) → content 200자 + tags
  - Tier 3: completed + 중요 → content 80자
  - Tier 4: completed + 일반 → id + importance + status만
- `expand=false`: 모든 핀을 80자 요약으로 (최소 토큰)
- `expand=true`: 모든 핀 전체 내용 (토큰 많음)
- 미완료 핀이 있으면 사용자에게 간략히 알린다

### 원칙 3: 작업 추적은 Pin으로

진행 중인 작업은 **pin**으로 추적한다. 일반 메모리(`add`)로 저장하지 않는다.

| 시점 | 동작 | 비고 |
|------|------|------|
| 작업 시작 | `pin_add(content, project_id="mem-mesh", importance=3)` | 3: 일반, 4: 중요, 5: 아키텍처 |
| 작업 완료 | `pin_complete(pin_id)` | — |
| 중요 작업 완료 | `pin_complete` → `pin_promote` | importance >= 4일 때 영구 메모리로 승격 |

### 원칙 4: 영구 메모리는 선별적으로

아래 상황에서**만** `add`로 영구 저장한다. 일상적 작업 상태는 pin으로 충분하다.

| 카테고리 | 저장 시점 | 예시 |
|---------|---------|------|
| `decision` | 기술 스택, DB 스키마, 아키텍처 결정 합의 시 | "SQLite + sqlite-vec을 유일한 벡터 저장소로 확정" |
| `bug` | 복잡한 버그 원인과 해결책 도출 시 | "sqlite-vec INSERT OR REPLACE 금지 — DELETE+INSERT 필요" |
| `incident` | 시스템 장애 복구 후 | "포트 8000 충돌로 서버 이중 기동 발생" |
| `idea` | 향후 개선 아이디어 기록 시 | "한국어 검색에 E5 prefix encoding 적용 검토" |
| `code_snippet` | 재사용 가능한 패턴 발견 시 | batch_operations 사용 패턴 |

### 원칙 5: 맥락 검색 활용

사용자가 과거 결정, 이전 작업, 기존 설계를 언급하면 코드 작성 전에 `search`로 기존 맥락을 확인한다.

```
search(query="관련 키워드", project_id="mem-mesh", limit=5)
search(query="", category="decision", limit=5)          # 최근 결정 조회
search(query="검색어", recency_weight=0.3)               # 최신 결과 부스트
```

### 원칙 6: 세션 종료

사용자가 작업 완료를 명시하면("오늘 끝", "여기까지", "PR 올려줘" 등), 요청을 먼저 처리한 뒤 마지막에 세션을 마감한다.

```
session_end(project_id="mem-mesh")
```

### 원칙 7: 토큰 효율

여러 메모리 작업이 필요하면 `batch_operations`로 묶어 호출한다 (30-50% 토큰 절감).

```
batch_operations(operations=[
  {"type": "add", "content": "...", "project_id": "mem-mesh", "category": "decision"},
  {"type": "search", "query": "...", "limit": 5}
])
```

---

## 코딩 규칙

- **Python**: Black 포맷, 타입 힌트 필수, `any` 금지
- **Import 순서**: stdlib → third-party → local (절대 경로)
- **비동기**: 모든 DB/벡터 연산은 async/await
- **입력 검증**: Pydantic 스키마를 거친 후 서비스 호출
- **sqlite-vec**: `INSERT OR REPLACE` 금지 → DELETE + INSERT
- **버전 정보**: `app.core.version` 단일 소스
- **커밋 메시지**: `type: description` (feat, fix, refactor, docs, test, chore)
