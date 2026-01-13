/**
 * Dashboard Page Component - Chroma Style
 * Interactive dashboard with live data, hover effects, and micro-interactions
 * Requirements: 4.4, 4.5
 */

import { wsClient } from '../services/websocket-client.js';

class DashboardPage extends HTMLElement {
  constructor() {
    super();
    this.stats = null;
    this.recentMemories = [];
    this.isLoading = true;
    this.isInitialized = false;
    this.refreshInterval = null;
    this.animationObserver = null;
  }
  
  connectedCallback() {
    if (this.isInitialized) {
      console.log('Dashboard already initialized, skipping...');
      return;
    }
    
    this.isInitialized = true;
    this.setupEventListeners();
    this.setupIntersectionObserver();
    this.setupWebSocketListeners();
    this.render();
    
    // 앱이 완전히 초기화될 때까지 기다린 후 데이터 로드
    this.waitForAppAndLoadData();
    
    // WebSocket 연결
    this.connectWebSocket();
    
    // 자동 새로고침 설정 (5분마다)
    this.setupAutoRefresh();
  }
  
  disconnectedCallback() {
    this.removeEventListeners();
    this.clearAutoRefresh();
    this.disconnectWebSocket();
    if (this.animationObserver) {
      this.animationObserver.disconnect();
    }
  }
  
  /**
   * Setup WebSocket listeners
   */
  setupWebSocketListeners() {
    // 메모리 생성 이벤트
    wsClient.on('memory_created', (data) => {
      console.log('Memory created via WebSocket:', data);
      this.handleMemoryCreated(data);
    });
    
    // 메모리 업데이트 이벤트
    wsClient.on('memory_updated', (data) => {
      console.log('Memory updated via WebSocket:', data);
      this.handleMemoryUpdated(data);
    });
    
    // 메모리 삭제 이벤트
    wsClient.on('memory_deleted', (data) => {
      console.log('Memory deleted via WebSocket:', data);
      this.handleMemoryDeleted(data);
    });
    
    // 통계 업데이트 이벤트
    wsClient.on('stats_updated', (data) => {
      console.log('Stats updated via WebSocket:', data);
      this.handleStatsUpdated(data);
    });
    
    // 연결 상태 이벤트
    wsClient.on('connected', () => {
      console.log('WebSocket connected');
      this.showConnectionStatus('connected');
    });
    
    wsClient.on('disconnected', () => {
      console.log('WebSocket disconnected');
      this.showConnectionStatus('disconnected');
    });
    
    wsClient.on('error', (error) => {
      console.error('WebSocket error:', error);
      this.showConnectionStatus('error');
    });
  }

