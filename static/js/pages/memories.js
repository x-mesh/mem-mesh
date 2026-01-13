/**
 * Unified Memories Page Web Component
 * Displays memories with different view modes based on URL parameters
 */

import { wsClient } from '../services/websocket-client.js';

class MemoriesPage extends HTMLElement {
  constructor() {
    super();
    this.memories = [];
    this.isLoading = false;
    this.currentView = 'recent';
    this.viewParams = {};
    this.currentPage = 1;
    this.pageSize = 25;
    this.totalMemories = 0;
    this.sortBy = 'created_at';
    this.sortDirection = 'desc';
    this.searchQuery = '';
    this.searchMode = 'hybrid'; // hybrid, vector, text
  }
  
  connectedCallback() {
    console.log('MemoriesPage connected');
    
    // Parse URL parameters
    this.parseURLParameters();
    
    this.render();
    this.setupEventListeners();
    this.setupWebSocketListeners();
    
    // Connect WebSocket
    this.connectWebSocket();
    
    // Set initial filter values from URL parameters
    setTimeout(() => {
      // Initialize category combobox with options
      const categoryCombobox = this.querySelector('.category-combobox');
      if (categoryCombobox) {
        // Set options explicitly
        categoryCombobox.setOptions([
          { value: '', text: 'All Categories' },
          { value: 'task', text: 'Task', icon: '📋' },
          { value: 'bug', text: 'Bug', icon: '🐛' },
          { value: 'idea', text: 'Idea', icon: '💡' },
          { value: 'decision', text: 'Decision', icon: '💎' },
          { value: 'incident', text: 'Incident', icon: '⚠️' },
          { value: 'code_snippet', text: 'Code Snippet', icon: '💻' },
          { value: 'git-history', text: 'Git History', icon: '📚' }
        ]);
        
        // Set initial value if provided
        if (this.viewParams.category) {
          categoryCombobox.setValue(this.viewParams.category);
        }
      }
      
      const projectCombobox = this.querySelector('.project-combobox');
      if (projectCombobox && this.viewParams.project_id) {
        projectCombobox.setValue(this.viewParams.project_id);
      }
    }, 100);
    
    // Load memories after a short delay
    setTimeout(() => {
      this.loadProjectsForFilter();
      this.loadMemories();
    }, 100);
  }
  
  disconnectedCallback() {
    console.log('MemoriesPage disconnected');
    
    // WebSocket 이벤트 리스너 제거
    wsClient.off('memory_created', this.handleMemoryCreated);
    wsClient.off('memory_updated', this.handleMemoryUpdated);
    wsClient.off('memory_deleted', this.handleMemoryDeleted);
    wsClient.off('connected', this.showConnectionStatus);
    wsClient.off('disconnected', this.showConnectionStatus);
    wsClient.off('error', this.showConnectionStatus);
    
    // 프로젝트 구독 해제
    if (this.viewParams.project_id) {
      wsClient.unsubscribeFromProject(this.viewParams.project_id);
    }
  }
  
  /**
   * Parse URL parameters to determine view mode
   */
  parseURLParameters() {
    const urlParams = new URLSearchParams(window.location.search);
    
    // Get view mode (default: recent)
    this.currentView = urlParams.get('view') || 'recent';
    
    // Parse view-specific parameters
    this.viewParams = {
      project_id: urlParams.get('project_id'),
      category: urlParams.get('category'),
      query: urlParams.get('query'),
      tag: urlParams.get('tag'),
      limit: parseInt(urlParams.get('limit')) || this.pageSize,
      source: urlParams.get('source')
    };
    
    // Set search query if provided
    this.searchQuery = this.viewParams.query || '';
    
    console.log('View mode:', this.currentView, 'Params:', this.viewParams);
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
    
    // 연결 상태 이벤트
    wsClient.on('connected', () => {
      console.log('WebSocket connected in memories page');
      this.showConnectionStatus('connected');
    });
    
    wsClient.on('disconnected', () => {
      console.log('WebSocket disconnected in memories page');
      this.showConnectionStatus('disconnected');
    });
    
    wsClient.on('error', (error) => {
      console.error('WebSocket error in memories page:', error);
      this.showConnectionStatus('error');
    });
  }

  /**
   * Connect WebSocket
   */
  async connectWebSocket() {
    try {
      await wsClient.connect();
      console.log('Memories page WebSocket connected');
      
      // 현재 프로젝트가 있으면 구독
      if (this.viewParams.project_id) {
        wsClient.subscribeToProject(this.viewParams.project_id);
      }
    } catch (error) {
      console.error('Failed to connect WebSocket in memories page:', error);
    }
  }

  /**
   * Handle memory created event
   */
  handleMemoryCreated(data) {
    const { memory } = data;
    
    // 현재 필터 조건에 맞는지 확인
    if (this.shouldIncludeMemory(memory)) {
      // 메모리 목록 맨 앞에 추가
      this.memories.unshift(memory);
      
      // 페이지 크기 제한 적용
      if (this.memories.length > this.pageSize) {
        this.memories = this.memories.slice(0, this.pageSize);
      }
      
      // UI 업데이트
      this.updateMemoriesGrid();
      
      // 토스트 알림
      this.showToast(`새 메모리가 생성되었습니다: ${memory.category}`, 'success');
    }
  }

