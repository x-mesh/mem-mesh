# mem-mesh Rules (All Tools Full)

이 규칙은 특정 IDE/툴에 의존하지 않는 범용 버전입니다.  
툴에서 제공하는 mem-mesh 호출 이름에 맞게 함수명만 치환해서 사용하세요.

## 1) 세션 맥락 유지 (Token 최적화)
1. 세션 시작 시 **요약만** 로드  
   - `session_resume(project_id, expand=false, limit=10)`
2. 새 작업 시작/컨텍스트 전환 시 검색  
   - `search(query, project_id, limit=3~5)`
3. 검색 결과가 중요할 때만 확장  
   - `context(memory_id, depth=2)`
4. 세션 내 반복 호출 금지 (최소 TTL 권장)

## 2) 작업 추적 (Pins)
- 작업 시작: `pin_add(project_id, content, importance=1~5, tags)`
- 작업 완료: `pin_complete(pin_id)`
- 중요도 4 이상: `pin_promote(pin_id)` 제안

## 3) 메모리 저장 (Triggers)
즉시 저장해야 하는 이벤트:
- 버그 진단/해결 완료 → `category="bug"`
- 아키텍처/트레이드오프 결정 → `category="decision"`
- 재사용 코드/패턴 작성 → `category="code_snippet"`
- 중요 요구사항/작업 이정표 완료 → `category="task"`
- 사고/장애 → `category="incident"`

기존 내용을 대체하면 `update(old_id)`로 업데이트하고 **중복 저장 금지**.

## 4) 저장 포맷 (WHY/WHAT/IMPACT)
```
## [한 줄 요약 제목]

### 배경 (WHY)
[문제/컨텍스트]

### 내용 (WHAT)
- 파일: `relative/path` - [주요 변경]
- 파일: `relative/path2` - [주요 변경]

### 영향 (IMPACT)
[효과/주의사항]
```

## 5) 태그 규칙
3~6개 필수. 반드시 포함:
- 기술 스택 (예: Python, FastAPI, SQLite)
- 모듈/영역 (예: API, Search, Database)
- 액션 타입 (예: Fix, Feature, Refactor)

## 6) 보안/정직성
- 비밀/토큰/PII/절대 경로 저장 금지
- 툴 성공 전 “저장 완료” 언급 금지
- 실패 시 의도한 payload를 그대로 제공

## 7) 팀 맥락 유지
- 결정/사고/재사용 패턴 중심으로 저장
- Q/A 전체 저장은 최소화 (노이즈 증가)

## 8) 프로젝트 목적 보장
- long term memory: 결정/버그/스니펫 위주
- 검색: 태그/카테고리 정합성 유지
- 맥락 유지: 핀 요약 우선
- 멀티 머신/IDE: 세션 요약 + 열린 pin
