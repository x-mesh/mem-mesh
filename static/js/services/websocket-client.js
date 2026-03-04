/**
 * WebSocket Client Service
 * 실시간 메모리 업데이트를 위한 WebSocket 클라이언트
 */

export class WebSocketClient {
  constructor() {
    this.ws = null;
    this.clientId = this.generateClientId();
    this.isConnected = false;
    this.reconnectAttempts = 0;
    this.maxReconnectDelay = 60000; // 60초 상한
    this.reconnectDelay = 1000; // 초기 1초
    this.eventListeners = new Map();
    this.subscribedProjects = new Set();
    this.heartbeatInterval = null;
    this.connectionPromise = null;
    this.isReconnecting = false; // 재연결 중 플래그

    // P4: Pong tracking for dead connection detection
    this._lastPongTime = 0;
    this._missedPongs = 0;
    this._awaitingPong = false;
    this._pongTimeout = null;
    this._reconnectTimer = null;

    // P6: Disconnection timestamp for catch-up
    this._disconnectedAt = null;
  }
  
  /**
   * 고유한 클라이언트 ID 생성
   */
  generateClientId() {
    return `client_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }
  
  /**
   * WebSocket 연결
   */
  async connect() {
    if (this.connectionPromise) {
      return this.connectionPromise;
    }
    
    this.connectionPromise = this._connect();
    return this.connectionPromise;
  }
  
  async _connect() {
    if (this.isConnected) {
      return;
    }
    
    try {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws/realtime?client_id=${this.clientId}`;
      
      console.log(`Connecting to WebSocket: ${wsUrl}`);
      
      this.ws = new WebSocket(wsUrl);
      let hasHandledError = false; // 에러 처리 플래그
      
      return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          this.connectionPromise = null;
          reject(new Error('WebSocket connection timeout'));
        }, 10000); // 10초 타임아웃
        
        this.ws.onopen = () => {
          clearTimeout(timeout);
          const wasReconnect = this.reconnectAttempts > 0 || this._disconnectedAt;
          this.isConnected = true;
          this.reconnectAttempts = 0;
          this.isReconnecting = false;
          this.connectionPromise = null;

          console.log('WebSocket connected successfully');
          this.emit('connected', { clientId: this.clientId });

          // 하트비트 시작
          this.startHeartbeat();

          // 기존 프로젝트 구독 복원
          this.restoreSubscriptions();

          // 브라우저 이벤트 리스너 (최초 1회)
          this.setupBrowserListeners();

          // P6: 재연결 시 catch-up 이벤트
          if (wasReconnect && this._disconnectedAt) {
            this.emit('reconnected', { disconnectedAt: this._disconnectedAt });
            this._disconnectedAt = null;
          }

          resolve();
        };
        
        this.ws.onmessage = (event) => {
          this.handleMessage(event);
        };
        
        this.ws.onclose = (event) => {
          clearTimeout(timeout);
          this.connectionPromise = null;
          
          // onerror에서 이미 처리했으면 스킵
          if (!hasHandledError) {
            this.handleDisconnect(event);
          }
        };
        
        this.ws.onerror = (error) => {
          clearTimeout(timeout);
          hasHandledError = true;
          this.connectionPromise = null;
          console.error('WebSocket error:', error);
          this.emit('error', error);
          // 에러 발생 시 재연결 시도
          this.handleDisconnect({ code: 1006, reason: 'Connection error' });
          reject(error);
        };
      });
      
    } catch (error) {
      this.connectionPromise = null;
      console.error('Failed to create WebSocket connection:', error);
      throw error;
    }
  }
  
  /**
   * WebSocket 연결 해제
   */
  disconnect() {
    if (this.ws) {
      this.isConnected = false;
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }

    this.stopHeartbeat();
    this.removeBrowserListeners();
    this.connectionPromise = null;

    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._pongTimeout) {
      clearTimeout(this._pongTimeout);
      this._pongTimeout = null;
    }

    console.log('WebSocket disconnected');
    this.emit('disconnected');
  }
  
  /**
   * 메시지 처리
   */
  handleMessage(event) {
    try {
      const message = JSON.parse(event.data);
      const { type, data } = message;
      
      console.log('WebSocket message received:', type, data);
      
      switch (type) {
        case 'connection_established':
          this.emit('connection_established', data);
          break;
          
        case 'memory_created':
          this.emit('memory_created', data);
          break;
          
        case 'memory_updated':
          this.emit('memory_updated', data);
          break;
          
        case 'memory_deleted':
          this.emit('memory_deleted', data);
          break;
          
        case 'stats_updated':
          this.emit('stats_updated', data);
          break;
          
        case 'subscription_confirmed':
          console.log(`Subscription confirmed for project: ${data.project_id}`);
          this.emit('subscription_confirmed', data);
          break;
          
        case 'unsubscription_confirmed':
          console.log(`Unsubscription confirmed for project: ${data.project_id}`);
          this.emit('unsubscription_confirmed', data);
          break;
          
        case 'heartbeat':
          // 서버 하트비트도 연결 활성 증거
          this._lastPongTime = Date.now();
          this._missedPongs = 0;
          break;

        case 'pong':
          this._lastPongTime = Date.now();
          this._missedPongs = 0;
          this._awaitingPong = false;
          if (this._pongTimeout) {
            clearTimeout(this._pongTimeout);
            this._pongTimeout = null;
          }
          break;
          
        default:
          console.warn('Unknown WebSocket message type:', type);
      }
      
    } catch (error) {
      console.error('Failed to parse WebSocket message:', error, event.data);
    }
  }
  
  /**
   * 연결 해제 처리
   */
  handleDisconnect(event) {
    // 이미 재연결 중이면 스킵 (중복 호출 방지)
    if (this.isReconnecting) {
      console.log('Already reconnecting, skipping duplicate handleDisconnect');
      return;
    }

    this.isConnected = false;
    this.stopHeartbeat();

    // P6: 끊김 시점 기록 (재연결 후 catch-up용)
    if (!this._disconnectedAt) {
      this._disconnectedAt = new Date().toISOString();
    }

    console.log('WebSocket disconnected:', event.code, event.reason, 'Attempt:', this.reconnectAttempts);
    this.emit('disconnected', { code: event.code, reason: event.reason });

    // 정상 종료(code 1000)가 아니면 항상 재연결 시도 — 포기 없음
    if (event.code !== 1000) {
      this.isReconnecting = true;
      const delay = this._getReconnectDelay();
      this.emit('reconnecting', { attempt: this.reconnectAttempts + 1, delay });
      this.scheduleReconnect();
    }
  }
  
  /**
   * 재연결 스케줄링
   */
  scheduleReconnect() {
    this.reconnectAttempts++;
    const delay = this._getReconnectDelay();

    console.log(`Scheduling reconnection attempt ${this.reconnectAttempts} in ${delay}ms`);

    this._reconnectTimer = setTimeout(async () => {
      this.isReconnecting = false;

      try {
        await this.connect();
      } catch (error) {
        console.error('Reconnection failed:', error);
        // connect() 실패 시 onerror → handleDisconnect → 다시 scheduleReconnect
      }
    }, delay);
  }

  /**
   * 지수 백오프 + 상한 60초
   * 1s → 2s → 4s → 8s → 16s → 32s → 60s → 60s → ...
   */
  _getReconnectDelay() {
    const exponential = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
    return Math.min(exponential, this.maxReconnectDelay);
  }
  
  /**
   * 하트비트 시작
   */
  startHeartbeat() {
    this.stopHeartbeat();
    this._lastPongTime = Date.now();
    this._missedPongs = 0;

    this.heartbeatInterval = setInterval(() => {
      if (!this.isConnected) return;

      // Check if previous pings were answered
      const timeSinceLastPong = Date.now() - this._lastPongTime;
      if (timeSinceLastPong > 65000) {
        // No pong for over 65s (missed 2+ heartbeats) — connection likely dead
        this._missedPongs++;
        console.warn(`WebSocket: no pong for ${Math.round(timeSinceLastPong / 1000)}s (missed: ${this._missedPongs})`);

        if (this._missedPongs >= 2) {
          console.error('WebSocket connection confirmed dead, force reconnecting');
          this._forceReconnect();
          return;
        }
      }

      this.send({
        type: 'ping',
        data: { timestamp: new Date().toISOString() }
      });
    }, 30000); // 30초마다 ping
  }
  
  /**
   * 하트비트 중지
   */
  stopHeartbeat() {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }
  
  /**
   * 강제 재연결 — 소켓 종료 + 상태 초기화 + 즉시 connect
   */
  _forceReconnect() {
    console.log('WebSocket: force reconnecting...');
    this.isConnected = false;
    this.isReconnecting = false;
    this.reconnectAttempts = 0;
    this.stopHeartbeat();

    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._pongTimeout) {
      clearTimeout(this._pongTimeout);
      this._pongTimeout = null;
    }

    if (this.ws) {
      try { this.ws.close(); } catch (e) { /* ignore */ }
      this.ws = null;
    }

    this.connectionPromise = null;
    this.connect().catch(() => {});
  }

  /**
   * 연결 검증 — ping 보내고 5초 내 pong 확인
   */
  _validateConnection() {
    if (this._awaitingPong) return; // 이미 검증 중
    this._awaitingPong = true;

    this._pongTimeout = setTimeout(() => {
      if (this._awaitingPong) {
        console.warn('WebSocket validation failed: no pong within 5s');
        this._awaitingPong = false;
        this._forceReconnect();
      }
    }, 5000);

    this.send({
      type: 'ping',
      data: { timestamp: new Date().toISOString() }
    });
  }

  /**
   * 메시지 전송
   */
  send(message) {
    if (!this.isConnected || !this.ws) {
      console.warn('WebSocket not connected, message not sent:', message);
      return false;
    }
    
    try {
      this.ws.send(JSON.stringify(message));
      return true;
    } catch (error) {
      console.error('Failed to send WebSocket message:', error);
      return false;
    }
  }
  
  /**
   * 프로젝트 구독
   */
  subscribeToProject(projectId) {
    if (!projectId) return;
    
    this.subscribedProjects.add(projectId);
    
    if (this.isConnected) {
      this.send({
        type: 'subscribe_project',
        data: {
          project_id: projectId
        }
      });
    }
  }
  
  /**
   * 프로젝트 구독 해제
   */
  unsubscribeFromProject(projectId) {
    if (!projectId) return;
    
    this.subscribedProjects.delete(projectId);
    
    if (this.isConnected) {
      this.send({
        type: 'unsubscribe_project',
        data: {
          project_id: projectId
        }
      });
    }
  }
  
  /**
   * 구독 복원 (재연결 시)
   */
  restoreSubscriptions() {
    for (const projectId of this.subscribedProjects) {
      this.send({
        type: 'subscribe_project',
        data: {
          project_id: projectId
        }
      });
    }
  }
  
  /**
   * 브라우저 visibility / network 이벤트 리스너 (최초 1회)
   */
  setupBrowserListeners() {
    if (this._visibilityHandler) return; // 이미 등록됨

    // P1: 탭 활성화 시 연결 검증
    this._visibilityHandler = () => {
      if (document.visibilityState === 'visible') {
        console.log('Tab became visible, checking WebSocket health...');
        if (!this.isConnected) {
          this.reconnectAttempts = 0;
          this.connect().catch(() => {});
        } else {
          this._validateConnection();
        }
      }
    };
    document.addEventListener('visibilitychange', this._visibilityHandler);

    // P2: 네트워크 복구 시 재연결
    this._onlineHandler = () => {
      console.log('Network came online, checking WebSocket...');
      if (!this.isConnected) {
        this.reconnectAttempts = 0;
        this.connect().catch(() => {});
      } else {
        this._validateConnection();
      }
    };
    window.addEventListener('online', this._onlineHandler);

    // P2: 네트워크 끊김 시 heartbeat 일시 중지
    this._offlineHandler = () => {
      console.log('Network went offline');
      this.emit('network_offline');
      this.stopHeartbeat();
    };
    window.addEventListener('offline', this._offlineHandler);
  }

  /**
   * 브라우저 이벤트 리스너 제거
   */
  removeBrowserListeners() {
    if (this._visibilityHandler) {
      document.removeEventListener('visibilitychange', this._visibilityHandler);
      this._visibilityHandler = null;
    }
    if (this._onlineHandler) {
      window.removeEventListener('online', this._onlineHandler);
      this._onlineHandler = null;
    }
    if (this._offlineHandler) {
      window.removeEventListener('offline', this._offlineHandler);
      this._offlineHandler = null;
    }
  }

  /**
   * 이벤트 리스너 등록
   */
  on(event, callback) {
    if (!this.eventListeners.has(event)) {
      this.eventListeners.set(event, []);
    }
    this.eventListeners.get(event).push(callback);
  }
  
  /**
   * 이벤트 리스너 제거
   */
  off(event, callback) {
    if (!this.eventListeners.has(event)) return;
    
    const listeners = this.eventListeners.get(event);
    const index = listeners.indexOf(callback);
    if (index > -1) {
      listeners.splice(index, 1);
    }
  }
  
  /**
   * 이벤트 발생
   */
  emit(event, data) {
    if (!this.eventListeners.has(event)) return;
    
    const listeners = this.eventListeners.get(event);
    listeners.forEach(callback => {
      try {
        callback(data);
      } catch (error) {
        console.error(`Error in event listener for ${event}:`, error);
      }
    });
  }
  
  /**
   * 연결 상태 확인
   */
  getConnectionStatus() {
    return {
      isConnected: this.isConnected,
      clientId: this.clientId,
      reconnectAttempts: this.reconnectAttempts,
      subscribedProjects: Array.from(this.subscribedProjects)
    };
  }
}

// 전역 WebSocket 클라이언트 인스턴스
export const wsClient = new WebSocketClient();