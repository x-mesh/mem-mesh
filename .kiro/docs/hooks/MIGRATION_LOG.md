# Hook Migration Log

## 수정 일시
2025-01-XX

## 문제
Kiro hook 파일들이 잘못된 `when.type` 값을 사용하여 에러 발생:
- `fileSaved` (존재하지 않음)
- `messageContains` (존재하지 않음)
- `agentExecutionComplete` (존재하지 않음)
- `messageSent` (존재하지 않음)

## 해결
모든 hook 파일을 올바른 이벤트 타입으로 수정

## 수정된 파일 (9개)

### 1. auto-save-code-changes.kiro.hook
- **변경 전**: `fileSaved` (파일 패턴 포함)
- **변경 후**: `fileEdited`
- **이유**: 파일 편집 이벤트를 감지하기 위함

### 2. auto-save-decisions.kiro.hook
- **변경 전**: `messageContains` (패턴 매칭)
- **변경 후**: `agentStop`
- **이유**: 에이전트 응답 완료 시점에 결정사항 저장

### 3. auto-save-errors.kiro.hook
- **변경 전**: `messageContains` (패턴 매칭)
- **변경 후**: `agentStop`
- **이유**: 에이전트 응답 완료 시점에 에러 해결 내용 저장

### 4. auto-save-ideas.kiro.hook
- **변경 전**: `messageContains` (패턴 매칭)
- **변경 후**: `agentStop`
- **이유**: 에이전트 응답 완료 시점에 아이디어 저장

### 5. auto-save-performance.kiro.hook
- **변경 전**: `messageContains` (패턴 매칭)
- **변경 후**: `agentStop`
- **이유**: 에이전트 응답 완료 시점에 성능 최적화 내용 저장

### 6. auto-save-qa-pairs.kiro.hook
- **변경 전**: `agentExecutionComplete`
- **변경 후**: `agentStop`
- **이유**: 올바른 에이전트 완료 이벤트 타입 사용

### 7. auto-save-task-completion.kiro.hook
- **변경 전**: `messageContains` (패턴 매칭)
- **변경 후**: `agentStop`
- **이유**: 에이전트 응답 완료 시점에 작업 완료 내용 저장

### 8. auto-save-tests.kiro.hook
- **변경 전**: `messageContains` (패턴 매칭)
- **변경 후**: `agentStop`
- **이유**: 에이전트 응답 완료 시점에 테스트 내용 저장

### 9. session-summary-hook.kiro.hook
- **변경 전**: `messageSent` (패턴 필터 포함)
- **변경 후**: `agentStop`
- **이유**: 에이전트 응답 완료 시점에 세션 요약 저장

## 유효한 이벤트 타입 (10개)

| 타입 | 용도 |
|------|------|
| `fileEdited` | 파일 편집 시 |
| `fileCreated` | 파일 생성 시 |
| `fileDeleted` | 파일 삭제 시 |
| `userTriggered` | 사용자 수동 트리거 (버튼 클릭 등) |
| `promptSubmit` | 프롬프트 제출 시 |
| `agentStop` | 에이전트 실행 완료 시 |
| `preToolUse` | 도구 사용 전 |
| `postToolUse` | 도구 사용 후 |
| `preTaskExecution` | 태스크 실행 전 |
| `postTaskExecution` | 태스크 실행 후 |

## 검증 결과
✅ 모든 16개 hook 파일이 유효한 이벤트 타입 사용
- Valid: 16
- Invalid: 0
- Enabled: 6 (🟢)
- Disabled: 10 (⚪)

## 주의사항

### 패턴 매칭 기능 제거
이전에 `messageContains`로 특정 키워드를 감지하던 hook들은 이제 `agentStop`으로 변경되어 **모든 응답 완료 시점에 실행**됩니다. 

필요시 hook의 `then.prompt`에서 조건부 로직을 추가하여 필터링해야 합니다:
```
"prompt": "현재 대화에 '에러', 'bug', 'exception' 등의 키워드가 포함되어 있으면 mem-mesh에 저장하고, 그렇지 않으면 무시하세요."
```

### 파일 패턴 필터링 제거
`auto-save-code-changes.kiro.hook`의 파일 패턴 필터링이 제거되었습니다. 필요시 `then.prompt`에서 파일 확장자를 확인하는 로직을 추가해야 합니다.

## 권장사항
1. 현재 대부분의 hook이 비활성화(`enabled: false`) 상태입니다
2. 필요한 hook만 선택적으로 활성화하여 사용하세요
3. `agentStop` 이벤트는 모든 응답마다 실행되므로, 불필요한 hook은 비활성화 권장
