# mem-mesh

[![PyPI version](https://img.shields.io/pypi/v/mem-mesh.svg)](https://pypi.org/project/mem-mesh/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP Protocol](https://img.shields.io/badge/MCP-2024--11--05%20%7C%202025--03--26-green.svg)](https://modelcontextprotocol.io/)

> AI 코딩 도구를 위한 지속 메모리 — 이어서 복원하는 세션 상태, git에는 남지 않는 결정 맥락, 그리고 가정이 아니라 계측으로 검증하는 주입. 단일 SQLite 파일, 외부 서비스 불필요.

[English](./README.md)

## 목차

- [mem-mesh란?](#mem-mesh란) · [Quick Start](#quick-start) · [MCP 설정](#mcp-설정) · [MCP 도구](#mcp-도구) · [검색](#검색) · [세션 & 핀](#세션--핀) · [메모리 관계](#메모리-관계) · [웹 대시보드](#웹-대시보드) · [설정](#설정) · [Docker](#docker) · [최초 실행 설정](#최초-실행-설정-대시보드-인증) · [개발](#개발) · [아키텍처](#아키텍처) · [문서](#문서)

---

## mem-mesh란?

mem-mesh는 "과거 세션을 검색하면 코딩 성능이 오른다"고 주장하지 않습니다. 그 효용은 계측해서 데이터로 판단하는 가설로 다룹니다([계측으로 검증](#계측으로-검증)). mem-mesh의 근거는 git·PR·잘 관리된 문서가 담지 못하는 세 가지입니다.

- **세션 간 작업 상태 복원** — `pin_add` / `pin_complete`로 작업 단위를 추적하고, `session_resume`이 지난 세션이 멈춘 지점을 복원합니다. "어디까지 했더라"에 바로 답합니다.
- **git에 남지 않는 지식** — 결정의 *왜*, 시도했다 실패한 접근(반복하지 않을 부정적 결과), 장애에서 배운 운영 제약. 커밋·PR·설계 문서가 잘 관리돼도 이 지식은 아티팩트에 남지 않습니다. 카테고리와 타입 관계(`supersedes` 등)로 대체된 결정이 새 결정에 연결됩니다.
- **관측성·회고** — `weekly_review`, 대시보드, 팀 relay가 에이전트가 무엇을 기록·조회했고 무엇이 stale해졌는지 보여줍니다.

MCP(Model Context Protocol)를 통해 메모리 추가·검색, 세션·핀 관리, 관계 연결, 배치 연산, 주입 계측, 문서 승격을 지원합니다.

### 계측으로 검증

"과거 세션 검색이 코딩 성능을 올린다"는 주장은 단정하지 않고 계측합니다. 주입된 모든 메모리는 `injected_memories`에 기록되고(턴당 1행), LLM을 쓰지 않는 Stop 시점 휴리스틱이 이후 실제로 참조됐는지 판정하며, `weekly_review`가 주입 적중률을 보고합니다. 오프라인에서는 `scripts/replay_injection_eval.py`가 실제로 수집된 프롬프트를 레거시·현행 주입 포맷으로 다시 렌더링해 결정적 지표와 선택적 블라인드 LLM 심판으로 양쪽을 채점합니다. 전제는 정직합니다 — 현행 포맷이 이점을 보이지 않으면 주입을 축소하는 것이 타당한 결론입니다. 커밋·PR·문서가 이미 잘 관리된 repo의 순수 코드 작업에서 과거 *세션* 검색의 한계 효용은 검증 대상이며, mem-mesh는 그 검증 도구를 내장합니다. 위 세 가지 근거는 이 측정 결과와 무관하게 성립합니다.

### 주요 기능

- **메모리 CRUD**: add, search, context, update, delete
- **하이브리드 검색**: 벡터 + FTS5 RRF 융합, 한국어 n-gram 최적화
- **세션 & 핀**: 단기 작업 추적, 중요도 기반 영구 메모리 승격
- **주입 계측**: injected_memories 추적 + Stop 시점 사용 판정 + weekly_review 주입 통계, 오프라인 replay 하네스로 주입 효용 검증
- **git 앵커 수명 관리**: 커밋·파일 앵커 + 클라이언트 stale 검증, stale 메모리는 주입에서 제외
- **문서 승격 (사람 승인)**: doc_proposal로 메모리를 버전 관리 문서로 승격 (LLM 초안, 사람 승인, 클라이언트 적용)
- **자동 마스킹**: 자동 수집 콘텐츠의 시크릿/PII를 결정적으로 `<REDACTED>` 치환
- **메모리 관계**: link, unlink, get_links (7가지 관계 타입)
- **배치 연산**: 30–50% 토큰 절감
- **웹 대시보드**: FastAPI 기반 REST API + 실시간 UI

---

## Quick Start

### 사전 요구사항

mem-mesh는 `sqlite-vec` 확장을 런타임에 로드하므로, Python의 `sqlite3` 모듈이 **loadable extension** 을 지원해야 합니다.

**macOS + pyenv 사용자**: pyenv 의 기본 빌드는 extension loading이 꺼져 있어 `Migration failed: no such module: vec0` 오류가 발생합니다. 다음 중 하나를 선택하세요.

```bash
# 옵션 A (권장): Homebrew sqlite3 와 함께 Python 재빌드
brew install sqlite3
SQLITE_PREFIX="$(brew --prefix sqlite3)"
PYTHON_CONFIGURE_OPTS="--enable-loadable-sqlite-extensions" \
LDFLAGS="-L${SQLITE_PREFIX}/lib" \
CPPFLAGS="-I${SQLITE_PREFIX}/include" \
CFLAGS="-I${SQLITE_PREFIX}/include" \
  pyenv install 3.13 --force
pyenv rehash

# 옵션 B: pysqlite3 바이너리 휠로 우회 (코드의 fallback 자동 사용)
pip install pysqlite3-binary
```

Linux 배포판 Python, Docker 이미지, conda Python 은 일반적으로 extension loading 이 활성화돼 있어 추가 조치가 필요 없습니다.

### 설치 및 실행

```bash
# 1. 클론 및 설치
git clone https://github.com/x-mesh/mem-mesh
cd mem-mesh
pip install -e .

# 2. 환경 설정 (선택)
cp .env.example .env

# 3. 웹 서버 실행
python -m app.web --reload
```

브라우저에서 http://localhost:8000 접속. SSE MCP 엔드포인트: `http://localhost:8000/mcp/sse`

---

## MCP 설정

### Stdio (AI 도구 연동)

AI 도구에서 mem-mesh를 사용하려면 MCP 설정 파일에 다음을 추가하세요.

**권장 설정 (한 번만 정의):**

```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio"],
      "cwd": "/절대/경로/to/mem-mesh",
      "env": {
        "MCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

### 도구별 설정 파일 위치

| 도구 | 설정 파일 |
|------|-----------|
| Cursor | `.cursor/mcp.json` |
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Kiro | `~/.kiro/settings/mcp.json` |

### Stdio vs SSE

| 항목 | Stdio | SSE |
|------|-------|-----|
| 사용처 | Cursor, Claude, Kiro 등 로컬 AI 도구 | 웹 기반 AI, 커스텀 클라이언트 |
| 실행 | `python -m app.mcp_stdio` | `python -m app.web --reload` 후 `http://localhost:8000/mcp/sse` |
| 프로토콜 | stdio JSON-RPC | Streamable HTTP (2025-03-26) |

**Pure MCP 프로토콜** (더 안정적인 stdio): `args`를 `["-m", "app.mcp_stdio_pure"]`로 변경

---

## MCP 도구 (15개)

| 도구 | 설명 | 주요 파라미터 |
|------|------|---------------|
| `add` | 메모리 추가 | content, project_id, category, tags |
| `search` | 하이브리드 검색 | query, project_id, category, limit, recency_weight, response_format |
| `context` | 메모리 주변 맥락 조회 | memory_id, depth, project_id |
| `update` | 메모리 수정 | memory_id, content, category, tags |
| `delete` | 메모리 삭제 | memory_id |
| `stats` | 통계 조회 | project_id, start_date, end_date |
| `link` | 메모리 간 관계 생성 | source_id, target_id, relation_type |
| `unlink` | 관계 제거 | source_id, target_id |
| `get_links` | 관계 조회 | memory_id, relation_type, direction |
| `pin_add` | 단기 작업 핀 추가 | content, project_id, importance, tags |
| `pin_complete` | 핀 완료 (promote=true로 승격 병합) | pin_id, promote, category |
| `pin_promote` | 핀을 영구 메모리로 승격 | pin_id, category |
| `session_resume` | 프로젝트 세션 재개 | project_id, expand, limit |
| `session_end` | 세션 종료 | project_id, summary, auto_complete_pins |
| `batch_operations` | 다중 연산 (토큰 절감) | operations (add/search/pin_add/pin_complete 배열) |

**search** `response_format`: `minimal` | `compact` | `standard` | `full`

---

## 검색

- **하이브리드**: 벡터(sentence-transformers) + FTS5 RRF 융합
- **한국어**: n-gram FTS, E5 모델 prefix, sigmoid 정규화
- **품질**: 노이즈 필터, 의도 분석, 벡터 pre-filter overfetch
- **임베딩**: 기본 `all-MiniLM-L6-v2` (384차원), E5 모델 지원

---

## 세션 & 핀

### 세션 생명주기

```
session_resume(project_id, expand="smart")  →  작업  →  session_end(project_id, summary)
```

- `session_resume`: 이전 세션의 미완료 핀과 맥락을 복원. Stale 핀 자동 정리 포함. `expand="smart"`는 중요도×상태 기반 선택적 로드로 ~60% 토큰 절감.
- `session_end`: 완료 작업 요약과 함께 세션 마감. 비정상 종료 시 다음 `session_resume`이 미완료 핀을 자동 복원.

### 핀(Pin) 생명주기

핀은 세션 내 **작업 추적 단위**입니다. AI 에이전트가 코드 변경, 구현, 설정 작업 시 핀으로 추적합니다.

```
pin_add(content, project_id)  →  작업 수행  →  pin_complete(pin_id, promote=true)
                                                 (promote=true로 완료+승격을 한 번에 처리)
```

**상태(status):** `open`(계획됨, 미착수) → `in_progress`(작업 중, **pin_add 기본값**) → `completed`(완료)
- 다단계 작업에서 나중 작업은 `open` 상태로 미리 등록 가능

**Stale 자동 정리:** `session_resume` 호출 시 오래된 핀을 자동 완료 처리
- `in_progress` 상태 7일 경과 → `completed`
- `open` 상태 30일 경과 → `completed`

**핀 생성 기준:** 파일이 변경되는 작업만 pin. 질문·설명·조회는 pin 불필요. 다단계 작업은 단계별 pin.

**중요도(importance):**
- `5`: 아키텍처 결정, 핵심 설계 변경
- `3–4`: 기능 구현, 주요 수정
- `1–2`: 단순 수정, 오타 수정
- 생략 시 내용 기반 자동 추정

**승격(promote):** `pin_complete(pin_id, promote=true)`로 완료와 승격을 한 번에 처리. 이미 완료된 핀은 `pin_promote`로 별도 승격 가능.

**클라이언트 감지:** HTTP 모드에서 MCP initialize 핸드셰이크 또는 User-Agent 헤더로 자동 감지 (25+ IDE/AI 플랫폼 지원). Stdio 모드에서는 `MEM_MESH_CLIENT` 환경변수 사용.

### AI 에이전트 사용 체크리스트

```
1. 세션 시작  → session_resume(project_id, expand="smart")
2. 과거 맥락  → 이전 결정/작업 언급 시 search() 후 코딩
3. 작업 추적  → pin_add → pin_complete(promote=true로 승격 병합 가능)
4. 영구 저장  → decision / bug / incident / idea / code_snippet 만
5. 세션 종료  → session_end(project_id, summary, auto_complete_pins=true)
6. 보안 금지  → API키 / 토큰 / 비밀번호 / PII 절대 저장 금지
```

> **원칙**: Hook은 상태 표시/리마인더만 수행(읽기 전용). 모든 핀 생성·완료·승격은 AI(LLM)가 문맥을 이해하고 판단합니다.

- **보안**: API키, 토큰, PII는 메모리에 저장되지 않으며, 민감 값은 `<REDACTED>` 치환

---

## 메모리 관계

- **link**: `related` | `parent` | `child` | `supersedes` | `references` | `depends_on` | `similar`
- **get_links**: `direction`: `outgoing` | `incoming` | `both`

---

## 웹 대시보드

- **URL**: http://localhost:8000
- **API 문서**: http://localhost:8000/docs
- **헬스체크**: http://localhost:8000/health

---

## 설정

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `MEM_MESH_DATABASE_PATH` | SQLite DB 경로 | `./data/memories.db` |
| `MEM_MESH_EMBEDDING_MODEL` | 임베딩 모델 | `all-MiniLM-L6-v2` |
| `MEM_MESH_EMBEDDING_DIM` | 벡터 차원 | `384` |
| `MEM_MESH_SERVER_PORT` | 웹 서버 포트 | `8000` |
| `MEM_MESH_SEARCH_THRESHOLD` | 검색 임계값 | `0.5` |
| `MEM_MESH_USE_UNIFIED_SEARCH` | 통합 검색 활성화 | `true` |
| `MEM_MESH_ENABLE_KOREAN_OPTIMIZATION` | 한국어 최적화 | `true` |
| `MCP_LOG_LEVEL` | MCP 로그 레벨 | `INFO` |
| `MCP_LOG_FILE` | MCP 로그 파일 | (미설정) |

전체 옵션은 `.env.example` 참조.

---

## Docker

```bash
# 빌드 및 실행
make quickstart
# 또는: make docker-build && make docker-up

# 접속: http://localhost:8000
```

---

## 최초 실행 설정 (대시보드 인증)

대시보드 인증이 **설정되지 않은 상태**로 서버가 뜨면 포트에 접근 가능한 누구나 모든 메모리를 읽기/쓰기/삭제할 수 있다. 셸 없이 브라우저에서 바로 잠글 수 있도록, mem-mesh는 첫 기동 시 **일회용 setup token**을 발급해 서버 콘솔에 출력한다:

```
============================================================
  FIRST-RUN SETUP  —  dashboard auth is NOT configured
============================================================
  Open : /setup
  Token: <one-time-token>
  (one-time — consumed the moment you finish setup)
============================================================
```

`Open`은 기본적으로 경로 `/setup`만 출력한다 — 서버를 바인딩한 host:port로 접속하면 된다. `MEM_MESH_PUBLIC_URL`을 설정하면 배너에 전체 URL(예: `https://your-host/setup`)이 출력된다.

토큰은 DB 옆(`/app/data/setup_token`)에도 기록되어 온보딩 도중 재시작에도 살아남는다. 언제든 확인:

```bash
docker exec mem-mesh-prod cat /app/data/setup_token
# 또는 로그에서
docker compose logs mem-mesh | grep -A1 "Token:"
```

`/setup`에 접속해 토큰 + 관리자 **username**(기본 `admin`) + **password**(8자 이상)를 입력한다. 제출하면 자격증명을 저장하고 Basic Auth를 켠 뒤 **토큰을 소비**(1회용)하고 대시보드로 자동 로그인시킨다. 새 서버의 첫 페이지 로드는 `/setup`으로 자동 리다이렉트된다.

인증이 설정된 뒤에는 매 기동 시 토큰이 삭제되므로, 남아있는 토큰으로 이미 잠긴 서버를 다시 설정하는 일은 불가능하다.

**토큰 리셋** (분실했고 아직 인증 미설정인 경우) — `ensure_setup_token()`은 idempotent라 그냥 재시작하면 같은 값이 유지되므로, 파일을 지우고 재시작해야 새 토큰이 발급된다:

```bash
docker exec mem-mesh-prod rm -f /app/data/setup_token
docker restart mem-mesh-prod
docker logs mem-mesh-prod 2>&1 | grep -A1 "Token:"
```

---

## 개발

```bash
# 의존성 (개발)
pip install -e ".[dev]"

# 테스트
python -m pytest tests/ -v

# 포맷/린트
black app/ tests/
ruff check app/ tests/

# 마이그레이션 확인
python scripts/migrate_embeddings.py --check-only
```

---

## 아키텍처

```mermaid
flowchart LR
    subgraph Clients
        Cursor[Cursor]
        Claude[Claude Desktop]
        Kiro[Kiro]
        Web[Web Client]
    end

    subgraph Transport
        Stdio[Stdio MCP]
        SSE[SSE MCP]
    end

    subgraph Core
        MCP[mcp_common]
        Storage[Storage]
    end

    subgraph Data
        SQLite[(SQLite + sqlite-vec + FTS5)]
    end

    Cursor --> Stdio
    Claude --> Stdio
    Kiro --> Stdio
    Web --> SSE
    Stdio --> MCP
    SSE --> MCP
    MCP --> Storage
    Storage --> SQLite
```

### 디렉토리 구조

```
mem-mesh/
├── app/
│   ├── core/              # DB, 임베딩, 서비스, 스키마
│   ├── mcp_common/        # 공통 MCP 도구, 디스패처, 배치
│   ├── mcp_stdio/         # FastMCP stdio 서버
│   ├── mcp_stdio_pure/    # Pure MCP stdio 서버
│   └── web/               # FastAPI (대시보드, SSE MCP, OAuth, WebSocket)
├── static/                # 프론트엔드 (Vanilla JS, Web Components)
├── tests/                 # pytest
├── scripts/               # 마이그레이션, 벤치마크
├── docs/rules/            # AI 에이전트 규칙 모듈
├── data/                  # memories.db
└── logs/
```

---

## 문서

- [CLAUDE.md](./CLAUDE.md) — AI 도구 Checklist (MUST/SHOULD/MAY 규칙, 보안 정책)
- [AGENTS.md](./AGENTS.md) — 프로젝트 컨텍스트, Golden Rules, Context Map, 세션 관리 상세

### AI 에이전트 규칙

| 문서 | 용도 |
|------|------|
| [DEFAULT_PROMPT.md](./app/web/rules/DEFAULT_PROMPT.md) | 설치 hook 없이 MCP만 쓸 때 복사하는 기본 행동 규칙 |
| [modules/](./app/web/rules/modules/) | Rule Manager 보조 모듈: core, search, memory-log, pins, relations, batch, security |

설치 hook과 같은 버전의 규칙은 CLI로 출력:

```bash
mem-mesh hooks rules --project-id <project-id> --format plain
mem-mesh hooks rules --project-id <project-id> --format claude
```

### 아키텍처 문서

- [app/core/AGENTS.md](./app/core/AGENTS.md) — Core 서비스
- [app/mcp_common/AGENTS.md](./app/mcp_common/AGENTS.md) — MCP 공통 로직

---

## 기여

1. 이슈/PR 생성
2. `black`, `ruff` 준수
3. 테스트 추가

자세한 내용은 [CONTRIBUTING.md](./CONTRIBUTING.md)를, 릴리즈 히스토리는 [CHANGELOG.md](./CHANGELOG.md)를 참조하세요.

---

## 라이선스

[MIT](./LICENSE)
