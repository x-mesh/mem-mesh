/**
 * Connection Status Component
 * WebSocket 연결 상태를 표시하는 공통 컴포넌트
 *
 * 사용법:
 *   <connection-status></connection-status>              — 기본 (dot + text)
 *   <connection-status compact></connection-status>      — 아이콘만 (헤더용)
 */

import { wsClient } from '../services/websocket-client.js';

class ConnectionStatus extends HTMLElement {
  constructor() {
    super();
    this.currentStatus = 'connecting';
    this._boundHandlers = null;
  }

  get compact() {
    return this.hasAttribute('compact');
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
        console.log(`Reconnecting (attempt ${data.attempt}, delay ${data.delay}ms)...`);
        this.updateStatus('connecting');
      },
      error: () => {
        this.updateStatus('error');
        if (!this.compact) this.showReconnectButton();
      },
      networkOffline: () => this.updateStatus('offline'),
    };

    wsClient.on('connected', this._boundHandlers.connected);
    wsClient.on('disconnected', this._boundHandlers.disconnected);
    wsClient.on('reconnecting', this._boundHandlers.reconnecting);
    wsClient.on('error', this._boundHandlers.error);
    wsClient.on('network_offline', this._boundHandlers.networkOffline);
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
      wsClient.off('network_offline', this._boundHandlers.networkOffline);
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

    if (this.compact) {
      this._updateCompact(status);
    } else {
      this._updateFull(status);
    }
  }

  _updateCompact(status) {
    const icon = this.querySelector('.ws-icon');
    if (!icon) return;

    const tooltips = {
      connected: 'WebSocket Connected',
      connecting: 'WebSocket Connecting…',
      disconnected: 'WebSocket Disconnected',
      offline: 'Network Offline',
      error: 'WebSocket Error',
    };

    icon.setAttribute('data-status', status);
    this.title = tooltips[status] || 'Unknown';

    // click-to-reconnect on error/offline
    if (status === 'error' || status === 'disconnected' || status === 'offline') {
      this.style.cursor = 'pointer';
    } else {
      this.style.cursor = 'default';
    }
  }

  _updateFull(status) {
    const statusEl = this.querySelector('.connection-status-inner');
    if (!statusEl) return;

    // Remove all status classes
    statusEl.classList.remove('connected', 'disconnected', 'connecting', 'error', 'offline');
    statusEl.classList.add(status);

    // Update text and icon
    const labels = {
      connected: 'Connected',
      connecting: 'Connecting...',
      disconnected: 'Disconnected',
      offline: 'Offline',
      error: 'Connection Error'
    };

    statusEl.innerHTML = `
      <span class="status-dot"></span>
      <span class="status-text">${labels[status] || 'Unknown'}</span>
    `;

    // Hide reconnect button if connected
    const reconnectBtn = this.querySelector('.reconnect-btn');
    if (reconnectBtn) {
      reconnectBtn.style.display = (status === 'error' || status === 'offline') ? 'inline-flex' : 'none';
    }
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
    if (this.compact) {
      this.innerHTML = `
        <svg class="ws-icon" data-status="connecting" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 12.55a11 11 0 0 1 14.08 0"/>
          <path d="M1.42 9a16 16 0 0 1 21.16 0"/>
          <path d="M8.53 16.11a6 6 0 0 1 6.95 0"/>
          <circle cx="12" cy="20" r="1" fill="currentColor"/>
        </svg>
      `;
      this.addEventListener('click', () => {
        if (this.currentStatus !== 'connected' && this.currentStatus !== 'connecting') {
          this.handleReconnect();
        }
      });
    } else {
      this.innerHTML = `
        <div class="connection-status-inner connecting">
          <span class="status-dot"></span>
          <span class="status-text">Connecting...</span>
        </div>
      `;
    }
  }
}

// Define custom element
customElements.define('connection-status', ConnectionStatus);

export { ConnectionStatus };
