# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.26.0] - 2026-07-05

**세션 메모리 실효성 강화(memory-effectiveness)** — "세션 기록 검색은 에이전트에 유용하지 않다"(12gramsofcarbon) 비판을 냉정 평가해, 주장 대신 계측으로 답하는 체계를 넣은 minor 릴리스. WHY: (1) 훅 주입 라인이 content[:300] 문장 중간 절단·나이/출처 미표시로 컨텍스트를 오염시켰고 LLM 미등록 사용자는 개선 경로가 없었다. (2) 주입된 memory_id가 어디에도 기록되지 않아 "메모리가 실제로 도움이 되는가"에 데이터로 답할 수 없었다(session_start 주석의 dead_ratio ~0.999 write-only sink). (3) 오래된/superseded 메모리가 무감쇠로 주입 후보에 경쟁했고 메모리에 수명 개념이 없었다. (4) 고가치 메모리가 버전 관리되는 문서로 승격될 경로가 없었다. 구현 후 cross-vendor 패널 리뷰(claude/codex/agy/cursor/kiro × security/logic)로 결함 8건(F1~F8)을 잡아 반영했다.

### Added
- **주입 포맷 3단 fallback + 나이·출처 표기** — 두 훅(session_start/user_prompt_submit)이 공유 포맷터를 경유해 `- [category] (나이 · enriched|extracted) title — abstract` 라인 생성. ① enrichment title/abstract → ② 구조 추출(마크다운 제목+첫 문장) → ③ 문장 경계 절단의 3단 fallback으로 **LLM 미등록 환경 포함 동일 동작**, 문장 중간 절단 0건. superseded(status!='canonical')·클라이언트 검증 stale 메모리는 주입 제외. `app/core/services/recall.py`, `app/web/dashboard/route_modules/hooks.py`, `app/core/services/unified_search.py`
- **주입 효용 계측(injection-tracking)** — 주입된 memory_id를 `injected_memories`(v12)에 세션·턴·경로별 기록하고, Stop 시점 결정적 휴리스틱(id 언급/키워드/활동, LLM 불필요)으로 utilized 판정(v13). `weekly_review`에 `injection_stats`(주입/판정/활용/방법별) 노출 + 존재하지 않는 `search_logs`를 조회하던 죽은 zero-result 코드를 `search_metrics` 기반으로 수리. `app/core/services/hook.py`, `app/mcp_common/tools.py`, `app/core/database/schema_migrator.py`
- **오프라인 replay 하네스** — 축적된 실제 프롬프트로 구/신 주입 포맷을 blind A/B 비교(결정적 지표 + 선택적 LLM judge, 순서 랜덤화). prod `.backup` 복사본 강제, L1~L5 체크리스트 헤더, LLM 미등록 시 결정적 지표만 부분 실행. 실측은 2주+ 데이터 축적 후 — **null 결과면 주입 축소도 유효한 결론**. `scripts/replay_injection_eval.py`
- **git anchors + stale 2단 게이트** — `add`/`pin_promote`에 optional `anchors`(commit_hash/file_paths/branch, 클라이언트가 `git rev-parse`로 수집·전달 — 서버는 git 접근 불가 확정). `report_anchor_status`로 클라이언트 검증 보고(v14 `stale_status`): 보고된 stale은 주입 제외(강신호), 미검증 90일+ anchor는 경고 표기(약신호). `app/core/services/memory.py`, `app/mcp_common/tools.py`
- **doc_proposal 문서 승격** — refine_proposal 패턴의 파일판 상태 머신(pending→approved→applied/rejected) + LLM 개정안 생성(미등록 시 승격 후보 목록만 — feature gate) + Curation diff 승인 UI + MCP 도구 2종(`doc_proposals`/`doc_proposal_applied`). **서버는 파일에 쓰지 않는다**(project_id→경로 매핑 부재 + Docker 미마운트) — 적용은 대상 저장소의 에이전트, 서버는 상태·diff 보관만. "메모리는 스테이징, git이 영구 계층". `app/core/services/doc_proposal.py`, `app/web/dashboard/route_modules/curation.py`, `app/web/static/js/pages/curation.js`
- **파생성 pre-check** — 대화 덤프(`Q:`/`A:` 페어, 턴 마커)·git 파생(diff/헌크/로그 나열) 콘텐츠를 write-time 순수 규칙으로 판별해 저장은 허용하되 improve 큐 자동 enqueue(동기 LLM 호출 없음 — L1/L5), `AddResponse.quality_hint`로 호출자에 안내. LLM 미등록 시 enqueue 스킵(큐 오염 방지). `app/core/services/quality_gate.py`, `app/core/services/memory.py`, `app/core/services/maintenance.py`
- **실측 API + 운영 가이드** — `GET /api/stats/coverage`: enrichment title 커버리지(전체/프로젝트별) + hook_events 축적 통계(archive 포함 `replay_prompts_total`). A1/A3 가정의 prod 실측 절차 문서화. `app/core/services/stats.py`, `app/web/dashboard/route_modules/stats.py`, `docs/ops-measure-coverage.md`
- **hook_events 보안·보존** — `_record()` 경로에 `redact_secrets` 적용(M4 — 기존엔 prompt 평문 저장), 14일 prune 전 `hook_events_archive`로 이동 보존 + 이동 시 방어적 재redact(소급 미적용 행 커버). `app/web/dashboard/route_modules/hooks.py`, `app/core/services/hook.py`

### Fixed
- **(cross-vendor 리뷰 F1~F8)** replay 검색 `project_id=None` 하드코딩으로 A/B 왜곡+타 프로젝트 유출(F1) · judge 전송 memory 블록 미redact — 4/5 벤더 독립 지적(F2) · coverage stats의 archive 미집계로 prune 직후 축적량 과소보고(F3) · FastMCP stdio에 doc_proposal 도구 2종 미등록(F4) · doc_proposal 소스 메모리 project 미스코프(F5) · anchors JSON 손상 시 context 조회 전체 실패 → tolerant parse(F6) · `report_anchor_status`에 anchorless 가드 부재+detail 로그 미redact(F7) · doc revision LLM 전송 전 file_content/메모리 블록 미redact(F8). 회귀 테스트 3건 신설. F9~F15(휴리스틱 정밀도·문장경계 엣지 등)는 later 백로그(l1~l7).

### Changed
- **PRODUCT.md 포지셔닝 재정의** — 방어 가능 코어 3축(세션 간 작업 상태 복원 / git에 남지 않는 지식 / 관측성·회고) 중심으로 전면 개정. "과거 세션 검색 = 코딩 성능 부스트" 주장은 계측 데이터 확보 전까지 유보(Empirical Stance: "포지셔닝은 측정을 따른다"), Honest Limits 명시. README 2종 정합. `PRODUCT.md`, `README.md`, `README.ko.md`

## [1.25.0] - 2026-07-02

**백그라운드 자동화(Overview 스케줄러)·전역 실시간 알림·분산 LLM 비용 절감(hub enrichment 재사용)·연합 검색**을 담은 minor 릴리스. WHY: (1) 프로젝트 Overview는 on-demand뿐이라 캐시가 stale로 방치됐다 — 워커가 주기적으로, 활동이 있는 프로젝트만 골라 갱신하게 한다. (2) 메모리 생성/삭제 알림이 페이지 의존적이라(WS는 정상인데 memories 페이지에서만 toast) "팝업이 안 뜬다"로 보였다 — 전역 알림 센터로 모든 페이지에서 받고 한곳에 모은다. (3) 개인 노드에서 이미 enrich한 메모리를 hub가 또 LLM으로 enrich해 공유 1건당 LLM 1회가 낭비됐다. (4) panel/review 실행 결과가 raw findings JSON 한 줄 blob으로 저장돼 읽을 수 없었다 — kiro/agy(클라이언트 셸)와 codex/claude(서버사이드) 두 저장 경로 모두에서 markdown으로 변환한다.

### Added
- **Overview 자동 갱신 스케줄러** — relay worker의 신규 `overview` task가 `overview_schedule`(프로젝트별 토글, Projects 페이지)에서 due+활동 있는 프로젝트를 골라 chat LLM으로 Overview를 재생성. idle 프로젝트는 스킵, 캐시가 fresh면 LLM 없이 시계만 전진, 실패는 격리·통계 기록 후 다음 주기 재시도. 생성 시 `overview_generated` 실시간 이벤트 발행. `app/core/services/overview.py`, `app/core/services/relay_worker.py`, `app/web/dashboard/route_modules/overview.py`, `app/cli/relay.py`, `app/web/static/js/pages/projects.js`, `app/web/static/js/pages/settings-page.js`
- **전역 실시간 알림 센터** — `<notification-center>`(body 1회 마운트)가 memory/pin/relay 이벤트 8종을 모든 페이지에서 toast + 좌하단 벨 패널(최근 100건 이력, unread 배지, WS 연결 상태 점)로 수집. 이벤트 도달 여부를 한곳에서 확인 가능(디버깅 뷰 겸용). 페이지 자체 toast는 제거(중복 방지). `app/web/static/js/components/notification-center.js`, `app/web/static/js/main.js`
- **연합 hub 검색** — 검색 스코프 local/hub/all로 개인 노드와 팀 hub를 함께 검색. `app/core/services/relay.py`, `app/web/static/js`
- **hub의 sender enrichment 재사용** — relay 공유 payload에 실려 온 개인 노드의 enrichment(`model='relay:sender-provided'`)가 있으면 hub item worker가 LLM 호출 없이 복사(embedding만 계산) — 공유 1건당 LLM 1회 절감. content 변경·강제 enrich는 기존대로 재실행. `app/core/services/relay.py`
- **findings JSON 저장의 markdown 변환** — panel/review 최종 응답이 `{"findings":[...]}` envelope이면 severity/file:line/claim/evidence markdown으로 저장. kiro/agy는 훅 셸(prompt v24)에서, codex/claude는 서버(`/api/hooks/claude/stop` → `_save_memory`)에서 변환 — 두 저장 경로 모두 커버. `app/cli/hooks/shell/kiro-stop.sh`, `app/web/dashboard/route_modules/hooks.py`
- **hook kill-trap 로깅** — 호스트가 훅을 죽였을 때(타임아웃/SIGTERM) `last_stage` breadcrumb을 남겨 "안 떴다 vs 중간에 죽었다"를 구분. `app/cli/hooks/hook_log.py`, shell 훅 전체

### Fixed
- **모바일 햄버거 메뉴 미동작** — 스크롤 hide용 transform이 걸린 헤더가 `position:fixed` 오버레이의 containing block이 되어 메뉴가 페이지 콘텐츠에 가려지고 탭이 뒤로 빠지던 문제. 오버레이를 body 직속으로 reparent. 실브라우저 E2E 검증. `app/web/static/js/components/chroma-header.js`
- **improve/enrich 후 화면 미갱신(F5 필요)** — raw fetch() 쓰기가 APIClient 영구 GET 캐시를 무효화하지 않아 reload가 stale 메모리를 반환하던 문제. enrich/refine-apply/dedup-apply/save-memory 4곳에서 캐시 클리어. `app/web/static/js/pages/memory-detail.js`, `app/web/static/js/components/chat-widget.js`
- **agy 저장 project 오귀속** — agy가 훅을 `~/.gemini/...`에서 spawn해 워크스페이스 미등록 실행이 전부 `config` 프로젝트로 저장되던 문제 → 워크스페이스 부재 시 `unknown`. 훅 저장 curl 타임아웃 5s→8s(배포 직후 유실 방지). `app/cli/hooks/shell/kiro-stop.sh`
- **overview_failed 통계 도달 불가** — 스케줄 실패가 `processed:False+error`로 반환되는데 worker가 processed를 먼저 검사해 실패 카운터가 0에 고정되던 문제(cross-vendor 리뷰). `app/core/services/relay_worker.py`
- **프로젝트 카드 상세 열기/Show More 동작** 수정. `app/web/static/js`

## [1.24.0] - 2026-07-02

**maintenance 배치의 신뢰성 회복(재시도·정확한 상태 표기·카드 진행률)과 id 기반 메모리 탐색**을 담은 minor 릴리스. WHY: (1) improve 배치에서 코드 펜스를 포함한 메모리가 LLM JSON 파싱에 결정적으로 실패해 dead_letter로 고착됐고, 재시도 수단이 없어 영구 방치됐다. 게다가 재시도 끝에 성공한 job에도 이전 에러가 남아 done 항목이 실패처럼 보였다(1.23.0 스크린샷 증상). (2) 배치 진행 상황을 보려면 Curation → Activity까지 가야 해서, 시작점인 Projects 카드에서 진행률이 보이지 않았다. (3) LLM 도구가 "mem-mesh f9732f1e"처럼 짧은 id로 메모리를 알려주는데 대시보드 검색(FTS/벡터)으로는 id를 찾을 수 없었다. 구현 후 cross-vendor 패널 리뷰(claude/codex/agy/cursor/kiro × security/logic)로 5건의 결함을 잡아 반영했다.

