/**
 * Dashboard Page Component - Chroma Style
 * Interactive dashboard with live data, hover effects, and micro-interactions
 * Requirements: 4.4, 4.5
 */

import { wsClient } from '../services/websocket-client.js';
import '../components/connection-status.js';

class DashboardPage extends HTMLElement {
  constructor() {
    super();
    this.stats = null;
    this.recentMemories = [];
    this.dailyCounts = [];
    this.chartDays = 7;
    this.systemHealth = null;
    this.topTags = [];
    this.isLoading = true;
    this.isInitialized = false;
    this.refreshInterval = null;
    this.animationObserver = null;
  }
  
  connectedCallback() {
    if (this.isInitialized) return;
    
    this.isInitialized = true;
    this.setupEventListeners();
    this.setupIntersectionObserver();
    this.render();
    
    // 앱이 완전히 초기화될 때까지 기다린 후 데이터 로드
    this.waitForAppAndLoadData();
    
    // WebSocket 연결 (이벤트 리스너 설정 포함)
    this.connectWebSocket();
    
    // 자동 새로고침 설정 (5분마다)
    this.setupAutoRefresh();
  }
  
  disconnectedCallback() {
    this.removeEventListeners();
    this.clearAutoRefresh();
    this.disconnectWebSocket();
    
    // WebSocket 데이터 이벤트 리스너 제거
    if (this._boundHandlers) {
      wsClient.off('memory_created', this._boundHandlers.memoryCreated);
      wsClient.off('memory_updated', this._boundHandlers.memoryUpdated);
      wsClient.off('memory_deleted', this._boundHandlers.memoryDeleted);
      wsClient.off('stats_updated', this._boundHandlers.statsUpdated);
    }
    
    if (this.animationObserver) {
      this.animationObserver.disconnect();
    }
  }
  
  /**
   * Setup WebSocket listeners - 데이터 이벤트만 처리
   * 연결 상태는 connection-status 컴포넌트가 처리
   */
  setupWebSocketListeners() {
    // 바인딩된 핸들러를 저장 (제거할 때 사용)
    this._boundHandlers = {
      memoryCreated: this.handleMemoryCreated.bind(this),
      memoryUpdated: this.handleMemoryUpdated.bind(this),
      memoryDeleted: this.handleMemoryDeleted.bind(this),
      statsUpdated: this.handleStatsUpdated.bind(this)
    };
    
    // 메모리 생성 이벤트
    wsClient.on('memory_created', this._boundHandlers.memoryCreated);
    
    // 메모리 업데이트 이벤트
    wsClient.on('memory_updated', this._boundHandlers.memoryUpdated);
    
    // 메모리 삭제 이벤트
    wsClient.on('memory_deleted', this._boundHandlers.memoryDeleted);
    
    // 통계 업데이트 이벤트
    wsClient.on('stats_updated', this._boundHandlers.statsUpdated);
  }

  /**
   * Connect WebSocket - 데이터 이벤트 리스너만 설정
   * 연결 상태 표시는 connection-status 컴포넌트가 처리
   */
  async connectWebSocket() {
    // 데이터 이벤트 리스너 설정
    this.setupWebSocketListeners();
    
    // 연결은 connection-status 컴포넌트가 처리하므로
    // 이미 연결되어 있지 않으면 연결 시도
    const status = wsClient.getConnectionStatus();
    if (!status.isConnected) {
      try {
        await wsClient.connect();
      } catch (error) {
        // WebSocket connection failed silently
      }
    }
  }

  /**
   * Disconnect WebSocket
   */
  disconnectWebSocket() {
    wsClient.disconnect();
  }

  /**
   * Handle memory created event
   */
  handleMemoryCreated(data) {
    try {
      const { memory } = data;
      if (!memory) return;
      
      // 중복 체크
      const existingIndex = this.recentMemories.findIndex(m => m.id === memory.id);
      if (existingIndex !== -1) return;
      
      // 최근 메모리 목록에 추가 (맨 앞에)
      this.recentMemories.unshift(memory);
      
      // 최대 개수 제한 (10개)
      if (this.recentMemories.length > 10) {
        this.recentMemories = this.recentMemories.slice(0, 10);
      }
      
      // UI 업데이트 - 애니메이션과 함께
      this.updateRecentMemoriesWithAnimation('created', memory);
      
      // 통계 새로고침 (비동기)
      this.refreshStatsAsync();
      
      // 토스트 알림
      this.showToast(`새 메모리가 생성되었습니다: ${memory.category}`, 'success');
    } catch (error) {
      // handleMemoryCreated error
    }
  }

  /**
   * Handle memory updated event
   */
  handleMemoryUpdated(data) {
    const { memory_id, memory } = data;
    
    // 최근 메모리 목록에서 해당 메모리 업데이트
    const index = this.recentMemories.findIndex(m => m.id === memory_id);
    if (index !== -1) {
      this.recentMemories[index] = memory;
      this.updateRecentMemoriesWithAnimation('updated', memory, index);
    }
    
    // 토스트 알림
    this.showToast(`메모리가 업데이트되었습니다`, 'info');
  }

  /**
   * Handle memory deleted event
   */
  handleMemoryDeleted(data) {
    const { memory_id } = data;
    
    // 최근 메모리 목록에서 제거
    const index = this.recentMemories.findIndex(m => m.id === memory_id);
    if (index !== -1) {
      const deletedMemory = this.recentMemories[index];
      this.recentMemories = this.recentMemories.filter(m => m.id !== memory_id);
      
      // UI 업데이트 - 애니메이션과 함께
      this.updateRecentMemoriesWithAnimation('deleted', deletedMemory, index);
    }
    
    // 통계 새로고침 (비동기)
    this.refreshStatsAsync();
    
    // 토스트 알림
    this.showToast(`메모리가 삭제되었습니다`, 'warning');
  }

  /**
   * Handle stats updated event
   */
  handleStatsUpdated(data) {
    const { stats } = data;
    this.stats = stats;
    this.updateStatsSection();
  }

