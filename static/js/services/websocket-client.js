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
    this.maxReconnectAttempts = 5;
    this.reconnectDelay = 1000; // 1초
    this.eventListeners = new Map();
    this.subscribedProjects = new Set();
    this.heartbeatInterval = null;
    this.connectionPromise = null;
    this.isReconnecting = false; // 재연결 중 플래그
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
      this.ws.close();
      this.ws = null;
    }
    
    this.stopHeartbeat();
    this.connectionPromise = null;
    
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
          // 하트비트 응답 - 특별한 처리 불필요
          break;
          
        case 'pong':
          // ping에 대한 응답
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
    
    console.log('WebSocket disconnected:', event.code, event.reason, 'Attempt:', this.reconnectAttempts);
    this.emit('disconnected', { code: event.code, reason: event.reason });
    
    // 자동 재연결 시도 (reconnectAttempts는 scheduleReconnect에서 증가)
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.isReconnecting = true;
      this.emit('reconnecting', { attempt: this.reconnectAttempts + 1, max: this.maxReconnectAttempts });
      this.scheduleReconnect();
    } else {
      console.error('Max reconnection attempts reached');
      this.isReconnecting = false;
      this.emit('max_reconnect_attempts_reached');
    }
  }
  
  /**
   * 재연결 스케줄링
   */
  scheduleReconnect() {
    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1); // 지수 백오프
    
    console.log(`Scheduling reconnection attempt ${this.reconnectAttempts} in ${delay}ms`);
    
    setTimeout(async () => {
      // 다음 재연결 시도를 위해 플래그 리셋
      this.isReconnecting = false;
      
      try {
        await this.connect();
      } catch (error) {
        console.error('Reconnection failed:', error);
        // 에러 발생해도 handleDisconnect에서 다음 재연결을 스케줄링함
      }
    }, delay);
  }
  
  /**
   * 하트비트 시작
   */
  startHeartbeat() {
    this.stopHeartbeat();
    
    this.heartbeatInterval = setInterval(() => {
      if (this.isConnected) {
        this.send({
          type: 'ping',
          data: {
            timestamp: new Date().toISOString()
          }
        });
      }
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