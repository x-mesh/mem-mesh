# Rules 패키지 (외부 툴용)

이 폴더는 Kiro 외부 툴 사용자를 위한 규칙 묶음입니다.  
필요한 규칙만 골라 복붙하거나, 헬퍼 스크립트로 번들링하세요.

## 구성
- `all-tools-full.md`: 모든 기능을 포함한 전체 규칙
- `modules/*.md`: 세부 기능별 규칙 모듈
- `index.json`: 규칙 메타데이터 (API/헬퍼 스크립트가 참조)

## 사용 방법
### 1) 전체 규칙
`docs/rules/all-tools-full.md`를 그대로 사용

### 2) 모듈 선택
`docs/rules/modules/*.md` 중 필요한 것만 복붙

### 3) 헬퍼 스크립트
```bash
python scripts/generate_rules_bundle.py --list
python scripts/generate_rules_bundle.py --ids core,search,pins --output my-rules.md
```

## API
- 목록: `GET /api/rules`
- 조회: `GET /api/rules/{rule_id}`
- 수정: `PUT /api/rules/{rule_id}`
