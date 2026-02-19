# mem-mesh Session Rules

> 상세: `docs/rules/all-tools-full.md`, `docs/rules/modules/pins.md`

## Session Lifecycle

```
session_resume → pin_add → [work] → pin_complete → (pin_promote) → session_end
```

### 1. Session Start
```
session_resume(project_id="<project>", expand=false, limit=10)
```
- `expand=false`: 요약만 (~90% 토큰 절약)
- 응답: pins_count, open_pins, completed_pins, token_info

### 2. Task Start
```
pin_add(content="<description>", project_id="<project>", importance=3, tags=[...])
```
- importance: 3=일반, 4=중요, 5=아키텍처

### 3. Task Complete
```
pin_complete(pin_id="<pin_id>")
```
- importance ≥ 4 → `pin_promote(pin_id)` 제안

### 4. Session End
```
session_end(project_id="<project>", summary="선택")
```
