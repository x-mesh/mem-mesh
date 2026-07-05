# prod 실측 운영 가이드 — enrichment 커버리지 & hook_events 축적

> A1(enrichment 커버리지) / A3(replay 데이터 축적량) 가정을 prod에서 검증하기 위한 운영 절차.
> 측정은 **읽기 전용 stats API**로만 수행하고, 커버리지가 낮으면 enrich 배치를 트리거한다.
> 실측 엔드포인트는 t2 구현(`app/web/dashboard/route_modules/stats.py`)을 그대로 문서화한 것이다.

---

## 1. 실측 API 호출 방법

### 1-1. 엔드포인트

| 목적 | Method / Path | 쿼리 파라미터 |
| --- | --- | --- |
| 커버리지·축적 실측 | `GET /api/stats/coverage` | `project_id`(선택, 미지정 시 전역 집계) |

- 라우터 마운트 경로: `route_modules/stats.py`의 `/stats/coverage` → 대시보드 라우터 prefix `/api` → 최종 `/api/stats/coverage`.
- 응답 스키마: `CoverageStatsResponse` (`app/core/schemas/responses.py`).

### 1-2. 인증

`/api/*`는 `web_auth_enabled`(미설정 시 `auth_enabled` 상속)가 켜져 있으면 인증이 필요하다. prod(네트워크 노출)에서는 인증이 켜져 있다고 가정한다.

- **프로그래밍 접근(curl 등): 정적 API 토큰 = hook token을 `Authorization: Bearer <token>`로 전달**한다. 이 토큰 하나가 hook / MCP / REST(`/api`)를 모두 인증한다 (`BearerTokenMiddleware`).
- 토큰 해석 우선순위 (`resolve_hook_token`, `app/core/config.py`):
  1. `MEM_MESH_HOOK_TOKEN` 환경변수 / `.env`
  2. `<data dir>/hook_token` (서버 관리 파일)
  3. `~/.mem-mesh/hook_token` (레거시 CLI 설치 경로)
- 브라우저 대시보드는 Basic Auth 세션(dual-auth)으로 접근하지만, 실측 자동화에는 Bearer 토큰을 쓴다.
- `auth_enabled=false`인 배포라면 토큰 없이도 접근 가능하지만, prod 노출 환경에서는 인증을 켜 둔 상태를 전제로 한다.

### 1-3. curl 예시

```bash
# 서버 주소와 토큰을 환경변수로 (토큰은 prod의 <data dir>/hook_token 또는 MEM_MESH_HOOK_TOKEN)
export MM_HOST="https://mem-mesh.example.com"
export MM_TOKEN="<hook_token>"

# 전역 커버리지·축적 실측
curl -s -H "Authorization: Bearer ${MM_TOKEN}" \
  "${MM_HOST}/api/stats/coverage" | jq .

# 특정 프로젝트만 집계
curl -s -H "Authorization: Bearer ${MM_TOKEN}" \
  "${MM_HOST}/api/stats/coverage?project_id=mem-mesh" | jq .
```

---

## 2. 응답 해석

`GET /api/stats/coverage` 응답은 `enrichment` / `hook_events` / `query_time_ms` 3개 블록이다.

```json
{
  "enrichment": {
    "total_memories": 150,
    "enriched_count": 120,
    "coverage_ratio": 0.8,
    "by_project": [
      { "project_id": "mem-mesh", "total": 60, "enriched": 55, "coverage_ratio": 0.9167 }
    ]
  },
  "hook_events": {
    "total_events": 4200,
    "prompt_events": 1800,
    "by_event": { "UserPromptSubmit": 1800, "SessionStart": 1200, "Stop": 1200 },
    "by_project": { "mem-mesh": 3000, "web-project": 1200 },
    "first_event_at": "2026-06-21T09:00:00Z",
    "last_event_at": "2026-07-05T18:30:00Z"
  },
  "query_time_ms": 12.3
}
```

### 2-1. enrichment 커버리지 (A1)

- `total_memories`: 전체 메모리 수. `enriched_count`: title이 채워진 메모리 수 (빈 문자열/공백 title은 미enriched로 계산).
- `coverage_ratio`: 전체 커버리지 = `enriched_count / total_memories` (0.0~1.0). **percent = ratio × 100**.
- `by_project[]`: 프로젝트별 `{total, enriched, coverage_ratio}`. 프로젝트별 편차를 보고 저커버리지 프로젝트를 특정한다.
- `memory_enrichment` 테이블이 아직 없어도 500이 나지 않고 `enriched_count=0`으로 보고된다(lazy 테이블).

