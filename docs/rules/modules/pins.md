# Session Pins Rules — 세션 & 핀 관리

토큰 최적화된 세션 워크플로우와 핀 사용법.

---

## 세션 라이프사이클

```
session_resume → pin_add → [work] → pin_complete(promote=true) → session_end
```

---

## session_resume (토큰 최적화)

| 파라미터 | 권장값 | 효과 |
|----------|--------|------|
| `expand` | `false` | 요약만 로드, ~90% 토큰 절약 |
| `expand` | `"smart"` | 중요도×상태 기반 선택적 로드 (~60% 절약) |
| `expand` | `true` | 전체 핀 내용 로드 |
| `limit` | 10 | 반환할 핀 수 |

```
session_resume(project_id="my-app", expand="smart", limit=10)
```

- `expand=false`: pins_count, in_progress_pins, completed_pins 요약만
- `token_info`: loaded_tokens, unloaded_tokens, estimated_total
- **Stale 자동 정리**: in_progress 7일, open 30일 경과 → completed 자동 처리

---

## 핀 상태 (Pin Status)

```
open(계획됨, 미착수) → in_progress(작업 중, pin_add 기본값) → completed(완료)
```

- `pin_add` 호출 시 기본 상태는 `in_progress`
- 다단계 작업에서 나중 단계는 `open`으로 미리 등록 가능

---

## pin_add / pin_complete

```
pin_add(content="작업 설명", project_id="my-app", importance=3, tags=[...])
pin_complete(pin_id="...", promote=true)
```

- **importance**: 1~5 (3: 일반, 4: 중요, 5: 아키텍처)
- importance 생략 시 내용 기반 자동 추정
- **응답(compact)**: `{id, importance, status}` — 자동 추정 시 `auto_importance: true` 추가
- `pin_complete(promote=true)`: 완료 + 영구 메모리 승격을 한 번에 처리
- `pin_complete` 응답에 `suggest_promotion` 포함 (importance ≥ 4)

---

## pin_promote

- **importance ≥ 4**일 때 `pin_promote(pin_id)` 호출
- 이미 완료된 핀을 별도로 영구 메모리로 승격

---

## 클라이언트 감지

- **HTTP 모드**: MCP initialize 핸드셰이크 또는 User-Agent 헤더로 자동 감지 (25+ IDE/AI 플랫폼)
- **Stdio 모드**: `MEM_MESH_CLIENT` 환경변수 사용

---

## session_end

```
session_end(project_id="my-app", summary="선택적 요약")
```

- summary 생략 시 자동 생성
- 활성 세션이 없으면 `no_active_session` 반환
