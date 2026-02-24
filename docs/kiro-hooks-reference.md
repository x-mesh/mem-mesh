# Kiro Agent Hooks 공식 문서 정리

> 출처: https://kiro.dev/docs/hooks (2026-02-18 업데이트)

## 개요

Agent Hooks는 IDE에서 특정 이벤트 발생 시 미리 정의된 에이전트 액션을 자동 실행하는 자동화 도구.

## Hook 파일 구조

- 위치: `.kiro/hooks/*.kiro.hook`
- 형식: JSON
- 주의: `.kiro/hooks/` 디렉토리에는 `.kiro.hook` 파일만 존재해야 함 (다른 파일은 파싱 에러 유발)

### JSON 스키마

```json
{
  "name": "string (필수)",
  "version": "string (필수)",
  "description": "string (선택)",
  "when": {
    "type": "트리거 타입 (필수)",
    "patterns": ["파일 패턴 (file 이벤트에만 필수)"],
    "toolTypes": ["도구 타입 (tool 이벤트에만 필수)"]
  },
  "then": {
    "type": "askAgent 또는 runCommand",
    "prompt": "에이전트 프롬프트 (askAgent일 때)",
    "command": "셸 명령어 (runCommand일 때)"
  }
}
```

## 트리거 타입 (when.type)

| JSON 값 | 문서 명칭 | 설명 | 필수 필드 |
|---------|----------|------|----------|
| `promptSubmit` | Prompt Submit | 사용자가 프롬프트 제출 시 | - |
| `agentStop` | Agent Stop | 에이전트 응답 완료 시 | - |
| `preToolUse` | Pre Tool Use | 도구 호출 직전 | `toolTypes` |
| `postToolUse` | Post Tool Use | 도구 호출 직후 | `toolTypes` |
| `fileEdited` | File Save | 파일 저장 시 | `patterns` |
| `fileCreated` | File Create | 파일 생성 시 | `patterns` |
| `fileDeleted` | File Delete | 파일 삭제 시 | `patterns` |
| `preTaskExecution` | Pre Task Execution | spec 태스크 시작 전 | - |
| `postTaskExecution` | Post Task Execution | spec 태스크 완료 후 | - |
| `userTriggered` | Manual Trigger | 수동 실행 (버튼 클릭) | - |

## toolTypes 카테고리 (Pre/Post Tool Use)

| 값 | 대상 |
|----|------|
| `read` | 내장 파일 읽기 도구 |
| `write` | 내장 파일 쓰기 도구 |
| `shell` | 내장 셸 명령 도구 |
| `web` | 내장 웹 도구 |
| `spec` | 내장 spec 도구 |
| `*` | 모든 도구 (내장 + MCP) |
| `@mcp` | 모든 MCP 도구 |
| `@powers` | 모든 Powers 도구 |
| `@builtin` | 모든 내장 도구 |

`@` 접두사는 정규식 매칭: `@mcp.*sql.*` 같은 패턴 사용 가능.

## 액션 타입 (then.type)

### askAgent (Agent Prompt)
- 트리거 시 에이전트에 프롬프트 전송
- 크레딧 소비 (새 에이전트 루프 트리거)
- `promptSubmit`에서는 "Add to prompt" 방식 — 사용자 프롬프트에 추가됨

### runCommand (Shell Command)
- 트리거 시 셸 명령어 실행
- 크레딧 소비 안 함
- exit code 0: stdout이 에이전트 컨텍스트에 추가
- exit code != 0: stderr이 에이전트에 전달, preToolUse/promptSubmit에서는 실행 차단
- `USER_PROMPT` 환경변수로 사용자 프롬프트 접근 가능 (promptSubmit)
- 기본 타임아웃: 60초 (0으로 비활성화)

## 관리

- Enable/Disable: Agent Hooks 패널에서 eye icon 토글
- 편집: 패널에서 hook 선택 후 설정 수정 (즉시 적용)
- 삭제: 패널에서 Delete Hook 클릭 (복구 불가)
- 수동 실행: play button(▷) 또는 Start Hook 클릭
- 생성: Command Palette → `Kiro: Open Kiro Hook UI`

## Best Practices

1. 하나의 hook은 하나의 구체적 작업에 집중
2. 구체적이고 명확한 지시 사용
3. 파일 패턴을 구체적으로 지정 (불필요한 실행 방지)
4. askAgent는 크레딧 소비 → 효율적으로 설계
5. 복잡한 작업은 단계별 번호 매기기
6. `.kiro/hooks/` 디렉토리에 hook 파일 외 다른 파일 넣지 않기

## 트러블슈팅

- Hook 미실행: 파일 패턴 확인, hook 활성화 여부, 이벤트 타입 확인
- 예상치 못한 동작: 지시 명확성 검토, 충돌 hook 확인, 패턴 범위 확인
- 성능 문제: 파일 패턴 범위 축소, 프롬프트 간결화, 셸 명령 실행 시간 확인
