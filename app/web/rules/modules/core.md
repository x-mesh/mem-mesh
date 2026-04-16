# Core Rules — 핵심 워크플로우

mem-mesh MCP 사용의 기본 사이클.

---

## 검색 → 작업 → 저장 사이클

```
1. search(query, project_id, limit=5)     # 작업 시작/전환 시
2. [작업 수행]
3. add(content, category, project_id, tags) # 트리거 발생 시
```

---

## 필수 규칙

1. **작업 시작/전환 전** `search(query, project_id, limit=3~5)` 호출
2. **필요할 때만** `context(memory_id, depth=2)` — 검색 결과가 실제 작업에 중요할 때
3. **저장 트리거** 발생 시 즉시 `add(...)` 호출
4. **중복 방지**: 대체 시 `update(memory_id, ...)` 사용

---

## 프로젝트 감지

- 디렉토리명 → `project_id`: `/path/to/my-app` → `project_id="my-app"`
- 명시적 지정: `project_id="custom-project"`

---

## 핵심 도구 5개

| 도구 | 용도 |
|------|------|
| `search` | 관련 기억 검색 |
| `add` | 기억 저장 |
| `context` | 메모리 연관 컨텍스트 확장 |
| `update` | 기존 메모리 수정 |
| `session_resume` | 세션 맥락 로드 |
