# Kiro Hooks for mem-mesh Integration

이 디렉토리에는 mem-mesh와 Kiro를 연동하기 위한 Hook 설정들이 포함되어 있습니다.

## 설정된 Hooks

### 1. auto-save-conversations.json
- **트리거**: 메시지 전송 시 (`onMessageSent`)
- **기능**: 모든 사용자 질문을 자동으로 mem-mesh에 저장
- **프로젝트 ID**: `kiro-conversations`
- **조건**: 최소 10자 이상, 테스트 메시지 제외

### 2. save-agent-responses.json
- **트리거**: AI 작업 완료 시 (`onAgentExecutionComplete`)
- **기능**: AI 에이전트의 작업 결과를 자동 저장
- **프로젝트 ID**: `kiro-agent-work`
- **조건**: 최소 50자 이상 응답, 시스템 메시지 제외

### 3. session-summary.json
- **트리거**: 새 세션 시작 시 (`onNewSession`)
- **기능**: 이전 세션 요약을 저장
- **프로젝트 ID**: `kiro-sessions`
- **카테고리**: `decision`

### 4. manual-save-button.json
- **트리거**: 수동 버튼 클릭 (`onManualTrigger`)
- **기능**: 현재 대화를 수동으로 저장
- **프로젝트 ID**: `kiro-manual-saves`
- **버튼 텍스트**: "💾 mem-mesh에 저장"

## Hook 활성화 방법

1. Kiro IDE에서 Command Palette 열기 (`Cmd+Shift+P`)
2. "Open Kiro Hook UI" 검색 및 실행
3. 또는 Explorer 뷰의 "Agent Hooks" 섹션 사용
4. 각 Hook을 개별적으로 활성화/비활성화 가능

## 사용 팁

- Hook이 너무 자주 실행되면 `conditions`에서 조건을 더 엄격하게 설정
- 특정 키워드나 패턴을 제외하려면 `excludePatterns` 수정
- 프로젝트별로 다른 저장 규칙이 필요하면 추가 Hook 생성

## 문제 해결

Hook이 작동하지 않는 경우:
1. mem-mesh MCP 서버가 정상 실행 중인지 확인
2. Hook JSON 파일의 문법 오류 확인
3. Kiro Hook UI에서 Hook 상태 확인