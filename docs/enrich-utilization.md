# Enrichment 활용 (enrich utilization)

> enrich한 title/abstract/tags/problem/resolution/lesson/confidence를 **실제로 활용**해
> 검색 토큰 절감·정확도·내비게이션·큐레이션·지식 롤업으로 ROI를 회수하는 작업의
> living 레퍼런스. 진행 중이며 이어서 확장한다.

## 배경

enrich는 "한 번 요약해두고, 이후 매 검색·주입마다 그 요약을 재사용"하는 구조라,
검색이 잦을수록 절감이 누적된다. 그러나 오랫동안 enrich 결과는 **주입 라인·대시보드·
hub 전파에만** 쓰이고 검색 응답 토큰 절감/정확도엔 미활용이었다 — 즉 enrich 투자의
ROI를 회수하는 코드가 없었다. 이 문서의 작업들이 그 회수 경로다.

관련 메모리(mem-mesh): enrich 활용 로드맵 `7be10f0f`, search abstract화 debate,
그리고 아래 각 기능의 decision/bug 메모리.

## Enrichment 데이터 — 무엇을 어디에 저장하나

로컬 enrichment는 `memory_enrichment` 사이드 테이블(`EnrichmentStore`, lazy schema)에
저장. memory 본문(`memories.content`)은 절대 바꾸지 않는다.

| 컬럼 | 내용 | 비고 |
|---|---|---|
| `title` | ≤80자 한 줄 제목 | 오래전부터 저장 |
| `abstract` | 2–3문장 요약(≈400자) | 오래전부터 저장 |
| `tags` | 3–7개 kebab-case 토픽 태그(JSON) | 오래전부터 저장 |
| `display_kind` | LLM이 본 종류(decision/bug/…/note/reference) | 오래전부터 저장 |
| `problem` / `resolution` / `lesson` | 문제/해결/교훈 | **최근 추가** |
| `confidence` | 0.0–1.0 근거 명확도 | **최근 추가** |

> ⚠️ **핵심 제약**: `problem/resolution/lesson/confidence`는 LLM이 원래 생성하지만
> 과거엔 전부 버려졌다(반환·스키마·upsert 미포함). 이제 저장하지만 **이 변경 이후
> (재)enrich된 메모리에만** 채워진다. 기존 대량 enriched 메모리는 **force 재-enrich
> 전까지 NULL**. `display_kind`는 이전부터 저장돼 기존 데이터로도 즉시 활용 가능.

hub 쪽은 별도 테이블 `relay_item_enrichment`(relay.py)로 problem/resolution/lesson/
confidence를 이미 보관한다.

## 저장 파이프라인

```
maintenance._run_enrich(memory)
  → chat.enrich_memory_content(content)      # RelayEnricher.enrich, chat LLM
      → returns title/abstract/tags/display_kind/problem/resolution/lesson/confidence
  → EnrichmentStore.upsert(...)              # 전 필드 저장(redact 후)
```

- 스키마 마이그레이션: `EnrichmentStore.ensure_schema`가 `CREATE TABLE`(신규 DB) +
  `PRAGMA table_info` 확인 후 누락 컬럼 `ALTER TABLE ADD COLUMN`(기존 DB). 버전 bump 불필요.
- auto-enrich(별도 문서 참조): per-project opt-in + write-time 훅 + worker 12h sweep로
  커버리지가 자동으로 차오른다 → 아래 활용들의 ROI가 시간이 갈수록 커진다.

## 구현된 활용

### 1. 검색 응답 abstract화 + topic tags (MCP `search`)

**목적**: MCP 검색 응답에서 `content[:80]` 절단 조각 대신 정제 abstract/tags를 실어
같은/적은 토큰에 정보 밀도를 높인다(원문은 `context()`/`get()` 드릴다운 = progressive
disclosure).

- `recall.fetch_enrichment_map(db, ids)` — 결과 id로 title/abstract/tags/display_kind를
  IN 배치 1회 조회(검색 경로 `search.py`는 미변경, 응답 조립부에서만 병합).
- `MCPToolHandlers._compress_search_response(result, format, enrichment_map)`:
  - `compact`: abstract 치환(없으면 content[:80] 폴백) + title + topic tags, **raw content 생략**.
  - `standard`(기본): enriched → title+abstract+tags(원문 생략), **un-enriched → full content 유지**(회귀 없음).
  - `minimal`: id+score.
- 파일: `app/mcp_common/tools.py`, `app/core/services/recall.py`.
- 테스트: `tests/test_search_compress_enrich.py`.

### 2. Tag facet 내비게이션

**목적**: 토픽 태그를 집계해 주제별 브라우징 + 클릭 필터.

- `recall.fetch_tag_facets(db, project_id, limit)` — enrichment tags + source tags를
  `json_each`로 unnest, `UNION`으로 (memory,tag) 중복 제거 후 count, project 스코프.
- 필터 확장: `Database._tag_filter_sql`로 search `tag` 필터가 **source tags OR
  enrichment tags** 매칭(`get_recent_memories`/`count_memories`, `memory_enrichment`
  존재 가드). → 집계된 enrichment-only 태그도 클릭 시 정확히 필터.
- API: `GET /api/memories/tags?project_id=&limit=` → `{facets:[{tag,count}]}`.
- UI: memories 페이지 `.mem-facets` chip row(기존 `mem-clickable-filter[data-filter-type=tag]`
  핸들러 재사용 → `viewParams.tag`).
- 파일: `app/core/services/recall.py`, `app/core/database/base.py`,
  `app/web/dashboard/route_modules/search.py`, `app/web/static/js/pages/memories.js`.
