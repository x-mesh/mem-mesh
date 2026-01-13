# WebSocket 실시간 업데이트 시스템

mem-mesh에서 메모리 변경사항을 실시간으로 클라이언트에게 전달하는 WebSocket 기반 시스템입니다.

## 🎯 주요 기능

- **실시간 메모리 업데이트**: 메모리 생성/수정/삭제 시 즉시 알림
- **프로젝트별 구독**: 특정 프로젝트만 구독 가능
- **자동 재연결**: 연결 끊김 시 자동으로 재연결 시도
- **하트비트**: 연결 상태 유지 및 모니터링
- **토스트 알림**: 사용자 친화적인 알림 표시

## 🏗️ 아키텍처

### 백엔드 구조

```
app/web/websocket/
├── __init__.py          # 모듈 초기화
└── realtime.py          # WebSocket 서버 및 알림 시스템
```

#### 주요 컴포넌트

1. **ConnectionManager**: WebSocket 연결 관리
   - 클라이언트 연결/해제 처리
   - 프로젝트별 구독 관리
   - 하트비트 및 연결 상태 모니터링

2. **RealtimeNotifier**: 실시간 알림 발송
   - 메모리 생성/수정/삭제 알림
   - 통계 업데이트 알림
   - 프로젝트별/전체 브로드캐스트

3. **WebSocket 엔드포인트**
   - `/ws/realtime`: WebSocket 연결 엔드포인트
   - `/ws/stats`: 연결 통계 조회

### 프론트엔드 구조

```
static/js/services/
└── websocket-client.js  # WebSocket 클라이언트
```

#### WebSocketClient 클래스

- **연결 관리**: 자동 연결/재연결
- **이벤트 처리**: 메시지 수신 및 이벤트 발생
- **구독 관리**: 프로젝트별 구독/해제
- **하트비트**: 연결 상태 유지

## 🚀 사용법

### 1. 백엔드 설정

WebSocket 라우터는 이미 웹 앱에 등록되어 있습니다:

```python
# app/web/app.py
app.include_router(websocket_router)  # WebSocket 라우터 등록
```

MCP 도구 핸들러에 notifier가 주입되어 메모리 변경 시 자동으로 알림을 전송합니다.

### 2. 프론트엔드 사용

#### 기본 연결

```javascript
import { wsClient } from './services/websocket-client.js';

// WebSocket 연결
await wsClient.connect();

// 연결 상태 확인
const status = wsClient.getConnectionStatus();
console.log('Connection status:', status);
```

#### 이벤트 리스너 등록

```javascript
// 메모리 생성 이벤트
wsClient.on('memory_created', (data) => {
  console.log('New memory created:', data.memory);
  // UI 업데이트 로직
});

// 메모리 수정 이벤트
wsClient.on('memory_updated', (data) => {
  console.log('Memory updated:', data.memory_id, data.memory);
  // UI 업데이트 로직
});

// 메모리 삭제 이벤트
wsClient.on('memory_deleted', (data) => {
  console.log('Memory deleted:', data.memory_id);
  // UI 업데이트 로직
});

// 연결 상태 이벤트
wsClient.on('connected', () => {
  console.log('WebSocket connected');
});

wsClient.on('disconnected', () => {
  console.log('WebSocket disconnected');
});
```

#### 프로젝트 구독

```javascript
// 특정 프로젝트 구독
wsClient.subscribeToProject('my-project');

// 프로젝트 구독 해제
wsClient.unsubscribeFromProject('my-project');
```

### 3. Dashboard 페이지 통합

Dashboard 페이지에서는 이미 WebSocket이 통합되어 있습니다:

- 메모리 생성 시 최근 메모리 목록에 자동 추가
- 메모리 수정 시 해당 메모리 카드 업데이트
- 메모리 삭제 시 목록에서 자동 제거
- 통계 자동 새로고침
- 연결 상태 표시
- 토스트 알림

## 📡 WebSocket 메시지 형식

### 클라이언트 → 서버

```javascript
// 프로젝트 구독
{
  "type": "subscribe_project",
  "data": {
    "project_id": "my-project"
  }
}

// 프로젝트 구독 해제
{
  "type": "unsubscribe_project",
  "data": {
    "project_id": "my-project"
  }
}

// Ping (하트비트)
{
  "type": "ping",
  "data": {
    "timestamp": "2026-01-13T15:30:00Z"
  }
}
```