  /**
   * Connect WebSocket
   */
  async connectWebSocket() {
    try {
      await wsClient.connect();
      console.log('Dashboard WebSocket connected');
    } catch (error) {
      console.error('Failed to connect WebSocket:', error);
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
    const { memory } = data;
    
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
   * Show connection status
   */
  showConnectionStatus(status) {
    const statusEl = this.querySelector('.connection-status');
    if (!statusEl) return;
    
    statusEl.className = `connection-status ${status}`;
    
    switch (status) {
      case 'connected':
        statusEl.innerHTML = '<span class="status-dot"></span> 실시간 연결됨';
        break;
      case 'disconnected':
        statusEl.innerHTML = '<span class="status-dot"></span> 연결 끊김';
        break;
      case 'error':
        statusEl.innerHTML = '<span class="status-dot"></span> 연결 오류';
        break;
    }
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
   * Animate new memory creation
   */
  animateMemoryCreated(container, memory) {
    // 새 메모리 카드 생성
    const newMemoryHTML = `
      <memory-card
        memory-id="${memory.id}"
        content="${this.escapeHtml(memory.content)}"
        project="${memory.project_id || ''}"
        category="${memory.category}"
        created-at="${memory.created_at}"
        updated-at="${memory.updated_at}"
        tags="${this.escapeHtml(JSON.stringify(memory.tags || []))}"
        source="${memory.source || 'unknown'}"
        style="opacity: 0; transform: translateY(-20px); transition: all 0.3s ease;"
      ></memory-card>
    `;

    // 기존 목록 업데이트
    const memoryList = container.querySelector('.recent-memories-list');
    if (memoryList) {
      // 새 메모리를 맨 앞에 추가
      memoryList.insertAdjacentHTML('afterbegin', newMemoryHTML);
      
      // 새로 추가된 카드 애니메이션
      const newCard = memoryList.firstElementChild;
      if (newCard) {
        // 하이라이트 효과
        newCard.style.background = 'linear-gradient(135deg, #f0fdf4, #dcfce7)';
        newCard.style.border = '2px solid #22c55e';
        
        // 페이드인 애니메이션
        requestAnimationFrame(() => {
          newCard.style.opacity = '1';
          newCard.style.transform = 'translateY(0)';
        });

        // 하이라이트 제거 (3초 후)
        setTimeout(() => {
          newCard.style.background = '';
          newCard.style.border = '';
          newCard.style.transition = 'all 0.3s ease';
        }, 3000);
      }

      // 10개 초과 시 마지막 항목 제거
      const cards = memoryList.querySelectorAll('memory-card');
      if (cards.length > 10) {
        const lastCard = cards[cards.length - 1];
        lastCard.style.opacity = '0';
        lastCard.style.transform = 'translateX(20px)';
        setTimeout(() => {
          if (lastCard.parentNode) {
            lastCard.parentNode.removeChild(lastCard);
          }
        }, 300);
      }
    } else {
      // 목록이 없으면 전체 재생성
      this.updateRecentMemoriesSection();
    }
  }

  /**
   * Animate memory update
   */
  animateMemoryUpdated(container, memory, index) {
    const memoryList = container.querySelector('.recent-memories-list');
    if (!memoryList) {
      this.updateRecentMemoriesSection();
      return;
    }

    const cards = memoryList.querySelectorAll('memory-card');
    const targetCard = cards[index];
    
    if (targetCard) {
      // 업데이트 하이라이트 효과
      targetCard.style.background = 'linear-gradient(135deg, #eff6ff, #dbeafe)';
      targetCard.style.border = '2px solid #3b82f6';
      targetCard.style.transform = 'scale(1.02)';
      
      // 속성 업데이트
      targetCard.setAttribute('content', this.escapeHtml(memory.content));
      targetCard.setAttribute('updated-at', memory.updated_at);
      targetCard.setAttribute('tags', this.escapeHtml(JSON.stringify(memory.tags || [])));

      // 하이라이트 제거 (2초 후)
      setTimeout(() => {
        targetCard.style.background = '';
        targetCard.style.border = '';
        targetCard.style.transform = '';
        targetCard.style.transition = 'all 0.3s ease';
      }, 2000);
    } else {
      // 카드를 찾을 수 없으면 전체 재생성
      this.updateRecentMemoriesSection();
    }
  }

  /**
   * Animate memory deletion
   */
  animateMemoryDeleted(container, memory, index) {
    const memoryList = container.querySelector('.recent-memories-list');
    if (!memoryList) {
      this.updateRecentMemoriesSection();
      return;
    }

    const cards = memoryList.querySelectorAll('memory-card');
    const targetCard = cards[index];
    
    if (targetCard) {
      // 삭제 애니메이션
      targetCard.style.background = 'linear-gradient(135deg, #fef2f2, #fee2e2)';
      targetCard.style.border = '2px solid #ef4444';
      targetCard.style.transform = 'scale(0.95)';
      targetCard.style.opacity = '0.7';
      
      // 슬라이드 아웃 후 제거
      setTimeout(() => {
        targetCard.style.transform = 'translateX(-100%)';
        targetCard.style.opacity = '0';
        
        setTimeout(() => {
          if (targetCard.parentNode) {
            targetCard.parentNode.removeChild(targetCard);
          }
        }, 300);
      }, 500);
    } else {
      // 카드를 찾을 수 없으면 전체 재생성
      this.updateRecentMemoriesSection();
    }
  }

  /**
   * Update stats section only
   */
  updateStatsSection() {
    const statsSection = this.querySelector('.stats-section');
    if (statsSection) {
      const statsContent = statsSection.querySelector('.chroma-stats-grid');
      if (statsContent) {
        statsContent.outerHTML = this.createStatsCards();
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
      console.error('Failed to refresh stats:', error);
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
      console.log(`Checking app for dashboard (attempt ${attempts + 1}/${maxAttempts})...`);
      
      if (window.app && window.app.apiClient) {
        console.log('App is ready, loading dashboard data...');
        this.loadData();
        return true;
      }
      
      attempts++;
      if (attempts >= maxAttempts) {
        console.error('App initialization timeout, trying direct API calls...');
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
    
    if (target.classList.contains('refresh-btn')) {
      this.loadData();
    } else if (target.classList.contains('view-all-btn')) {
      const section = target.getAttribute('data-section');
      this.navigateToSection(section);
    } else if (target.classList.contains('stat-card')) {
      const type = target.getAttribute('data-type');
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
      
      console.log('Loading dashboard data...');
      
      // Load stats and recent memories in parallel
      const [stats, recentResponse] = await Promise.all([
        window.app.apiClient.getStats(),
        window.app.apiClient.searchMemories(' ', { limit: 10 })  // 공백 문자 사용
      ]);
      
      console.log('Stats received:', stats);
      console.log('Recent memories received:', recentResponse);
      
      this.stats = stats;
      this.recentMemories = recentResponse.results || [];
      
      console.log('Dashboard data loaded successfully');
      
    } catch (error) {
      console.error('Failed to load dashboard data:', error);
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
    console.log('loadDataDirect called for dashboard');
    
    this.isLoading = true;
    this.updateLoadingState();
    
    try {
      console.log('Loading dashboard data via direct API calls...');
      
      // Load stats and recent memories using direct fetch
      const [statsResponse, searchResponse] = await Promise.all([
        fetch('/api/memories/stats'),
        fetch('/api/memories/search?query= &limit=10')
      ]);
      
      if (!statsResponse.ok) {
        throw new Error(`Stats API failed: ${statsResponse.status}`);
      }
      
      if (!searchResponse.ok) {
        throw new Error(`Search API failed: ${searchResponse.status}`);
      }
      
      const [stats, searchResult] = await Promise.all([
        statsResponse.json(),
        searchResponse.json()
      ]);
      
      console.log('Direct API - Stats received:', stats);
      console.log('Direct API - Recent memories received:', searchResult);
      
      this.stats = stats;
      this.recentMemories = searchResult.results || [];
      
      console.log('Direct API - Dashboard data loaded successfully');
      
    } catch (error) {
      console.error('Direct API - Failed to load dashboard data:', error);
      this.showError('대시보드 데이터를 불러오는데 실패했습니다. 페이지를 새로고침해주세요.');
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
   * Calculate trend for stats
   */
  calculateTrend(value, type) {
    // Mock trend calculation - in real app this would compare with previous period
    const trends = {
      memories: { type: 'positive', value: '+12%' },
      projects: { type: 'positive', value: '+3' },
      categories: { type: 'neutral', value: 'Stable' },
      leadtime: { type: 'positive', value: '-0.3d' }
    };
    
    return trends[type] || { type: 'neutral', value: 'N/A' };
  }
  
  /**
   * Create category distribution chart
   */
  createCategoryChart() {
    if (!this.stats || !this.stats.categories_breakdown) {
      return '<div class="loading-placeholder">Loading chart...</div>';
    }
    
    const categories = this.stats.categories_breakdown;
    const total = Object.values(categories).reduce((sum, count) => sum + count, 0);
    
    if (total === 0) {
      return '<div class="no-data">No data available</div>';
    }
    
    // 일관된 회색 톤 색상 팔레트
    const categoryColors = {
      task: '#525252',
      bug: '#737373',
      idea: '#a3a3a3',
      decision: '#404040',
      incident: '#262626',
      code_snippet: '#171717'
    };
    
    // SVG 아이콘으로 변경
    const categoryIcons = {
      task: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
               <path d="M9 12L11 14L15 10M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" stroke-width="2"/>
             </svg>`,
      bug: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M8 2V5M16 2V5M8 19L16 5M16 19L8 5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            </svg>`,
      idea: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
               <path d="M9 21H15M12 3C8.68629 3 6 5.68629 6 9C6 11.973 7.818 14.441 10.5 15.5V17C10.5 17.8284 11.1716 18.5 12 18.5C12.8284 18.5 13.5 17.8284 13.5 17V15.5C16.182 14.441 18 11.973 18 9C18 5.68629 15.3137 3 12 3Z" stroke="currentColor" stroke-width="2"/>
             </svg>`,
      decision: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M12 3L2 12L12 21L22 12L12 3Z" stroke="currentColor" stroke-width="2"/>
                </svg>`,
      incident: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M12 9V13M12 17H12.01M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" stroke-width="2"/>
                </svg>`,
      code_snippet: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M16 18L22 12L16 6M8 6L2 12L8 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>`
    };
    
    let chartHTML = '<div class="category-chart">';
    let currentAngle = 0;
    
    // Create pie chart using CSS conic-gradient
    const gradientStops = [];
    Object.entries(categories).forEach(([category, count]) => {
      const percentage = (count / total) * 100;
      const color = categoryColors[category] || '#64748b';
      
      gradientStops.push(`${color} ${currentAngle}% ${currentAngle + percentage}%`);
      currentAngle += percentage;
    });
    
    chartHTML += `
      <div class="pie-chart" style="background: conic-gradient(${gradientStops.join(', ')})"></div>
      <div class="chart-legend">
    `;
    
    Object.entries(categories).forEach(([category, count]) => {
      const percentage = ((count / total) * 100).toFixed(1);
      const color = categoryColors[category] || '#64748b';
      const icon = categoryIcons[category] || categoryIcons.task;
      
      chartHTML += `
        <div class="legend-item">
          <div class="legend-color" style="background: ${color}"></div>
          <span class="legend-icon">${icon}</span>
          <span class="legend-text">${category}</span>
          <span class="legend-count">${count} (${percentage}%)</span>
        </div>
      `;
    });
    
    chartHTML += '</div></div>';
    return chartHTML;
  }
  
  /**
   * Create recent memories list
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
    
    // Recent Activity 표시 개수 (기본 10개)
    const displayCount = this.getAttribute('recent-count') || 10;
    
    return `
      <div class="recent-memories-list">
        ${this.recentMemories.slice(0, displayCount).map(memory => `
          <memory-card
            memory-id="${memory.id}"
            content="${this.escapeHtml(memory.content)}"
            project="${memory.project_id || ''}"
            category="${memory.category}"
            created-at="${memory.created_at}"
            updated-at="${memory.updated_at}"
            tags="${this.escapeHtml(JSON.stringify(memory.tags || []))}"
            source="${memory.source || 'unknown'}"
          ></memory-card>
        `).join('')}
      </div>
    `;
  }
  
  /**
   * Create project overview
   */
  createProjectOverview() {
    if (!this.stats || !this.stats.projects_breakdown) {
      return '<div class="loading-placeholder">Loading projects...</div>';
    }
    
    const projects = this.stats.projects_breakdown;
    const projectEntries = Object.entries(projects)
      .sort(([,a], [,b]) => b - a)
      .slice(0, 5);
    
    if (projectEntries.length === 0) {
      return '<div class="no-data">No projects found</div>';
    }
    
    return `
      <div class="project-list">
        ${projectEntries.map(([project, count]) => `
          <div class="project-item">
            <div class="project-info">
              <div class="project-name">${project}</div>
              <div class="project-count">${count} memories</div>
            </div>
            <div class="project-bar">
              <div class="project-bar-fill" style="width: ${(count / Math.max(...Object.values(projects))) * 100}%"></div>
            </div>
          </div>
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
    this.className = 'dashboard-page chroma-dashboard';
    
    this.innerHTML = `
      <div class="chroma-dashboard-header">
        <div class="header-content">
          <div class="header-title-section">
            <h1 class="dashboard-title">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M3 3V21H21V3H3Z" stroke="currentColor" stroke-width="2"/>
                <path d="M7 12L12 7L17 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              Dashboard
            </h1>
            <p class="header-subtitle">Get insights into your memory collection and activity</p>
          </div>
          <div class="header-actions">
            <div class="connection-status disconnected">
              <span class="status-dot"></span> 연결 중...
            </div>
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
            <h2 class="section-title">Analytics</h2>
            <p class="section-subtitle">Data insights and trends</p>
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
                <h3>Weekly Activity</h3>
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
    // Mock weekly activity data - in real app this would come from API
    const weeklyData = [12, 19, 15, 27, 22, 18, 24];
    
    // Generate unique ID for this chart
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
    if (!window.ChromaCharts) {
      console.warn('ChromaCharts not loaded');
      return;
    }
    
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
    
    // Initialize weekly activity line chart
    const weeklyChartEl = this.querySelector('[id^="weekly-activity-"]');
    if (weeklyChartEl) {
      const weeklyData = [12, 19, 15, 27, 22, 18, 24];
      
      charts.createLineChart(
        weeklyData,
        weeklyChartEl.id,
        {
          title: 'Daily Memory Creation',
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
  .dashboard-page {
    padding: var(--space-6) 0; /* 상하 패딩만 유지, 좌우는 main-content에서 처리 */
    max-width: var(--container-xl);
    margin: 0 auto;
  }
  
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
    color: white;
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
    background: var(--bg-primary);
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
    background: var(--bg-primary);
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
    text-transform: capitalize;
  }
  
  .legend-count {
    color: var(--text-secondary);
    font-weight: 500;
  }
  
  /* Recent Memories */
  .recent-memories-list {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  
  /* Project List */
  .project-list {
    background: var(--bg-primary);
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
    color: white;
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
  
  /* Connection Status */
  .connection-status {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    border-radius: var(--border-radius);
    font-size: 0.875rem;
    font-weight: 500;
    border: 1px solid;
    transition: var(--transition);
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
  
  .connection-status.error {
    background: #fef3c7;
    border-color: #f59e0b;
    color: #d97706;
  }
  
  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: currentColor;
    animation: pulse 2s infinite;
  }
  
  .connection-status.connected .status-dot {
    background: #22c55e;
  }
  
  .connection-status.disconnected .status-dot {
    background: #ef4444;
  }
  
  .connection-status.error .status-dot {
    background: #f59e0b;
  }
  
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
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