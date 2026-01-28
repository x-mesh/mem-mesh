# mem-mesh Quick Start

## MCP 설정
```json
{
  "mcpServers": {
    "mem-mesh": {
      "url": "http://localhost:8000/mcp/sse"
    }
  }
}
```

## 핵심 도구 3개
| 도구 | 용도 | 예시 |
|------|------|------|
| `search` | 기억 검색 | `search(query="에러 해결", project_id="my-app", limit=5)` |
| `add` | 기억 저장 | `add(content="Q: ...\nA: ...", project_id="my-app", category="bug", tags=["error"])` |
| `stats` | 통계 확인 | `stats(project_id="my-app")` |

## 사용 패턴

### 1. 작업 시작 시
```
search(query="현재 작업 관련 키워드", project_id="프로젝트명", limit=5)
```

### 2. 문제 해결 후
```
add(
  content="Q: 문제 설명\n\nA: 해결 방법\n- 핵심: ...\n- 코드: `...`",
  project_id="프로젝트명",
  category="bug",  # task, bug, idea, decision, code_snippet
  tags=["관련", "키워드"]
)
```

### 3. 세션 관리 (선택)
```
session_resume(project_id="프로젝트명")  # 이전 작업 확인
pin_add(content="현재 작업", project_id="프로젝트명")  # 작업 추적
pin_complete(pin_id="...")  # 완료 표시
```

## 카테고리
- `task`: 일반 작업
- `bug`: 버그/에러 해결
- `idea`: 아이디어
- `decision`: 결정 사항
- `code_snippet`: 코드 조각

## 팁
- 검색 먼저, 저장은 가치 있는 것만
- Q&A 형식으로 저장하면 검색 효율 ↑
- 태그는 영어 소문자, kebab-case 권장
