# Kiro Hooks for mem-mesh Integration

이 디렉토리에는 mem-mesh와 Kiro를 연동하기 위한 Hook 설정들이 포함되어 있습니다.

## 자동 저장 Hooks (Auto-Save)

### 1. auto-save-code-changes.kiro.hook
- **트리거**: 코드 파일 저장 시 (`fileSaved`)
- **대상**: Python, JavaScript, TypeScript 등 코드 파일
- **기능**: 코드 변경사항을 자동으로 mem-mesh에 저장
- **카테고리**: `code_snippet`

### 2. auto-save-errors.kiro.hook
- **트리거**: 에러/버그 관련 키워드 감지 시
- **키워드**: error, bug, exception, failed, 에러, 버그 등
- **기능**: 에러 해결 과정을 자동 저장
- **카테고리**: `bug`

### 3. auto-save-decisions.kiro.hook
- **트리거**: 설계/결정 관련 키워드 감지 시
- **키워드**: decided, decision, architecture, design, 결정 등
- **기능**: 중요한 설계 결정사항을 자동 저장
- **카테고리**: `decision`

### 4. auto-save-task-completion.kiro.hook
- **트리거**: 작업 완료 관련 키워드 감지 시
- **키워드**: 완료, 구현, finished, completed, done 등
- **기능**: 완료된 작업 내용을 자동 저장
- **카테고리**: `task`

### 5. auto-save-ideas.kiro.hook
- **트리거**: 아이디어/제안 관련 키워드 감지 시
- **키워드**: idea, suggest, 아이디어, 제안, 개선 등
- **기능**: 새로운 아이디어나 제안사항을 자동 저장
- **카테고리**: `idea`

### 6. auto-save-tests.kiro.hook
- **트리거**: 테스트 관련 키워드 감지 시
- **키워드**: test, testing, 테스트, unittest, pytest 등
- **기능**: 테스트 작성 및 결과를 자동 저장
- **카테고리**: `code_snippet`

### 7. auto-save-performance.kiro.hook
- **트리거**: 성능 최적화 관련 키워드 감지 시
- **키워드**: performance, optimization, 성능, 최적화 등
- **기능**: 성능 개선 작업을 자동 저장
- **카테고리**: `code_snippet`

## 수동 실행 Hooks (Manual Triggers)

### 8. manual-save-memmesh.kiro.hook
- **트리거**: 수동 버튼 클릭
- **기능**: 현재 대화를 수동으로 mem-mesh에 저장
- **프로젝트 ID**: `kiro-manual-saves`

### 9. manual-search-memories.kiro.hook
- **트리거**: 수동 버튼 클릭
- **기능**: 현재 대화와 관련된 메모리를 검색
- **용도**: 과거 작업 내용 참조

### 10. show-project-stats.kiro.hook
- **트리거**: 수동 버튼 클릭
- **기능**: 프로젝트의 mem-mesh 통계 조회
- **용도**: 프로젝트 진행 상황 파악

## 세션 관리 Hooks

### 11. load-project-context.kiro.hook
- **트리거**: 수동 실행 (원래는 sessionStart 예정)
- **기능**: 프로젝트 관련 최근 작업들을 자동 로드
- **용도**: 컨텍스트 연속성 유지

### 12. session-summary-hook.kiro.hook
- **트리거**: 키워드 자동 감지 (`messageSent`)
- **키워드**: "세션 요약", "세션 종료", "작업 완료", "session summary", "done for today" 등
- **기능**: 세션 요약을 자동으로 mem-mesh에 저장
- **카테고리**: `decision`
- **태그**: `session-summary`, `checkpoint`

### 13. manual-session-summary.kiro.hook
- **트리거**: 수동 버튼 클릭
- **기능**: 언제든지 수동으로 세션 요약 생성
- **용도**: 중요한 체크포인트 생성

## 기존 Hooks

### 13. auto-save-conversations.kiro.hook
- **트리거**: 메시지 전송 시
- **기능**: 모든 사용자 질문을 자동 저장
- **프로젝트 ID**: `kiro-conversations`

## Hook 활성화 방법

1. Kiro IDE에서 Command Palette 열기 (`Cmd+Shift+P`)
2. "Open Kiro Hook UI" 검색 및 실행
3. 또는 Explorer 뷰의 "Agent Hooks" 섹션 사용
4. 각 Hook을 개별적으로 활성화/비활성화 가능

## 사용 팁

### 자동 저장 Hook 관리
- 너무 많은 자동 저장이 발생하면 일부 Hook을 비활성화
- 키워드 패턴을 프로젝트에 맞게 조정
- 카테고리와 태그를 일관성 있게 사용

### 수동 Hook 활용
- 중요한 대화나 결정사항은 수동 저장 Hook 사용
- 정기적으로 프로젝트 통계를 확인하여 진행 상황 파악
- 새로운 작업 시작 전 관련 메모리 검색

### 성능 최적화
- 불필요한 Hook은 비활성화
- 키워드 패턴을 너무 광범위하게 설정하지 않기
- 정기적으로 mem-mesh 데이터베이스 정리

## 문제 해결

Hook이 작동하지 않는 경우:
1. mem-mesh MCP 서버가 정상 실행 중인지 확인
2. Hook JSON 파일의 문법 오류 확인
3. Kiro Hook UI에서 Hook 상태 확인
4. MCP 서버 로그 확인 (`~/.kiro/logs/`)

## 커스터마이징

프로젝트별 특별한 요구사항이 있다면:
1. 기존 Hook을 복사하여 수정
2. 키워드 패턴을 프로젝트에 맞게 조정
3. 카테고리와 태그를 프로젝트 구조에 맞게 설정
4. 프로젝트 ID를 명확하게 구분