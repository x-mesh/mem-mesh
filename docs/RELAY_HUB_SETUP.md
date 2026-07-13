# Relay Hub 브릿지 설정 가이드

> 개인 mem-mesh 노드를 팀 허브에 연결(브릿지)하는 방법. 아키텍처 배경은
> [mem-mesh-relay-PRD.md](./mem-mesh-relay-PRD.md) 참조.

## 개념 요약

- **허브는 별도 바이너리가 아니다.** 모든 mem-mesh 인스턴스가 `/api/relay/v1/*`
  API를 노출하며, 팀에서 한 인스턴스를 허브로 지정하면 된다.
- **클라이언트(MCP/IDE)는 항상 자기 개인 노드만 본다.** 개인 노드가 서버측에서
  허브에 접속하는 브릿지다: 공유는 `relay_outbox` → S2S push, 팀 검색은
  `search(scope="hub"|"all")` 시 live fetch + RRF 융합.
- **데이터 흐름은 개인 → 허브 단방향, 소비는 view-only.** 팀 데이터를 로컬에
  복제하지 않는다.

## 새 팀원 연결 (권장: 초대 코드 페어링)

1. **허브 admin** — 대시보드 Relay → Team Hub 탭 → *Pairing Invites*:
   User ID / Display Name (+ 필요 시 Source Node ID 고정, 만료 선택) 입력 후
   **Issue Invite**. 코드는 1회만 표시된다 — 신규 팀원에게 전달.
2. **신규 팀원** — 자기 노드의 Relay → Personal Node 탭:
   Team Hub URL 입력 → *Pair with Invite*에 코드 붙여넣기 → **Pair with Invite**.
   노드가 허브에서 코드를 상환해 `hub_url` / `hub_token` / `source_node_id`를
   한 번에 저장하고 Check Hub 검증까지 수행한다.

초대 코드 속성: 단일 사용, TTL 만료(기본 24h), 허브에는 해시만 저장,
미상환 코드는 Team Hub 탭에서 회수(Revoke) 가능.

API로 직접 할 경우:

```bash
# 허브에서 (admin, loopback/인증 세션 필요)
curl -X POST https://hub/api/relay/v1/admin/invites \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "yuna", "display_name": "Yuna", "expires_in_seconds": 86400}'
# → {"invite": {...}, "code": "<one-time-code>"}

# 신규 노드에서 (자기 노드 API에 요청; 노드가 허브와 통신)
curl -X POST http://localhost:8000/api/relay/v1/admin/pair \
  -H 'Content-Type: application/json' \
  -d '{"hub_url": "https://hub", "code": "<one-time-code>"}'
```

## 수동 연결 (구버전 허브 / 세밀 제어)

1. 허브 admin이 Team Hub 탭 → Hub Identities에서 identity 등록(토큰 1회 표시).
2. 토큰을 대역외로 전달, 신규 노드의 Personal Node 탭에 Hub URL + 토큰 입력.
3. **Check Hub** — 성공 시 검증된 토큰과 허브가 도출한 source_node_id가
   자동 저장된다.

## 공유가 실제로 전송되려면: relay worker

웹 서버 프로세스는 outbox를 배달하지 않는다. 별도 worker 프로세스가 필요하다:

```bash
python -m app.cli.main relay worker            # 데몬
python -m app.cli.main relay worker --once     # 1회 드레인 (디버깅)
```

Docker compose에는 `mem-mesh-worker` 컨테이너로 포함되어 있다. worker 없이
공유하면 메모리가 outbox에 쌓이기만 하고 전송되지 않는다.

**허브도 worker를 돌려야 한다.** 수신된 메모리의 벡터는 worker의 `item` 태스크가
만든다 — 안 돌리면 허브 검색이 substring 매칭으로 떨어져 자연어 쿼리가 0건이 된다.
`item`은 LLM 없이도 동작한다(embedding-only 모드: 벡터만 인덱싱, title/abstract는
비움). 나중에 LLM을 붙이면 worker가 해당 항목들을 다시 큐에 넣어 enrichment를
채운다. `aggregate`(프로젝트 다이제스트)는 LLM이 필수다.

## 장애·재시도 동작

- **Federated 검색 서킷 브레이커** — 허브 호출이 연속
  `relay_federated_breaker_threshold`(기본 3)회 실패하면
  `relay_federated_breaker_cooldown`(기본 30s) 동안 허브 호출을 생략하고 즉시
  로컬 결과로 degrade한다(`hub_status="unavailable"`). cooldown 후 probe 1회가
  통과하고, 성공하면 정상 복귀한다. 허브 다운이 검색 지연으로 전이되지 않는다.
- **outbox 백오프** — 지수 백오프 + downward jitter, `--max-attempts`(기본 8)
  초과 시 dead_letter. 대시보드 Operations 탭 또는
  `POST /relay/v1/admin/retry-dead-letters`로 재시도.

## 카테고리 필터

`search(scope="hub"|"all", category=...)`의 카테고리는 허브측 `kinds` 필터로
전달된다(text/vector 경로 모두). 구버전 허브는 이 필드를 무시하므로 클라이언트가
2×limit 오버페치 후 재필터한다 — 결과 수가 조용히 줄어들지 않는다.

## 관련 설정

| 설정 | env | 기본값 |
|---|---|---|
| 허브 URL | `MEM_MESH_RELAY_HUB_URL` | — |
| 허브 토큰 | `MEM_MESH_RELAY_HUB_TOKEN` | — |
| 소스 노드 ID | `MEM_MESH_RELAY_SOURCE_NODE_ID` | — |
| federated timeout | `MEM_MESH_RELAY_FEDERATED_TIMEOUT` | 2.5s |
| 브레이커 임계 | `MEM_MESH_RELAY_FEDERATED_BREAKER_THRESHOLD` | 3 |
| 브레이커 cooldown | `MEM_MESH_RELAY_FEDERATED_BREAKER_COOLDOWN` | 30s |
| hub RRF 가중치 | `MEM_MESH_RELAY_FEDERATED_HUB_WEIGHT` | 0.75 |

값은 대시보드(DB) 우선, env는 폴백이다 (Personal Node 탭 Connection State에서
필드별 source 확인 가능).
