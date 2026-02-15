# Relations Rules — 메모리 관계 관리

메모리 간 관계 생성, 조회, 삭제 가이드.

---

## 관계 타입 (7종)

| 타입 | 용도 |
|------|------|
| `related` | 일반 연관 (기본) |
| `parent` | 상위 개념 |
| `child` | 하위 개념 |
| `supersedes` | 이전 내용 대체 |
| `references` | 참조/인용 |
| `depends_on` | 의존성 |
| `similar` | 유사 내용 |

---

## link — 관계 생성

```
link(source_id, target_id, relation_type="related", strength=1.0, metadata={})
```

- `strength`: 0.0~1.0 (기본 1.0)
- `metadata`: 선택적 메타데이터
- 이미 존재하면 `created: false` 반환

---

## get_links — 관계 조회

```
get_links(memory_id, relation_type, direction, limit=20)
```

- `direction`: `outgoing` | `incoming` | `both` (기본)
- `relation_type`: 특정 타입만 필터

---

## unlink — 관계 삭제

```
unlink(source_id, target_id, relation_type)
```

- `relation_type` 생략 시 두 메모리 간 모든 관계 삭제

---

## 사용 시나리오

- **버그 수정**: 원인 메모리와 `references` 연결
- **결정 업데이트**: 이전 결정과 `supersedes` 연결
- **의존성**: `depends_on` 연결
- **유사 패턴**: `similar` 연결