  /**
   * Handle memory updated event
   */
  handleMemoryUpdated(data) {
    const { memory_id, memory } = data;
    
    // 기존 메모리 찾기
    const index = this.memories.findIndex(m => m.id === memory_id);
    
    if (index !== -1) {
      // 업데이트된 메모리가 현재 필터 조건에 맞는지 확인
      if (this.shouldIncludeMemory(memory)) {
        this.memories[index] = memory;
        this.updateMemoriesGrid();
      } else {
        // 필터 조건에 맞지 않으면 제거
        this.memories.splice(index, 1);
        this.updateMemoriesGrid();
      }
      
      this.showToast('메모리가 업데이트되었습니다', 'info');
    } else if (this.shouldIncludeMemory(memory)) {
      // 새로 필터 조건에 맞게 된 경우 추가
      this.memories.unshift(memory);
      if (this.memories.length > this.pageSize) {
        this.memories = this.memories.slice(0, this.pageSize);
      }
      this.updateMemoriesGrid();
      this.showToast('새 메모리가 추가되었습니다', 'info');
    }
  }

  /**
   * Handle memory deleted event
   */
  handleMemoryDeleted(data) {
    const { memory_id } = data;
    
    // 메모리 목록에서 제거
    const index = this.memories.findIndex(m => m.id === memory_id);
    if (index !== -1) {
      this.memories.splice(index, 1);
      this.updateMemoriesGrid();
      this.showToast('메모리가 삭제되었습니다', 'warning');
    }
  }

  /**
   * Check if memory should be included based on current filters
   */
  shouldIncludeMemory(memory) {
    // 프로젝트 필터
    if (this.viewParams.project_id && memory.project_id !== this.viewParams.project_id) {
      return false;
    }
    
    // 카테고리 필터
    if (this.viewParams.category && memory.category !== this.viewParams.category) {
      return false;
    }
    
    // 소스 필터
    if (this.viewParams.source && memory.source !== this.viewParams.source) {
      return false;
    }
    
    // 태그 필터
    if (this.viewParams.tag) {
      const tags = memory.tags || [];
      if (!tags.includes(this.viewParams.tag)) {
        return false;
      }
    }
    
    // 검색 쿼리는 실시간으로 확인하기 어려우므로 일단 포함
    // (서버에서 검색 결과를 다시 가져와야 정확함)
    
    return true;
  }

  /**
   * Update memories grid only
   */
  updateMemoriesGrid() {
    const memoriesGrid = this.querySelector('.memories-grid');
    if (memoriesGrid) {
      memoriesGrid.innerHTML = this.createMemoriesGrid();
    }
    
    // 메모리 카드 이벤트 리스너 재설정
    this.setupMemoryCardListeners();
  }