- 테스트: `tests/test_tag_facets.py`.

### 3. 큐레이션 후보 (miscategorized / low-confidence)

**목적**: enrichment 신호로 정리할 메모리를 노출.

- `recall.fetch_curation_candidates(db, project_id, limit, confidence_threshold=0.5)`:
  - `display_kind`이 유효 카테고리인데 stored `category`와 다르면 → `miscategorized`.
  - `confidence < threshold` → `low_confidence`.
  - `note`/`reference` 등 비-카테고리 display_kind는 오탐 방지로 제외.
- API: `GET /api/memories/curation-candidates?project_id=&limit=`.
- `miscategorized`는 **기존 데이터로 즉시 동작**, `low_confidence`는 재-enrich 후.

### 4. Lessons 롤업 ("우리가 배운 것")

**목적**: enrichment `lesson`을 모아 지식 뷰 / weekly_review 강화.

- `recall.fetch_lessons(db, project_id, limit)` — 비어있지 않은 lesson + memory 참조.
- API: `GET /api/memories/lessons?project_id=&limit=`.
- **재-enrich 후** 채워진다(lesson은 최근 추가 필드).

> 3·4 파일: `app/core/services/enrich_store.py`, `app/core/services/chat.py`,
> `app/core/services/maintenance.py`, `app/core/services/recall.py`,
> `app/web/dashboard/route_modules/search.py`. 테스트: `tests/test_enrich_curation.py`.

## 로드맵 / 다음

- [x] 검색 응답 abstract화 (compact)
- [x] standard 기본 abstract-first (기본 호출에 절감 적용)
- [x] tag facet 집계 + 필터 확장 + 대시보드 UI
- [x] enrichment 필드 저장 확장(problem/resolution/lesson/confidence)
- [x] 큐레이션 후보 API
- [x] lessons 롤업 API
- [ ] **큐레이션 / lessons 대시보드 UI** (현재 API만) — 재분류 승인, lesson 뷰
- [x] **enrich 백필(수렴형)** — 기존 enriched에 confidence/lesson 채우기(아래 참조).
- [ ] **② abstract 임베딩 검색** — content→abstract 기반 임베딩으로 정확도↑.
      **전량 재임베딩 + A/B 필요**. CLAUDE.md L1/L5(무거운 ML) — GPU/배치 신중, 명시 opt-in 시에만. **백필로 abstract 커버리지 채운 뒤** 착수.
- [ ] **큐레이션/lessons 대시보드 UI**
- [ ] dedup/reconcile를 abstract 유사도로(현재 content 기반) — 비용 절감 후보.

## enrich 백필 (수렴형)

confidence/lesson은 필드 추가 이후 (재)enrich된 메모리에만 있으므로, 기존 enriched를
재-enrich해 채운다. **부하 스파이크 없음** — worker가 concurrency만큼 LLM을 동시 처리하고
비용만 시간에 분산된다.

- 타겟: `memory_enrichment.confidence IS NULL`(= 필드 추가 이전 것)만. 재-enrich되면
  confidence가 non-NULL이 되어 **다음 회차에 자동 제외 → 스스로 수렴**(무한루프 없음).
- `MaintenanceService.enqueue_backfill(project_id, limit)` — 타겟을 `_insert_job(enrich)`로
  적재(live 잡은 스킵). worker에 수렴형 sweep(회차당 cap, LLM 게이트).
- **켜기(worker env)**:
  - `MEM_MESH_ENRICH_BACKFILL=1` — 백필 sweep 활성(기본 off).
  - `MEM_MESH_ENRICH_BACKFILL_CAP=200` — 회차당 적재 상한.
  - `MEM_MESH_WORKER_CONCURRENCY=5` — 동시 처리 수(드레인 속도). 부하 감당되면 올린다.
- 완료 판단: `SELECT COUNT(*) FROM memory_enrichment WHERE confidence IS NULL` → 0이면 수렴.
- 파일: `app/core/services/maintenance.py`, `app/core/services/relay_worker.py`,
  `app/cli/relay.py`. 테스트: `tests/test_auto_enrich.py`.

## 병렬/메모리 안전 (E 재임베딩 대비)

과거 병렬 작업 중 Python 프로세스가 ~60GB를 점유한 사고의 근원은 **EmbeddingService가
인스턴스마다 모델(~2GB)을 로드**한 것 — worker `concurrency=N`이면 한 프로세스에 모델 N벌.
`EmbeddingService._MODEL_CACHE`(model_name별 class-level 캐시)로 **프로세스당 1벌 공유**로
수정. worker의 concurrent 인스턴스는 단일 asyncio 스레드라 encode가 어차피 직렬이므로
공유는 무손실·안전. → **한 프로세스 concurrency 5도 모델 1벌**, 별도 프로세스 2개면 2벌
(64GB에서 안전).

E(abstract 재임베딩)는 이 공유 위에서 소표본·throttle로 진행하면 메모리 안전.
측정(A/B)은 여전히 GPU 권장(CPU 반복 추론 회피, L1/L5).

## 운영 노트

- confidence/lesson을 지금 보려면: 대상 프로젝트를 **force 재-enrich**해야 채워진다.
- worker 미가동 / Worker LLM 미설정이면 enrich 자체가 안 돌아 위 활용도 공백
  (별도 문서: relay worker / Worker LLM 설정).
- 모든 fetch_* 헬퍼는 enrichment 테이블 부재·JSON1 이슈에 graceful(빈 결과, 비-치명).
