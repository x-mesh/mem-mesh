/**
 * Alert Panel Component
 * 활성 알림 표시 및 관리
 */

export class AlertPanel extends HTMLElement {
  constructor() {
    super();
    this.alerts = [];
    this.filter = 'active'; // 'active', 'resolved', 'all'
  }

  connectedCallback() {
    this.render();
    this.loadAlerts();
    
    // Auto-refresh every 30 seconds
    this.refreshInterval = setInterval(() => {
      this.loadAlerts();
    }, 30000);
  }

  disconnectedCallback() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
    }
  }

  render() {
    this.innerHTML = `
      <div class="alert-panel">
        <div class="alert-panel-header">
          <h3>알림</h3>
          <div class="alert-filters">
            <button class="filter-btn active" data-filter="active">활성</button>
            <button class="filter-btn" data-filter="resolved">해결됨</button>
            <button class="filter-btn" data-filter="all">전체</button>
          </div>
          <button class="refresh-btn" title="새로고침">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M13.65 2.35A7.958 7.958 0 008 0C3.58 0 0 3.58 0 8s3.58 8 8 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L9 7h7V0l-2.35 2.35z" fill="currentColor"/>
            </svg>
          </button>
        </div>
        <div class="alert-list" id="alert-list">
          <div class="loading">알림을 불러오는 중...</div>
        </div>
      </div>
    `;

    this.setupEventListeners();
  }

  setupEventListeners() {
    // Filter buttons
    this.querySelectorAll('.filter-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        this.filter = e.target.dataset.filter;
        this.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        this.renderAlerts();
      });
    });

    // Refresh button
    this.querySelector('.refresh-btn')?.addEventListener('click', () => {
      this.loadAlerts();
    });
  }

  async loadAlerts() {
    try {
      const response = await fetch('/api/monitoring/alerts?limit=50');
      if (!response.ok) throw new Error('Failed to fetch alerts');
      
      this.alerts = await response.json();
      this.renderAlerts();
    } catch (error) {
      console.error('Failed to load alerts:', error);
      this.showError('알림을 불러올 수 없습니다.');
    }
  }

  renderAlerts() {
    const listEl = this.querySelector('#alert-list');
    
    // Filter alerts
    let filtered = this.alerts;
    if (this.filter === 'active') {
      filtered = this.alerts.filter(a => a.status === 'active');
    } else if (this.filter === 'resolved') {
      filtered = this.alerts.filter(a => a.status === 'resolved');
    }

    if (filtered.length === 0) {
      listEl.innerHTML = `
        <div class="empty-state">
          <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
            <path d="M24 4C12.96 4 4 12.96 4 24s8.96 20 20 20 20-8.96 20-20S35.04 4 24 4zm-2 30l-8-8 2.83-2.83L22 28.34l11.17-11.17L36 20l-14 14z" fill="currentColor" opacity="0.3"/>
          </svg>
          <p>${this.filter === 'active' ? '활성 알림이 없습니다' : '알림이 없습니다'}</p>
        </div>
      `;
      return;
    }

    listEl.innerHTML = filtered.map(alert => this.renderAlertItem(alert)).join('');

    // Add resolve button listeners
    listEl.querySelectorAll('.resolve-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const alertId = e.target.closest('.resolve-btn').dataset.alertId;
        this.resolveAlert(alertId);
      });
    });
  }

  renderAlertItem(alert) {
    const severityClass = this.getSeverityClass(alert.severity);
    const severityIcon = this.getSeverityIcon(alert.severity);
    const timeAgo = this.getTimeAgo(alert.timestamp);

    return `
      <div class="alert-item ${severityClass} ${alert.status === 'resolved' ? 'resolved' : ''}">
        <div class="alert-icon">${severityIcon}</div>
        <div class="alert-content">
          <div class="alert-header">
            <span class="alert-type">${this.getAlertTypeLabel(alert.alert_type)}</span>
            <span class="alert-time">${timeAgo}</span>
          </div>
          <p class="alert-message">${this.escapeHtml(alert.message)}</p>
          <div class="alert-details">
            <span class="alert-metric">
              현재: <strong>${this.formatMetricValue(alert.metric_value, alert.alert_type)}</strong>
            </span>
            <span class="alert-threshold">
              임계값: <strong>${this.formatMetricValue(alert.threshold_value, alert.alert_type)}</strong>
            </span>
          </div>
          ${alert.project_id ? `<span class="alert-project">프로젝트: ${this.escapeHtml(alert.project_id)}</span>` : ''}
        </div>
        <div class="alert-actions">
          ${alert.status === 'active' ? `
            <button class="resolve-btn" data-alert-id="${alert.id}" title="해결">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M13.5 4L6 11.5L2.5 8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </button>
          ` : `
            <span class="resolved-badge">✓ 해결됨</span>
          `}
        </div>
      </div>
    `;
  }

  getSeverityClass(severity) {
    const classes = {
      'warning': 'alert-warning',
      'error': 'alert-error',
      'critical': 'alert-critical'
    };
    return classes[severity] || 'alert-warning';
  }

  getSeverityIcon(severity) {
    const icons = {
      'warning': '⚠️',
      'error': '❌',
      'critical': '🚨'
    };
    return icons[severity] || '⚠️';
  }

  getAlertTypeLabel(type) {
    const labels = {
      'low_similarity': '낮은 유사도',
      'high_no_results': '높은 Zero-Result 비율',
      'slow_response': '느린 응답',
      'embedding_failure': '임베딩 실패',
      'search_drop': '검색 수 급감'
    };
    return labels[type] || type;
  }

  formatMetricValue(value, type) {
    if (type === 'low_similarity') {
      return (value * 100).toFixed(1) + '%';
    } else if (type === 'high_no_results') {
      return value.toFixed(1) + '%';
    } else if (type === 'slow_response') {
      return value.toFixed(0) + 'ms';
    } else if (type === 'search_drop') {
      return value.toFixed(1) + '%';
    }
    return value.toString();
  }

  getTimeAgo(timestamp) {
    const now = new Date();
    const time = new Date(timestamp);
    const diff = Math.floor((now - time) / 1000); // seconds

    if (diff < 60) return '방금 전';
    if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
    if (diff < 604800) return `${Math.floor(diff / 86400)}일 전`;
    
    return time.toLocaleDateString('ko-KR');
  }

  async resolveAlert(alertId) {
    try {
      const response = await fetch(`/api/monitoring/alerts/${alertId}/resolve`, {
        method: 'POST'
      });

      if (!response.ok) throw new Error('Failed to resolve alert');

      // Update local state
      const alert = this.alerts.find(a => a.id === alertId);
      if (alert) {
        alert.status = 'resolved';
        alert.resolved_at = new Date().toISOString();
      }

      this.renderAlerts();
      this.showSuccess('알림이 해결되었습니다.');
    } catch (error) {
      console.error('Failed to resolve alert:', error);
      this.showError('알림 해결 실패');
    }
  }

  showError(message) {
    // TODO: Integrate with toast notification system
    console.error(message);
  }

  showSuccess(message) {
    // TODO: Integrate with toast notification system
    console.log(message);
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

customElements.define('alert-panel', AlertPanel);