  /**
   * Setup memory card event listeners
   */
  setupMemoryCardListeners() {
    // 메모리 카드 클릭 이벤트
    const memoryCards = this.querySelectorAll('memory-card');
    memoryCards.forEach(card => {
      // 메모리 선택 이벤트 리스너
      card.addEventListener('memory-select', this.handleMemorySelect.bind(this));
      
      // 즐겨찾기 토글 이벤트 리스너
      card.addEventListener('memory-favorite', this.handleMemoryFavorite.bind(this));
    });
    
    // 기타 메모리 관련 버튼들
    const editButtons = this.querySelectorAll('.edit-memory-btn');
    editButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const memoryId = btn.getAttribute('data-memory-id');
        if (memoryId && window.app && window.app.router) {
          window.app.router.navigate(`/memory/${memoryId}/edit`);
        }
      });
    });
    
    const deleteButtons = this.querySelectorAll('.delete-memory-btn');
    deleteButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const memoryId = btn.getAttribute('data-memory-id');
        if (memoryId && confirm('정말로 이 메모리를 삭제하시겠습니까?')) {
          this.deleteMemory(memoryId);
        }
      });
    });
  }

  /**
   * Create memories grid HTML
   */
  createMemoriesGrid() {
    if (!this.memories || this.memories.length === 0) {
      return `
        <div class="no-memories">
          <div class="no-memories-icon">📝</div>
          <h3>No memories found</h3>
          <p>No memories match your current filters.</p>
          <button class="clear-filters-btn">Clear Filters</button>
        </div>
      `;
    }
    
    return this.memories.map(memory => `
      <memory-card
        memory-id="${memory.id}"
        content="${this.escapeAttribute(memory.content)}"
        project="${memory.project_id || ''}"
        category="${memory.category}"
        created-at="${memory.created_at}"
        updated-at="${memory.updated_at}"
        tags="${this.escapeAttribute(JSON.stringify(memory.tags || []))}"
        source="${memory.source || 'unknown'}"
      ></memory-card>
    `).join('');
  }

  /**
   * Delete a memory
   */
  async deleteMemory(memoryId) {
    try {
      if (!window.app || !window.app.apiClient) {
        throw new Error('API client not available');
      }
      
      await window.app.apiClient.deleteMemory(memoryId);
      
      // 로컬 메모리 목록에서 제거
      this.memories = this.memories.filter(m => m.id !== memoryId);
      
      // UI 업데이트
      this.updateMemoriesGrid();
      this.updateSummary();
      
      // 성공 토스트
      this.showToast('메모리가 삭제되었습니다', 'success');
      
    } catch (error) {
      console.error('Failed to delete memory:', error);
      this.showToast('메모리 삭제에 실패했습니다', 'error');
    }
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
   * Setup event listeners
   */
  setupEventListeners() {
    // Search input
    const searchInput = this.querySelector('.search-input');
    if (searchInput) {
      searchInput.addEventListener('input', this.handleSearch.bind(this));
      searchInput.value = this.searchQuery;
    }
    
    // Sort controls
    const sortSelect = this.querySelector('.sort-select');
    if (sortSelect) {
      sortSelect.addEventListener('change', this.handleSortChange.bind(this));
    }
    
    const sortToggle = this.querySelector('.sort-toggle');
    if (sortToggle) {
      sortToggle.addEventListener('click', this.toggleSortDirection.bind(this));
    }
    
    // View mode tabs
    const viewTabs = this.querySelectorAll('.view-tab');
    viewTabs.forEach(tab => {
      tab.addEventListener('click', this.handleViewChange.bind(this));
    });
    
    // Search mode select
    const searchModeSelect = this.querySelector('.search-mode-select');
    if (searchModeSelect) {
      searchModeSelect.addEventListener('change', this.handleSearchModeChange.bind(this));
    }
    
    // Filter controls
    const categoryCombobox = this.querySelector('.category-combobox');
    if (categoryCombobox) {
      categoryCombobox.addEventListener('change', (event) => {
        this.viewParams.category = event.detail.value || null;
        this.currentPage = 1;
        this.updateURL();
        this.loadMemories();
      });
    }
    
    const projectCombobox = this.querySelector('.project-combobox');
    if (projectCombobox) {
      projectCombobox.addEventListener('change', (event) => {
        this.viewParams.project_id = event.detail.value || null;
        this.currentPage = 1;
        this.updateURL();
        this.loadMemories();
      });
    }
    
    // Refresh button
    const refreshBtn = this.querySelector('.refresh-btn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', this.loadMemories.bind(this));
    }
    
    // Memory card events
    this.addEventListener('memory-select', this.handleMemorySelect.bind(this));
    this.addEventListener('memory-favorite-toggle', this.handleMemoryFavorite.bind(this));
    
    // Pagination
    this.addEventListener('click', this.handlePaginationClick.bind(this));
  }
  
  /**
   * Update search mode visibility
   */
  updateSearchModeVisibility() {
    const searchModeSelect = this.querySelector('.search-mode-select');
    if (searchModeSelect) {
      if (this.shouldShowSearchMode()) {
        searchModeSelect.style.display = '';
      } else {
        searchModeSelect.style.display = 'none';
      }
    }
  }
  
  /**
   * Handle search input
   */
  handleSearch(event) {
    this.searchQuery = event.target.value;
    this.currentPage = 1;
    this.updateSearchModeVisibility();
    this.debounceSearch();
  }
  
  /**
   * Debounced search
   */
  debounceSearch() {
    clearTimeout(this.searchTimeout);
    this.searchTimeout = setTimeout(() => {
      this.loadMemories();
    }, 300);
  }
  
  /**
   * Handle sort change
   */
  handleSortChange(event) {
    this.sortBy = event.target.value;
    this.loadMemories();
  }
  
  /**
   * Toggle sort direction
   */
  toggleSortDirection() {
    this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
    this.loadMemories();
    
    const toggle = this.querySelector('.sort-toggle');
    if (toggle) {
      toggle.textContent = this.sortDirection === 'asc' ? '↑' : '↓';
    }
  }
  
  /**
   * Handle view mode change
   */
  handleViewChange(event) {
    const newView = event.target.getAttribute('data-view');
    if (newView && newView !== this.currentView) {
      this.currentView = newView;
      this.currentPage = 1;
      this.updateURL();
      this.updateViewTabs();
      this.updateSearchModeVisibility();
      this.loadMemories();
    }
  }
  
  /**
   * Handle search mode change
   */
  handleSearchModeChange(event) {
    this.searchMode = event.target.value;
    if (this.searchQuery) {
      this.currentPage = 1;
      this.loadMemories();
    }
  }
  
  /**
   * Handle category filter
   */
  handleCategoryFilter(event) {
    this.viewParams.category = event.target.value || null;
    this.currentPage = 1;
    this.updateURL();
    this.loadMemories();
  }
  
  /**
   * Handle project filter
   */
  handleProjectFilter(event) {
    this.viewParams.project_id = event.target.value || null;
    this.currentPage = 1;
    this.updateURL();
    this.loadMemories();
  }
  
  /**
   * Handle memory selection
   */
  handleMemorySelect(event) {
    const { memoryId } = event.detail;
    console.log('Memory selected:', memoryId);
  }
  
  /**
   * Handle memory favorite toggle
   */
  handleMemoryFavorite(event) {
    const { memoryId } = event.detail;
    console.log('Memory favorite toggled:', memoryId);
    // TODO: Implement favorite functionality
  }
  
  /**
   * Handle pagination clicks
   */
  handlePaginationClick(event) {
    const pageBtn = event.target.closest('.page-btn');
    if (pageBtn) {
      const page = parseInt(pageBtn.getAttribute('data-page'));
      if (page && page !== this.currentPage) {
        this.currentPage = page;
        this.loadMemories();
      }
    }
    
    const prevBtn = event.target.closest('.prev-btn');
    if (prevBtn && this.currentPage > 1) {
      this.currentPage--;
      this.loadMemories();
    }
    
    const nextBtn = event.target.closest('.next-btn');
    if (nextBtn && this.currentPage < this.getTotalPages()) {
      this.currentPage++;
      this.loadMemories();
    }
  }
  
  /**
   * Update URL with current parameters
   */
  updateURL() {
    const params = new URLSearchParams();
    
    params.set('view', this.currentView);
    
    if (this.viewParams.project_id) {
      params.set('project_id', this.viewParams.project_id);
    }
    
    if (this.viewParams.category) {
      params.set('category', this.viewParams.category);
    }
    
    if (this.searchQuery) {
      params.set('query', this.searchQuery);
    }
    
    if (this.viewParams.tag) {
      params.set('tag', this.viewParams.tag);
    }
    
    if (this.viewParams.source) {
      params.set('source', this.viewParams.source);
    }
    
    const newURL = `${window.location.pathname}?${params.toString()}`;
    window.history.replaceState({}, '', newURL);
  }
  
  /**
   * Update view tabs active state
   */
  updateViewTabs() {
    const tabs = this.querySelectorAll('.view-tab');
    tabs.forEach(tab => {
      tab.classList.toggle('active', tab.getAttribute('data-view') === this.currentView);
    });
  }
  
  /**
   * Load available projects for filter dropdown
   */
  async loadProjectsForFilter() {
    try {
      let projectsData;
      
      // Try to use the new projects API endpoint first
      try {
        const response = await fetch('/api/projects');
        if (response.ok) {
          projectsData = await response.json();
        }
      } catch (error) {
        console.log('Projects API not available, falling back to search API');
      }
      
      // Fallback to search API if projects API is not available
      if (!projectsData) {
        let searchResult;
        
        if (window.app && window.app.apiClient) {
          // Use a smaller limit for project discovery
          searchResult = await window.app.apiClient.searchMemories('', { limit: 100 });
        } else {
          const response = await fetch('/api/memories/search?query=&limit=100');
          if (response.ok) {
            searchResult = await response.json();
          }
        }
        
        if (searchResult && searchResult.results) {
          const projects = new Set();
          searchResult.results.forEach(memory => {
            const projectId = memory.project_id || 'default';
            projects.add(projectId);
          });
          
          projectsData = {
            projects: Array.from(projects).map(id => ({ id, name: id === 'default' ? 'Default Project' : id }))
          };
        }
      }
      
      if (projectsData && projectsData.projects) {
        const projectCombobox = this.querySelector('.project-combobox');
        if (projectCombobox) {
          const options = [
            { value: '', text: 'All Projects' },
            ...projectsData.projects.map(project => ({
              value: project.id,
              text: project.name || (project.id === 'default' ? 'Default Project' : project.id)
            }))
          ];
          
          projectCombobox.setOptions(options);
          
          // Set current value if specified
          if (this.viewParams.project_id) {
            projectCombobox.setValue(this.viewParams.project_id);
          }
        }
      }
    } catch (error) {
      console.error('Failed to load projects for filter:', error);
    }
  }
  async loadMemories() {
    try {
      this.setLoading(true);
      
      // Build search parameters with proper pagination
      let searchParams = {
        limit: this.pageSize,
        offset: (this.currentPage - 1) * this.pageSize,
        sort_by: this.sortBy,
        sort_direction: this.sortDirection
      };
      
      // Add filters to search params
      if (this.viewParams.category) {
        searchParams.category = this.viewParams.category;
      }
      
      if (this.viewParams.project_id) {
        searchParams.project_id = this.viewParams.project_id;
      }
      
      if (this.viewParams.source) {
        searchParams.source = this.viewParams.source;
      }
      
      if (this.viewParams.tag) {
        searchParams.tag = this.viewParams.tag;
      }
      
      // Build search query based on view mode
      let query = this.searchQuery || '';
      
      if (window.app && window.app.apiClient) {
        const searchResult = await window.app.apiClient.searchMemories(query, searchParams);
        
        if (searchResult && searchResult.results) {
          this.memories = searchResult.results;
          this.totalMemories = searchResult.total || searchResult.results.length;
          this.renderMemories();
          this.renderPagination();
          this.updateSummary();
        } else {
          this.memories = [];
          this.totalMemories = 0;
          this.renderMemories();
          this.renderPagination();
          this.updateSummary();
        }
      } else {
        // Fallback to direct API call
        const urlParams = new URLSearchParams({
          query: query,
          limit: searchParams.limit.toString(),
          offset: searchParams.offset.toString(),
          sort_by: searchParams.sort_by,
          sort_direction: searchParams.sort_direction
        });
        
        // Add filter parameters
        Object.entries(searchParams).forEach(([key, value]) => {
          if (!['limit', 'offset', 'sort_by', 'sort_direction'].includes(key) && value) {
            urlParams.set(key, value);
          }
        });
        
        const response = await fetch(`/api/memories/search?${urlParams.toString()}`);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const searchResult = await response.json();
        if (searchResult && searchResult.results) {
          this.memories = searchResult.results;
          this.totalMemories = searchResult.total || searchResult.results.length;
          this.renderMemories();
          this.renderPagination();
          this.updateSummary();
        }
      }
      
    } catch (error) {
      console.error('Failed to load memories:', error);
      this.showError('Failed to load memories: ' + error.message);
    } finally {
      this.setLoading(false);
    }
  }
  

  
  /**
   * Sort memories (now handled server-side, but keeping for potential client-side sorting)
   */
  sortMemories(memories) {
    // Note: Sorting is now primarily handled server-side
    // This method is kept for potential client-side sorting needs
    memories.sort((a, b) => {
      let aVal, bVal;
      
      switch (this.sortBy) {
        case 'created_at':
          aVal = new Date(a.created_at);
          bVal = new Date(b.created_at);
          break;
        case 'updated_at':
          aVal = new Date(a.updated_at || a.created_at);
          bVal = new Date(b.updated_at || b.created_at);
          break;
        case 'category':
          aVal = a.category;
          bVal = b.category;
          break;
        case 'project':
          aVal = a.project_id || 'default';
          bVal = b.project_id || 'default';
          break;
        case 'size':
          aVal = a.content?.length || 0;
          bVal = b.content?.length || 0;
          break;
        default:
          aVal = new Date(a.created_at);
          bVal = new Date(b.created_at);
      }
      
      if (aVal < bVal) return this.sortDirection === 'asc' ? -1 : 1;
      if (aVal > bVal) return this.sortDirection === 'asc' ? 1 : -1;
      return 0;
    });
  }
  
  /**
   * Get page title based on current view
   */
  getPageTitle() {
    switch (this.currentView) {
      case 'project':
        return this.viewParams.project_id ? 
          `Project: ${this.viewParams.project_id}` : 'Project Memories';
      case 'category':
        return this.viewParams.category ? 
          `Category: ${this.viewParams.category}` : 'Category Memories';
      case 'tag':
        return this.viewParams.tag ? 
          `Tag: #${this.viewParams.tag}` : 'Tagged Memories';
      case 'search':
        return this.searchQuery ? 
          `Search: "${this.searchQuery}"` : 'Search Memories';
      case 'source':
        return this.viewParams.source ? 
          `Source: ${this.viewParams.source}` : 'Source Memories';
      case 'recent':
      default:
        return 'Recent Memories';
    }
  }
  
  /**
   * Get view description based on current view
   */
  getViewDescription() {
    switch (this.currentView) {
      case 'project':
        return this.viewParams.project_id ? 
          `All memories from the ${this.viewParams.project_id} project` : 
          'Browse memories by project';
      case 'category':
        return this.viewParams.category ? 
          `All ${this.viewParams.category} memories` : 
          'Browse memories by category';
      case 'tag':
        return this.viewParams.tag ? 
          `All memories tagged with #${this.viewParams.tag}` : 
          'Browse memories by tags';
      case 'search':
        return this.searchQuery ? 
          `Search results for "${this.searchQuery}" using ${this.searchMode} mode` : 
          'Search through all memories';
      case 'source':
        return this.viewParams.source ? 
          `All memories from ${this.viewParams.source}` : 
          'Browse memories by source';
      case 'recent':
      default:
        return 'Most recently created memories';
    }
  }
  
  /**
   * Check if search mode should be visible
   */
  shouldShowSearchMode() {
    return this.currentView === 'search' || this.searchQuery || this.currentView === 'recent';
  }
  
  /**
   * Get total pages
   */
  getTotalPages() {
    return Math.ceil(this.totalMemories / this.pageSize);
  }
  
  /**
   * Set loading state
   */
  setLoading(loading) {
    this.isLoading = loading;
    
    const loadingEl = this.querySelector('.loading-state');
    const contentEl = this.querySelector('.memories-content');
    
    if (loading) {
      if (loadingEl) loadingEl.style.display = 'flex';
      if (contentEl) contentEl.style.display = 'none';
    } else {
      if (loadingEl) loadingEl.style.display = 'none';
      if (contentEl) contentEl.style.display = 'block';
    }
  }
  
  /**
   * Show error message
   */
  showError(message) {
    const errorEl = this.querySelector('.error-message');
    if (errorEl) {
      errorEl.textContent = message;
      errorEl.style.display = 'block';
      setTimeout(() => {
        errorEl.style.display = 'none';
      }, 5000);
    }
  }
  
  /**
   * Render memories list
   */
  renderMemories() {
    const container = this.querySelector('.memories-list');
    if (!container) return;
    
    if (this.memories.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">📝</div>
          <h3>No memories found</h3>
          <p>Try adjusting your search or filters</p>
          ${this.searchQuery || Object.values(this.viewParams).some(v => v) ? `
            <button class="clear-filters-btn">Clear all filters</button>
          ` : ''}
        </div>
      `;
      
      const clearBtn = container.querySelector('.clear-filters-btn');
      if (clearBtn) {
        clearBtn.addEventListener('click', this.clearAllFilters.bind(this));
      }
      return;
    }
    
    container.innerHTML = this.memories.map(memory => `
      <memory-card
        memory-id="${memory.id}"
        content="${this.escapeAttribute(memory.content)}"
        project="${memory.project_id || ''}"
        category="${memory.category}"
        created-at="${memory.created_at}"
        updated-at="${memory.updated_at || ''}"
        similarity-score="${memory.similarity_score || ''}"
        tags="${this.escapeAttribute(JSON.stringify(memory.tags || []))}"
        source="${memory.source || 'unknown'}"
        search-query="${this.escapeAttribute(this.searchQuery)}"
      ></memory-card>
    `).join('');
  }
  
  /**
   * Clear all filters
   */
  clearAllFilters() {
    this.searchQuery = '';
    this.viewParams = {};
    this.currentView = 'recent';
    this.currentPage = 1;
    
    const searchInput = this.querySelector('.search-input');
    if (searchInput) searchInput.value = '';
    
    const categoryCombobox = this.querySelector('.category-combobox');
    if (categoryCombobox) categoryCombobox.setValue('');
    
    const projectCombobox = this.querySelector('.project-combobox');
    if (projectCombobox) projectCombobox.setValue('');
    
    this.updateURL();
    this.updateViewTabs();
    this.loadMemories();
  }
  
  /**
   * Escape attribute values
   */
  escapeAttribute(value) {
    if (typeof value !== 'string') return '';
    return value
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
  
  /**
   * Render pagination
   */
  renderPagination() {
    const container = this.querySelector('.pagination');
    if (!container) return;
    
    const totalPages = this.getTotalPages();
    
    if (totalPages <= 1) {
      container.innerHTML = '';
      return;
    }
    
    let paginationHTML = `
      <button class="prev-btn ${this.currentPage === 1 ? 'disabled' : ''}" 
              ${this.currentPage === 1 ? 'disabled' : ''}>
        ← Previous
      </button>
    `;
    
    // Show page numbers (with ellipsis for large ranges)
    const maxVisible = 5;
    let startPage = Math.max(1, this.currentPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);
    
    if (endPage - startPage < maxVisible - 1) {
      startPage = Math.max(1, endPage - maxVisible + 1);
    }
    
    if (startPage > 1) {
      paginationHTML += `<button class="page-btn" data-page="1">1</button>`;
      if (startPage > 2) {
        paginationHTML += `<span class="ellipsis">...</span>`;
      }
    }
    
    for (let i = startPage; i <= endPage; i++) {
      paginationHTML += `
        <button class="page-btn ${i === this.currentPage ? 'active' : ''}" 
                data-page="${i}">${i}</button>
      `;
    }
    
    if (endPage < totalPages) {
      if (endPage < totalPages - 1) {
        paginationHTML += `<span class="ellipsis">...</span>`;
      }
      paginationHTML += `<button class="page-btn" data-page="${totalPages}">${totalPages}</button>`;
    }
    
    paginationHTML += `
      <button class="next-btn ${this.currentPage === totalPages ? 'disabled' : ''}"
              ${this.currentPage === totalPages ? 'disabled' : ''}>
        Next →
      </button>
    `;
    
    container.innerHTML = paginationHTML;
  }
  
  /**
   * Update summary information
   */
  updateSummary() {
    const summaryEl = this.querySelector('.memories-summary');
    if (!summaryEl) return;
    
    const startIndex = (this.currentPage - 1) * this.pageSize + 1;
    const endIndex = Math.min(this.currentPage * this.pageSize, this.totalMemories);
    
    summaryEl.innerHTML = `
      <span class="summary-text">
        Showing ${startIndex}-${endIndex} of ${this.totalMemories} memories
      </span>
      <span class="view-mode">View: ${this.currentView}</span>
    `;
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'memories-page';
    
    this.innerHTML = `
      <div class="page-header">
        <div class="page-title-section">
          <h1>${this.getPageTitle()}</h1>
          <p class="page-description">${this.getViewDescription()}</p>
        </div>
        <div class="header-actions">
          <div class="connection-status disconnected">
            <span class="status-dot"></span> 연결 중...
          </div>
          <button class="refresh-btn secondary-button">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="23,4 23,10 17,10"/>
              <polyline points="1,20 1,14 7,14"/>
              <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"/>
            </svg>
            Refresh
          </button>
        </div>
      </div>
      
      <div class="error-message" style="display: none;"></div>
      
      <div class="view-tabs">
        <button class="view-tab ${this.currentView === 'recent' ? 'active' : ''}" data-view="recent">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/><polyline points="12,6 12,12 16,14"/>
          </svg>
          Recent
        </button>
        <button class="view-tab ${this.currentView === 'project' ? 'active' : ''}" data-view="project">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
          By Project
        </button>
        <button class="view-tab ${this.currentView === 'category' ? 'active' : ''}" data-view="category">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/>
          </svg>
          By Category
        </button>
        <button class="view-tab ${this.currentView === 'search' ? 'active' : ''}" data-view="search">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
          </svg>
          Search
        </button>
      </div>
      
      <div class="controls-section">
        <div class="search-controls">
          <div class="search-input-group">
            <input 
              type="text" 
              class="search-input" 
              placeholder="Search memories..."
              value="${this.searchQuery}"
            />
            <select class="search-mode-select" ${!this.shouldShowSearchMode() ? 'style="display: none;"' : ''}>
              <option value="hybrid" ${this.searchMode === 'hybrid' ? 'selected' : ''}>Hybrid</option>
              <option value="vector" ${this.searchMode === 'vector' ? 'selected' : ''}>Vector</option>
              <option value="text" ${this.searchMode === 'text' ? 'selected' : ''}>Text</option>
            </select>
          </div>
        </div>
        
        <div class="filter-controls">
          <searchable-combobox class="category-combobox" placeholder="All Categories">
            <option value="">All Categories</option>
            <option value="task" data-icon="📋">Task</option>
            <option value="bug" data-icon="🐛">Bug</option>
            <option value="idea" data-icon="💡">Idea</option>
            <option value="decision" data-icon="💎">Decision</option>
            <option value="incident" data-icon="⚠️">Incident</option>
            <option value="code_snippet" data-icon="💻">Code Snippet</option>
            <option value="git-history" data-icon="📚">Git History</option>
          </searchable-combobox>
          
          <searchable-combobox class="project-combobox" placeholder="All Projects">
            <option value="">All Projects</option>
          </searchable-combobox>
        </div>
        
        <div class="sort-controls">
          <select class="sort-select">
            <option value="created_at">Created Date</option>
            <option value="updated_at">Updated Date</option>
            <option value="category">Category</option>
            <option value="project">Project</option>
            <option value="size">Size</option>
          </select>
          <button class="sort-toggle" title="Toggle sort direction">↓</button>
        </div>
      </div>
      
      <div class="loading-state" style="display: none;">
        <div class="loading-spinner"></div>
        <p>Loading memories...</p>
      </div>
      
      <div class="memories-content">
        <div class="memories-summary"></div>
        <div class="memories-list"></div>
        <div class="pagination"></div>
      </div>
    `;
    
    // Update view tabs and summary
    this.updateViewTabs();
    this.updateSummary();
    
    // Update search mode visibility after render
    setTimeout(() => {
      this.updateSearchModeVisibility();
    }, 0);
  }
}

// Define the custom element
customElements.define('memories-page', MemoriesPage);

export { MemoriesPage };

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .memories-page {
    padding: var(--space-6) 0;
    max-width: 1200px;
    margin: 0 auto;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  }
  
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 2rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border-color);
  }
  
  .page-title-section h1 {
    margin: 0 0 0.5rem 0;
    color: var(--text-primary);
    font-size: 1.75rem;
  }
  
  .page-description {
    margin: 0;
    color: var(--text-secondary);
    font-size: 0.875rem;
    line-height: 1.4;
  }
  
  .header-actions {
    display: flex;
    gap: 1rem;
  }
  
  .secondary-button {
    background: var(--bg-secondary);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
    padding: 0.5rem 1rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    transition: var(--transition);
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  
  .secondary-button:hover {
    background: var(--bg-tertiary);
  }
  
  .secondary-button svg {
    width: 16px;
    height: 16px;
    stroke: currentColor;
  }
  
  .error-message {
    background: var(--error-bg);
    color: var(--error-text);
    border: 1px solid var(--error-color);
    border-radius: var(--border-radius);
    padding: 1rem;
    margin-bottom: 1rem;
  }
  
  .view-tabs {
    display: flex;
    gap: 0.25rem;
    margin-bottom: 1.5rem;
    border-bottom: 1px solid var(--border-color);
  }
  
  .view-tab {
    background: none;
    border: none;
    padding: 0.75rem 1rem;
    cursor: pointer;
    font-size: 0.875rem;
    color: var(--text-secondary);
    border-bottom: 2px solid transparent;
    transition: var(--transition);
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  
  .view-tab svg {
    width: 16px;
    height: 16px;
    stroke: currentColor;
  }
  
  .view-tab:hover {
    color: var(--text-primary);
    background: var(--bg-secondary);
  }
  
  .view-tab.active {
    color: var(--primary-color);
    border-bottom-color: var(--primary-color);
    background: var(--primary-color-alpha);
  }
  
  .controls-section {
    display: grid;
    grid-template-columns: 1fr auto auto;
    gap: 1.5rem;
    margin-bottom: 1.5rem;
    align-items: center;
  }
  
  .search-controls {
    display: flex;
    gap: 0.5rem;
  }
  
  .search-input-group {
    display: flex;
    gap: 0.5rem;
    align-items: center;
  }
  
  .search-input {
    flex: 1;
    min-width: 200px;
    padding: 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 1rem;
  }
  
  .search-input:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px var(--primary-color-alpha);
  }
  
  .search-mode-select {
    padding: 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.875rem;
    min-width: 100px;
  }
  
  .filter-controls {
    display: flex;
    gap: 0.75rem;
    align-items: center;
  }
  
  .category-combobox,
  .project-combobox {
    min-width: 150px;
  }
  
  .sort-controls {
    display: flex;
    gap: 0.5rem;
    align-items: center;
  }
  
  .sort-select {
    padding: 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.875rem;
  }
  
  .sort-toggle {
    background: none;
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    padding: 0.5rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 1rem;
    width: 2rem;
    height: 2rem;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .sort-toggle:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }
  
  .loading-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 4rem;
    color: var(--text-muted);
  }
  
  .loading-spinner {
    width: 32px;
    height: 32px;
    border: 3px solid var(--border-color);
    border-top: 3px solid var(--primary-color);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-bottom: 1rem;
  }
  
  @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }
  
  .memories-content {
    min-height: 400px;
  }
  
  .memories-summary {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
    padding: 0.75rem;
    background: var(--bg-secondary);
    border-radius: var(--border-radius);
    font-size: 0.875rem;
    color: var(--text-secondary);
  }
  
  .view-mode {
    font-weight: 500;
    color: var(--primary-color);
    text-transform: capitalize;
  }
  
  .memories-list {
    margin-bottom: 2rem;
  }
  
  .empty-state {
    text-align: center;
    padding: 4rem 2rem;
    color: var(--text-muted);
  }
  
  .empty-icon {
    font-size: 3rem;
    margin-bottom: 1rem;
  }
  
  .empty-state h3 {
    margin: 0 0 0.5rem 0;
    color: var(--text-primary);
    font-size: 1.25rem;
  }
  
  .empty-state p {
    margin: 0 0 1.5rem 0;
    font-size: 1rem;
  }
  
  .clear-filters-btn {
    background: var(--primary-color);
    color: white;
    border: none;
    padding: 0.75rem 1.5rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
  }
  
  .clear-filters-btn:hover {
    background: var(--primary-hover);
  }
  
  .pagination {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 0.5rem;
    margin-top: 2rem;
  }
  
  .page-btn,
  .prev-btn,
  .next-btn {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    padding: 0.5rem 0.75rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    transition: var(--transition);
  }
  
  .page-btn:hover,
  .prev-btn:hover:not(.disabled),
  .next-btn:hover:not(.disabled) {
    background: var(--bg-secondary);
    border-color: var(--primary-color);
  }
  
  .page-btn.active {
    background: var(--primary-color);
    color: white;
    border-color: var(--primary-color);
  }
  
  .prev-btn.disabled,
  .next-btn.disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  
  .ellipsis {
    padding: 0.5rem;
    color: var(--text-muted);
    font-size: 0.875rem;
  }
  
  /* Responsive design */
  @media (max-width: 768px) {
    .memories-page {
      padding: var(--space-4) 0;
    }
    
    .page-header {
      flex-direction: column;
      align-items: flex-start;
      gap: 1rem;
    }
    
    .header-actions {
      align-self: stretch;
    }
    
    .view-tabs {
      overflow-x: auto;
      scrollbar-width: none;
      -ms-overflow-style: none;
    }
    
    .view-tabs::-webkit-scrollbar {
      display: none;
    }
    
    .controls-section {
      grid-template-columns: 1fr;
      gap: 1rem;
    }
    
    .search-input-group {
      flex-direction: column;
    }
    
    .filter-controls {
      flex-direction: row;
      gap: 1rem;
    }
    
    .filter-group {
      flex: 1;
    }
    
    .sort-group {
      justify-content: space-between;
    }
    
    .memories-summary {
      flex-direction: column;
      align-items: flex-start;
      gap: 0.5rem;
    }
    
    .pagination {
      flex-wrap: wrap;
      gap: 0.25rem;
    }
    
    .page-btn,
    .prev-btn,
    .next-btn {
      padding: 0.375rem 0.5rem;
      font-size: 0.75rem;
    }
  }
`;

document.head.appendChild(style);