### Added
- **dead_letter 재시도** — `POST /api/maintenance/retry`(operation/project_id/job_id 스코프)로 dead_letter job을 pending으로 되돌려 워커가 자연 드레인. Curation Activity 워커 카드의 'Retry N failed' 일괄 버튼 + dead_letter 행 개별 retry 버튼. live(pending/processing) 중복이 있으면 해당 행은 제외(부분 unique 인덱스 `idx_maintenance_queue_live` 충돌 방지), 일괄 재시도는 중복 dead_letter 그룹당 최신 1건만 되돌린다. `app/core/services/maintenance.py`, `app/web/dashboard/route_modules/maintenance.py`, `app/web/static/js/pages/curation.js`
- **프로젝트 카드 배치 진행률** — 카드에 op별 진행 바(N/M done · K failed + Retry). `GET /api/maintenance/status?by_project=true`가 전 프로젝트 큐 카운트(reconcile 포함)를 한 요청으로 반환하고, 활성 job이 있을 때만 3초 재귀 폴링(active 0이면 자기 종료, 연속 5회 실패 시 포기). 진행률 영역 클릭(Retry 제외) 시 `/curation?tab=activity&filter=maintenance`로 이동해 문제를 바로 조사할 수 있다(curation 딥링크 `?tab=`/`?filter=` 신설). `app/web/static/js/pages/projects.js`, `app/web/static/js/pages/curation.js`
- **hex id로 메모리 검색** — 쿼리에 id 형태 토큰(8+ hex, UUID 부분/전체)이 있으면 id-prefix 직접 조회를 우선 수행(score 1.0), 미매치 시 일반 검색으로 폴백. "제안 저장 완료(mem-mesh f9732f1e)" 같은 도구 출력 문장을 통째로 붙여넣어도 동작. 메모리 상세 메타에 전체 ID 표시 + 클릭 복사. `app/core/services/unified_search.py`, `app/web/static/js/pages/memory-detail.js`

