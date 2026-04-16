# mem-mesh Session Rules

> 상세: `docs/rules/all-tools-full.md`, `docs/rules/modules/pins.md`

## Session Lifecycle

```
session_resume → pin_add → [work] → pin_complete(promote=true) → session_end
```

### 1. Session Start
```
session_resume(project_id="<project>", expand="smart", limit=10)
```
- `expand="smart"`: 중요도×상태 기반 선택적 로드 (~60% 토큰 절약)
- 응답: pins_count, in_progress_pins, completed_pins, token_info
- Stale 자동 정리: in_progress 7일, open 30일 경과 → completed

### 2. Task Start
```
pin_add(content="<description>", project_id="<project>", importance=3, tags=[...])
```
- importance: 3=일반, 4=중요, 5=아키텍처 (생략 시 자동 추정)
- 기본 상태: `in_progress`. 나중 단계는 `open`으로 미리 등록 가능
- 응답(compact): `{id, importance, status}`

### 3. Task Complete
```
pin_complete(pin_id="<pin_id>", promote=true)
```
- `promote=true`: 완료 + 영구 메모리 승격을 한 번에 처리
- importance ≥ 4 → `suggest_promotion` 제안 (promote 미사용 시)

### 4. Session End
```
session_end(project_id="<project>", summary="선택")
```
