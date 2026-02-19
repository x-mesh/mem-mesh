# Session Pins Rules — 세션 & 핀 관리

토큰 최적화된 세션 워크플로우와 핀 사용법.

---

## 세션 라이프사이클

```
session_resume → pin_add → [work] → pin_complete → (pin_promote) → session_end
```

---

## session_resume (토큰 최적화)

| 파라미터 | 권장값 | 효과 |
|----------|--------|------|
| `expand` | `false` | 요약만 로드, ~90% 토큰 절약 |
| `expand` | `true` | 전체 핀 내용 로드 |
| `limit` | 10 | 반환할 핀 수 |

```
session_resume(project_id="my-app", expand=false, limit=10)
```

- `expand=false`: pins_count, open_pins, completed_pins 요약만
- `token_info`: loaded_tokens, unloaded_tokens, estimated_total

---

## pin_add / pin_complete

```
pin_add(content="작업 설명", project_id="my-app", importance=3, tags=[...])
pin_complete(pin_id="...")
```

- **importance**: 1~5 (3: 일반, 4: 중요, 5: 아키텍처)
- importance 생략 시 자동 추정
- `pin_complete` 응답에 `suggest_promote` 포함

---

## pin_promote

- **importance ≥ 4**일 때 `pin_promote(pin_id)` 호출
- 핀 내용을 영구 메모리로 승격

---

## session_end

```
session_end(project_id="my-app", summary="선택적 요약")
```

- summary 생략 시 자동 생성
- 활성 세션이 없으면 `no_active_session` 반환
