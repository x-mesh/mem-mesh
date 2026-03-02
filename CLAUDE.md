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

아키텍처, Golden Rules, Context Map, API 상세는 **[AGENTS.md](./AGENTS.md)** 참조.

---

## mem-mesh 도구 Checklist

> 매 세션에서 아래 흐름을 따른다. 상세 API/예시는 [AGENTS.md § Session Context Management](./AGENTS.md) 참조.

```
1. 세션 시작  → session_resume(project_id, expand="smart")
2. 과거 맥락  → 이전 결정/작업 언급 시 search() 후 코딩
3. 작업 추적  → pin_add → pin_complete → (중요시 pin_promote)
4. 영구 저장  → decision / bug / incident / idea / code_snippet 만
5. 세션 종료  → 지식 보존 판단 + session_end()
6. 보안 금지  → API키 / 토큰 / 비밀번호 / PII 절대 저장 금지
```

---

## MUST (반드시

**M1. 세션 복원** — 새 대화의 첫 응답 직후 `session_resume` 호출. 미완료 핀이 있으면 사용자에게 알린다.

**M2. 세션 종료와 지식 보존** — 작업 완료 명시 시("오늘 끝", "PR 올려줘" 등), 요청 처리 후:
1. 영구 저장 가치 판단 (decision/bug/code_snippet → `add`, Pin → `pin_complete`/`pin_promote`)
2. `session_end`로 마감. 저장 시 **WHY 포함** 필수.

비정상 종료(사용자가 그냥 나감) 시 다음 세션의 `session_resume`이 미완료 Pin을 복원한다.

**M3. 영구 메모리 카테고리 제한** — `add`는 `decision` / `bug` / `incident` / `idea` / `code_snippet`에서만. 일상 작업은 pin. (`git-history` / `task`는 시스템 전용, 직접 사용 지양)

**M4. 보안** — API키, 토큰, PII, `.env` 내용 **절대 저장 금지**. 코드 스니펫의 민감 값은 `<REDACTED>`.

**M5. Stop hook 피드백 즉시 실행** — system-reminder에 `"mem-mesh에 저장하세요"` 또는 `mcp__mem-mesh__add` 지시가 포함되어 있으면, **사용자 메시지 처리 전에 반드시 해당 저장을 먼저 실행**한다. Stop hook은 대화 분석 후 저장이 필요하다고 판단한 것이므로, 이 지시를 무시하거나 뒤로 미루면 안 된다.

---

## SHOULD (권장)

**S1. 코딩 응답 우선** — 코드와 답변 먼저, mem-mesh 호출은 후. 단, 과거 맥락 언급 시 `search()` 후 코딩 (S2).

**S2. 맥락 검색** — 과거 결정/설계 언급 시 `search`로 확인 후 코딩.

**S3. Pin 추적** — 진행 중 작업은 `pin_add` → `pin_complete` → (importance ≥ 4 시 `pin_promote`).

**S4. 토큰 효율** — 여러 메모리 작업은 `batch_operations`로 묶기.

---

## MAY (선택)

- `recency_weight=0.3` 최신 부스트 / `category` 필터 / `link()` 관계 설정

---

## 코딩 규칙

- **Python**: Black 포맷, 타입 힌트 필수, `any` 금지
- **Import 순서**: stdlib → third-party → local (절대 경로)
- **비동기**: 모든 DB/벡터 연산은 async/await
- **입력 검증**: Pydantic 스키마를 거친 후 서비스 호출
- **sqlite-vec**: `INSERT OR REPLACE` 금지 → DELETE + INSERT
- **버전 정보**: `app.core.version` 단일 소스
- **커밋 메시지**: `type: description` (feat, fix, refactor, docs, test, chore)

> Hook이 bash로 직접 콘텐츠를 DB에 저장하지 않는다. Hook은 세션 라이프사이클(SessionStart)과 AI에게 저장 판단을 위임(prompt/followup)하는 용도로만 사용한다.