  /**
   * Show toast notification
   */
  showToast(message, type = 'info') {
    // 간단한 토스트 구현
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    
    // 스타일 적용
    Object.assign(toast.style, {
      position: 'fixed',
      top: '20px',
      right: '20px',
      padding: '12px 20px',
      borderRadius: '6px',
      color: 'white',
      fontSize: '14px',
      fontWeight: '500',
      zIndex: '10000',
      opacity: '0',
      transform: 'translateY(-20px)',
      transition: 'all 0.3s ease'
    });
    
    // 타입별 배경색
    const colors = {
      success: '#10b981',
      info: '#3b82f6',
      warning: '#f59e0b',
      error: '#ef4444'
    };
    toast.style.backgroundColor = colors[type] || colors.info;
    
    document.body.appendChild(toast);
    
    // 애니메이션
    requestAnimationFrame(() => {
      toast.style.opacity = '1';
      toast.style.transform = 'translateY(0)';
    });
    
    // 3초 후 제거
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(-20px)';
      setTimeout(() => {
        if (toast.parentNode) {
          toast.parentNode.removeChild(toast);
        }
      }, 300);
    }, 3000);
  }

  /**
   * Update recent memories section only
   */
  updateRecentMemoriesSection() {
    const activityContent = this.querySelector('.activity-content');
    if (activityContent) {
      activityContent.innerHTML = this.createRecentMemories();
    }
  }

  /**
   * Update recent memories with animation
   */
  updateRecentMemoriesWithAnimation(action, memory, index = 0) {
    const activityContent = this.querySelector('.activity-content');
    if (!activityContent) return;

    switch (action) {
      case 'created':
        this.animateMemoryCreated(activityContent, memory);
        break;
      case 'updated':
        this.animateMemoryUpdated(activityContent, memory, index);
        break;
      case 'deleted':
        this.animateMemoryDeleted(activityContent, memory, index);
        break;
      default:
        this.updateRecentMemoriesSection();
    }
  }

  /**
   * Build a single compact recent-item HTML
   */
  buildRecentItemHTML(memory) {
    const icon = this.getCategorySvgIcon(memory.category);
    const preview = (memory.content || '').replace(/#{1,6}\s+/g, '').replace(/\*\*(.*?)\*\*/g, '$1').replace(/\n/g, ' ').trim();
    const truncated = preview.length > 120 ? preview.substring(0, 120) + '...' : preview;
    const timeStr = this.formatRelativeTime(memory.created_at);
    const source = memory.source && memory.source !== 'unknown' ? memory.source : '';
    return `
      <div class="recent-item" data-memory-id="${memory.id}" role="button" tabindex="0">
        <span class="recent-item-icon">${icon}</span>
        <span class="recent-item-badge">${memory.category}</span>
        ${memory.project_id ? `<span class="recent-item-project">${this.escapeHtml(memory.project_id)}</span>` : ''}
        <span class="recent-item-content">${this.escapeHtml(truncated)}</span>
        <span class="recent-item-time">${timeStr}${source ? ` · ${source}` : ''}</span>
      </div>`;
  }

  /**
   * Animate new memory creation
   */
  animateMemoryCreated(container, memory) {
    const memoryList = container.querySelector('.recent-list-compact');
    if (!memoryList) {
      this.updateRecentMemoriesSection();
      return;
    }

    const newItemHTML = this.buildRecentItemHTML(memory);
    memoryList.insertAdjacentHTML('afterbegin', newItemHTML);

    const newItem = memoryList.firstElementChild;
    if (newItem) {
      newItem.style.opacity = '0';
      newItem.style.background = 'rgba(34, 197, 94, 0.1)';
      requestAnimationFrame(() => {
        newItem.style.transition = 'all 0.3s ease';
        newItem.style.opacity = '1';
      });
      setTimeout(() => { newItem.style.background = ''; }, 3000);
    }

    const items = memoryList.querySelectorAll('.recent-item');
    if (items.length > 10) {
      const last = items[items.length - 1];
      last.style.opacity = '0';
      setTimeout(() => last.remove(), 300);
    }
  }

  /**
   * Animate memory update
   */
  animateMemoryUpdated(container, memory, index) {
    const memoryList = container.querySelector('.recent-list-compact');
    if (!memoryList) {
      this.updateRecentMemoriesSection();
      return;
    }

    const items = memoryList.querySelectorAll('.recent-item');
    const target = items[index];
    
    if (target) {
      target.style.background = 'rgba(59, 130, 246, 0.1)';
      const contentEl = target.querySelector('.recent-item-content');
      if (contentEl) {
        const preview = (memory.content || '').replace(/#{1,6}\s+/g, '').replace(/\*\*(.*?)\*\*/g, '$1').replace(/\n/g, ' ').trim();
        contentEl.textContent = preview.length > 120 ? preview.substring(0, 120) + '...' : preview;
      }
      setTimeout(() => { target.style.background = ''; }, 2000);
    } else {
      this.updateRecentMemoriesSection();
    }
  }

  /**
   * Animate memory deletion
   */
  animateMemoryDeleted(container, memory, index) {
    const memoryList = container.querySelector('.recent-list-compact');
    if (!memoryList) {
      this.updateRecentMemoriesSection();
      return;
    }

    const items = memoryList.querySelectorAll('.recent-item');
    const target = items[index];
    
    if (target) {
      target.style.background = 'rgba(239, 68, 68, 0.1)';
      target.style.opacity = '0.5';
      setTimeout(() => {
        target.style.opacity = '0';
        setTimeout(() => target.remove(), 300);
      }, 500);
    } else {
      this.updateRecentMemoriesSection();
    }
  }

  /**
   * Update stats section only
   */
  updateStatsSection() {
    const statsSection = this.querySelector('.stats-section');
    if (statsSection) {
      const statsGrid = statsSection.querySelector('.chroma-stats-grid');
      if (statsGrid) {
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = this.createStatsCards();
        const newGrid = tempDiv.querySelector('.chroma-stats-grid');
        if (newGrid) {
          statsGrid.innerHTML = newGrid.innerHTML;
        }
      }
    }
  }

  /**
   * Refresh stats asynchronously
   */
  async refreshStatsAsync() {
    try {
      if (window.app && window.app.apiClient) {
        const stats = await window.app.apiClient.getStats();
        this.stats = stats;
        this.updateStatsSection();
      }
    } catch (error) {
      // stats refresh failed silently
    }
  }
  setupIntersectionObserver() {
    this.animationObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('animate-in');
        }
      });
    }, {
      threshold: 0.1,
      rootMargin: '50px'
    });
  }

  /**
   * Setup auto refresh
   */
  setupAutoRefresh() {
    // 5분마다 자동 새로고침
    this.refreshInterval = setInterval(() => {
      if (!this.isLoading) {
        this.loadData();
      }
    }, 5 * 60 * 1000);
  }

  /**
   * Clear auto refresh
   */
  clearAutoRefresh() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
      this.refreshInterval = null;
    }
  }

  /**
   * Wait for app initialization and then load data
   */
  async waitForAppAndLoadData() {
    // 앱이 초기화될 때까지 최대 5초 대기
    let attempts = 0;
    const maxAttempts = 50; // 100ms * 50 = 5초
    
    const checkApp = () => {
      if (window.app && window.app.apiClient) {
        this.loadData();
        return true;
      }
      
      attempts++;
      if (attempts >= maxAttempts) {
        this.loadDataDirect();
        return false;
      }
      
      setTimeout(checkApp, 100);
      return false;
    };
    
    checkApp();
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    this.addEventListener('click', this.handleClick.bind(this));
    this.addEventListener('mouseenter', this.handleMouseEnter.bind(this), true);
    this.addEventListener('mouseleave', this.handleMouseLeave.bind(this), true);
    
    // Listen for memory selection events
    this.addEventListener('memory-select', this.handleMemorySelect.bind(this));
    
    // Listen for refresh events
    window.addEventListener('data-refresh', this.loadData.bind(this));
    
    // Listen for visibility change to pause/resume auto refresh
    document.addEventListener('visibilitychange', this.handleVisibilityChange.bind(this));
  }
  
  /**
   * Remove event listeners
   */
  removeEventListeners() {
    window.removeEventListener('data-refresh', this.loadData);
    document.removeEventListener('visibilitychange', this.handleVisibilityChange);
  }

  /**
   * Handle mouse enter for micro-interactions
   */
  handleMouseEnter(event) {
    const target = event.target;
    
    if (target.classList.contains('stat-card')) {
      this.animateStatCard(target, 'enter');
    } else if (target.classList.contains('memory-card')) {
      this.animateMemoryCard(target, 'enter');
    } else if (target.classList.contains('chart-section')) {
      this.animateChart(target, 'enter');
    }
  }

  /**
   * Handle mouse leave for micro-interactions
   */
  handleMouseLeave(event) {
    const target = event.target;
    
    if (target.classList.contains('stat-card')) {
      this.animateStatCard(target, 'leave');
    } else if (target.classList.contains('memory-card')) {
      this.animateMemoryCard(target, 'leave');
    } else if (target.classList.contains('chart-section')) {
      this.animateChart(target, 'leave');
    }
  }

  /**
   * Handle visibility change
   */
  handleVisibilityChange() {
    if (document.hidden) {
      this.clearAutoRefresh();
    } else {
      this.setupAutoRefresh();
      // 페이지가 다시 보일 때 데이터 새로고침
      if (!this.isLoading) {
        this.loadData();
      }
    }
  }

  /**
   * Animate stat card
   */
  animateStatCard(card, type) {
    const icon = card.querySelector('.stat-icon');
    const number = card.querySelector('.stat-number');
    
    if (type === 'enter') {
      card.style.transform = 'translateY(-4px)';
      card.style.boxShadow = '0 8px 25px rgba(0, 0, 0, 0.15)';
      if (icon) icon.style.transform = 'scale(1.1)';
      if (number) number.style.color = 'var(--primary-500)';
    } else {
      card.style.transform = '';
      card.style.boxShadow = '';
      if (icon) icon.style.transform = '';
      if (number) number.style.color = '';
    }
  }

  /**
   * Animate memory card
   */
  animateMemoryCard(card, type) {
    if (type === 'enter') {
      card.style.transform = 'translateX(4px)';
      card.style.borderColor = 'var(--primary-400)';
    } else {
      card.style.transform = '';
      card.style.borderColor = '';
    }
  }

  /**
   * Animate chart
   */
  animateChart(chart, type) {
    const bars = chart.querySelectorAll('.chart-bar-fill');
    
    if (type === 'enter') {
      bars.forEach((bar, index) => {
        setTimeout(() => {
          bar.style.transform = 'scaleY(1.05)';
        }, index * 50);
      });
    } else {
      bars.forEach(bar => {
        bar.style.transform = '';
      });
    }
  }
  
  /**
   * Handle click events
   */
  handleClick(event) {
    const target = event.target;
    
    // Refresh button (check both self and parent for SVG clicks)
    if (target.closest('.chroma-refresh-btn')) {
      this.loadData();
      return;
    }
    
    // Settings button
    if (target.closest('.chroma-settings-btn')) {
      if (window.app && window.app.router) {
        window.app.router.navigate('/settings');
      }
      return;
    }

    // Time range selector
    const timeRangeBtn = target.closest('.time-range-btn');
    if (timeRangeBtn) {
      const days = parseInt(timeRangeBtn.getAttribute('data-days'));
      if (days && days !== this.chartDays) {
        this.chartDays = days;
        this.loadData();
      }
      return;
    }

    // Chart expand button
    if (target.closest('.chart-expand-btn')) {
      const chartCard = target.closest('.chart-card');
      if (chartCard) this.expandChart(chartCard);
      return;
    }
    
    // Recent activity item click
    const recentItem = target.closest('.recent-item');
    if (recentItem) {
      const memoryId = recentItem.getAttribute('data-memory-id');
      if (memoryId && window.app && window.app.router) {
        window.app.router.navigate(`/memory/${memoryId}`);
      }
      return;
    }

    if (target.classList.contains('view-all-btn') || target.closest('.view-all-btn')) {
      const btn = target.closest('.view-all-btn') || target;
      const section = btn.getAttribute('data-section');
      this.navigateToSection(section);
    } else if (target.closest('.chroma-stat-card')) {
      const card = target.closest('.chroma-stat-card');
      const type = card.getAttribute('data-type');
      this.navigateToFilteredView(type);
    }
  }
  
  /**
   * Handle memory selection
   */
  handleMemorySelect(event) {
    const { memoryId } = event.detail;
    if (window.app && window.app.router) {
      window.app.router.navigate(`/memory/${memoryId}`);
    }
  }
  
  /**
   * Navigate to section
   */
  navigateToSection(section) {
    if (window.app && window.app.router) {
      switch (section) {
        case 'memories':
          window.app.router.navigate('/memories?view=recent');
          break;
        case 'projects':
          window.app.router.navigate('/projects');
          break;
        case 'analytics':
          window.app.router.navigate('/analytics');
          break;
      }
    }
  }
  
  /**
   * Navigate to filtered view
   */
  navigateToFilteredView(type) {
    if (window.app && window.app.router) {
      const filters = {};
      
      switch (type) {
        case 'category':
          // Navigate to memories with category filter
          window.app.router.navigate('/memories?view=category');
          break;
        case 'project':
          window.app.router.navigate('/memories?view=project');
          break;
        default:
          window.app.router.navigate('/memories?view=recent');
      }
    }
  }
  
  /**
   * Expand a chart card into a modal
   */
  expandChart(chartCard) {
    const title = chartCard.querySelector('.chart-header h3')?.textContent || 'Chart';
    const content = chartCard.querySelector('.chart-content');
    if (!content) return;

    const overlay = document.createElement('div');
    overlay.className = 'chart-modal-overlay';
    overlay.innerHTML = `
      <div class="chart-modal">
        <div class="chart-modal-header">
          <h3>${title}</h3>
          <button class="chart-modal-close" title="Close">&times;</button>
        </div>
        <div class="chart-modal-body">${content.innerHTML}</div>
      </div>
    `;
    document.body.appendChild(overlay);

    requestAnimationFrame(() => overlay.classList.add('active'));

    const close = () => {
      overlay.classList.remove('active');
      setTimeout(() => overlay.remove(), 200);
    };
    overlay.querySelector('.chart-modal-close').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  }

  /**
   * Load dashboard data
   */
  async loadData() {
    this.isLoading = true;
    this.updateLoadingState();
    
    try {
      // 앱과 API 클라이언트 가용성 재확인
      if (!window.app) {
        throw new Error('App not available');
      }
      
      if (!window.app.apiClient) {
        throw new Error('API client not available');
      }
      
      // Load stats, recent memories, pin stats, and daily counts in parallel
      const [stats, recentResponse, pinStatsResponse, dailyResponse, healthResponse, projectsResponse] = await Promise.all([
        window.app.apiClient.getStats(),
        window.app.apiClient.searchMemories(' ', { limit: 10 }),
        window.app.apiClient.get('/work/projects/default/stats').catch(() => null),
        window.app.apiClient.get(`/memories/daily-counts?days=${this.chartDays}`).catch(() => null),
        window.app.apiClient.get('/monitoring/dashboard/summary').catch(() => null),
        window.app.apiClient.get('/projects').catch(() => null)
      ]);
      
      this.stats = stats;
      this.recentMemories = recentResponse.results || [];
      this.dailyCounts = dailyResponse?.daily_counts || [];
      this.systemHealth = healthResponse;

      // Extract top tags from projects data (tags is an array of strings per project)
      if (projectsResponse?.projects) {
        const tagCounts = {};
        projectsResponse.projects.forEach(p => {
          if (Array.isArray(p.tags)) {
            p.tags.forEach(tag => {
              if (tag && typeof tag === 'string') {
                tagCounts[tag] = (tagCounts[tag] || 0) + 1;
              }
            });
          }
        });
        this.topTags = Object.entries(tagCounts)
          .sort(([,a], [,b]) => b - a)
          .slice(0, 15);
      }
      
      // Pin stats에서 avg_lead_time 추가
      if (pinStatsResponse && pinStatsResponse.pins) {
        this.stats.average_lead_time = pinStatsResponse.pins.avg_lead_time_hours 
          ? pinStatsResponse.pins.avg_lead_time_hours / 24
          : 0;
        this.stats.pin_stats = pinStatsResponse.pins;
      }
      
    } catch (error) {
      if (window.app && window.app.errorHandler) {
        window.app.errorHandler.showError('Failed to load dashboard data');
      }
    } finally {
      this.isLoading = false;
      this.render();
    }
  }

  /**
   * Load dashboard data using direct API calls (fallback)
   */
  async loadDataDirect() {
    this.isLoading = true;
    this.updateLoadingState();
    
    try {
      // Load stats, recent memories, pin stats, and daily counts using APIClient
      const api = window.app?.apiClient;
      if (!api) throw new Error('APIClient not available');

      const [stats, searchResult, pinStats, dailyResponse, healthResponse, projectsResponse] = await Promise.all([
        api.getStats(),
        api.searchMemories(' ', { limit: 10 }),
        api.get('/work/projects/default/stats').catch(() => null),
        api.get(`/memories/daily-counts?days=${this.chartDays}`).catch(() => null),
        api.get('/monitoring/dashboard/summary').catch(() => null),
        api.get('/projects').catch(() => null)
      ]);
      
      this.stats = stats;
      this.recentMemories = searchResult.results || [];
      this.dailyCounts = dailyResponse?.daily_counts || [];
      this.systemHealth = healthResponse;

      if (projectsResponse?.projects) {
        const tagCounts = {};
        projectsResponse.projects.forEach(p => {
          if (Array.isArray(p.tags)) {
            p.tags.forEach(tag => {
              if (tag && typeof tag === 'string') {
                tagCounts[tag] = (tagCounts[tag] || 0) + 1;
              }
            });
          }
        });
        this.topTags = Object.entries(tagCounts)
          .sort(([,a], [,b]) => b - a)
          .slice(0, 15);
      }
      
      // Pin stats에서 avg_lead_time 추가
      if (pinStats && pinStats.pins) {
        this.stats.average_lead_time = pinStats.pins.avg_lead_time_hours 
          ? pinStats.pins.avg_lead_time_hours / 24
          : 0;
        this.stats.pin_stats = pinStats.pins;
      }
      
    } catch (error) {
      this.showError('Failed to load dashboard data. Please refresh the page.');
    } finally {
      this.isLoading = false;
      this.render();
    }
  }

  /**
   * Show error message
   */
  showError(message) {
    this.innerHTML = `
      <div class="dashboard-error">
        <div class="error-content">
          <h1>⚠️ Error</h1>
          <p>${message}</p>
          <div class="error-actions">
            <button class="retry-btn">Retry</button>
            <button class="refresh-btn">Refresh Page</button>
          </div>
        </div>
      </div>
    `;
    
    // 이벤트 리스너 추가
    const retryBtn = this.querySelector('.retry-btn');
    const refreshBtn = this.querySelector('.refresh-btn');
    
    if (retryBtn) {
      retryBtn.addEventListener('click', () => {
        if (window.app && window.app.apiClient) {
          this.loadData();
        } else {
          this.loadDataDirect();
        }
      });
    }
    
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        window.location.reload();
      });
    }
  }
  
  /**
   * Update loading state
   */
  updateLoadingState() {
    const loadingElements = this.querySelectorAll('.loading-placeholder');
    loadingElements.forEach(el => {
      el.style.display = this.isLoading ? 'block' : 'none';
    });
    
    const contentElements = this.querySelectorAll('.dashboard-content');
    contentElements.forEach(el => {
      el.style.display = this.isLoading ? 'none' : 'block';
    });
  }
  
  /**
   * Create statistics cards - Chroma Style
   */
  createStatsCards() {
    if (!this.stats) {
      return '<div class="loading-placeholder chroma-loading">Loading statistics...</div>';
    }
    
    const totalMemories = this.stats.total_memories || 0;
    const totalProjects = this.stats.unique_projects || 0;
    const totalCategories = Object.keys(this.stats.categories_breakdown || {}).length;
    const avgLeadTime = this.stats.average_lead_time || 0;
    
    // Calculate trends (mock data for now)
    const memoryTrend = this.calculateTrend(totalMemories, 'memories');
    const projectTrend = this.calculateTrend(totalProjects, 'projects');
    
    return `
      <div class="chroma-stats-grid">
        <div class="chroma-stat-card animate-on-scroll" data-type="total">
          <div class="stat-header">
            <div class="stat-icon-wrapper">
              <div class="stat-icon">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M9 12L11 14L15 10M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" stroke-width="2"/>
                </svg>
              </div>
            </div>
            <div class="stat-trend ${memoryTrend.type}">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M7 14L12 9L17 14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <span>${memoryTrend.value}</span>
            </div>
          </div>
          <div class="stat-content">
            <div class="stat-number" data-count="${totalMemories}">${totalMemories.toLocaleString()}</div>
            <div class="stat-label">Total Memories</div>
            <div class="stat-description">All stored memories</div>
          </div>
        </div>
        
        <div class="chroma-stat-card animate-on-scroll" data-type="project">
          <div class="stat-header">
            <div class="stat-icon-wrapper">
              <div class="stat-icon">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M22 19C22 19.5304 21.7893 20.0391 21.4142 20.4142C21.0391 20.7893 20.5304 21 20 21H4C3.46957 21 2.96086 20.7893 2.58579 20.4142C2.21071 20.0391 2 19.5304 2 19V5C2 4.46957 2.21071 3.96086 2.58579 3.58579C2.96086 3.21071 3.46957 3 4 3H9L11 6H20C20.5304 6 21.0391 6.21071 21.4142 6.58579C21.7893 6.96086 22 7.46957 22 8V19Z" stroke="currentColor" stroke-width="2"/>
                </svg>
              </div>
            </div>
            <div class="stat-trend ${projectTrend.type}">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M7 14L12 9L17 14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <span>${projectTrend.value}</span>
            </div>
          </div>
          <div class="stat-content">
            <div class="stat-number" data-count="${totalProjects}">${totalProjects}</div>
            <div class="stat-label">Active Projects</div>
            <div class="stat-description">Organized collections</div>
          </div>
        </div>
        
        <div class="chroma-stat-card animate-on-scroll" data-type="category">
          <div class="stat-header">
            <div class="stat-icon-wrapper">
              <div class="stat-icon">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M20.59 13.41L13.42 20.58C13.2343 20.766 13.0137 20.9135 12.7709 21.0141C12.5281 21.1148 12.2678 21.1666 12.005 21.1666C11.7422 21.1666 11.4819 21.1148 11.2391 21.0141C10.9963 20.9135 10.7757 20.766 10.59 20.58L2 12V2H12L20.59 10.59C20.9625 10.9647 21.1716 11.4716 21.1716 12C21.1716 12.5284 20.9625 13.0353 20.59 13.41V13.41Z" stroke="currentColor" stroke-width="2"/>
                  <circle cx="7" cy="7" r="1" fill="currentColor"/>
                </svg>
              </div>
            </div>
            <div class="stat-badge">
              <span>Well organized</span>
            </div>
          </div>
          <div class="stat-content">
            <div class="stat-number" data-count="${totalCategories}">${totalCategories}</div>
            <div class="stat-label">Categories</div>
            <div class="stat-description">Content types</div>
          </div>
        </div>
        
        <div class="chroma-stat-card animate-on-scroll" data-type="leadtime">
          <div class="stat-header">
            <div class="stat-icon-wrapper">
              <div class="stat-icon">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/>
                  <path d="M12 6V12L16 14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </div>
            </div>
            <div class="stat-badge success">
              <span>Improved</span>
            </div>
          </div>
          <div class="stat-content">
            <div class="stat-number" data-count="${avgLeadTime.toFixed(1)}">${avgLeadTime.toFixed(1)}d</div>
            <div class="stat-label">Avg Lead Time</div>
            <div class="stat-description">Task completion</div>
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Calculate trend for stats using daily counts data
   */
  calculateTrend(value, type) {
    if (!this.dailyCounts || this.dailyCounts.length === 0) {
      return { type: 'neutral', value: '—' };
    }

    if (type === 'memories') {
      const half = Math.floor(this.dailyCounts.length / 2);
      const recentHalf = this.dailyCounts.slice(half);
      const olderHalf = this.dailyCounts.slice(0, half);
      const recentSum = recentHalf.reduce((s, d) => s + d.count, 0);
      const olderSum = olderHalf.reduce((s, d) => s + d.count, 0);

      if (olderSum === 0) {
        return recentSum > 0
          ? { type: 'positive', value: `+${recentSum}` }
          : { type: 'neutral', value: '—' };
      }
      const pct = Math.round(((recentSum - olderSum) / olderSum) * 100);
      if (pct > 0) return { type: 'positive', value: `+${pct}%` };
      if (pct < 0) return { type: 'negative', value: `${pct}%` };
      return { type: 'neutral', value: '0%' };
    }

    if (type === 'projects') {
      const totalToday = this.dailyCounts.reduce((s, d) => s + d.count, 0);
      if (totalToday > 0 && value > 0) {
        return { type: 'positive', value: `${value}` };
      }
      return { type: 'neutral', value: `${value}` };
    }

    return { type: 'neutral', value: '—' };
  }
  
  /**
   * Create recent memories list (compact inline layout)
   */
  createRecentMemories() {
    if (this.isLoading) {
      return '<div class="loading-placeholder">Loading recent memories...</div>';
    }
    
    if (!this.recentMemories.length) {
      return `
        <div class="no-data">
          <p>No memories found</p>
          <button class="create-memory-btn">Create your first memory</button>
        </div>
      `;
    }
    
    const displayCount = this.getAttribute('recent-count') || 10;
    
    return `
      <div class="recent-list-compact">
        ${this.recentMemories.slice(0, displayCount).map(memory => {
          const icon = this.getCategorySvgIcon(memory.category);
          const preview = (memory.content || '').replace(/#{1,6}\s+/g, '').replace(/\*\*(.*?)\*\*/g, '$1').replace(/\n/g, ' ').trim();
          const truncated = preview.length > 120 ? preview.substring(0, 120) + '...' : preview;
          const timeStr = this.formatRelativeTime(memory.created_at);
          const source = memory.source && memory.source !== 'unknown' ? memory.source : '';
          return `
            <div class="recent-item" data-memory-id="${memory.id}" role="button" tabindex="0">
              <span class="recent-item-icon">${icon}</span>
              <span class="recent-item-badge">${memory.category}</span>
              ${memory.project_id ? `<span class="recent-item-project">${this.escapeHtml(memory.project_id)}</span>` : ''}
              <span class="recent-item-content">${this.escapeHtml(truncated)}</span>
              <span class="recent-item-time">${timeStr}${source ? ` · ${source}` : ''}</span>
            </div>`;
        }).join('')}
      </div>
    `;
  }

  /**
   * Get SVG icon for category (gray tone, 14px)
   */
  getCategorySvgIcon(category) {
    const icons = {
      task: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>',
      bug: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
      decision: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
      code_snippet: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
      incident: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      idea: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 00-4 12.7V17h8v-2.3A7 7 0 0012 2z"/></svg>'
    };
    return icons[category] || '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
  }

  /**
   * Format relative time string
   */
  formatRelativeTime(dateStr) {
    if (!dateStr) return '';
    const now = new Date();
    const date = new Date(dateStr);
    const diffMs = now - date;
    const diffMin = Math.floor(diffMs / 60000);
    const diffHour = Math.floor(diffMs / 3600000);
    const diffDay = Math.floor(diffMs / 86400000);
    if (diffMin < 1) return '방금';
    if (diffMin < 60) return `${diffMin}분 전`;
    if (diffHour < 24) return `${diffHour}시간 전`;
    if (diffDay < 7) return `${diffDay}일 전`;
    if (diffDay < 30) return `${Math.floor(diffDay / 7)}주 전`;
    return `${Math.floor(diffDay / 30)}개월 전`;
  }
  
  /**
   * Create search performance mini dashboard
   */
  createSearchPerfWidget() {
    const h = this.systemHealth;
    const s24h = h?.search?.last_24h || {};
    const s7d = h?.search?.last_7d || {};

    const avgMs = s24h.avg_response_time_ms != null ? `${Math.round(s24h.avg_response_time_ms)}ms` : '—';
    const noResultRate = s24h.no_results_rate != null ? `${s24h.no_results_rate}%` : '—';
    const totalSearches24h = s24h.total ?? '—';
    const totalSearches7d = s7d.total ?? '—';

    return `
      <div class="search-perf-grid">
        <div class="perf-metric">
          <div class="perf-value">${avgMs}</div>
          <div class="perf-label">평균 응답시간 (24h)</div>
        </div>
        <div class="perf-metric">
          <div class="perf-value">${totalSearches24h}</div>
          <div class="perf-label">검색 수 (24h)</div>
        </div>
        <div class="perf-metric">
          <div class="perf-value">${totalSearches7d}</div>
          <div class="perf-label">검색 수 (7일)</div>
        </div>
        <div class="perf-metric">
          <div class="perf-value">${noResultRate}</div>
          <div class="perf-label">무결과 비율</div>
        </div>
      </div>
    `;
  }

  /**
   * Create system health widget
   */
  createSystemHealthWidget() {
    const h = this.systemHealth;
    if (!h) {
      return '<div class="system-health-grid"><div class="health-item"><span class="health-indicator good"></span><div class="health-info"><div class="health-label">상태</div><div class="health-value">데이터 없음</div></div></div></div>';
    }

    const s24h = h.search?.last_24h || {};
    const avgTime = s24h.avg_response_time_ms;
    const searchStatus = avgTime == null ? 'good' : avgTime < 200 ? 'good' : avgTime < 500 ? 'warn' : 'error';
    const searchLabel = avgTime != null ? `${Math.round(avgTime)}ms` : 'N/A';

    const embed24h = h.embedding?.last_24h || {};
    const embedOps = embed24h.total_operations || 0;
    const embedOk = embedOps >= 0;

    const alerts = h.alerts?.active_count || 0;
    const alertStatus = alerts === 0 ? 'good' : alerts < 3 ? 'warn' : 'error';

    const avgSim = s24h.avg_similarity;
    const simLabel = avgSim != null ? `${(avgSim * 100).toFixed(1)}%` : 'N/A';

    return `
      <div class="system-health-grid">
        <div class="health-item">
          <span class="health-indicator ${searchStatus}"></span>
          <div class="health-info">
            <div class="health-label">검색 응답</div>
            <div class="health-value">${searchLabel}</div>
          </div>
        </div>
        <div class="health-item">
          <span class="health-indicator ${embedOk ? 'good' : 'error'}"></span>
          <div class="health-info">
            <div class="health-label">임베딩 (24h)</div>
            <div class="health-value">${embedOps}회</div>
          </div>
        </div>
        <div class="health-item">
          <span class="health-indicator ${alertStatus}"></span>
          <div class="health-info">
            <div class="health-label">알림</div>
            <div class="health-value">${alerts}건</div>
          </div>
        </div>
        <div class="health-item">
          <span class="health-indicator good"></span>
          <div class="health-info">
            <div class="health-label">검색 유사도</div>
            <div class="health-value">${simLabel}</div>
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Create top tags widget
   */
  createTopTagsWidget() {
    if (!this.topTags || this.topTags.length === 0) {
      return '<div class="no-data">태그 데이터 없음</div>';
    }

    return `
      <div class="top-tags-list">
        ${this.topTags.map(([tag, count]) => `
          <span class="top-tag-chip">#${this.escapeHtml(tag)} <span class="top-tag-count">${count}</span></span>
        `).join('')}
      </div>
    `;
  }

  /**
   * Escape HTML for safe attribute usage
   * Handles: < > & " ' to prevent XSS and attribute breaking
   */
  escapeHtml(text) {
    if (text == null) return '';
    const str = String(text);
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
  
  /**
   * Render the component - Chroma Style
   */
  render() {
    this.className = 'dashboard-page chroma-dashboard page-container';
    
    this.innerHTML = `
      <div class="page-header">
        <div class="page-header-main">
          <h1 class="page-title">Dashboard</h1>
          <p class="page-subtitle">Get insights into your memory collection and activity</p>
        </div>
        <div class="page-header-actions">
          <connection-status></connection-status>
          <button class="chroma-refresh-btn" title="Refresh data">
            <svg class="refresh-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M1 4V10H7M23 20V14H17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M20.49 9C19.9828 7.56678 19.1209 6.28392 17.9845 5.27493C16.8482 4.26595 15.4745 3.56905 13.9917 3.24575C12.5089 2.92246 10.9652 2.98546 9.51691 3.42597C8.06861 3.86648 6.76302 4.66921 5.64 5.76L1 10M23 14L18.36 18.24C17.237 19.3308 15.9314 20.1335 14.4831 20.574C13.0348 21.0145 11.4911 21.0775 10.0083 20.7542C8.52547 20.431 7.1518 19.7341 6.01547 18.7251C4.87913 17.7161 4.01717 16.4332 3.51 15" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span class="btn-text">Refresh</span>
          </button>
          <button class="chroma-settings-btn" title="Dashboard settings">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2"/>
              <path d="M19.4 15C19.2669 15.3016 19.2272 15.6362 19.286 15.9606C19.3448 16.285 19.4995 16.5843 19.73 16.82L19.79 16.88C19.976 17.0657 20.1235 17.2863 20.2241 17.5291C20.3248 17.7719 20.3766 18.0322 20.3766 18.295C20.3766 18.5578 20.3248 18.8181 20.2241 19.0609C20.1235 19.3037 19.976 19.5243 19.79 19.71C19.6043 19.896 19.3837 20.0435 19.1409 20.1441C18.8981 20.2448 18.6378 20.2966 18.375 20.2966C18.1122 20.2966 17.8519 20.2448 17.6091 20.1441C17.3663 20.0435 17.1457 19.896 16.96 19.71L16.9 19.65C16.6643 19.4195 16.365 19.2648 16.0406 19.206C15.7162 19.1472 15.3816 19.1869 15.08 19.32C14.7842 19.4468 14.532 19.6572 14.3543 19.9255C14.1766 20.1938 14.0813 20.5082 14.08 20.83V21C14.08 21.5304 13.8693 22.0391 13.4942 22.4142C13.1191 22.7893 12.6104 23 12.08 23C11.5496 23 11.0409 22.7893 10.6658 22.4142C10.2907 22.0391 10.08 21.5304 10.08 21V20.91C10.0723 20.579 9.96512 20.2573 9.77251 19.9887C9.5799 19.7201 9.31074 19.5176 9 19.41C8.69838 19.2769 8.36381 19.2372 8.03941 19.296C7.71502 19.3548 7.41568 19.5095 7.18 19.74L7.12 19.8C6.93425 19.986 6.71368 20.1335 6.47088 20.2341C6.22808 20.3348 5.96783 20.3866 5.705 20.3866C5.44217 20.3866 5.18192 20.3348 4.93912 20.2341C4.69632 20.1335 4.47575 19.986 4.29 19.8C4.10405 19.6143 3.95653 19.3937 3.85588 19.1509C3.75523 18.9081 3.70343 18.6478 3.70343 18.385C3.70343 18.1222 3.75523 17.8619 3.85588 17.6191C3.95653 17.3763 4.10405 17.1557 4.29 16.97L4.35 16.91C4.58054 16.6743 4.73519 16.375 4.794 16.0506C4.85282 15.7262 4.81312 15.3916 4.68 15.09C4.55324 14.7942 4.34276 14.542 4.07447 14.3643C3.80618 14.1866 3.49179 14.0913 3.17 14.09H3C2.46957 14.09 1.96086 13.8793 1.58579 13.5042C1.21071 13.1291 1 12.6204 1 12.09C1 11.5596 1.21071 11.0509 1.58579 10.6758C1.96086 10.3007 2.46957 10.09 3 10.09H3.09C3.42099 10.0823 3.742 9.97512 4.01062 9.78251C4.27925 9.5899 4.48167 9.32074 4.59 9.01C4.72312 8.70838 4.76282 8.37381 4.704 8.04941C4.64519 7.72502 4.49054 7.42568 4.26 7.19L4.2 7.13C4.01405 6.94425 3.86653 6.72368 3.76588 6.48088C3.66523 6.23808 3.61343 5.97783 3.61343 5.715C3.61343 5.45217 3.66523 5.19192 3.76588 4.94912C3.86653 4.70632 4.01405 4.48575 4.2 4.3C4.38575 4.11405 4.60632 3.96653 4.84912 3.86588C5.09192 3.76523 5.35217 3.71343 5.615 3.71343C5.87783 3.71343 6.13808 3.76523 6.38088 3.86588C6.62368 3.96653 6.84425 4.11405 7.03 4.3L7.09 4.36C7.32568 4.59054 7.62502 4.74519 7.94941 4.804C8.27381 4.86282 8.60838 4.82312 8.91 4.69H9C9.29577 4.56324 9.54802 4.35276 9.72569 4.08447C9.90337 3.81618 9.99872 3.50179 10 3.18V3C10 2.46957 10.2107 1.96086 10.5858 1.58579C10.9609 1.21071 11.4696 1 12 1C12.5304 1 13.0391 1.21071 13.4142 1.58579C13.7893 1.96086 14 2.46957 14 3V3.09C14.0013 3.41179 14.0966 3.72618 14.2743 3.99447C14.452 4.26276 14.7042 4.47324 15 4.6C15.3016 4.73312 15.6362 4.77282 15.9606 4.714C16.285 4.65519 16.5843 4.50054 16.82 4.27L16.88 4.21C17.0657 4.02405 17.2863 3.87653 17.5291 3.77588C17.7719 3.67523 18.0322 3.62343 18.295 3.62343C18.5578 3.62343 18.8181 3.67523 19.0609 3.77588C19.3037 3.87653 19.5243 4.02405 19.71 4.21C19.896 4.39575 20.0435 4.61632 20.1441 4.85912C20.2448 5.10192 20.2966 5.36217 20.2966 5.625C20.2966 5.88783 20.2448 6.14808 20.1441 6.39088C20.0435 6.63368 19.896 6.85425 19.71 7.04L19.65 7.1C19.4195 7.33568 19.2648 7.63502 19.206 7.95941C19.1472 8.28381 19.1869 8.61838 19.32 8.92V9C19.4468 9.29577 19.6572 9.54802 19.9255 9.72569C20.1938 9.90337 20.5082 9.99872 20.83 10H21C21.5304 10 22.0391 10.2107 22.4142 10.5858C22.7893 10.9609 23 11.4696 23 12C23 12.5304 22.7893 13.0391 22.4142 13.4142C22.0391 13.7893 21.5304 14 21 14H20.91C20.5882 14.0013 20.2738 14.0966 20.0055 14.2743C19.7372 14.452 19.5268 14.7042 19.4 15Z" stroke="currentColor" stroke-width="2"/>
            </svg>
          </button>
        </div>
      </div>
      
      <div class="chroma-dashboard-content">
        <!-- Statistics Section -->
        <section class="chroma-dashboard-section stats-section">
          <div class="section-header">
            <h2 class="section-title">Overview</h2>
            <p class="section-subtitle">Key metrics and performance indicators</p>
          </div>
          ${this.createStatsCards()}
        </section>
        
        <!-- Charts and Analytics Section -->
        <section class="chroma-dashboard-section charts-section">
          <div class="section-header">
            <div>
              <h2 class="section-title">Analytics</h2>
              <p class="section-subtitle">Data insights and trends</p>
            </div>
            <div class="time-range-selector">
              <button class="time-range-btn${this.chartDays === 7 ? ' active' : ''}" data-days="7">7일</button>
              <button class="time-range-btn${this.chartDays === 30 ? ' active' : ''}" data-days="30">30일</button>
              <button class="time-range-btn${this.chartDays === 90 ? ' active' : ''}" data-days="90">90일</button>
            </div>
          </div>
          <div class="charts-grid">
            <div class="chart-card animate-on-scroll">
              <div class="chart-header">
                <h3>Category Distribution</h3>
                <button class="chart-expand-btn" title="Expand chart">
                  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M15 3H21V9M9 21H3V15M21 3L14 10M3 21L10 14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                </button>
              </div>
              <div class="chart-content">
                ${this.createCategoryChart()}
              </div>
            </div>
            
            <div class="chart-card animate-on-scroll">
              <div class="chart-header">
                <h3>Top Projects</h3>
                <button class="view-all-btn" data-section="projects">View All</button>
              </div>
              <div class="chart-content">
                ${this.createProjectOverview()}
              </div>
            </div>
            
            <div class="chart-card animate-on-scroll">
              <div class="chart-header">
                <h3>${this.chartDays <= 7 ? 'Weekly' : this.chartDays <= 30 ? 'Monthly' : 'Quarterly'} Activity</h3>
                <button class="chart-expand-btn" title="Expand chart">
                  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M15 3H21V9M9 21H3V15M21 3L14 10M3 21L10 14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                </button>
              </div>
              <div class="chart-content">
                ${this.createWeeklyActivityChart()}
              </div>
            </div>
          </div>
        </section>
        
        <!-- System Health & Top Tags Row -->
        <section class="chroma-dashboard-section">
          <div class="charts-grid">
            <div class="chart-card animate-on-scroll">
              <div class="chart-header">
                <h3>시스템 상태</h3>
              </div>
              <div class="chart-content">
                ${this.createSystemHealthWidget()}
              </div>
            </div>
            <div class="chart-card animate-on-scroll">
              <div class="chart-header">
                <h3>인기 태그</h3>
              </div>
              <div class="chart-content">
                ${this.createTopTagsWidget()}
              </div>
            </div>
          </div>
        </section>

        <!-- Search Performance Mini Dashboard -->
        <section class="chroma-dashboard-section">
          <div class="chart-card animate-on-scroll">
            <div class="chart-header">
              <h3>검색 성능</h3>
              <button class="view-all-btn" data-section="analytics">상세 보기</button>
            </div>
            <div class="chart-content">
              ${this.createSearchPerfWidget()}
            </div>
          </div>
        </section>

        <!-- Recent Activity Section -->
        <section class="chroma-dashboard-section activity-section">
          <div class="section-header">
            <h2 class="section-title">Recent Activity</h2>
            <p class="section-subtitle">Latest memories and updates</p>
            <button class="view-all-btn" data-section="memories">View All</button>
          </div>
          <div class="activity-content animate-on-scroll">
            ${this.createRecentMemories()}
          </div>
        </section>
      </div>
    `;
    
    // Setup intersection observer for animations
    this.setupScrollAnimations();
    
    // Setup create memory button if it exists
    const createBtn = this.querySelector('.create-memory-btn');
    if (createBtn) {
      createBtn.addEventListener('click', () => {
        if (window.app && window.app.router) {
          window.app.router.navigate('/create');
        }
      });
    }
  }

  /**
   * Setup scroll animations
   */
  setupScrollAnimations() {
    const animateElements = this.querySelectorAll('.animate-on-scroll');
    
    if (this.animationObserver) {
      animateElements.forEach(el => {
        this.animationObserver.observe(el);
      });
    }
    
    // Animate stat numbers
    this.animateStatNumbers();
    
    // Initialize charts after a short delay
    setTimeout(() => {
      this.initializeCharts();
    }, 300);
  }

  /**
   * Animate stat numbers with counting effect
   */
  animateStatNumbers() {
    const statNumbers = this.querySelectorAll('.stat-number[data-count]');
    
    statNumbers.forEach(numberEl => {
      const targetValue = parseFloat(numberEl.getAttribute('data-count'));
      const duration = 1500;
      const startTime = performance.now();
      
      const animate = (currentTime) => {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        
        // Easing function
        const easeOutQuart = 1 - Math.pow(1 - progress, 4);
        const currentValue = targetValue * easeOutQuart;
        
        if (targetValue % 1 === 0) {
          numberEl.textContent = Math.floor(currentValue).toLocaleString();
        } else {
          numberEl.textContent = currentValue.toFixed(1);
        }
        
        if (progress < 1) {
          requestAnimationFrame(animate);
        }
      };
      
      // Start animation after a small delay
      setTimeout(() => {
        requestAnimationFrame(animate);
      }, 300);
    });
  }

  /**
   * Create category distribution chart - Enhanced with Chroma Charts
   */
  createCategoryChart() {
    if (!this.stats || !this.stats.categories_breakdown) {
      return '<div class="loading-placeholder chroma-loading">Loading chart...</div>';
    }
    
    const categories = this.stats.categories_breakdown;
    const total = Object.values(categories).reduce((sum, count) => sum + count, 0);
    
    if (total === 0) {
      return '<div class="no-data">No data available</div>';
    }
    
    // Generate unique ID for this chart
    const chartId = `category-chart-${Date.now()}`;
    
    return `
      <div class="enhanced-category-chart">
        <div id="${chartId}" class="chart-placeholder" style="min-height: 300px;"></div>
      </div>
    `;
  }

  /**
   * Create project overview with enhanced bar chart
   */
  createProjectOverview() {
    if (!this.stats || !this.stats.projects_breakdown) {
      return '<div class="loading-placeholder chroma-loading">Loading projects...</div>';
    }
    
    const projects = this.stats.projects_breakdown;
    const projectEntries = Object.entries(projects)
      .sort(([,a], [,b]) => b - a)
      .slice(0, 5);
    
    if (projectEntries.length === 0) {
      return '<div class="no-data">No projects found</div>';
    }
    
    // Generate unique ID for this chart
    const chartId = `projects-chart-${Date.now()}`;
    
    return `
      <div class="enhanced-projects-chart">
        <div id="${chartId}" class="chart-placeholder" style="min-height: 250px;"></div>
      </div>
    `;
  }

  /**
   * Create weekly activity chart
   */
  createWeeklyActivityChart() {
    const chartId = `weekly-activity-${Date.now()}`;
    
    return `
      <div class="enhanced-weekly-chart">
        <div id="${chartId}" class="chart-placeholder" style="min-height: 200px;"></div>
      </div>
    `;
  }

  /**
   * Initialize charts after render
   */
  initializeCharts() {
    if (!window.ChromaCharts) return;
    
    const charts = new ChromaCharts();
    
    // Initialize category donut chart
    const categoryChartEl = this.querySelector('[id^="category-chart-"]');
    if (categoryChartEl && this.stats && this.stats.categories_breakdown) {
      charts.createCategoryDonutChart(
        this.stats.categories_breakdown,
        categoryChartEl.id
      );
    }
    
    // Initialize projects bar chart
    const projectsChartEl = this.querySelector('[id^="projects-chart-"]');
    if (projectsChartEl && this.stats && this.stats.projects_breakdown) {
      const projectsData = Object.fromEntries(
        Object.entries(this.stats.projects_breakdown)
          .sort(([,a], [,b]) => b - a)
          .slice(0, 5)
      );
      
      charts.createBarChart(
        projectsData,
        projectsChartEl.id,
        {
          title: 'Top Projects by Memory Count',
          showValues: true,
          animate: true,
          height: 250
        }
      );
    }
    
    // Initialize weekly activity line chart with real data
    const weeklyChartEl = this.querySelector('[id^="weekly-activity-"]');
    if (weeklyChartEl) {
      const dailyData = this.dailyCounts.length > 0
        ? this.dailyCounts.map(d => d.count)
        : [0];
      const dailyLabels = this.dailyCounts.length > 0
        ? this.dailyCounts.map(d => d.date)
        : [];
      
      charts.createLineChart(
        dailyData,
        weeklyChartEl.id,
        {
          title: 'Daily Memory Creation',
          labels: dailyLabels,
          showPoints: true,
          showGrid: true,
          animate: true,
          height: 200,
          width: 400
        }
      );
    }
  }
}

// Define the custom element
customElements.define('dashboard-page', DashboardPage);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .dashboard-page .dashboard-header {
    margin-bottom: var(--space-8);
  }
  
  .dashboard-page .dashboard-content {
    /* No additional constraints needed */
  }
  
  .dashboard-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    margin-bottom: 2rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border-color);
  }
  
  .header-content h1 {
    margin: 0 0 0.5rem 0;
    font-size: 2rem;
    color: var(--text-primary);
  }
  
  .header-subtitle {
    margin: 0;
    color: var(--text-secondary);
    font-size: 1rem;
  }
  
  .refresh-btn {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: var(--primary-color);
    color: var(--bg-primary);
    border: none;
    padding: 0.75rem 1rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
    transition: var(--transition);
  }
  
  .refresh-btn:hover {
    background: var(--primary-hover);
  }
  
  .refresh-icon {
    width: 1rem;
    height: 1rem;
  }
  
  .dashboard-section {
    margin-bottom: 3rem;
  }
  
  .section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
  }
  
  .section-header h2 {
    margin: 0;
    font-size: 1.5rem;
    color: var(--text-primary);
  }
  
  .view-all-btn {
    background: none;
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    padding: 0.5rem 1rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    transition: var(--transition);
  }
  
  .view-all-btn:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }
  
  /* Statistics Grid */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 1.5rem;
  }
  
  .stat-card {
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 1.5rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    cursor: pointer;
    transition: var(--transition);
  }
  
  .stat-card:hover {
    box-shadow: var(--shadow-md);
    transform: translateY(-2px);
    border-color: var(--border-hover);
  }
  
  .stat-icon {
    width: 2rem;
    height: 2rem;
    color: var(--text-secondary);
    opacity: 0.8;
  }
  
  .stat-icon svg {
    width: 100%;
    height: 100%;
  }
  
  .stat-content {
    flex: 1;
  }
  
  .stat-number {
    font-size: 2rem;
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1;
    margin-bottom: 0.25rem;
  }
  
  .stat-label {
    font-size: 0.875rem;
    color: var(--text-secondary);
    font-weight: 500;
  }
  
  /* Category Chart */
  .category-chart {
    display: flex;
    align-items: center;
    gap: 2rem;
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 2rem;
  }
  
  .pie-chart {
    width: 200px;
    height: 200px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  
  .chart-legend {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }
  
  .legend-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    font-size: 0.875rem;
  }
  
  .legend-color {
    width: 1rem;
    height: 1rem;
    border-radius: 50%;
    flex-shrink: 0;
  }
  
  .legend-icon {
    width: 1rem;
    height: 1rem;
    color: var(--text-secondary);
  }
  
  .legend-icon svg {
    width: 100%;
    height: 100%;
  }
  
  .legend-text {
    flex: 1;
    color: var(--text-primary);
  }
  
  .legend-count {
    color: var(--text-secondary);
    font-weight: 500;
  }
  
  /* Recent Activity - Compact List */
  .recent-list-compact {
    display: flex;
    flex-direction: column;
  }

  .recent-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border-color);
    cursor: pointer;
    transition: background 0.15s;
    font-size: 0.8125rem;
    line-height: 1.4;
  }

  .recent-item:last-child {
    border-bottom: none;
  }

  .recent-item:hover {
    background: var(--bg-secondary);
  }

  .recent-item-icon {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    color: var(--text-muted);
  }

  .recent-item-icon svg {
    display: block;
  }

  .recent-item-badge {
    flex-shrink: 0;
    font-size: 0.6875rem;
    padding: 1px 6px;
    border-radius: var(--border-radius-sm);
    background: var(--bg-secondary);
    color: var(--text-secondary);
    font-weight: 500;
  }

  .recent-item-project {
    flex-shrink: 0;
    font-size: 0.6875rem;
    padding: 1px 6px;
    border-radius: var(--border-radius-sm);
    background: var(--bg-tertiary, var(--bg-secondary));
    color: var(--text-primary);
    font-weight: 500;
    border: 1px solid var(--border-color);
  }

  .recent-item-content {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-primary);
  }

  .recent-item-time {
    flex-shrink: 0;
    font-size: 0.6875rem;
    color: var(--text-muted);
    white-space: nowrap;
  }
  
  /* Project List */
  .project-list {
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    overflow: hidden;
  }
  
  .project-item {
    padding: 1rem;
    border-bottom: 1px solid var(--border-color);
    transition: var(--transition);
  }
  
  .project-item:last-child {
    border-bottom: none;
  }
  
  .project-item:hover {
    background: var(--bg-secondary);
  }
  
  .project-info {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
  }
  
  .project-name {
    font-weight: 500;
    color: var(--text-primary);
  }
  
  .project-count {
    font-size: 0.875rem;
    color: var(--text-secondary);
  }
  
  .project-bar {
    height: 4px;
    background: var(--bg-secondary);
    border-radius: 2px;
    overflow: hidden;
  }
  
  .project-bar-fill {
    height: 100%;
    background: var(--primary-color);
    border-radius: 2px;
    transition: width 0.3s ease;
  }
  
  /* Loading and No Data States */
  .loading-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 3rem;
    color: var(--text-muted);
    font-style: italic;
  }
  
  .no-data {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 3rem;
    color: var(--text-muted);
    text-align: center;
  }
  
  .no-data p {
    margin: 0 0 1rem 0;
    font-style: italic;
  }
  
  .create-memory-btn {
    background: var(--primary-color);
    color: var(--bg-primary);
    border: none;
    padding: 0.75rem 1.5rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
    transition: var(--transition);
  }
  
  .create-memory-btn:hover {
    background: var(--primary-hover);
  }
  
  /* Toast Notifications */
  .toast {
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
    border-radius: 8px;
    backdrop-filter: blur(10px);
  }
  
  .toast-success {
    background: linear-gradient(135deg, #10b981, #059669) !important;
  }
  
  .toast-info {
    background: linear-gradient(135deg, #3b82f6, #2563eb) !important;
  }
  
  .toast-warning {
    background: linear-gradient(135deg, #f59e0b, #d97706) !important;
  }
  
  .toast-error {
    background: linear-gradient(135deg, #ef4444, #dc2626) !important;
  }
  @media (max-width: 768px) {
    .dashboard-page {
      padding: var(--space-4) 0; /* 모바일에서 상하 패딩 줄임 */
    }
    
    .dashboard-header {
      flex-direction: column;
      gap: 1rem;
      align-items: flex-start;
    }
    
    .stats-grid {
      grid-template-columns: 1fr;
      gap: 1rem;
    }
    
    .stat-card {
      padding: 1rem;
    }
    
    .stat-number {
      font-size: 1.5rem;
    }
    
    .category-chart {
      flex-direction: column;
      gap: 1.5rem;
      padding: 1.5rem;
    }
    
    .pie-chart {
      width: 150px;
      height: 150px;
    }
    
    .section-header {
      flex-direction: column;
      gap: 0.5rem;
      align-items: flex-start;
    }
  }
`;

document.head.appendChild(style);

export { DashboardPage };