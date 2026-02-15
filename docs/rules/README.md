# Rules 패키지 (AI 에이전트용)

AI 에이전트가 mem-mesh MCP 도구를 효과적으로 사용하기 위한 규칙 묶음.  
IDE system prompt, rules 파일, 또는 API로 주입.

---

## 구성

| 파일 | 용도 |
|------|------|
| `all-tools-full.md` | 전체 규칙 (16개 도구, 검색/저장/세션/관계/배치) |
| `mem-mesh-ide-prompt.md` | IDE용 컴팩트 프롬프트 (~300 토큰) |
| `mem-mesh-session-rules.md` | 세션 라이프사이클 상세 |
| `mem-mesh-mcp-guide.md` | MCP 통합 가이드 |
| `modules/*.md` | 기능별 모듈 |
| `index.json` | 규칙 메타데이터 (API/헬퍼 참조) |

---

## 사용 방법

### 1) 전체 규칙
`all-tools-full.md`를 IDE rules 또는 system prompt에 주입

### 2) IDE 컴팩트 버전
`mem-mesh-ide-prompt.md` 내 코드 블록 복사 → Cursor/Windsurf/Claude Code

### 3) 모듈 선택
`modules/*.md` 중 필요한 것만 조합:
- `core.md` — 핵심 워크플로우
- `search.md` — 검색 최적화
- `memory-log.md` — 저장 가이드
- `pins.md` — 세션 & 핀
- `relations.md` — 메모리 관계
- `batch.md` — 배치 작업
- `security.md` — 보안
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
