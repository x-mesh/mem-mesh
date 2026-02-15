# Batch Rules — 배치 작업

여러 작업을 한 번에 처리하여 토큰을 절약.

---

## batch_operations

```
batch_operations(operations=[
  {"type": "add", "content": "...", "project_id": "...", "category": "task", "tags": [...]},
  {"type": "search", "query": "...", "project_id": "...", "limit": 5}
])
```

---

## 지원 작업 타입

- **add**: 메모리 저장 (content, project_id, category, tags)
- **search**: 메모리 검색 (query, project_id, limit)

---

## 토큰 절약

- add + search 조합 시 **30~50% 토큰 절약**
- 여러 검색/저장을 한 요청으로 처리

---

## 예시

```
batch_operations(operations=[
  {"type": "search", "query": "이전 버그 수정", "project_id": "my-app", "limit": 3},
  {"type": "add", "content": "## 버그 수정\n\n### 배경\n...", "project_id": "my-app", "category": "bug", "tags": ["Fix", "API"]}
])
```
