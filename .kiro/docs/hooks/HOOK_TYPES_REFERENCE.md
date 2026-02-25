# Kiro Hook Types Reference

## 유효한 이벤트 타입 (Valid Event Types)

### 파일 관련 이벤트
| 타입 | 트리거 시점 | 사용 예시 |
|------|------------|----------|
| `fileEdited` | 파일이 편집될 때 | 코드 변경사항 자동 저장 |
| `fileCreated` | 새 파일이 생성될 때 | 파일 생성 로그 기록 |
| `fileDeleted` | 파일이 삭제될 때 | 삭제 이력 추적 |

### 사용자 인터랙션 이벤트
| 타입 | 트리거 시점 | 사용 예시 |
|------|------------|----------|
| `userTriggered` | 사용자가 수동으로 트리거 (버튼 클릭 등) | 수동 메모리 저장, 통계 조회 |
| `promptSubmit` | 사용자가 프롬프트를 제출할 때 | 작업 시작 감지, Pin 생성 |

### 에이전트 실행 이벤트
| 타입 | 트리거 시점 | 사용 예시 |
|------|------------|----------|
| `agentStop` | 에이전트 실행이 완료될 때 | 대화 저장, 세션 요약 |
| `preTaskExecution` | 태스크 실행 전 | 사전 검증, 컨텍스트 로드 |
| `postTaskExecution` | 태스크 실행 후 | 결과 저장, 후처리 |

### 도구 사용 이벤트
| 타입 | 트리거 시점 | 사용 예시 |
|------|------------|----------|
| `preToolUse` | 도구 사용 전 | 도구 호출 로깅 |
| `postToolUse` | 도구 사용 후 | 도구 결과 분석 |

## Hook 구조 예시

### 기본 구조
```json
{
  "enabled": true,
  "name": "Hook Name",
  "description": "Hook description",
  "version": "1",
  "when": {
    "type": "agentStop"
  },
  "then": {
    "type": "askAgent",
    "prompt": "Your prompt here..."
  }
}
```

### userTriggered 예시 (수동 트리거)
```json
{
  "enabled": true,
  "name": "Manual Save",
  "description": "수동으로 메모리 저장",
  "version": "1",
  "when": {
    "type": "userTriggered"
  },
  "then": {
    "type": "askAgent",
    "prompt": "현재 대화를 mem-mesh에 저장해주세요."
  }
}
```

### promptSubmit 예시 (프롬프트 제출 시)
```json
{
  "enabled": true,
  "name": "Auto Create Pin",
  "description": "작업 시작 시 Pin 자동 생성",
  "version": "1",
  "when": {
    "type": "promptSubmit"
  },
  "then": {
    "type": "askAgent",
    "prompt": "작업 요청이 감지되면 Pin을 생성하세요."
  }
}
```

### agentStop 예시 (에이전트 완료 시)
```json
{
  "enabled": true,
  "name": "Auto Save Conversation",
  "description": "대화 자동 저장",
  "version": "1",
  "when": {
    "type": "agentStop"
  },
  "then": {
    "type": "askAgent",
    "prompt": "대화 내용을 mem-mesh에 저장해주세요."
  }
}
```

### fileEdited 예시 (파일 편집 시)
```json
{
  "enabled": false,
  "name": "Auto Save Code Changes",
  "description": "코드 변경사항 자동 저장",
  "version": "1",
  "when": {
    "type": "fileEdited"
  },
  "then": {
    "type": "askAgent",
    "prompt": "파일 변경사항을 mem-mesh에 저장해주세요."
  }
}
```

## 주의사항

### 1. 제거된 타입들 (사용 불가)
- ❌ `fileSaved` → `fileEdited` 사용
- ❌ `messageContains` → `agentStop` + 프롬프트 내 조건 로직 사용
- ❌ `messageSent` → `agentStop` 사용
- ❌ `agentExecutionComplete` → `agentStop` 사용

### 2. 패턴 매칭 대안
이전 `messageContains`의 패턴 매칭 기능은 제거되었습니다. 대신 프롬프트 내에서 조건부 로직을 사용하세요:

```json
{
  "when": {
    "type": "agentStop"
  },
  "then": {
    "type": "askAgent",
    "prompt": "현재 대화에 '에러', 'bug', 'exception' 키워드가 포함되어 있으면 mem-mesh에 저장하고, 그렇지 않으면 무시하세요."
  }
}
```

### 3. 파일 패턴 필터링 대안
이전 `fileSaved`의 `filePattern` 기능은 제거되었습니다. 대신 프롬프트 내에서 파일 확장자를 확인하세요:

```json
{
  "when": {
    "type": "fileEdited"
  },
  "then": {
    "type": "askAgent",
    "prompt": "편집된 파일이 .py, .js, .ts 확장자인 경우에만 mem-mesh에 저장하세요."
  }
}
```

### 4. 성능 고려사항
- `agentStop`은 모든 에이전트 응답마다 실행됩니다
- 불필요한 hook은 `enabled: false`로 비활성화하세요
- 여러 hook이 동시에 활성화되면 성능에 영향을 줄 수 있습니다

## 현재 프로젝트 Hook 현황

### 활성화된 Hook (6개)
1. `auto-create-pin-on-task.kiro.hook` - promptSubmit
2. `auto-save-conversations.kiro.hook` - agentStop
3. `load-project-context.kiro.hook` - userTriggered
4. `manual-save-memmesh.kiro.hook` - userTriggered
5. `manual-search-memories.kiro.hook` - userTriggered
6. `show-project-stats.kiro.hook` - userTriggered

### 비활성화된 Hook (10개)
모두 `enabled: false` 상태로 필요시 활성화 가능

## 추가 리소스
- [Kiro Hook Documentation](https://docs.kiro.ai/hooks)
- [Hook Examples](https://github.com/kiro/examples/hooks)