### 2-2. hook_events 축적 (A3 = replay 데이터 신호)

- `total_events`: 총 hook 이벤트 수. `by_event`: 이벤트명별 분포(`UserPromptSubmit` / `SessionStart` / `Stop` 등).
- **`prompt_events`: prompt가 실제로 기록된 `UserPromptSubmit` 이벤트 수** — replay 가능한 프롬프트 데이터의 직접 신호다. 공백 prompt는 제외된다. (`by_event.UserPromptSubmit` ≥ `prompt_events`인 이유: 빈 prompt UserPromptSubmit도 by_event엔 포함되나 prompt_events엔 미포함.)
- `first_event_at` ~ `last_event_at`: 축적 **기간**. 이 구간 대비 `prompt_events` 수로 일평균 축적 속도를 어림한다.
- `by_project`: 프로젝트별 이벤트 분포.

> 실측 시 최소 기록: **전역 `coverage_ratio`(%), `enriched_count/total_memories`, `prompt_events`, `first_event_at`~`last_event_at`**. 필요하면 저커버리지 프로젝트를 `by_project`에서 뽑아 둔다.

---

## 3. 판단 기준과 후속 조치

### 3-1. 커버리지 낮음(예: `coverage_ratio` < 0.70) → enrich 배치 트리거

enrich는 프로젝트의 canonical 메모리마다 **비동기 per-memory job**을 큐에 넣는다(동기 LLM 루프 아님). 결과는 대시보드 AI enrichment 박스에 반영된다.

**엔드포인트**: `POST /api/maintenance/projects/{project_id}` (`route_modules/maintenance.py`)

**요청 바디** (`ProjectMaintenanceRequest`):

```json
{ "operations": ["enrich"], "force": false }
```

- `operations`: `"enrich"` / `"improve"` / `"reconcile"` 중 1개 이상. 커버리지 보충은 `["enrich"]`.
- **`force` 판단 기준**:
  - `force=false` (기본, 권장): 이미 enrichment가 있는 메모리는 **skip**하고 빈 것만 큐에 넣는다. 커버리지 갭 메우기에는 이것으로 충분.
  - `force=true`: 이미 enriched된 메모리까지 재큐잉(전체 title 재생성). 프롬프트/모델을 바꿔 **전량 재생성이 필요할 때만** 사용. 이미 완료된 메모리에도 LLM 호출 비용이 드므로 갭 메우기 목적에는 쓰지 않는다.

**호출 예시**:

```bash
# 커버리지 갭만 채우기 (권장)
curl -s -X POST -H "Authorization: Bearer ${MM_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"operations":["enrich"],"force":false}' \
  "${MM_HOST}/api/maintenance/projects/mem-mesh" | jq .
```

**응답** (`ProjectMaintenanceResponse`): `{project_id, enqueued:{enrich:N}, skipped:{enrich:M}, total_memories, reconcile}`.
- `enqueued.enrich`: 새로 큐에 넣은 수. `skipped.enrich`: 이미 완료됐거나 이미 큐에 있어 건너뛴 수. `total_memories`: 프로젝트 canonical 메모리 수.

**진행 상황 모니터링**: `GET /api/maintenance/status?project_id=<pid>`로 큐 상태 카운트를 폴링한다. 배치 후 커버리지 재측정은 `GET /api/stats/coverage`를 다시 호출해 `coverage_ratio` 상승을 확인한다.

### 3-2. replay 데이터 부족(예: `prompt_events` < 100) → M2b 연기

- `hook_events.prompt_events`가 100 미만이면 replay/재현 실험에 쓸 프롬프트 표본이 부족하다는 신호다.
- 이 경우 **M2b(replay 기반 후속 작업)를 연기**하고, hook 이벤트가 더 축적되기를 기다린다. `first_event_at`~`last_event_at` 기간과 일평균 축적 속도로 목표(예: 100 프롬프트) 도달 시점을 어림해 재측정 일정을 잡는다.

---

## 4. 결과 기록 절차

실측/결정 결과는 x-build decisions에 남긴다.

```bash
xm build decisions add \
  "prod 실측: enrichment 커버리지 N%, hook_events 총 X건 (prompt_events M건, 기간 YYYY-MM-DD~YYYY-MM-DD)" \
  --type measurement \
  --rationale "A1 검증: 커버리지 N%로 임계(70%) 상회/미달 → enrich 배치 실행/보류. A3 검증: prompt_events M건으로 M2b 진행/연기 판단."
```

- 저커버리지로 enrich를 돌렸다면 배치 응답(`enqueued`/`skipped`/`total_memories`)과 재측정 후 커버리지도 rationale에 함께 남긴다.

