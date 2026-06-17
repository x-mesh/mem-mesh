# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