### Fixed
- **improve JSON 파싱 결정적 실패 (펜스 안의 펜스)** — 모델이 ```json으로 감싼 응답의 JSON 문자열 값 내부에 코드 펜스가 있으면 non-greedy 펜스 정규식이 조기 절단해 매 재시도가 실패 → 3회 후 dead_letter로 고착되던 문제. 파서를 후보 순차(raw → 펜스 추출 → 원본 텍스트 string-aware balanced salvage)로 재구성하고 `strict=False`로 문자열 내 literal 개행 허용. refine 프롬프트에 "no markdown fences" 명시. enrich/merge/overview/summary 동일 파서 공유. `app/core/services/relay_worker.py`, `app/core/services/chat.py`
- **done 오표기 (stale last_error)** — `_finish()`가 done 전환 시 `last_error`를 지우지 않아 재시도 끝에 성공한 job이 실패처럼 표시되던 문제. done/stale 시 클리어 + UI는 실패 상태(dead_letter, 재시도 대기)에서만 에러 표시(activity에 `attempts` 노출). `app/core/services/maintenance.py`, `app/core/services/curation.py`, `app/web/static/js/pages/curation.js`
- **파싱 실패 진단 불가** — "Could not parse ... as JSON"만 남던 last_error에 모델 출력 head 160자(secret redact)를 포함해 원인 추적 가능. `app/core/services/chat.py`
- **(리뷰) bulk retry unique 위반** — 같은 (memory, operation)에 dead_letter 2건이면 단일 UPDATE가 IntegrityError로 전체 롤백돼 0건 재큐잉되던 문제(재현 확인) → 그룹당 최신 1건만 전환. `app/core/services/maintenance.py`
- **(리뷰) 카드 폴링 이중 루프/영구 정지** — in-flight 중 start 호출이 idempotency 가드를 통과해 루프가 증식하던 문제(busy 플래그 추가), 첫 poll 일시 실패를 "활성 없음"으로 오판해 영구 정지하던 문제(연속 5회 실패까지 지속). `app/web/static/js/pages/projects.js`
- **(리뷰) curation 딥링크 셀렉터 인젝션** — URL 쿼리 값을 querySelector 문자열에 그대로 삽입해 조작값이 페이지 로드를 깨뜨릴 수 있던 문제 → dataset 값 JS 비교로 전환. `app/web/static/js/pages/curation.js`

## [1.23.0] - 2026-07-01

**프로젝트 Overview(LLM 서사 요약)**를 도입한 minor 릴리스. WHY: 프로젝트에 쌓인 메모리가 늘어날수록 "이 프로젝트가 지금 어떤 상태이고 무엇이 미결인가"를 한눈에 보기 어려웠다. 개별 메모리 enrich(title/abstract)는 있지만 프로젝트 전체를 관통하는 서사 요약이 없었다. 그래서 최근 20개 메모리를 한 번의 LLM 호출로 요약(summary/themes/recent_activity/open_issues/key_decisions)해 두 곳(Projects 카드 모달 · 메모리 상세 사이드바)에서 동일 렌더러로 노출하고, 입력 메모리의 source_hash로 stale을 감지해 on-demand 재생성한다.

### Added
- **프로젝트 Overview (LLM 요약)** — 프로젝트의 최근 20개 메모리를 한 번의 chat LLM 호출로 요약해 summary·themes·recent_activity·open_issues·key_decisions(소스 메모리 링크 포함)를 생성. Projects 페이지 카드의 `📋 Overview` 버튼(모달)과 메모리 상세 사이드바(Related Memories 위 패널)에서 공유 렌더러(`window.ProjectOverviewRender`)로 동일하게 표시. 결과는 `project_overview` 테이블에 캐시하고 입력 메모리의 source_hash로 stale 감지 후 on-demand 재생성. `app/core/services/overview.py`, `app/core/services/chat.py`, `app/web/dashboard/route_modules/overview.py`, `app/web/static/js/components/overview-render.js`, `app/web/static/js/pages/projects.js`, `app/web/static/js/pages/memory-detail.js`

### Fixed
- **Overview stale 오탐** — source_hash가 `id:content_hash`만 포함해 category-only 편집·enrichment(title/abstract) 갱신 시 cached overview가 fresh로 남던 문제를, 해시에 category+enrichment 필드를 포함해 해결. `app/core/services/overview.py`
- **Overview 생성 500 (no such table)** — `_gather_items`가 lazy 생성되는 `memory_enrichment`를 LEFT JOIN하는데 enrich를 한 번도 안 쓴 DB에선 테이블이 없어 500나던 것을, `ensure_schema`가 EnrichmentStore 스키마를 선행 보장하도록 수정(curation.py의 동일 JOIN 가드 패턴과 정합). `app/core/services/overview.py`
- **메모리 상세 단축키 리스너 누수** — `.bind(this)`로 매번 새 함수를 만들어 removeEventListener가 실패, 숫자키가 Settings 등 다른 페이지에서 페이지 이동을 유발하던 것을 stored bound handler + 입력 필드 포커스 가드로 해결. `app/web/static/js/pages/memory-detail.js`

### Changed
- **relay enricher temperature 노출** — 구조적 추출(enrich/digest/reconcile)의 출력 안정성을 위해 temperature를 0.2로 낮추고 파라미터화. `app/core/services/relay_worker.py`, `app/core/services/chat.py`

## [1.22.0] - 2026-07-01

**프로젝트 단위 일괄 지식 정리(maintenance)**를 도입하고, **relay 팀공유를 실사용 가능한 수준으로 완성**(identity 관리·토큰 검증·config hot-reload·enrichment 전파·sharing policy)한 minor 릴리스. WHY: (1) 지금까지 enrich/improve/reconcile은 메모리 하나씩만 가능해 프로젝트 전체를 한 번에 정리할 수 없었고, reconcile은 write-time(`create`)에만 걸려 있어 "reconcile 켜기 전부터 있던 메모리"는 영원히 비교되지 않았다. 그래서 프로젝트 단위로 큐에 적재해 백그라운드 워커가 페이싱 처리하는 maintenance 서브시스템을 얹는다(동기 LLM 루프 금지 — CLAUDE.md L1/L5). (2) relay가 hub에 붙긴 했지만 토큰이 맞는지 확인할 방법(도달성만 체크됨)·발급된 identity를 rotate/delete할 방법·대시보드에서 LLM 키를 바꿔도 워커 재시작 없이 반영할 방법이 없었고, 로컬 Enrich 결과(title/abstract)가 공유 시 전달되지 않았다. (3) 공유 가능 카테고리가 코드에 하드코딩돼 새 카테고리가 조용히 공유 불가로 굳었다. 이들을 실사용 관점에서 메운다.

### Added
- **프로젝트 단위 일괄 maintenance (enrich/improve/reconcile)** — Projects 페이지 각 프로젝트에서 Enrich(title/abstract 생성, content 불변)·Improve(content 재작성 제안, 승인 후에만 적용)·Reconcile(중복/모순 탐지, 사람 승인) 배치를 큐에 적재. enrich/improve는 relay 워커의 신규 `maintenance` task가 chat LLM으로 처리하고, reconcile은 기존 `reconcile_queue`를 재사용해 write-time에만 걸리던 탐지를 기존 메모리에 소급 실행한다. `app/core/services/maintenance.py`, `app/web/dashboard/route_modules/maintenance.py`, `app/web/static/js/pages/projects.js`, `app/cli/relay.py`
- **Improve 제안 리뷰 (Curation)** — 재작성 제안을 원본/제안 diff로 검토해 개별 승인(적용)/거부. content는 승인 시에만 변경(reconcile→curation과 동일한 human-gate). `app/web/static/js/pages/curation.js`, `app/web/dashboard/route_modules/maintenance.py`
- **Curation Activity 진행 대시보드** — 워커별(Enrichment/Digest/Reconcile/Maintenance enrich·improve) 진행률 바 + "N/M done" + 상태 카운트 + 처리된 메모리 id·제목·링크 + 3초 라이브 폴링 + 배치 취소(Cancel pending). `app/core/services/curation.py`, `app/web/static/js/pages/curation.js`
- **relay identity 관리** — hub identity 발급 토큰의 rotate(재발급)·delete(영구 제거, revoke와 별개). Hub Identities 패널 통합 + User ID 자동완성. `app/core/services/relay.py`, `app/web/dashboard/route_modules/relay.py`, `app/web/static/js/pages/relay.js`
- **relay 토큰 검증 (Check Hub)** — `/auth/check` 엔드포인트로 도달성뿐 아니라 토큰 유효성까지 검증하고, 성공 시 hub가 알려준 source_node_id 자동 동기화·저장. 검증된 토큰은 즉시 저장돼 리로드 후에도 재검증 가능. `app/core/services/relay.py`, `app/web/dashboard/route_modules/relay.py`, `app/web/static/js/pages/relay.js`
- **relay Sharing Policy** — 공유 가능 카테고리를 하드코딩 allowlist에서 denylist(`task`만 구조적 차단)로 전환하고, 실제 존재하는 카테고리를 동적 조회해 opt-out 토글 제공. 새 카테고리는 기본 공유 가능(fail-open). `app/core/services/relay.py`, `app/web/static/js/pages/relay.js`
- **로컬 enrichment relay 전파** — 대시보드 Enrich 결과(title/abstract/display_kind)를 relay share payload에 실어 hub가 자체 LLM 없이 표시하도록 전달. `app/core/services/relay.py`, `app/core/schemas/relay.py`
- **relay worker 디버그 로깅** — `-v`/`-d` 플래그(INFO/DEBUG) + 시작 시 설정 요약(active/waiting tasks) + task skip 사유. `app/cli/relay.py`, `app/cli/main.py`
- **메모리 멀티카테고리 검색 필터**. `app/web/static/js`

### Changed
- **relay worker config hot-reload** — 데몬이 매 사이클 LLM 키/hub 토큰/prompt_version을 워커 인스턴스에 in-place 갱신해, 대시보드 설정 변경이 프로세스 재시작 없이 다음 사이클에 반영된다(무거운 embedding/NLI 모델은 유지). `app/cli/relay.py`, `app/core/services/relay_worker.py`
- **manual share source_version 자동 파생** — 수동 Share가 auto-share와 동일하게 `memory.updated_at`(+enrichment 시각)에서 버전을 파생해, enrich/편집 후 재공유 시 `RelayIdempotencyConflict`(same key, different hash)를 방지. `app/core/services/relay.py`, `app/web/dashboard/route_modules/relay.py`
- **RelayKind 완화** — ingest `kind`를 Literal enum에서 길이 검증된 str로 넓혀 새 카테고리가 wire validation에서 막히지 않게 함. `app/core/schemas/relay.py`
- **Settings/Relay UX** — secret 필드(토큰/키) 저장 상태 배지, worker tasks에 `maintenance` 추가, prompt_version 필드 숨김, Source Node ID 읽기전용, Worker LLM 필드 순서 정리. `app/web/static/js/pages/settings-page.js`, `app/web/static/js/pages/relay.js`, `app/web/static/js/pages/security-page.js`

### Fixed
- **대시보드 메모리 목록 stale** — APIClient의 TTL 없는 GET 캐시가 외부 경로(MCP/hook/relay/다른 탭) 생성 메모리를 반영 못하던 것을 전역 WebSocket memory 이벤트에서 `/memories` 캐시 무효화로 해결. Activity/Improve 폴링도 GET 전 캐시 무효화. `app/web/static/js/main.js`, `app/web/static/js/pages/curation.js`
- **relay LLM JSON 파싱 복원력** — prose로 감싸인 LLM 응답에서 outermost balanced JSON을 salvage하고, refine의 `max_tokens`를 입력 크기에 맞춰 잘림을 방지. `app/core/services/relay_worker.py`, `app/core/services/chat.py`
- **memory-detail/settings 레이아웃·단축키 가드** 정리. `app/web/static/js/pages`

### Performance
- **프로젝트 reconcile 배치 최적화** — 메모리마다 `reconcile_queue` 전체 COUNT를 2번 하던 것을 `INSERT OR IGNORE` rowcount 기반으로 대체(2N COUNT + race 제거)하고, 양방향 중복 쌍(A→B/B→A)을 undirected로 dedup해 reconcile LLM 비용을 절반으로 줄임. `app/core/services/memory.py`

## [1.21.1] - 2026-06-30

v1.21.0의 **반쪽 발행을 복구**하는 patch. WHY: 1.21.0은 PyPI에는 정상 발행됐지만, Docker publish 워크플로의 Test gate(`pytest tests/`)가 테스트 회귀 3건으로 실패해 **이미지가 발행되지 못했다**(Build/Merge가 skip). 회귀는 chat output-language 기능 추가 과정에서 (1) chat-stream 테스트의 fake service가 실제 `ChatService`에 새로 생긴 `resolve_output_language`를 따라가지 못했고, (2) 에러 중앙화 테스트가 `ChatError` 계층 같은 2단계 상속(`ChatNotConfiguredError(ChatError)`)을 직접-base만 검사해 거부한 데서 비롯됐다. 아울러 ruff/isort/black lint 부채로 CI도 red였다. 기능 변경 없이 테스트·lint만 정리한다.

### Fixed
- **chat-stream 테스트 fake service 동기화** — `_FakeService`에 `resolve_output_language`를 추가해 실제 `ChatService` 인터페이스와 일치시킴(`test_chat_stream_*` 2건 복구). `tests/test_chat_stream_api.py`, `app/core/services/chat.py`
- **에러 상속 검증의 transitive 인정** — `test_all_errors_inherit_memmesh_error`가 직접 base만 보던 것을 상속 체인 재귀 탐색으로 바꿔, `ChatError`→`MemMeshError` 같은 2단계 계층을 허용. `RelayError` 계층과 동일 패턴인 chat 에러를 정당하게 통과시킨다. `tests/test_error_centralization.py`
- **CI lint 게이트 복구** — ruff F401 unused import 3건 제거(`memory.py`/`reconcile.py`/`test_chat_tools.py`)와 isort/black 포맷 정리로 `ruff`/`isort`/`black` 체크를 green으로 되돌림. `app/`, `tests/`

## [1.21.0] - 2026-06-30

대시보드에 **LLM chat assistant**를 본격 도입하고, enrichment LLM을 **multi-provider**로 확장하며, hook 설치를 **다중 IDE(Antigravity·agy·Kiro native·Cursor)**로 넓히는 minor 릴리스. WHY: (1) 그동안 메모리 검색·정제는 도구 호출로만 가능해, "이 메모리를 더 낫게 다듬어줘"·"이 대화를 메모리로 저장해줘" 같은 자연어 워크플로를 대시보드 안에서 직접 처리할 수 없었다. 그래서 tool-calling·streaming·floating widget을 갖춘 chat assistant(M0~M2)를 얹고, refine/enrich/save-as-memory/dedup을 approve 게이트와 함께 제공한다. (2) relay enrichment가 단일 벤더(Anthropic)에 묶여 있어 운영 환경별 모델 선택이 불가능했다 — provider 어댑터 + factory로 OpenAI 등으로 교체 가능하게 한다. (3) hook 설치가 Claude/Cursor/Kiro 중심이라 Antigravity·agy 등 신규 IDE에서 동작하지 않았고, project ID 해석이 IDE 경계에서 불안정했다 — hook input에서 workspace 경로를 추출하도록 resolver를 강화하고 설치/진단/제거 경로를 다중 IDE로 일반화한다. 아울러 LLM 출력 언어 설정, 중복 메모리 AI 병합(curation/reconcile), schema migrator 확장을 포함한다.

### Added
- **대시보드 LLM chat assistant (M0~M2)** — tool-calling·streaming·floating widget을 갖춘 채팅 어시스턴트. 페이지 컨텍스트 인식, enable 게이팅, 스트리밍 컨트롤을 포함한다. `app/web/dashboard/route_modules`, `app/web/static/js`
- **AI 메모리 정제/보강 워크플로** — refine(refine → diff → approve → apply), enrichment(title/abstract/tags), save-as-memory(summarize → approve → store), AI 기반 중복 병합(dedup). 모두 approve 게이트를 거친다. `app/core/services/curation.py`, `app/core/services/reconcile.py`, `app/web/dashboard/route_modules/curation.py`
- **multi-provider LLM 지원 (relay enrichment)** — relay enricher를 provider 추상화(Anthropic/OpenAI 어댑터 + factory)로 확장해 벤더 교체가 가능하다. `app/core/services/relay_worker.py`
- **다중 IDE hook 지원** — Antigravity·agy CLI·Kiro native·Cursor 설치/상태/진단/제거 경로 추가. hook input에서 workspace 경로를 추출해 IDE 경계를 넘어 project ID 해석을 안정화한다. atomic file write·legacy 마이그레이션 정리 포함. `app/cli/hooks/installer.py`, `app/cli/install_hooks.py`, `app/cli/hooks/doctor.py`, `app/cli/hooks/status.py`, `app/cli/project_identity.py`, `app/cli/hooks/shell/*.sh`
- **chat 출력 언어 설정** — chat/refine/enrich/digest의 LLM 출력 언어를 설정값으로 강제. 국문 설정 시 영문 출력되던 문제 해결. chat services 전반
- **`mem-mesh auth set-password`** — 서버 측 admin 비밀번호를 CLI에서 재설정. `app/cli`

### Changed
- **design token 통합 + enrichment UI 개선** — 대시보드 CSS/JS의 색상·스타일 토큰을 단일화하고 enrichment UI를 정비. `app/web/static/css/modules`, `app/web/static/js/pages`
- **docker-compose.dev.yml `.env` 구성화** — 개발용 compose 파라미터를 `.env`로 외부화.

### Fixed
- **schema migrator 확장** — 신규 컬럼/관계 타입 마이그레이션 경로 추가로 기존 DB 업그레이드 시 누락을 방지. `app/core/database/schema_migrator.py`, `app/core/database/models.py`, `app/core/schemas/relations.py`

### Tests
- **hook·CLI·설치 커버리지 확대** — multi-IDE hook 스크립트, hooks doctor/status, cursor/kiro/antigravity 설치 멱등성, uvx 엔트리포인트, frontend client badge에 대한 단위 테스트 추가. `tests/test_hook_scripts.py`, `tests/test_cli_diagnostics.py`, `tests/test_install_hooks_idempotency.py`, `tests/test_connect_install.py`, `tests/snapshots/*.sh`

## [1.20.0] - 2026-06-29

v1.19.0이 도입한 Relay 인프라(worker·API·CLI·fusion) 위에 **공유 UX와 continuous auto-share**를 본격적으로 얹는 minor 릴리스. WHY: 1.19.0에서 공유 진입점이 CLI·대시보드 일부에만 있어, 정작 메모리가 만들어지는 일상 워크플로(메모리 행·peek·batch·프로젝트 카드·상세 페이지)에서 한 번에 팀으로 보내기가 번거로웠다. 그래서 (1) 모든 메모리 표면에 share 진입점을 노출하고, (2) 프로젝트 단위로 "한 번 켜두면 새 메모리가 memory-write hook을 통해 자동으로 허브로 흐르는" continuous auto-share를 추가하며, (3) 공유 대상이 될 수 없는 kind는 버튼을 dim/notice 처리해 오발행을 막는다. 아울러 outbox/admin 등 부수효과 엔드포인트에 auth-or-loopback 게이트를 강제해 보안 최소선을 닫고, purge/schema 경로의 hot-loop 비용을 줄인다.

### Added
- **메모리 전 표면에서 relay share 노출** — 메모리 행·peek·batch 및 프로젝트 카드에서 직접 팀 허브로 공유하는 진입점을 추가. `app/web/static/js/pages`
- **프로젝트 단위 continuous auto-share** — 프로젝트 카드의 토글로 auto-share를 켜면 memory-write hook이 새 메모리를 지속적으로 허브에 push하고, 카드에 sync 상태를 표시한다. `app/web/static/js/pages/relay.js`, 대시보드 relay 라우팅
- **kind 기반 share 게이트 + 상세 페이지 team-share** — 공유 가능한 kind에만 share 버튼을 활성화하고(비공유 kind는 dim + notice), 메모리 상세 페이지에서도 team-share를 수행할 수 있게 했다.
- **top navigation에 Projects 링크** — 대시보드 상단 내비게이션에서 프로젝트 화면으로 바로 이동. `app/web`

### Changed
- **share 버튼 상시 노출** — 비공유 kind는 숨기는 대신 dim 처리 + 안내를 띄워, 왜 공유할 수 없는지 사용자가 알 수 있게 변경.
- **relay materialization이 원본 project 이름 보존** — 허브 projection을 개인 노드로 backfill할 때 client 측 node에서 원래 project 이름을 유지하도록 수정. `app/core/services/relay.py`
- **share 아이콘 클릭/배치 auto-share hook 정리** — share 아이콘 클릭 동작, batch auto-share hook, 관련 docstring을 정비.

### Fixed
- **outbox share 엔드포인트 인증 강제** — outbox share 엔드포인트가 auth 또는 loopback을 요구하도록 닫아, 무인증 외부 호출로 공유가 트리거되지 않게 했다. `app/web/dashboard/route_modules/relay.py`
- **destructive relay admin 엔드포인트 인증 강제** — purge·재시도 등 부수효과 admin 엔드포인트도 auth/loopback 게이트로 보호. `app/web/dashboard/route_modules/relay.py`

### Performance
- **ensure_schema를 DB connection별 memoize** — relay 스키마 보장을 연결 단위로 캐시해 매 호출 재실행을 제거. `app/core/services/relay.py`
- **purge 경로 hot-loop 정리** — vector-table lookup을 purge 루프 밖으로 hoist하고 memory delete를 배치 처리. `app/core/services/relay.py`

### Tests
- **delete fallback / dead-letter 커버리지** — relay delete fallback 경로와 item·aggregate dead-letter 처리에 대한 단위 테스트 추가. `tests/test_relay_*.py`

## [1.19.0] - 2026-06-25

개인 mem-mesh를 팀 단위로 연결하는 **Relay(공유) 레이어**를 도입하는 minor 릴리스. 부수적으로 프로젝트 식별을 중앙화하고, CLI 버전 배너·프롬프트 drift 가드를 추가한다. WHY: 팀원 각자가 축적한 개발 메모리(결정·버그·gotcha)를 팀 단위로 재사용하려면 노드 간 연결이 필요한데, P2P mesh는 8명 규모에서 N×N 신뢰·충돌·invalidation 비용이 과하다. 그래서 개인 N → 팀 허브 1의 **star topology**를 채택하고, 개인은 팀 공유분을 로컬 복제하지 않는 **view-only 소비자**로 두어 검색 시점에 허브 view를 live fetch + RRF 융합한다. write path는 LLM/임베딩 호출과 분리해 deterministic·low-latency를 유지하고, 정제는 SQLite 큐 + 비동기 워커로 밀어낸다(Postgres/Redis/Kafka 미도입, Golden Rule 준수). 설계 상세는 `docs/mem-mesh-relay-PRD.md`.

### Added
- **Relay 레이어 (worker + API + CLI + 대시보드)** — 개인 노드가 선택한 memory/project를 팀 허브로 push하고, 팀원이 federated search로 재사용한다. write path는 deterministic(LLM 없이 SQLite outbox에 raw event 저장 후 즉시 응답), 정제는 비동기 SQLite 큐 + 워커가 담당(텍스트는 `claude-sonnet-4-6`, 임베딩은 로컬 sentence-transformers). per-item enrichment는 검색 critical path, project digest는 bounded-stale 파생 view. idempotency는 `같은 key+payload=200 replay / 다른 payload=409 conflict`. `app/core/schemas/relay.py`, `app/core/services/relay.py`, `app/core/services/relay_worker.py`, `app/core/services/relay_fusion.py`, `app/web/dashboard/route_modules/relay.py`, `app/cli/relay.py`, `app/web/static/js/pages/relay.js`, `app/web/static/css/modules/relay.css`
- **Relay 보안 최소선 (opt-in + type-gate + secret guard)** — 공유는 명시적 opt-in이며, API key/token 등 high-confidence secret은 outbox 진입 전 차단/redaction한다. pin은 직접 동기화하지 않고 `pin_promote → memory`를 거친다.
- **Relay memory materialization** — 허브의 current projection을 개인 노드의 일반 memory로 backfill하는 CLI 명령·API·서비스. `app/core/services/relay.py`, 대시보드 버튼 UI
- **Realtime relay notifications** — relay ingestion/materialization 이벤트를 WebSocket으로 브로드캐스트해 대시보드가 실시간 갱신된다. `app/web` realtime 라우팅 + 프론트 핸들러
- **Dead-letter queue 관리** — admin overview에서 dead-letter 가시화, outbox/item/aggregate 큐의 dead-lettered job 재시도, 수신한 relay memory purge, relay-materialized memory 삭제 시 자동 sync 숨김. `app/web/dashboard/route_modules/relay.py`
- **Relay diagnostics + hub connectivity** — verbose worker 진단 모드(큐 상태 스냅샷·pending work 분석·config sourcing), hub reachability 체크, force requeue, worker config 파라미터. `app/cli/relay.py`
- **Stable project identity resolution** — git 기반 ad-hoc 감지를 중앙화한 `mem_mesh_project_id()`(env → git config → `.mem-mesh/project-id` 파일 → basename 순)와 `mem-mesh init` 명령. 모든 hook 스크립트·렌더러가 새 resolver를 사용. `app/cli/project_identity.py`, `tests/test_project_identity.py`
- **CLI version banner + `--version`** — 매 CLI run마다 stderr로 버전 배너 출력(`--json`/mcp 명령 제외)하고 `--version` 플래그 추가. `app/core/version`
- **Prompt content hash guard** — `PROMPT_CONTENT_HASH`를 drift 가드로 도입해, rule 콘텐츠 변경 시 `PROMPT_VERSION` bump를 강제(`test_prompt_rules.py`가 assert). 의도치 않은 rule drift를 차단. `tests/test_prompt_rules.py`
- **MCP approval tool 설정** — Codex TOML/JSON 엔트리에 MCP 도구별 approval mode 설정 지원. tool name 해석·TOML table segment 포매팅 헬퍼 포함. `app/cli/codex_config.py`
- **Relay/WebSocket 테스트 커버리지** — relay api/service/worker/fusion/cli 단위 테스트와 WebSocket live integration 테스트 추가. `tests/test_relay_*.py`, `tests/integration/test_websocket_live.py`

### Changed
- **session_start hook이 pin counts 직접 주입** — 세션 시작 시 `session_resume`를 호출하던 것을, hook이 pin 카운트를 컨텍스트에 직접 주입하도록 변경(round-trip 제거). `PROMPT_VERSION` 22→23. `app/cli/hooks/renderer.py`
- **toast 알림 shared utility로 리팩토링** — 대시보드 toast 알림을 공용 유틸리티로 통합하고 옵션·app instance·memory 생성 알림·error handler 연동을 정리. `app/web/static/js/pages`
- **hook 셸 스크립트 정합화** — 전 hook 셸 스크립트에 `set -euo pipefail`을 적용하고 신규 project identity resolver를 사용하도록 갱신. `app/cli/hooks/shell/*.sh`

## [1.18.2] - 2026-06-24

Hook stdout 노이즈를 제어하고, 토큰 SSOT 모델을 env 우선으로 일관화하며, `--yes` 비대화 onboarding의 auth 검증 갭을 닫는 patch 릴리스. WHY: (1) Codex/Claude/Cursor hook이 매 세션·프롬프트마다 mem-mesh 컨텍스트를 stdout으로 그대로 쏟아내 노이즈가 컸다. (2) 토큰의 단일 정본이 "`~/.mem-mesh/hook_token` 파일(Option 2)"로 표기돼 있었으나 실제 운영 정본은 `MEM_MESH_HOOK_TOKEN` env이고 파일은 materialized fallback이라, 진단 표면마다 설명이 어긋났다. (3) `--yes` 설치의 auth probe가 토큰 소스 `env`에만 걸려 있어, stale한 파일 토큰이면 401 hook이 조용히 설치되고(원래 이 플로우가 막으려던 함정), 비대화 모드인데도 401 재시도에서 `input()`을 호출했다.

### Added
- **Hook output mode (`compact` / `quiet` / `full`)** — 모든 hookSpecificOutput 계열 hook(session-start, user-prompt-submit, subagent-start, precompact + local·cursor variants)에 `HOOK_OUTPUT_MODE`를 도입. `compact`는 컨텍스트를 1200자로 절단, `quiet`는 stdout을 억제(mem-mesh 저장 payload는 유지), `full`은 기존 동작. CLI install 템플릿과 shell 스크립트 전반에 적용. `app/cli/hooks/renderer.py`, `app/cli/install_hooks.py`, `app/cli/hooks/shell/*.sh`
- **MCP 전용 서버 → 대시보드 실시간 알림 브리지** — MCP 전용 서버에는 in-process WebSocket 라우터가 없어 memory/pin 이벤트가 대시보드에 실시간 반영되지 않았다. `HttpNotifier`로 대시보드 서버에 이벤트를 전달하고, 알림 base URL을 `MEM_MESH_API_URL`→`api_base_url`→`localhost:port` 순으로 결정한다. `app/web/mcp/lifespan.py`, `tests/test_mcp_lifespan.py`

### Changed
- **토큰 SSOT 모델 env 우선으로 정합화** — 정본은 `MEM_MESH_HOOK_TOKEN` env, `~/.mem-mesh/hook_token`은 shell hook이 읽고 MCP config 스탬핑에 쓰이는 materialized fallback/cache로 명시. doctor/status/config 표면이 env→file→server-data 순으로 일관되게 상태와 drift를 표시한다. `app/cli/hooks/diagnostics.py`, `app/cli/system_doctor.py`, `app/cli/system_status.py`, `app/cli/hooks/status.py`, `app/cli/config_cmd.py`, `app/cli/main.py`
- **MCP install transport 보존** — `--yes` auto 모드에서 기존 엔트리의 transport(http/local)를 요청 mode와 달라도 무단 전환하지 않고 유지. `app/cli/mcp_config.py`
- **CORS origins 기본값/안내 명시** — `MEM_MESH_CORS_ORIGINS` 기본값을 localhost로 두고, 리버스 프록시 뒤 공개 도메인 설정 안내를 docker-compose에 추가. `docker-compose.yml`

### Fixed
- **onboarding `--yes` auth 검증 갭** — auth probe를 토큰 소스(env/file) 무관하게 실행하도록 검증 블록을 분기 밖으로 이동해, stale 파일 토큰으로 401 hook이 조용히 설치되던 문제를 해결. 아울러 `--yes` 비대화 모드에서는 401 시 `input()` 프롬프트 대신 즉시 fail-fast(`auth_blocked`)하도록 수정해 CI에서의 EOFError/행을 제거. `app/cli/onboarding.py`
- **`hook_output_mode` 입력 검증** — 알 수 없는 mode 값에 `ValueError`를 던져 오타가 조용히 통과하지 않도록 가드. `app/cli/hooks/renderer.py`
- **memory 삭제 전 조회 오류 처리** — 삭제 직전 memory 로드에 `service.get()`을 사용하고, 실패 시 로그를 error→warning으로 낮춰 정상 삭제 흐름을 방해하지 않도록 수정. `app/web/dashboard/route_modules/memories.py`

## [1.18.1] - 2026-06-24

1.18.0에서 유입된 회귀를 수정하는 patch 릴리스. `uvx mem-mesh` onboarding이 `ModuleNotFoundError: No module named 'httpx'`로 즉시 실패하던 문제를 해결한다. WHY: 1.18.0의 autoApprove SSOT 변경(`app/cli/mcp_config.py`가 `app.mcp_common.schemas`를 import)이 패키지 `__init__`의 eager `storage` import를 경유해 `core.storage.api`의 `httpx`까지 끌어왔고, base 의존성(httpx 미포함)으로 설치되는 `uvx mem-mesh` onboarding 경로가 import 시점에 깨졌다.

### Fixed
- **uvx onboarding httpx ModuleNotFoundError 회귀** — `app/mcp_common/__init__.py`를 PEP 562 lazy export(`__getattr__`)로 전환해 `StorageManager`/`MCPToolHandlers`를 실제 접근 시점에만 import. 가벼운 `schemas` import가 더는 `storage`→`httpx` 체인을 끌어오지 않아, httpx 없는 base 환경의 onboarding이 정상 동작한다. `app/mcp_common/__init__.py`

## [1.18.0] - 2026-06-24

mem-mesh의 **프롬프트/rules 시스템을 단일 정본으로 통합**하고, 적용 중인 rules를 대시보드에서 조회할 수 있게 노출한다. 부수적으로 HTTP hook에 인증 토큰을 조건부로 baking하고 신규 클라이언트를 지원한다. WHY: rules·prompt가 `all-tools-full.md`·`mem-mesh-ide-prompt.md`·`mem-mesh-mcp-guide.md`·`session-rules.md`와 8개 모듈로 흩어져 같은 규칙이 파일마다 제각각 드리프트했고, 사용자가 실제로 어떤 rules가 주입되는지 확인할 길이 없었다. 이를 `DEFAULT_PROMPT.md` + 핵심 모듈로 통합하고 API·settings 페이지로 노출해 정본화한다.

### Added
- **Rules 조회 API + UI** — `list_rules()`/`_resolve_rule_path()`로 적용 중인 rules를 노출하고, settings 페이지에서 모듈별로 펼쳐 볼 수 있게 했다. `app/web/dashboard/routes.py`, `app/web/static/js/pages/settings-page.js`, `tests/test_prompt_rules.py`
- **HTTP hook 토큰 조건부 baking** — 인증이 필요한 경우에만 HTTP hook 설치 시 Bearer 토큰을 리터럴로 baking. `app/web/dashboard/route_modules/connect.py`, `tests/test_connect_install.py`
- **신규 클라이언트 지원/색상** — 대시보드 client 색상 팔레트에 새 클라이언트(kiro 등)를 추가. `app/web/static/js/pages/dashboard.js`, `app/web/static/css/modules/dashboard.css`, `app/web/static/js/pages/connect-page.js`

### Changed
- **Rules/prompt 정본 통합** — `DEFAULT_PROMPT.md` 재작성 + `modules/{core,pins,search,relations,batch,memory-log,security}.md` 정비로 중복 규칙을 단일화. `render_rules_text`/`behaviors.py`(`CORE_RULES`)와 `index.json`을 통합 구조에 맞춰 정리하고 `PROMPT_VERSION`을 22로 상향(재설치 유도). `app/cli/prompts/behaviors.py`, `app/cli/prompts/renderers.py`, `app/web/rules/`
- README(ko/en) onboarding/rules 안내를 통합 구조로 갱신. `README.md`, `README.ko.md`

### Removed
- 중복·구식 rules 파일 정리 — `all-tools-full.md`, `mem-mesh-ide-prompt.md`, `mem-mesh-mcp-guide.md`, `mem-mesh-session-rules.md`, `modules/{api-usage,mcp-helper,minimal,quick-start,team-context}.md`를 삭제하고 정본 모듈로 흡수. `app/web/rules/`

## [1.17.0] - 2026-06-24

여러 AI 클라이언트(claude/cursor/codex/claude-desktop)에서 동시에 들어오는 hook 이벤트의 **출처 관측성**을 확보하고, mem-mesh를 **reverse proxy 뒤에 배포**할 수 있게 한다. WHY: (1) hook 이벤트가 어느 클라이언트·프로젝트에서 발생했는지 페이로드에 실리지 않아 대시보드에서 출처를 추적할 수 없었고, 빈/노이즈 이벤트가 메모리로 저장돼 코퍼스를 오염시켰다. (2) 프록시(nginx 등) 뒤에 두면 OAuth issuer가 내부 호스트(`127.0.0.1:8000`)로 잡혀 MCP 클라이언트의 인증 메타데이터가 외부 URL과 어긋났다. 이 릴리스는 셸 hook이 `project_id`를, 서버가 client/source를 이벤트에 태깅하고, `X-Forwarded-*` 헤더로 외부 origin을 해석한다.

### Added
- **Hook 이벤트 client/source/project 태깅** — 모든 셸 hook(`session-start.sh`/`stop.sh`/`post-tool-use.sh`/`user-prompt-submit.sh` 등)이 `PROJECT_DIR`(git toplevel basename)을 페이로드에 주입하고, `HookEventBase`에 client/source 필드를 추가해 대시보드가 출처별로 이벤트를 구분한다. `app/cli/hooks/shell/*.sh`, `app/core/schemas/hooks.py`, `app/web/dashboard/route_modules/hooks.py`
- **`mem-mesh hooks rules` 커맨드** — 프로젝트 rules(managed block)를 렌더·동기화하는 CLI 서브커맨드. `render_claude_project_rules`/`render_rules_text` 기반. `app/cli/main.py`, `app/cli/install_hooks.py`(`cmd_sync_project`), `tests/test_prompt_rules.py`
- **Reverse proxy issuer origin resolution** — OAuth 메타데이터/클라이언트 등록이 `X-Forwarded-*` 헤더로 외부 origin을 해석해, 프록시 뒤 배포에서도 issuer/endpoint URL이 외부에서 접근 가능한 주소로 발급된다. `app/web/oauth/routes.py`
- **HTTP MCP 클라이언트 자동 감지** — `streamable_http` 요청에서 client를 추론(`_detect_client_from_request`)해 세션에 기록. `app/web/mcp/sse.py`
- **대시보드 live memory 캐시 + 필터링** — 실시간 메모리 목록 캐시와 필터 UI. `app/web/static/js/pages/dashboard.js`

### Changed
- **MCP config/auth 핸들링 리팩토링** — `generate_mcp_entry`/`run_mcp_setup` 정리, claude-desktop 엔드포인트를 `mcp-remote` 프록시로 지원, codex client 정규화 및 null secret 생략, MCP approve 목록을 도구 스키마에서 도출. `app/cli/mcp_config.py`, `app/cli/codex_config.py`, `app/web/dashboard/route_modules/connect.py`
- **Hook 노이즈 필터링** — 빈/노이즈 이벤트(`_is_noise`)를 메모리 저장 전에 걸러 코퍼스 오염 차단. `app/web/dashboard/route_modules/hooks.py`
- **Prompt rules / PROMPT_VERSION bump** — Pin Gate·CORE_RULES 문구 정비로 `PROMPT_VERSION`을 21로 상향(재설치 유도). `app/cli/prompts/behaviors.py`

### Fixed
- **security auth endpoint/method 정정** — 잘못된 인증 엔드포인트·HTTP 메서드를 수정. `app/web/oauth/routes.py`, `app/cli/system_doctor.py`
- **HTTP 저장 경로 secret 마스킹 검증** — hook 저장 시 민감 값 redaction이 영속화 전에 적용되는지 회귀 테스트 추가. `tests/test_hook_consistency.py`

## [1.16.0] - 2026-06-24

설정 모델을 **"파일 정본 + 리터럴 분배"**로 확정한다 — 환경변수(`MEM_MESH_API_URL`/`MEM_MESH_HOOK_TOKEN`)를 **완전히 제거**하고, `~/.mem-mesh/{api_url,hook_token}` 파일을 단일 정본으로 두고 mem-mesh CLI가 각 AI 툴(claude/cursor/kiro/codex/…) 설정에 실제 값을 **리터럴로 직접 박는다**. WHY: 1.15.0의 "파일 SSOT"가 MCP/HTTP 인증과 구조적으로 충돌했다 — MCP 클라이언트는 토큰을 헤더의 `${ENV}` 치환(또는 리터럴)으로만 받아 파일을 못 읽고, 셸 env에 의존하면 GUI 앱(launchd, env 미상속)에서 깨지며 env가 파일을 shadow하는 추적 어려운 상태("설정은 localhost인데 hook은 옛 원격으로 401")가 반복됐다. env를 빼고 mem-mesh가 정본 파일에서 각 툴에 리터럴을 stamp하면 그 모든 문제가 사라진다(토큰 평문이 각 설정 파일에 박히는 것은 수용된 트레이드오프).

### Added
- **doctor 옵션2 진단** — `[SSOT]`(파일 정본 + 각 툴의 stamped 리터럴), `[Config Conflicts]`(툴 리터럴 vs 파일 정본 stale + 잔존 env 경고), 헤더의 `${ENV}` 참조를 무조건 결함으로 검출하고 `mem-mesh mcp config --auth` 재-stamp를 안내. `_file_canonical_token()`/`_entry_literal_token()` 헬퍼 신설. `app/cli/system_doctor.py`
- **Codex `http_headers` 리터럴** — Codex는 inline `bearer_token`을 지원하지 않아 `[mcp_servers.mem-mesh.http_headers]`의 리터럴 `Authorization`으로 토큰을 baking. `app/cli/codex_config.py`

### Changed
- **환경변수 완전 제거 → 파일 정본 + 리터럴 분배** — MCP 헤더(`mcp_config.py`/`connect.py`)와 HTTP hook 헤더(`install_hooks.py`)가 `Bearer ${MEM_MESH_HOOK_TOKEN}` 참조 대신 리터럴 토큰을 박고 `allowedEnvVars`를 제거. `mem-mesh mcp config --token/--auth`가 토큰을 각 툴 설정에 리터럴로 stamp.
- **hook `.sh` env 참조 제거** — `${MEM_MESH_*:-$(cat ...)}` → `$(cat ~/.mem-mesh/...)` 직접. 잔존 env가 파일을 shadow하던 핵심 버그를 차단. `PROMPT_VERSION` bump로 재설치 유도. `app/cli/hooks/shell/*.sh`, `app/cli/hooks/status.py`
- **`setup-token` 명령 제거** — 셸 env 다리가 불필요해져 `token_setup.py` 모듈과 CLI 서브커맨드를 삭제. 토큰 파일 보장은 `_ensure_hook_token`이 담당. `app/cli/hooks/token_setup.py`(삭제), `main.py`, `onboarding.py`
- 대시보드 안내(settings/security/connect 페이지)를 "`MEM_MESH_HOOK_TOKEN` env export" → "각 툴 설정에 리터럴 baking"으로 정정. `app/web/dashboard/route_modules/security.py`, `app/web/static/js/pages/*.js`

### Fixed
- **doctor 거짓양성** — `${MEM_MESH_HOOK_TOKEN}` 참조 헤더를 healthy로 통과시켜 "doctor는 healthy인데 클라이언트는 연결 실패"가 숨던 모순을 결함으로 격상.
- **codex install idempotency** — `_install_codex`가 토큰 생성(`_ensure_hook_token`)보다 먼저 헤더를 stamp해 첫 install에서 헤더가 누락되고 재실행 시 달라지던 버그.
- **테스트 격리** — `get_settings`의 `_settings` 싱글톤이 테스트 간 `MEM_MESH_*` env를 캐시해 다음 테스트로 새던(예: 토큰 헤더에 ENV-SHADOW가 박힘) 누수를 conftest에서 매 테스트 리셋. `tests/conftest.py`

## [1.15.0] - 2026-06-24

mem-mesh 연결 설정(`api_url` + `hook_token`)을 **단일 출처(SSOT)** 로 정리하고, 어디에 설정이 흩어져 있고 무엇이 무엇을 덮어쓰는지 보이지 않아 401 디버깅이 길어지던 문제를 구조적으로 막는다. WHY: env(`MEM_MESH_API_URL`/settings.json/셸)가 파일·CLI 인자를 조용히 override(silent shadowing)하면서, "설정은 했는데 동작 안 함"·"설치는 됐는데 401" 같은 추적 어려운 상태가 반복됐다. 이제 `~/.mem-mesh/{api_url,hook_token}` 파일이 GUI·터미널 실행 모든 도구의 공통 출처가 되고, install/doctor가 이를 명시·검증·fail-fast 처리한다.

### Added
- **Config SSOT** — `~/.mem-mesh/api_url`·`~/.mem-mesh/hook_token`을 모든 도구 hook이 읽는 정식 단일 출처로 확정. install 시 `_ensure_api_url()`이 URL 파일도 기록(기존엔 token만 기록)하고, `_write_hook_token()`으로 명시 토큰을 저장한다. `app/cli/install_hooks.py`
- **인터랙티브 install** — `mem-mesh install`이 API URL과 hook token을 현재값을 기본으로 채운 프롬프트로 받고(Enter로 유지·표시), 설치 *전에* 서버 인증을 테스트한다. 401이면 토큰을 최대 5회 재입력받고, 끝내 인증 실패면 hook 설치를 건너뛴다(설치-후-401 방지). `app/cli/onboarding.py`
- **doctor 진단 강화** — `[SSOT]`(정본 파일 값·active/shadowed), `[Config Conflicts]`(우선순위 체인에서 가려진 값 surface), MCP↔hook URL 불일치 경고를 추가. `app/cli/system_doctor.py`
- **`mcp config --token`** + `--url`이 hook URL SSOT(`~/.mem-mesh/api_url`)도 함께 기록 — MCP와 hook이 한 서버를 가리키도록 통일. `app/cli/main.py`, `app/cli/mcp_config.py`
- **`MEM_MESH_HOOK_LOG`** opt-in 셸 hook 관측성(레벨 1/2) — hook이 실제 fired/sent/exit됐는지 `~/.mem-mesh/hooks.log`로 추적. `app/cli/hooks/hook_log.py`
- `mcp clean`(프로젝트 override 정리)·`restore`(백업 복구) 커맨드, verbose 모드 MCP 엔트리 `file:line` 표시, 3-state API probe(auth gate vs 네트워크 구분). `app/cli/mcp_clean.py`, `app/cli/hooks/diagnostics.py`

### Changed
- **`mcp config --url` 우선순위 수정** — 명시적 `--url` 인자가 `MEM_MESH_API_URL` env보다 우선(기존엔 env가 인자를 silent override). `app/cli/mcp_config.py`
- **`setup-token` 토큰 전용화** — rc에 토큰만 파일-source로 export하고, `--api-url`은 env 리터럴 대신 `~/.mem-mesh/api_url`(SSOT)에 기록. `app/cli/hooks/token_setup.py`
- README onboarding 안내를 env var 중심에서 파일 SSOT 중심으로 재정리. `README.md`

### Fixed
- `test_hook_logging` 격리 버그 — 테스트가 `HOME`만 격리하고 실제 `MEM_MESH_HOOK_TOKEN` env를 상속해 `auth=absent` 단언이 토큰 있는 환경에서 깨지던 문제(`_base_env` 헬퍼로 제어 변수 제거). `tests/test_hook_logging.py`

## [1.14.0] - 2026-06-23

세션 시작 시 저장된 메모리가 거의 재호출되지 않던(운영 dead_ratio ≈0.999) 읽기 격차를 메운다 — `session_resume`/`SessionStart`가 그동안 pins만 반환했으나, 이제 열린 작업과 관련된 큐레이션 메모리를 자동으로 surface한다.

### Added
- 세션 재개 시 관련 메모리 자동 surface — `SessionStart` 훅과 `session_resume` MCP 툴이 열린 pin 맥락을 쿼리로 큐레이션 메모리(`decision`/`code_snippet`/`incident`)를 검색해 컨텍스트에 함께 노출한다. 공유 헬퍼는 **read-only**로 동작해(`search(record_access=False)`) `access_count`를 올리지 않는다 — 자동 surface가 recall 지표를 부풀리면 안 되기 때문이며, 실제 recall은 에이전트가 직접 `search`할 때만 집계된다. WHY: 운영 분석 결과 17k+ 메모리의 ~99.9%가 한 번도 재호출되지 않았다. 정규 세션 루프가 `SessionContext`에 pins만 담아 memories 테이블을 전혀 읽지 않아 코퍼스가 "쓰기 전용 싱크"로 전락한 것이 원인이었다. `app/core/services/recall.py`, `app/web/dashboard/route_modules/hooks.py`, `app/mcp_common/tools.py`
- `UnifiedSearchService.search`에 `record_access` 플래그(기본 `True`) — `False`면 `_record_access`를 건너뛰어 read-only 검색이 가능하다. surface 경로가 이를 사용한다. `app/core/services/unified_search.py`
- `SessionContext.relevant_memories` 필드 — surface된 메모리(`id`/`category`/`content`/`created_at`/`score`)를 담아 MCP·HTTP 응답에 함께 반환한다. `app/core/schemas/sessions.py`

### Fixed
- `/api/system/info`의 `db_size_bytes`가 컨테이너에서 항상 `0`으로 보고되던 문제 — 비정규 환경변수(`MEM_MESH_DB_PATH`)를 읽고 존재하지 않는 상대 경로 기본값(`data/mem_mesh.db`)으로 폴백했다. 정규 `get_settings().database_path`(절대 경로, `MEM_MESH_DATABASE_PATH` 존중)를 사용하도록 수정. `app/web/dashboard/routes.py`
- `RelationService.auto_link_similar`의 잠복 `AttributeError` — 존재하지 않는 `self.get_or_create_relation`을 호출하고 있었다(실제 메서드: `find_or_create_relation`). 호출처가 없어 표면화되지 않았으나 쓰기 경로에 자동 링크를 배선하는 순간 터질 버그였다. `app/core/services/relation.py`

## [1.13.1] - 2026-06-23

`uvx mem-mesh` 단일 진입점 온보딩 + 에이전트용 `--json` 출력. 두 환경변수(`MEM_MESH_API_URL`·`MEM_MESH_HOOK_TOKEN`)로 온보딩을 비대화 구동 가능.

> 참고: 1.13.0은 `git-kit ship`이 version bump 없이 tag-only로 발행돼(pyproject가 1.12.1에 머묾) PyPI publish가 `skip-existing`으로 no-op 처리됐다 — 동일 코드가 PyPI에 올라가지 않았다. 본 1.13.1이 pyproject·태그·PyPI를 정렬해 1.13.0의 내용을 실제 발행한다. (Docker `xmesh/mem-mesh:1.13.0` 이미지는 git 태그 기반이라 발행됐으나 내부 `__VERSION__`은 1.12.1이었다.)

### Added
- `uvx mem-mesh`(서브커맨드 없음) 온보딩 진입점 — `--from "mem-mesh[server]"` 없이 base 패키지만으로 온보딩 마법사를 구동한다(설치 경로는 server extra 불필요; 작성되는 MCP config는 런타임용으로 계속 `[server]`를 가리킨다). TTY면 대화형, 비-TTY(파이프/에이전트)면 자동 비대화로 프롬프트가 멈추지 않는다. WHY: 기존 `uvx --from "mem-mesh[server]" mem-mesh install`이 길고, LLM 에이전트가 떨굴 파일 없이 한 줄로 온보딩할 진입점이 필요했다. `app/cli/main.py`
- 온보딩 `--json` 머신 출력 — `mem-mesh --json` / `mem-mesh install --json`이 단계별 상태(server/hooks/mcp/hook_token) + `next_actions` + `errors`를 단일 JSON으로 emit하고 종료코드로 성공/실패를 알린다(`--json`은 비대화 함의). 사람용 진행 출력은 redirect로 억제해 stdout을 깨끗한 JSON 1건으로 유지. `app/cli/onboarding.py`
- 온보딩이 `MEM_MESH_HOOK_TOKEN`을 감지·표시 — env export / file-only(`~/.mem-mesh/hook_token`) / none을 구분해 출력하고(시크릿 값은 비노출), file-only일 때만 `mem-mesh hooks setup-token` 안내를 `next_actions`에 추가한다. `MEM_MESH_API_URL`은 기존대로 기본값으로 사용하고 출처를 출력한다. WHY: 두 환경변수로 온보딩을 비대화 구성하려면 토큰 상태가 보여야 했는데, 기존 온보딩은 토큰을 조용히 파일로만 생성했다. `app/cli/onboarding.py`

### Changed
- `run_mcp_setup`이 `None` 대신 구조화 요약 dict(`status`·`mode`·`detected_tools`·`configured`·`verification`)를 반환(순수 additive, 기존 출력 유지) — 온보딩 `--json`의 `steps.mcp`를 채운다. `app/cli/mcp_config.py`
- README 온보딩 명령을 `uvx mem-mesh`로 단축하고 에이전트/CI용 `--json` + 두 환경변수 사용법을 문서화. `serve`/MCP 런타임의 `mem-mesh[server]` extra 표기는 유지. `README.md`

## [1.12.1] - 2026-06-23

웹 대시보드 버그 수정 — Security 페이지에서 admin 비밀번호 입력 중 onboarding으로 강제 이동되던 문제.

### Fixed
- `checkEmbeddingStatus()`가 임베딩 모델이 준비되지 않았을 때(`not_loaded`·`error`·timeout) `router.navigate('/onboarding')`로 현재 페이지를 교체하면서, Security 페이지(`/security`)에서 admin 비밀번호를 입력하던 사용자가 onboarding으로 튕겨 입력이 소실되던 문제. 예외 경로가 `/onboarding` 하나뿐이었다. WHY: v1.12.0의 기본 임베딩 모델 전환(KURE → arctic)으로 모델이 로딩/마이그레이션 상태가 되자 이 모델-상태 폴링이 활성화돼 표면화됐다. 보호 경로 목록(`/onboarding`, `/security`)을 두어 해당 페이지에 있는 동안에는 redirect를 억제하되, 폴링은 3초 간격으로 유지해 사용자가 페이지를 떠나면 모델 미준비 안내가 정상 재개되도록 했다. `app/web/static/js/main.js`

## [1.12.0] - 2026-06-23

기본 임베딩 모델을 한국어 검색 SOTA급인 `dragonkue/snowflake-arctic-embed-l-v2.0-ko`로 전환 — 신규 설치·온보딩 추천이 KURE-v1 대신 arctic-ko를 기본으로 사용한다.

### Changed
- 기본/추천 임베딩 모델 `nlpai-lab/KURE-v1` → `dragonkue/snowflake-arctic-embed-l-v2.0-ko`. config 기본값, 온보딩 추천 플래그(`recommended`)·CLI 첫 선택지·compose 기본값, README 기본 모델 표기, `.env.example` 주석을 일괄 전환했다. WHY: ko-embedding-leaderboard 기준 arctic-ko는 평균 82.14(2위)로 KURE-v1 80.76(5위)을 상회하며, 자체 측정에서도 한국어 메모리 검색 품질이 가장 우수했다. 차원은 1024로 동일하고 인프라는 이미 arctic을 지원한다 — `MODEL_SIMILARITY_BASELINE`에 arctic=0.37을 등록해 KURE(0.45) 기준으로 튜닝된 코사인 threshold(conflict·auto-link·dup detection)를 모델별로 자동 보정하고, arctic의 비대칭 prefix(쿼리에만 `query: `, passage 무접두)를 적용한다. 568M·query당 ~0.5s로 점수 대비 효율이 최상이며, CPU 운영 제약(CLAUDE.md L1·L2)상 더 상위인 4B급 모델보다 현실적이다. KURE-v1·BGE-m3-ko·E5 등은 여전히 선택 가능한 모델로 남는다. `app/core/config.py`, `app/core/embeddings/service.py`, `app/cli/onboarding.py`, `README.md`, `.env.example`

### Upgrade Notes
- 기존 배포가 모델을 전환하려면 저장된 벡터를 재임베딩해야 한다(임베딩 공간 비호환 — 차원은 1024로 같지만 KURE 벡터와 arctic 쿼리를 섞으면 검색이 깨진다). `MEM_MESH_EMBEDDING_MODEL`을 바꾼 뒤 서버가 모델 불일치(`needs_migration`)를 감지하면 `POST /api/embeddings/migrate`(또는 대시보드 마이그레이션)로 전량 재임베딩한다. CPU 환경에서는 무거우므로 백그라운드 단일 작업으로 수행한다. KURE-v1을 유지하려면 `MEM_MESH_EMBEDDING_MODEL=nlpai-lab/KURE-v1`로 고정하면 된다.

## [1.11.1] - 2026-06-23

문서 정비 — 1.10.0에 도입된 first-run setup token 온보딩 흐름을 README에 문서화하고, 직전 릴리스에서 누락된 lint/format 정합성을 마저 맞춘다.

### Added
- README first-run setup 섹션 — dashboard 인증 미설정 상태에서 부팅 시 출력되는 일회용 setup token 흐름(콘솔 배너 · `<data dir>/setup_token` 영속 · `/setup` 온보딩)을 영문·국문 README에 문서화했다. WHY: 기능은 1.10.0에 들어갔으나 운영자가 노출된 대시보드를 브라우저에서 잠그는 절차가 문서에 없어 발견성이 낮았다. 콘솔 배너 예시는 실제 출력(기본 `Open : /setup` bare path + 일회성 소비 캡션)과 일치시키고, `MEM_MESH_PUBLIC_URL` 설정 시 전체 URL이 출력됨을 명시. 국문 README 목차에도 누락된 섹션 링크를 보강했다. `README.md`, `README.ko.md`

### Changed
- analytics stats · schema migrator Black 포맷 적용, ruff 위반(미사용 import · 빈 f-string) 해소. `app/core/services/stats.py`, `app/core/database/schema_migrator.py`

## [1.11.0] - 2026-06-20

분석 플랫폼 도입 — recall 추적 · 지식베이스(KB) 헬스 · 토큰 이코노믹스 대시보드. 더불어 프로덕션 Docker 로깅을 호스트에서 직접 tail 가능하도록 정비.

> 참고: 1.10.0은 버전 bump · CHANGELOG · 릴리스 커밋까지 준비됐으나 태그/푸시가 완료되지 않아 발행되지 않았다. 본 1.11.0이 v1.9.0 이후 작업 전체를 발행하며, 1.10.0 섹션은 당시 준비된 내용으로 그대로 보존한다.

### Added
- Analytics 플랫폼 — 토큰 이코노믹스, KB 헬스 메트릭, recall 통계, 활동 추세를 한 번에 보여주는 분석 스위트. recall 분석을 뒷받침하기 위해 schema migration **v10**으로 `access_count`·`last_accessed_at` 컬럼을 추가하고, 검색 서비스에서 best-effort 접근 추적을 수행한 뒤 대시보드 API로 분석 엔드포인트를 노출한다. WHY: 어떤 메모리가 실제로 재호출되는지, KB가 건강하게 유지되는지를 수치로 관찰할 수 없어 품질 개선의 근거가 부족했다. 접근 추적은 검색 경로에 부하/실패를 전가하지 않도록 best-effort(실패 무시)로 처리한다. `app/core/database/schema_migrator.py`, `app/core/services/stats.py`, `app/core/services/unified_search.py`, `app/web/dashboard/route_modules/stats.py`, `app/web/static/js/pages/analytics.js`, `app/web/static/js/services/api-client.js`

### Changed
- 프로덕션 Docker 로깅 정비 — 1.10.0의 named-volume 방식을 개선해, `data`·`model-cache`는 named volume으로 유지(컨테이너 recreate에도 DB/모델 보존)하되 `./logs`만 호스트로 bind mount해 직접 tail 가능하게 했다. 파일 로깅을 켜고(`LOG_OUTPUT=both` + `LOG_FILE`), `user: ${HOST_UID:-1000}:${HOST_GID:-1000}`로 컨테이너를 호스트 사용자로 실행한다(ubuntu root 서버는 `.env`에 `HOST_UID=0`). `HOME=/home/memmesh`를 설정해 numeric user에서도 캐시된 모델을 재사용한다. WHY: 비-root 이미지 사용자(UID 1000)가 root 소유 `./logs`에 쓰지 못하면 uvicorn의 access_file 핸들러가 치명적으로 동작해 crash loop에 빠진다. `docker-compose.yml`
- dev compose 환경변수 표준화 — `DATABASE_PATH`/`LOG_LEVEL`/`LOG_FORMAT`에 `MEM_MESH_` 접두사 부여(pydantic `env_prefix`가 비-접두 변수를 조용히 무시하던 문제) 및 파일 로깅 활성화. `docker-compose.dev.yml`
- 컨테이너 포트 8000을 모든 인터페이스에 노출. `docker-compose.yml`

### Fixed
- `codex_config` ↔ `hooks` 순환 import — `codex_config`가 모듈 최상단에서 `app.cli.hooks.json_ops`를 import해 `hooks/__init__` → `status` eager import → `CODEX_CONFIG` 정의 전 `codex_config` 재진입을 유발했다. isort(profile=black) 재정렬이 기존 import 순서가 가리던 이 문제를 테스트 수집 단계의 ImportError로 드러냈다. `json_ops` import를 두 writer 함수 안으로 옮겨 `codex_config`를 어떤 순서에서도 안전한 leaf 모듈로 유지한다. `app/cli/codex_config.py`

## [1.10.0] - 2026-06-17

웹 온보딩 UX 개선 — 셸 접근 없이 브라우저에서 대시보드 인증을 최초 설정하는 first-run setup token.

### Added
- First-run setup token — 대시보드 인증이 전혀 구성되지 않은 상태(`web_basic_auth_enabled`·`auth_enabled`·admin_password 모두 미설정)에서만 부팅 시 일회용 토큰을 생성해 **서버 콘솔에 출력**하고 `<data dir>/setup_token`(0600, hook token과 동일 패턴)에 영속한다. 웹 `/setup` 페이지에서 토큰 + admin 계정 입력 시 Basic Auth 활성화 · 비밀번호 설정 · 토큰 소멸 · 자동 로그인을 한 번에 처리한다. auth가 이미 구성된 경우 토큰은 발급되지 않고 stale 토큰은 부팅 시 제거된다. WHY: auth 미설정(부트스트랩) 상태에선 원격 웹에서 인증을 켤 수 없어(loopback / 세션 / OAuth 모두 부재) SSH나 env 수정이 필요했다. 노출된 서버를 원격에서 탈취하지 못하게 막는 `_can_reveal` 가드는 그대로 유지하면서, 그 1회성 온보딩 마찰을 "콘솔/데이터 디렉터리를 읽을 수 있는 운영자"에게로 옮긴다(첫 유효 제출이 토큰을 소비 → first-writer-wins로 race 차단). `app/core/config.py`, `app/web/oauth/setup_routes.py`, `app/web/lifespan.py`, `app/web/oauth/basic_auth.py`, `app/web/app.py`
- First-run 자동 리다이렉트 — dashboard 인증이 미설정이고 setup token이 pending인 동안, 브라우저 페이지 내비게이션(GET + `Accept: text/html`)을 `/setup`으로 리다이렉트해 빈 대시보드 대신 온보딩 화면을 바로 보여준다(정적 자산 · API · `/login` · `/setup` 자체는 통과, basic auth가 켜지면 자동 해제). setup 페이지에는 토큰을 `<data dir>/setup_token`에서 읽는 방법(`docker exec … cat /app/data/setup_token`)을 안내한다. `app/web/oauth/basic_auth.py`, `app/web/oauth/setup_routes.py`

### Fixed
- Production Docker compose가 `./data`·`./logs`를 bind mount로 걸어, 호스트에 디렉터리가 없으면 docker가 root 소유로 생성 → 비-root(`memmesh`, UID 1000) 컨테이너가 SQLite DB를 열지 못해(`unable to open database file`) 부팅이 exit 3 루프에 빠지던 문제. named volume으로 전환해 이미지의 `memmesh` 소유권이 볼륨 초기화 시 복사되도록 함(호스트 chown 불필요). 백업은 `docker compose cp mem-mesh:/app/data/memories.db ./backup.db`. `docker-compose.yml`

## [1.9.0] - 2026-06-17

멀티 IDE 클라이언트 지원 확장 — Codex IDE 지원 + Kiro/Antigravity 클라이언트 + Claude 프로젝트 로컬 룰 동기화.

### Added
- Codex IDE 지원 — hook 설치, MCP 설정, `status`/`doctor` 명령, interactive installer 및 web dashboard connect 통합을 Claude Code/Kiro/Cursor와 나란히 추가. `app/cli/codex_config.py`, `app/cli/install_hooks.py`, `app/cli/hooks/status.py`, `app/cli/hooks/doctor.py`, `app/web/dashboard/route_modules/connect.py`
- Kiro / Antigravity 클라이언트 지원 — `mcp_config.py`의 MCP 도구 자동 감지, 대시보드 `/kiro`·`/antigravity` 설치 alias, connect 부트스트랩(Kiro hook 설정 + Antigravity MCP config), 클라이언트 타깃 UI 및 안내. `app/cli/mcp_config.py`, `app/web/dashboard/pages.py`, `app/web/dashboard/route_modules/connect.py`, `app/web/static/js/pages/connect-page.js`
- Claude 프로젝트 로컬 룰 동기화 — `_sync_claude_rules()`가 세션/핀 gate를 담은 managed CLAUDE.md 블록 생성, `sync-project --target`에 `claude`/`kiro`/`antigravity` 추가, `render_claude_project_rules()` 렌더러. `app/cli/hooks/sync.py`, `app/cli/prompts/renderers.py`

### Changed
- Pin gate 결정 로직 명확화(PIN_CRITERIA v17) — "파일이 변경되는 작업만 pin" 등 핀 생성 기준 정리. `app/cli/prompts/behaviors.py`

## [1.7.0] - 2026-06-15

검색 품질·동시성·임베딩 파이프라인 개선. arctic-ko 임베딩 도입(blue-green 무중단 재임베딩) + read/write 분리 풀(C3) + reranking(opt-in).

### Added
- arctic-ko 임베딩 모델(`dragonkue/snowflake-arctic-embed-l-v2.0-ko`, MTEB-ko #1) 지원 + 모델별 score scaling — 비대칭 prefix(query에만 `query: `), CLS pooling, per-model similarity baseline로 sigmoid 정규화 중심을 보정. `app/core/embeddings/service.py`
- Blue-green 재임베딩 마이그레이션 — vec0가 RENAME 불가하므로 active-pointer(`active_embedding_table` 메타데이터) + dual-write + atomic swap으로 무중단 모델 전환. `app/core/services/embedding_manager.py`
- Read/write 분리 커넥션 풀(C3) — read-only 연결을 단일 스레드 executor에 pin(pysqlite3 threadsafety=1 안전), 읽기 head-of-line blocking 해소. `app/core/database/read_pool.py`, `app/core/database/base.py`
- Cross-encoder reranking(`BAAI/bge-reranker-v2-m3`, opt-in `enable_reranking`) — 정규화 후 적용, device를 cuda>mps>cpu로 자동 선택 + 문서 truncate(512). GPU에서 +~8% MRR/+15.8% R@1, CPU-only 배포는 비활성 권장. `app/core/services/reranker.py`, `app/core/services/unified_search.py`
- 쿼리 길이 적응형 RRF 가중치(opt-in `enable_adaptive_hybrid`). `app/core/services/unified_search.py`

### Fixed
- noise filter가 모든 검색에 30일 시간 필터를 강제하던 버그 제거(`time_range` 기본값 `30d`→`None`) — 30일 이전 메모리가 조용히 누락되어 recall이 무너지던 문제, MRR 3배 개선. `app/core/services/noise_filter.py`
- blue-green 마이그레이션이 defer-loading된 모델을 로드하지 않아 "Embedding model not ready"로 실패하던 문제 — 재임베딩 전 명시적 load. `app/core/services/embedding_manager.py`
- `complete_pin`을 conditional UPDATE + rowcount 체크로 원자화 — read pool 도입으로 노출된 read-then-write 경쟁 차단. `app/core/services/memory.py`
- score normalizer 캐시 키에 `sigmoid_threshold` 포함 — 모델 전환 시 stale 정규화 방지. `app/core/services/score_normalizer.py`

### Performance
- `/api/projects` N+1 제거(240→3 쿼리). `content_bytes` denormalize로 `SUM(LENGTH(content))` 풀스캔 제거. stats/resume 정렬 경로 인덱스 추가 + fuzzy 후보 풀 축소. dashboard 메모리 목록 복합 인덱스.

## [1.6.0] - 2026-06-15

운영(production) 전환을 위한 적대적 리뷰(red-team)에서 확인된 차단 결함 해소 + 임베딩 성능 개선.

### Security
- OAuth auth 하위 플래그(`mcp_auth_enabled`/`web_auth_enabled`)가 실제로 `auth_enabled`를 상속 — 이전엔 static `False`라 `auth_enabled=True`로도 `/mcp`·`/api`가 미인증으로 열려 있었음(middleware 독스트링만 상속 주장). `app/core/config.py`, `app/web/oauth/middleware.py`
- `POST /api/internal/notify`(stdio→web 브리지)를 `verify_hook_token`으로 보호하고 `HttpNotifier`가 토큰을 전송 — 미인증 대시보드 이벤트 위조 차단
- MCP/Web API가 비-loopback 바인드에서 인증 비활성으로 노출될 때 startup 경고

### Added
- `/api/ready` readiness probe — 임베딩 모델이 준비될 때까지 503 반환. Docker/compose HEALTHCHECK를 `/api/ready`로 변경(기존 `/health` 프로브는 존재하지 않는 경로였음). `app/web/dashboard/routes.py`

### Fixed
- DB torn-transaction 방지: 모든 연결 접근을 연결 lock + `_in_transaction` contextvar로 직렬화 — lock 없는 writer가 다른 코루틴의 열린 트랜잭션에 끼어들거나 조기 커밋하지 못함. `app/core/database/connection.py`
- `(project_id, user_id)`당 active 세션 1개 보장: idempotent dedup + partial unique index + INSERT race 폴백. `app/core/database/initializer.py`, `app/core/services/session.py`
- `embedding_metadata` 쓰기를 DELETE+INSERT에서 원자적 `ON CONFLICT` upsert로 — 크래시 시 메타데이터 영구 손실/모델 불일치 은폐 차단. `app/core/database/migrator.py`
- `batch_operations`가 중간 실패 시 `status:"partial"` 보고(기존엔 부분 쓰기에도 `success`)

### Performance
- 임베딩 추론(`model.encode()`)을 이벤트 루프에서 워커 스레드로 오프로드(`aembed`/`aembed_batch`, `asyncio.to_thread` + 타임아웃) — 초 단위 블로킹 추론이 더 이상 전체 서버를 프리징하지 않음. 검색/메모리/배치 핫패스 전환. `app/core/embeddings/service.py`

### Changed
- `PRAGMA synchronous=FULL`(WAL 기본 NORMAL은 커밋 시 fsync 안 함 — 전원 손실 내구성)
- CI가 `develop`에서도 실행 + Docker 이미지 빌드를 test 게이트(`build needs: test`) 뒤로 — 미검증 `:latest` 발행 차단. `docker-compose.yml`에 리소스 한계(`mem_limit`/`cpus`) + `workers=1`

## [1.5.5] - 2026-06-09

### Security
- Hook HTTP write endpoints (`/api/hooks/claude/*`) require a shared secret (`MEM_MESH_HOOK_TOKEN`, stored at `~/.mem-mesh/hook_token`, mode `0600`) when set. The loopback exception is now judged by the **effective bind host** captured at server start (`app/web/common/server.py`), not the static `settings.server_host`, so `--host 0.0.0.0` no longer silently bypasses auth. With a token set, a matching `Authorization: Bearer` is required on any host; no token + non-loopback bind is allowed with a one-time warning (the firewall is the trust boundary). `docker-compose.yml` binds `127.0.0.1` and requires the token (`app/web/oauth/middleware.py`, `app/core/config.py`)
- Local shell hooks (`app/cli/hooks/shell/local-*.sh`) pass stdin/CWD via argv/stdin instead of interpolating into `python -c` source — closes code injection via crafted repo directory name or transcript content
- Installer rejects shell metacharacters in `--path`/URL and drops the outer quotes around `path`/`url`/`project_id` template placeholders (`app/cli/hooks/renderer.py`) — closes command injection in local-mode install and `RULES_TEXT`
- Secret redaction applied at the `MemoryService.create` chokepoint (`app/core/redaction.py`) masks PEM/JWT/`sk-ant-`/AWS/GitHub/Slack/`Authorization` (all schemes)/`KEY=value`/email across every save path (HTTP hook, command hook, explicit add). An exact secret-key allowlist avoids redacting `max_tokens`-style config keys (which previously caused false dedup)

### Fixed
- `_merge_json_settings` backs up a malformed `settings.json` to `.bak` and raises instead of overwriting; all settings writes are atomic (`tempfile` + `os.replace`). Added the `--force` flag that the error message references (`app/cli/install_hooks.py`, `app/cli/hooks/json_ops.py`)
- `uninstall` removes only mem-mesh-managed hook entries instead of the entire top-level `hooks` key — preserves user-registered Claude/Cursor hooks (`app/cli/install_hooks.py`, `app/cli/hooks/uninstaller.py`)
- `normalize_project_id` splits on both `/` and `\` (`app/core/schemas/requests.py`) — a Windows client `cwd` sent over HTTP hooks no longer collapses every repo to `unknown` on a POSIX server
- Hook byte truncation (`head -c`) replaced with codepoint slicing (`jq -Rrs`) across all shell hooks — no more broken UTF-8 at multibyte boundaries
- Latent `NameError`s surfaced by linting: `logger` was used before its definition in `app/core/embeddings/service.py` (raised at import time when `MEM_MESH_IGNORE_SSL` is set), and `cutoff` was undefined in `app/core/services/session.py` cross-session resume when no prior session exists
- `app/cli/onboarding.py` used a Python 3.12+ f-string quoting form that failed to compile on the supported Python 3.9/3.10 target

### Changed
- `project_id` normalization unified across all hook-facing endpoints (resume / search / pins / memories / end-by-project / `/api/hooks/claude/*`) — shell sends the raw basename, the server normalizes (`app/core/schemas/requests.py`)
- `turns_since_save` (the "N turns without a save" reminder) counts `UserPromptSubmit` events only, not `UserPromptSubmit` + `Stop` (`app/core/services/hook.py`)
- Noise filter (`<task-notification>` / `<system-reminder>` / `<tool-use-id>` skip) added to shell `stop-decide` / `subagent-stop` / `stop` / `kiro-stop`, mirroring the server `_is_noise()`
- Shell auto-save length filter raised to `>= 100` to match the server `content` min-length; the stop-hook debug log is gated behind `MEM_MESH_HOOK_DEBUG`

## [1.5.4] - 2026-06-05

### Fixed
- MCP quick-start doc (`app/web/rules/modules/quick-start.md`) was missing the `type` field in the `mem-mesh` entry — clients infer legacy `type:"sse"` from the `/mcp/sse` URL, which hangs after a server restart. Now specifies `"type": "http"`

### Changed
- `mcp_config.py`: `generate_mcp_entry` accepts `mode="http"` (backward-compatible alias of `"sse"`; both emit `type:"http"`). Interactive/CLI labels and `verify_tool_config` messages renamed SSE → "HTTP (streamable)" to match the actual transport (the entry was already `type:"http"`; only the naming was misleading)
- README MCP section retitled SSE → "HTTP (streamable)" with a legacy `type:"sse"` warning

## [1.5.3] - 2026-06-05

### Fixed
- `_normalize_project_id` (hooks + migration script) missed underscore worktree suffixes — only the hyphen form `-wt-<hex>` was stripped, so ~94 `term-mesh_wt_<hex>` ids never collapsed to `term-mesh`. The worktree regex now matches both separators: `[-_]wt[-_][0-9a-f]{6,}$`
- `_normalize_project_id` left path-shaped ids (`/Users/.../oci-terraform`) intact — now reduced to the last path segment before normalization, and `_` / `.` are unified to `-`. `hooks.py` and `scripts/migrate_project_id_normalization.py` updated in lockstep (dry-run against the live server: 263 → 155 projects)

## [1.5.2] - 2026-06-05

### Changed
- Hook auto-save classification (`app/cli/hooks/keywords.py`) — the `bug` category no longer matches a bare fix verb (`수정`/`fix`/`해결`/`patch`/`debug`); a symptom word (`버그`/`error`/`exception`/`crash`/…) must co-occur. Rule order is now `incident → decision → code_snippet → bug → idea` so `bug` is no longer the default winner on score ties. `match_category()` and `KEYWORD_MATCHER_BLOCK` updated in lockstep
- HTTP hook `_project_id` (`app/web/dashboard/route_modules/hooks.py`) normalizes ids via `_normalize_project_id()` — strips git-worktree suffixes (`-wt-<hex>`), lowercases, and unifies `_`→`-` so worktree / casing / separator variants of one repo collapse to a single project id

### Added
- `_is_noise()` guard in the stop / subagent-stop hooks — skips `<task-notification>` / `<tool-use-id>` / `<system-reminder>` artifacts; a noise-only question is dropped from the saved Q&A pair
- `scripts/migrate_project_id_normalization.py` — dry-run (default) / `--apply` backfill that normalizes existing `project_id`s across `memories`, `projects` (PK merge), `sessions`, `pins`, `token_usage`, `hook_events`, `search_metrics`. The FTS index syncs via triggers; sqlite-vec tables key on `memory_id` only, so they need no changes

## [1.5.1] - 2026-05-26

### Added
- `~/.mem-mesh/api_url` config file as a third source for the API URL — lets one installed hook bundle target different remote servers per machine without editing `settings.json` or exporting an environment variable into the Claude Code session
- `status._read_config_file_url()` helper and `doctor` now report `~/.mem-mesh/api_url` alongside env vars

### Changed
- Bash hook templates (`app/cli/hooks/shell/*.sh`) — URL resolution chain widened to `${MEM_MESH_API_URL:-$(cat ~/.mem-mesh/api_url 2>/dev/null || echo <baked>)}`. Behaviour for users who only export `MEM_MESH_API_URL` is unchanged; the new fallback only activates when neither env var is present
- `resolve_api_url()` priority is now: `MEM_MESH_API_URL` env > `API_URL` env > `~/.mem-mesh/api_url` > baked URL > `DEFAULT_URL`
- `_extract_url_from_script()` recognises both the legacy single-fallback and the new config-file fallback patterns

### Fixed
- Stop / Session / SubagentStop hooks silently failing with `HTTP 000` when the Claude Code session was started before `MEM_MESH_API_URL` was added to `settings.json.env`. Claude Code does not export `settings.json.env` retroactively to already-running sessions; the config file gives users an out-of-band way to point hooks at a remote server without re-running the installer.

## [1.5.0] - 2026-05-14

### Added
- Claude Code HTTP hook support (requires Claude Code >= v2.1.105) — `bash + curl` hooks can be replaced with native `{"type":"http"}` hooks
- `hook_events` table + `HookService` — reconstructs per-session state (continuation detection, Q&A pairing, save-reminder turn counter) from the hook event stream instead of the client-side transcript file, which is unreachable when mem-mesh runs remotely or in Docker
- `/api/hooks/claude/{session-start,user-prompt-submit,stop,subagent-stop,task-completed}` endpoints — always return HTTP 200, degrade gracefully when the embedding model is not ready (a hook must never stall the user's session). "do nothing" replies use an empty body; context injection emits only `{"hookSpecificOutput": {...}}` to satisfy Claude Code's strict hook-output schema
- `keywords.match_category()` — pure function mirroring `KEYWORD_MATCHER_BLOCK`, lets the server classify messages without spawning `python3` client-side
- `install_hooks` gains `mode="http"` (`--mode http`, default in the interactive wizard) — emits HTTP hooks for events with a server endpoint, keeps command hooks for `SubagentStart`/`SessionEnd`/`PreCompact`
- `tests/test_hook_service.py` + HTTP-mode coverage in `tests/test_install_hooks_idempotency.py`

### Changed
- `_is_mem_mesh_hook` recognises url-based HTTP hooks so settings.json merges stay idempotent; switching `api` → `http` removes the now-replaced shell scripts
- bash hooks remain the fallback for Cursor / Kiro / local / remote deployments

## [1.4.3] - 2026-04-28

### Fixed
- **`MemoryNotFoundError` double-prefix message** (`app/core/errors.py`, `app/core/services/memory.py`, `app/core/services/relation.py`): callers passed pre-formatted strings like `f"Memory not found: {id}"` while the constructor wrapped them again, producing `"Memory not found: Memory not found: <id>"`. Constructor now accepts a raw `memory_id` plus an optional `role` kwarg (`"Source memory"` / `"Target memory"`); all call sites pass the raw id.

### Improved
- **MCP `memory_id` discoverability** (`app/mcp_common/schemas.py`): `context` / `update` / `delete` / `get_links` schema descriptions now state `"full 36-char UUID from add/search response"` and explicitly note that truncated/short ids are NOT accepted. Reduces a class of LLM-client errors (e.g., Cursor) where the short display id was reused as a tool argument.
- **`MemoryNotFoundError` self-correction hint** (`app/core/errors.py`): when the supplied id is shorter than 36 chars, the error message appends `(got N chars; ids are 36-char UUIDs — pass the complete id from the add/search response)` so calling LLMs can self-correct without a round-trip to docs.

## [1.4.2] - 2026-04-17

### Fixed
- **`setup_access_log` XDG handling** (`app/web/common/server.py`): three defects fixed — (1) eager evaluation of `_default_data_dir()` on every call produced spurious legacy-DB stderr warnings, (2) empty-string `XDG_STATE_HOME=''` fell through to CWD-relative logs, (3) missing `mem-mesh` app namespace under `$XDG_STATE_HOME` violated the XDG Base Directory spec. Now uses `os.environ.get("XDG_STATE_HOME") or str(_default_data_dir())` short-circuit with explicit `/ "mem-mesh"` suffix.
- **`make release` broken on Linux** (`Makefile`): `bump` target used BSD-only `sed -i ''` syntax that fails on GNU sed. Switched to portable `sed -i.bak ... && rm -f *.bak`.
- **docker-compose ignored `MEM_MESH_SERVER_WORKERS`** (`docker-compose.yml`): top-level `command: ["uvicorn", ...]` bypassed the Dockerfile CMD `python -m app.web`, so uvicorn launched with 1 worker regardless of env. Dropped the override; container now honors `Settings.server_workers`.
- **Onboarding-generated compose: unprefixed env vars + unpublished image** (`app/cli/onboarding.py`): `_generate_compose_file()` wrote `DATABASE_PATH` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` / `LOG_LEVEL` without the `MEM_MESH_` prefix (the same class of bug 1.4.1 fixed in committed compose files) and referenced the unpublished `mem-mesh:latest` tag. Now emits `MEM_MESH_*` prefixes and `xmesh/mem-mesh:latest`.
- **`.env.example` overrides XDG default** (`.env.example`): uncommented `MEM_MESH_DATABASE_PATH=./data/memories.db` defeated the new 1.4.0 XDG default when users `cp .env.example .env`. Commented out with a note referencing `_default_db_path`. Also removed duplicate `MEM_MESH_LOG_LEVEL=DEBUG` at line 61 that shadowed the earlier `INFO` assignment.

### Docs
- README `Search` section and `Configuration` table now reflect the 1.4.0 defaults (`nlpai-lab/KURE-v1`, 1024-dim, XDG per-user DB path). Legacy `MCP_LOG_LEVEL` / `MCP_LOG_FILE` rows renamed to `MEM_MESH_LOG_LEVEL` / `MEM_MESH_LOG_FILE`.

## [1.4.1] - 2026-04-16

### Added
- `.github/workflows/docker.yml` — publishes `docker.io/xmesh/mem-mesh` on `v*` tag / main push. Multi-arch (linux/amd64 + linux/arm64), GHA cache, provenance + SBOM. Requires `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` secrets.
- Makefile targets: `uvx-install`, `uvx-serve`, `uvx-hooks`, `uvx-refresh`, `docker-buildx-push`, `release V=x.y.z`, `release-tag`.

### Fixed
- **Docker compose env vars ignored**: all `DATABASE_PATH`, `EMBEDDING_MODEL`, `LOG_LEVEL`, `STORAGE_MODE` etc. in `docker-compose.yml` and `docker/docker-compose.yml` lacked the required `MEM_MESH_` prefix, so pydantic-settings silently dropped them. User overrides had no effect. Now properly prefixed.
- **Dockerfile dependency resolution**: `requirements.txt` upper bounds conflicted with `mcp>=1.13` (needs `uvicorn>=0.31.1`) and `fastmcp>=2.14.2` (needs `httpx>=0.28.1`). Bumped both to compatible ranges (`uvicorn>=0.31.1`, `httpx>=0.28.1`).
- `docker/docker-compose.yml` no longer mounts the removed `../static` and `../templates` directories (content lives under `app/web/` since 1.4.0 and is covered by the `/app/app` source mount).
- `.env.example`: commented out legacy `MEM_MESH_EMBEDDING_MODEL=all-MiniLM-L6-v2` / `DIM=384` so copying the template doesn't silently override the new KURE-v1 default.

### Docs
- Noted in CHANGELOG that existing DBs created with 1.3.x keep their persisted `embedding_model` metadata, overriding the new default. To adopt KURE-v1 on an existing install: delete the database volume or update `embedding_metadata` via `sqlite3` / dashboard.

## [1.4.0] - 2026-04-16

### Added
- **uvx-first install flow** — `uvx mem-mesh install` / `uvx mem-mesh serve` work out of the box. MCP config now emits a `uvx` command (`--from "mem-mesh[server]" mem-mesh-mcp-stdio`) so clients auto-spawn an isolated, cached mem-mesh per call
- `mem-mesh install` onboarding detects `uvx` and offers it as the recommended server option; warms the uv cache so the first MCP call is instant
- Packaging smoke-test suite (`tests/test_packaging.py`, 19 tests) — catches missing shell templates, web templates/static/rules, undeclared deps, and default-path CWD leaks before release
- Boot-time "Loading server modules…" message + 25%-step embedding-model progress logs so the banner → first-response gap is visible

### Changed
- **Default embedding model**: `intfloat/multilingual-e5-large` → `nlpai-lab/KURE-v1` (Korean-tuned BGE-M3, 1024-dim); onboarding model picker lists KURE-v1 first
- **Default database path**: uses XDG-compliant per-user directory (`~/Library/Application Support/mem-mesh/` on macOS, `$XDG_DATA_HOME/mem-mesh/` on Linux, `%APPDATA%/mem-mesh/` on Windows) instead of `./data/memories.db` relative to CWD. A legacy `./data/memories.db` in CWD is still detected with a one-line stderr warning for backwards compatibility
- Default access-log dir follows the same XDG convention
- `templates/`, `static/`, and `docs/rules/` moved under `app/web/` and resolved via `Path(__file__)` so they're packaged into the wheel
- `TemplateResponse` calls switched to the new Starlette API (`request, "index.html", {…}`) — fixes `TypeError: unhashable type: 'dict'` on recent starlette/jinja2

### Fixed
- **Packaging**: `pyproject.toml` now includes `app/cli/hooks/shell/*.sh`, `app/web/templates/*.html`, `app/web/static/**`, `app/web/rules/*` as package data. Previously `uvx` installs hit `FileNotFoundError` for shell templates and dashboard assets
- **Server deps**: `urllib3`, `sse-starlette`, `tiktoken`, `requests` added to `[project.optional-dependencies.server]` (were transitive-only in dev envs; missing in clean uvx installs)
- `pysqlite3-binary` moved to Linux-only (`sys_platform == 'linux'`) — no wheels exist for macOS arm64; uv's managed Python builds include SQLite extension loading so the binary is unnecessary on macOS
- Dead `/test` endpoint serving a non-existent `test_web_ui.html` removed
- `_model_embedding_dim()` helper with fallback — silences `FutureWarning` from sentence-transformers ≥3 (`get_sentence_embedding_dimension` → `get_embedding_dimension`)
- `release.yml` verify step: `app.core.version.VERSION` → `app.core.version.__VERSION__` (matched actual symbol)

## [1.3.0] - 2026-04-16

### Added
- `RelationService.auto_link_similar` — vector similarity-based automatic memory linking (replaces prior TODO stub)
- `auto_complete_pins` strategy parameter on `session_end` — 3-state enum (`none`/`in_progress`/`all`), backwards compatible with boolean
- `tests/test_auto_complete_strategy.py` covering all strategies + backwards compatibility
- Public release tooling — `.github/workflows/release.yml` (PyPI publish automation via tag push)
- `CONTRIBUTING.md` with dev setup, PR workflow, tests, commit style, release process

### Changed
- `pin_list` optimization: when client-side filters (`min_importance`, `tags`) apply, fetch up to 200 records then trim to `limit` (prevents fewer-than-requested results); stats calculation merged into the pin iteration loop
- Repository ownership migrated from `JINWOO-J/mem-mesh` to `x-mesh/mem-mesh`; all URLs updated (`pyproject.toml`, `README*`, `Dockerfile`)
- `pyproject.toml`: authors email dropped (name-only), aligned with public-facing package metadata
- Renamed top-level `build.py` → `build_webui.py` to resolve module-name collision with PyPA's `build` (caused `python -m build` to import the local web UI script instead of the packaging frontend)

### Fixed
- `pyproject.toml`: moved `dependencies` out of `[project.urls]` table back into `[project]` (TOML scoping regression)
- Dockerfile `ENV MEM_MESH_SERVER_HOST=0.0.0.0` default — bare `docker run -p 8000:8000` now reachable from host (previously bound to `127.0.0.1` inside container, unreachable via published port)

### Security
- Bump `jinja2` pin `>=3.1.0` → `>=3.1.6` (CVE-2024-22195, CVE-2024-34064, CVE-2024-56326, CVE-2024-56201, CVE-2025-27516)
- Bump `fastmcp` pin `>=0.1.0,<1.0.0` → `>=2.14.2` (CVE-2025-62800, CVE-2025-62801, CVE-2025-64340, CVE-2025-69196, CVE-2026-27124, GHSA-rcfx-77hg-w2wv). `FastMCP(name)` API is source-compatible; MCP tests remain green.
- Reduces pip-audit findings from 46 CVEs (8 packages) to 1 CVE (transformers 4.57.6 → fix only available as 5.0.0rc3 pre-release; deferred pending sentence-transformers compatibility).

## [1.2.6] - 2026-04-14

### Fixed
- PreCompact hook JSON validation failure: switched output schema from `hookSpecificOutput` wrapper to `{continue, systemMessage}` format

## [Pre-1.2.x backlog]

### Fixed
- `MemoryService.create_with_embedding()` bug: replaced non-existent `db.add_memory()` with direct SQL INSERT + transaction
- CORS `allow_origins=["*"]` replaced with configurable `MEM_MESH_CORS_ORIGINS` environment variable
- Environment variable priority: `MEM_MESH_LOG_*` now takes precedence over deprecated `MCP_LOG_*`

### Added
- `MEM_MESH_CORS_ORIGINS` setting for configurable CORS origins
- `app/core/errors.py`: unified error codes, exception hierarchy, HTTP/JSON-RPC mappings
- `tests/conftest.py`: shared test fixtures (temp_db, mock services, MCP tool handlers)
- `.pre-commit-config.yaml` with Black, isort, Ruff, mypy hooks
- `CHANGELOG.md` (this file)
- `scripts/README.md`: categorized script documentation
- `docs/rfc-search-mode-simplification.md`: RFC for search mode consolidation
- Security warnings in `.env.example` for production deployment
- FastMCP stdio: pin/session/relations tools (pin_add, pin_complete, pin_promote, session_resume, session_end, link, unlink, get_links)
- CI: coverage reporting, Ruff linting, isort check, Codecov upload

### Changed
- Synced version in `pyproject.toml` to match `app/core/version.py` (1.0.4)

### Removed
- Legacy search files: `enhanced_search.py`, `improved_search.py`, `final_improved_search.py`, `simple_improved_search.py`

## [1.0.4] - 2026-02-15

### Added
- OAuth 2.1 authentication (Bearer token + Basic Auth)
- MCP Protocol 2025-03-26 Streamable HTTP transport
- UnifiedSearchService with hybrid/semantic/exact/fuzzy modes
- Work tracking system (projects, sessions, pins)
- Memory relations (link, unlink, get_links)
- Batch operations for MCP tools
- Token estimation and context optimization
- Web dashboard with SPA architecture
- WebSocket real-time notifications
- Monitoring API and search metrics

## [1.0.0] - 2026-01-01

### Added
- Initial release
- SQLite + sqlite-vec vector storage
- sentence-transformers embedding service
- MCP stdio server (FastMCP + Pure)
- FastAPI REST API
- Memory CRUD operations
- Vector search and FTS5 full-text search
- Project-based memory organization