---

## 5. 주의 (L4 — 시스템 안정성)

- **측정은 읽기 전용 stats API(`GET /api/stats/coverage`, `GET /api/maintenance/status`)로만 수행한다.**
- **prod DB 파일에 직접 접근(sqlite3 등)하지 않는다.** 원본 오염·잠금 위험이 있다. DB 수준 확인이 꼭 필요하면 백업 복사본을 `mode=ro`로 열되, 본 가이드의 정규 절차는 API 호출뿐이다.
- 배포 자체(서버 기동/토큰 설정)는 운영자(사용자)가 수행한다. 이 문서는 호출·해석·후속 결정 절차만 규정한다.

---

## 6. 주입 포맷 replay 하네스 (M2b) — 구/신 포맷 A/B

> "세션 메모리는 효과 없음" 비판에 실증으로 답하는 오프라인 도구.
> `scripts/replay_injection_eval.py`. 실측은 **hook_events가 2주+ 축적된 뒤**(§2의 `prompt_events` 확인) 실행한다. null 결과면 주입 축소도 정당한 결론이라는 전제이므로, 비교가 공정해야 한다(동일 검색 결과에 구/신 포맷만 다르게 적용, judge blind A/B).

### 6-1. 무엇을 비교하나

- **구 포맷**: 레거시 훅의 `- [cat] (YYYY-MM-DD) content[:300]`(문장 무시 하드 절단) — 스크립트에 하드코딩 재현.
- **신 포맷**: 현행 `app.core.services.recall.render_memory_lines` 실경로(문장 경계 요약 + 나이·출처 메타).
- 표본: 실제 사용자 프롬프트(`hook_events_archive` + `hook_events`의 prompt 존재분, redact 재통과). 각 프롬프트에 동일 하이브리드 검색(threshold 0.75, limit 3)을 돌려 같은 결과를 두 포맷으로 렌더.
- **결정적 지표(LLM 불필요)**: 블록 토큰 수 추정, 라인당 문자 수, 문장 중간 절단 비율.
- **LLM judge(선택)**: 관련성·완결성·오도위험을 1–5로 blind A/B 채점(chat LLM 미설정 시 judge 스킵, 결정적 지표만 리포트).

### 6-2. 실행 방법 (반드시 prod 복사본 · 단일 · 백그라운드)

```bash
# 1) prod DB 복사본 생성 (원본 직접 열기 금지 — 스크립트가 live DB면 거부한다)
sqlite3 "$(python -c 'from app.core.config import get_settings; print(get_settings().database_path)')" \
  ".backup /tmp/replay_eval.db"

# 2) 단일 프로세스로 백그라운드 실행
nohup python -m scripts.replay_injection_eval \
  --db /tmp/replay_eval.db --project-id mem-mesh --samples 30 \
  --out /tmp/replay_out > /tmp/replay.log 2>&1 &

# 3) 완료 후 리포트 확인 (JSON + Markdown)
cat /tmp/replay_out/replay_*.md
```

- `--samples` 기본 30, 최대 50. `--seed`로 blind A/B 순서 재현 가능.
- judge를 켜려면 대시보드/설정에서 chat LLM(원격 API)을 구성해 둔다. 미설정이면 리포트의 `judge.enabled=false`, `llm=null`로 결정적 지표만 나온다.

### 6-3. 리포트 스키마 (필수 필드)

```
{
  "generated_at", "db_path", "project_id",
  "samples_requested", "prompts_collected", "samples_used",
  "search": { "threshold", "limit", "mode" },
  "judge":  { "enabled", "provider", "model", "scored", "skipped_reason" },
  "deterministic": {
    "old"/"new": { "lines", "avg_block_tokens", "avg_chars_per_line", "mid_sentence_cut_rate" },
    "delta_new_minus_old": { ... }
  },
  "llm":  null | { "n", "old", "new", "win_rate_new", "win_rate_old", "ties" },
  "recommendation": { "recalibrate_threshold", "recalibrate_recency", "notes": [ ... ] }
}
```

### 6-4. L 규칙 준수

- **L1/L2**: reranker 미로드, 임베딩 모델은 검색용 1개만. **L4**: `--db`가 `settings.database_path`와 같으면 거부, 복사본 마커 없는 파일명은 경고. **L5**: 단일 프로세스 · 백그라운드(위 `nohup ... &`).
- judge는 원격 API(ChatService)만 사용 — 로컬 대형 LLM 로드 없음.
- 스크립트는 **앱 코드를 수정하지 않고 재사용만** 한다. 결과는 §4 절차로 x-build decisions에 기록한다.
