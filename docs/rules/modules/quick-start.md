# mem-mesh Quick Start (5분)

MCP 설정부터 첫 검색/저장까지.

---

## 1. MCP 설정 (1분)

### Cursor / Claude Desktop / Windsurf

```json
{
  "mcpServers": {
    "mem-mesh": {
      "url": "http://your-server/mcp/sse"
    }
  }
}
```

또는 stdio:
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio"]
    }
  }
}
```

---

## 2. 첫 검색 (1분)

```
search(query="프로젝트 관련 키워드", project_id="프로젝트명", limit=5)
```

- `project_id`: 현재 디렉토리명 또는 프로젝트 ID
- 쿼리는 구문 사용 (단일 단어 금지)

---

## 3. 첫 저장 (2분)

```
add(
  content="## 제목\n\n### 배경\n...\n### 내용\n...\n### 영향\n...",
  project_id="프로젝트명",
  category="bug",
  tags=["Python", "API", "Fix"]
)
```

또는 Q&A 형식:
```
Q: 문제 설명
A: 해결 방법
- 핵심: ...
- 코드: `...`
```

---

## 4. 세션 관리 (선택, 1분)

```
session_resume(project_id="프로젝트명", expand="smart")
pin_add(content="현재 작업", project_id="프로젝트명", importance=3)  # 기본 상태: in_progress
pin_complete(pin_id="...", promote=true)  # 완료+승격 한 번에 처리
```

---

## 카테고리

`task` | `bug` | `idea` | `decision` | `code_snippet` | `incident` | `git-history`

---

## 다음 단계

- 전체 규칙: `docs/rules/all-tools-full.md`
- 검색 최적화: `docs/rules/modules/search.md`
- 저장 가이드: `docs/rules/modules/memory-log.md`
