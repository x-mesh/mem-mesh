# mem-mesh Minimal Prompt

mem-mesh MCP 서버(`https://meme.24x365.online/mcp/sse`)를 사용하여 작업 기억을 관리합니다.

## 규칙
1. **작업 시작 전**: `search(query, project_id, limit=5)`로 관련 기억 확인
2. **문제 해결 후**: `add(content, project_id, category, tags)`로 Q&A 형식 저장
3. **중복 방지**: 동일 content+project_id는 자동 스킵됨

## 저장 형식
```
Q: [문제/질문]

A: [해결책/답변]
- 핵심: ...
- 코드: `...`
```

## 카테고리
task | bug | idea | decision | code_snippet
