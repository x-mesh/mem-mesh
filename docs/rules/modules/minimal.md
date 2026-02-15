# mem-mesh Minimal Prompt (~100 tokens)

```
mem-mesh MCP로 작업 기억 관리.

1. 작업 시작 전: search(query, project_id, limit=5)
2. 문제 해결 후: add(content, project_id, category, tags) — Q&A 형식
3. 중복 방지: update(memory_id) 사용

포맷: Q: [질문]\nA: [답변]\n- 핵심: ...
카테고리: task | bug | idea | decision | code_snippet
```
