# Rules 패키지 (AI 에이전트용)

AI 에이전트가 mem-mesh MCP 도구를 효과적으로 사용하기 위한 규칙 묶음.  
IDE system prompt, rules 파일, 또는 API로 주입.

---

## 구성

### 통합 문서

| 파일 | 용도 | 토큰 |
|------|------|------|
| **`DEFAULT_PROMPT.md`** | **기본 행동 규칙 — 프로젝트에 복사하여 사용** | **~600** |
| `all-tools-full.md` | 전체 규칙 (15개 도구, 검색/저장/세션/관계/배치) | ~1500 |
| `mem-mesh-ide-prompt.md` | IDE용 컴팩트 프롬프트 | ~300 |
| `mem-mesh-session-rules.md` | 세션 라이프사이클 상세 | ~200 |
| `mem-mesh-mcp-guide.md` | MCP 통합 가이드 (Quick Reference) | ~200 |
| `index.json` | 규칙 메타데이터 (API/헬퍼 참조) | - |

### 기능별 모듈 (modules/)

| 모듈 | 내용 | 관련 통합 문서 섹션 |
|------|------|---------------------|
| `core.md` | 검색→작업→저장 사이클, 프로젝트 감지 | all-tools-full §2 |
| `search.md` | 쿼리 작성법, E5/RRF/sigmoid 상세 | all-tools-full §4 |
| `memory-log.md` | 저장 트리거, WHY/WHAT/IMPACT 포맷, 태그 | all-tools-full §5 |
| `pins.md` | 세션 라이프사이클, 토큰 최적화 | all-tools-full §3 |
| `relations.md` | 7가지 관계 타입, link/unlink/get_links | all-tools-full §6 |
| `batch.md` | batch_operations, 토큰 절약 | all-tools-full §7 |
| `security.md` | PII/비밀 저장 금지, 정직성 원칙 | all-tools-full §10 |
| `team-context.md` | 팀 저장 전략 | all-tools-full §11 |
| `api-usage.md` | REST API 엔드포인트 | all-tools-full §12 |
| `quick-start.md` | MCP 설정 → 첫 검색/저장 (5분) | - |
| `minimal.md` | 최소 규칙 (~100 토큰) | - |

---

## 사용 방법

### 1) 전체 규칙
`all-tools-full.md`를 IDE rules 또는 system prompt에 주입

### 2) IDE 컴팩트 버전
`mem-mesh-ide-prompt.md` 내 코드 블록 복사 → Cursor/Windsurf/Claude Code

### 3) 모듈 선택
`modules/*.md` 중 필요한 것만 조합:
- `core.md` — 핵심 워크플로우
- `search.md` — 검색 최적화 (E5, RRF, sigmoid)
- `memory-log.md` — 저장 가이드 (트리거, 포맷, 태그)
- `pins.md` — 세션 & 핀
- `relations.md` — 메모리 관계
- `batch.md` — 배치 작업
- `security.md` — 보안
- `team-context.md` — 팀 저장 전략
- `api-usage.md` — REST API
- `minimal.md` — 최소 (~100 토큰)
- `quick-start.md` — 5분 가이드

### 4) 헬퍼 스크립트
```bash
python scripts/generate_rules_bundle.py --list
python scripts/generate_rules_bundle.py --ids core,search,pins --output my-rules.md
```

---

## API

- 목록: `GET /api/rules`
- 조회: `GET /api/rules/{rule_id}`
- 수정: `PUT /api/rules/{rule_id}` (content 필수)

---

## 레거시: mcp_prompts/

`mcp_prompts/` 폴더의 파일들은 **레거시**입니다.

| 파일 | 상태 | 대체 |
|------|------|------|
| `optimized_search.md` | 레거시 | `modules/search.md` |
| `auto_project_prompt.md` | 레거시 | `mem-mesh-ide-prompt.md`, `modules/core.md` |

**권장**: 새 규칙은 `docs/rules/` 사용. `mcp_prompts/`는 참고용으로만 유지하거나 삭제 가능.
