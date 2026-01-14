/**
 * Connection Status Component
 * WebSocket 연결 상태를 표시하는 공통 컴포넌트
 * Dashboard, Memories, Search 등 모든 페이지에서 사용
 */

import { wsClient } from '../services/websocket-client.js';

class ConnectionStatus extends HTMLElement {
  constructor() {
    super();
    this.currentStatus = 'connecting';
    this._boundHandlers = null;
  }
  
  connectedCallback() {
    this.render();
    this.setupWebSocketListeners();
    this.checkInitialStatus();
  }
  
  disconnectedCallback() {
    this.removeWebSocketListeners();
  }
  
  /**
   * Setup WebSocket event listeners
   */
  setupWebSocketListeners() {
    this._boundHandlers = {
      connected: () => this.updateStatus('connected'),
      disconnected: () => this.updateStatus('disconnected'),
      reconnecting: (data) => {
        console.log(`Reconnecting (${data.attempt}/${data.max})...`);
        this.updateStatus('connecting');
      },
      error: () => this.updateStatus('error'),
      maxReconnectAttemptsReached: () => {
        this.updateStatus('error');
        this.showReconnectButton();
      }
    };
    
    wsClient.on('connected', this._boundHandlers.connected);
    wsClient.on('disconnected', this._boundHandlers.disconnected);
    wsClient.on('reconnecting', this._boundHandlers.reconnecting);
    wsClient.on('error', this._boundHandlers.error);
    wsClient.on('max_reconnect_attempts_reached', this._boundHandlers.maxReconnectAttemptsReached);
  }
  
  /**
   * Remove WebSocket event listeners
   */
  removeWebSocketListeners() {
    if (this._boundHandlers) {
      wsClient.off('connected', this._boundHandlers.connected);
      wsClient.off('disconnected', this._boundHandlers.disconnected);
      wsClient.off('reconnecting', this._boundHandlers.reconnecting);
      wsClient.off('error', this._boundHandlers.error);
      wsClient.off('max_reconnect_attempts_reached', this._boundHandlers.maxReconnectAttemptsReached);
    }
  }
  
  /**
   * Check initial WebSocket status
   */
  checkInitialStatus() {
    const status = wsClient.getConnectionStatus();
    if (status.isConnected) {
      this.updateStatus('connected');
    } else {
      // 연결 시도
      this.connectWebSocket();
    }
  }
  
  /**
   * Connect WebSocket
   */
  async connectWebSocket() {
    this.updateStatus('connecting');
    
    try {
      await wsClient.connect();
      // connected 이벤트가 발생하면 updateStatus가 호출됨
    } catch (error) {
      console.error('WebSocket connection failed:', error);
      this.updateStatus('error');
    }
  }
  
  /**
   * Update connection status
   */
  updateStatus(status) {
    this.currentStatus = status;
    
    const statusEl = this.querySelector('.connection-status-inner');
    if (!statusEl) return;
    
    // Remove all status classes
    statusEl.classList.remove('connected', 'disconnected', 'connecting', 'error');
    statusEl.classList.add(status);
    
    // Update text and icon
    const labels = {
      connected: 'Connected',
      connecting: 'Connecting...',
      disconnected: 'Disconnected',
      error: 'Connection Error'
    };
    
    statusEl.innerHTML = `
      <span class="status-dot"></span>
      <span class="status-text">${labels[status] || 'Unknown'}</span>
    `;
    
    // Hide reconnect button if connected
    const reconnectBtn = this.querySelector('.reconnect-btn');
    if (reconnectBtn) {
      reconnectBtn.style.display = status === 'error' ? 'inline-flex' : 'none';
    }
    
    console.log('Connection status updated:', status);
  }
  
  /**
   * Show reconnect button
   */
  showReconnectButton() {
    let reconnectBtn = this.querySelector('.reconnect-btn');
    if (!reconnectBtn) {
      reconnectBtn = document.createElement('button');
      reconnectBtn.className = 'reconnect-btn';
      reconnectBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M1 4v6h6M23 20v-6h-6"/>
          <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/>
        </svg>
        Retry
      `;
      reconnectBtn.addEventListener('click', () => this.handleReconnect());
      this.appendChild(reconnectBtn);
    }
    reconnectBtn.style.display = 'inline-flex';
  }
  
  /**
   * Handle reconnect button click
   */
  async handleReconnect() {
    // Reset reconnect attempts
    wsClient.reconnectAttempts = 0;
    await this.connectWebSocket();
  }
  
  /**
   * Render component
   */
  render() {
    this.innerHTML = `
      <div class="connection-status-inner connecting">
        <span class="status-dot"></span>
        <span class="status-text">Connecting...</span>
      </div>
    `;
  }
}

// Define custom element
customElements.define('connection-status', ConnectionStatus);

export { ConnectionStatus };