### 서버 → 클라이언트

```javascript
// 메모리 생성 알림
{
  "type": "memory_created",
  "data": {
    "memory": { /* 메모리 객체 */ },
    "timestamp": "2026-01-13T15:30:00Z"
  }
}

// 메모리 수정 알림
{
  "type": "memory_updated",
  "data": {
    "memory_id": "memory-123",
    "memory": { /* 업데이트된 메모리 객체 */ },
    "timestamp": "2026-01-13T15:30:00Z"
  }
}

// 메모리 삭제 알림
{
  "type": "memory_deleted",
  "data": {
    "memory_id": "memory-123",
    "project_id": "my-project",
    "timestamp": "2026-01-13T15:30:00Z"
  }
}

// 연결 확인
{
  "type": "connection_established",
  "data": {
    "client_id": "client_1234567890_abc123",
    "timestamp": "2026-01-13T15:30:00Z",
    "message": "WebSocket connection established"
  }
}
```

## 🔧 설정 및 모니터링

### 연결 통계 조회

```bash
curl http://localhost:8000/ws/stats
```

응답:
```json
{
  "total_connections": 5,
  "global_subscribers": 5,
  "project_subscriptions": {
    "mem-mesh": 3,
    "my-project": 2
  }
}
```

### 로그 모니터링

WebSocket 관련 로그는 `mem-mesh-web` 로거를 통해 출력됩니다:

```bash
# 개발 모드에서 실행
python -m app.web --reload

# 로그에서 WebSocket 관련 메시지 확인
# - "WebSocket client connected: {client_id}"
# - "WebSocket client disconnected: {client_id}"
# - "Memory created notification sent to {count} clients"
```

## 🚨 오류 처리

### 자동 재연결

클라이언트는 연결이 끊어지면 자동으로 재연결을 시도합니다:

- 최대 5회 재연결 시도
- 지수 백오프 방식 (1초, 2초, 4초, 8초, 16초)
- 재연결 성공 시 기존 구독 복원

### 오류 이벤트

```javascript
wsClient.on('error', (error) => {
  console.error('WebSocket error:', error);
});

wsClient.on('max_reconnect_attempts_reached', () => {
  console.error('Failed to reconnect after maximum attempts');
  // 사용자에게 수동 새로고침 안내
});
```

## 🎨 UI 통합 예시

### 실시간 메모리 카드 업데이트

```javascript
// Dashboard 페이지에서 사용하는 방식
wsClient.on('memory_created', (data) => {
  const { memory } = data;
  
  // 최근 메모리 목록에 추가
  this.recentMemories.unshift(memory);
  
  // 최대 개수 제한
  if (this.recentMemories.length > 10) {
    this.recentMemories = this.recentMemories.slice(0, 10);
  }
  
  // UI 업데이트
  this.updateRecentMemoriesSection();
  
  // 토스트 알림
  this.showToast(`새 메모리가 생성되었습니다: ${memory.category}`, 'success');
});
```

### 연결 상태 표시

```css
.connection-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  font-size: 0.875rem;
}

.connection-status.connected {
  background: #f0fdf4;
  border-color: #22c55e;
  color: #15803d;
}

.connection-status.disconnected {
  background: #fef2f2;
  border-color: #ef4444;
  color: #dc2626;
}
```

## 🔮 향후 개선사항

1. **메시지 큐잉**: 연결 끊김 중 발생한 이벤트 저장 및 재연결 시 전송
2. **사용자별 알림**: 특정 사용자에게만 알림 전송
3. **알림 필터링**: 사용자가 원하는 이벤트만 구독
4. **성능 최적화**: 대량 연결 시 메모리 및 CPU 사용량 최적화
5. **메트릭스**: WebSocket 연결 및 메시지 전송 통계

## 🧪 테스트

구현된 기능을 테스트하려면:

```bash
# 기본 구조 테스트
python test_websocket_implementation.py

# 웹 서버 실행
python -m app.web --reload

# 브라우저에서 Dashboard 페이지 접속
# http://localhost:8000/dashboard

# 다른 탭에서 메모리 생성/수정/삭제 테스트
# 실시간으로 Dashboard가 업데이트되는지 확인
```

이제 mem-mesh의 memories recents에서 WebSocket을 통한 실시간 업데이트가 완전히 구현되었습니다! 🎉