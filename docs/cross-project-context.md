# 연관 프로젝트 간 컨텍스트 공유

> frontend/backend처럼 **별도 repo·별도 project_id인데 API 계약·env·auth·port로 결합된** 쌍에서,
> "이건 둘 다 바꿔야 해"를 놓치지 않게 하는 기능.

## 설계 배경 (왜 이렇게 만들었나)

5개 모델 cross-vendor council(`.xm/op/council-2026-07-13-cross-project-context-sharing.json`)이
`project_links` 테이블 + `include_linked` 플래그 + RRF 가중 + `affects:` 태그 + 세션 자동주입을
**만장일치로 기각**했다. 근거는 이 레포의 실측이다:

| 지표 | 값 |
|---|---|
| code-tied 메모리 (decision/bug/code_snippet/incident) | 15,582건 |
| **git anchors 부착률** | **0.0%** — hook 규칙이 명시적으로 요구하는데도 |
| 자유형 태그 부착률 | 99.6% |
| `prefix:value` 구조화 태그 | 2.7% |

**한계 비용 기울기**: 이미 채우는 배열에 값 넣기(비용 0) → 99.6%. 규약을 상기하고 형식을
지키기 → 2.7%. 추가 tool call + 중첩 객체 → 0%.

여기서 나온 원칙 하나가 이 기능 전체를 지배한다:

> **훅이 "검색하라"고 지시하면 안 된다. 훅이 직접 검색해서 결과를 주입해야 한다.
> 지시는 산문이고, 주입은 사실이다.**

`affects:backend` 같은 규약 태그를 도입하지 않은 이유도 같다 — 그 태그는 **저장 시점에,
보이지 않는 repo에 대한 미래 관련성을 예언**하라고 요구한다. Pin Gate가 작동하는 건 현재 턴
자기 상태의 **관측**이기 때문이다.

## 구성 요소 두 개

### 1. `search(project_ids=[...])` — 한 쿼리로 두 프로젝트

```python
search(query="인증 토큰 TTL", project_ids=["frontend", "backend"])
```

`WHERE project_id IN (?,?)` 하나다. 별도 코퍼스도, 랭킹 융합도, 링크 테이블도 없다.
`project_id`(단수)와 같이 주면 `project_ids`가 이긴다. 로컬 스코프 전용(hub는 다른 코퍼스).

MCP·HTTP(GET/POST) 모두 지원한다.

### 2. PreToolUse 훅 — 계약 파일을 건드리면 상대 프로젝트를 읽어다 준다

**설정**(opt-in): repo 루트에 `.mem-mesh/cross-project.json`

```json
{
  "peers": ["backend"],
  "globs": ["**/openapi*", "**/contracts/**"]
}
```

- `peers` — 이 repo와 결합된 프로젝트 id. **없으면 훅은 즉시 종료하고 아무 비용도 쓰지 않는다.**
- `globs` — 생략하면 서버 기본값(아래). 지정하면 기본값을 **대체**한다.

**기본 계약 판정**(글롭 문자열이 아니라 두 규칙):

- **디렉토리**: 경로 어딘가에 `auth` `api` `routes` `schema(s)` `migrations` `contracts` `proto` `graphql` `openapi` `swagger` 세그먼트가 있으면 발화. **루트 레벨 포함** (`api/tokens.py`도 잡힌다).
- **파일명**: `openapi*` `swagger*` `schema*` `auth.*`/`auth-*`/`auth_*` `.env*` `docker-compose*` `Dockerfile*` `*.proto` `*.graphql`

`auth`는 **경계**를 요구한다 — `AUTHORS`, `AuthorCard.tsx`, `oauth-modal.js`는 발화하지 않는다. 이건 중요하다: 헛발화는 kill-condition이 읽는 발화 횟수를 부풀려, 죽은 기능을 살아있는 것처럼 보이게 만든다.

**동작**: `Edit|Write|MultiEdit|NotebookEdit`이 위 글롭에 걸리는 파일을 건드리려 하면 —

```
## Cross-project context — editing `src/auth/token.ts` (peer: backend)

This file is a contract surface. What the peer project recorded:

- [decision] (오늘) 백엔드 인증 정책: access token TTL 15분, refresh는 로테이션…

If the change alters a shared contract (API shape, env var, auth flow, port),
it likely has to land on both sides.
```

이게 편집이 실행되기 **전에** 모델 컨텍스트에 들어간다.

발화하지 않는 경우: 일반 파일(`Button.tsx`), peer 미설정, 읽기 도구, peer가 자기 자신,
peer 쪽에 관련 메모리 없음. 서버가 죽었거나 느려도 5초 타임아웃 후 편집은 그대로 진행된다 —
훅이 작업을 막지 않는다.

## kill-condition (반드시 판정할 것)

이 기능은 **삭제 조건을 정해두고** 넣었다. 안 쓰이면 지운다.

```sql
-- 발화 횟수
SELECT count(*) FROM hook_events WHERE event_name = 'PreToolUse';

-- 주입 횟수 / 주입된 메모리
SELECT count(*), count(DISTINCT memory_id)
FROM injected_memories WHERE injected_via = 'pre_tool_use';
```

- **2~4주 후 발화가 주 1회 미만** → 글롭이 현실과 안 맞거나 애초에 문제가 없었다는 뜻. 삭제.
- **주입은 되는데 아무도 안 본다** → 노이즈. 글롭을 좁히거나 삭제.

두 지표 모두 훅 로그에서 기계적으로 나온다 — 에이전트의 자기 판단에 의존하지 않는다.
(council에서 기각된 지표: "API/env/auth를 건드린 변경의 비율" — 그 분류를 에이전트가 해야
하는데, 그 분류 실패가 애초의 문제다. 자기 자신을 측정 도구로 쓰는 지표는 항상 통과한다.)
