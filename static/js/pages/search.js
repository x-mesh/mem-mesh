/**
 * Chroma-Style Search Page Component
 * Advanced search interface with filters, results, and pagination
 * Requirements: 6.1, 6.2, 6.3, 6.4
 */

class SearchPage extends HTMLElement {
  constructor() {
    super();
    this.searchQuery = '';
    this.selectedCategory = '';
    this.selectedProject = '';
    this.sortBy = 'relevance';
    this.searchMode = 'hybrid';  // 검색 모드 추가
    this.searchResults = [];
    this.isLoading = false;
    this.pageSize = 20;
    this.currentPage = 1;
    this.totalResults = 0;
    this.hasMore = false;
    this.isInitialized = false;
  }
  
  connectedCallback() {
    if (this.isInitialized) return;
    this.isInitialized = true;
    
    // Check if we should redirect to unified memories page
    const shouldRedirect = window.location.pathname === '/search';
    
    if (shouldRedirect) {
      // Redirect to unified memories page with search parameters
      const urlParams = new URLSearchParams(window.location.search);
      const query = urlParams.get('query') || urlParams.get('q') || '';
      const category = urlParams.get('category') || '';
      const project = urlParams.get('project') || '';
      
      let redirectURL = '/memories?view=search';
      if (query) redirectURL += `&query=${encodeURIComponent(query)}`;
      if (category) redirectURL += `&category=${encodeURIComponent(category)}`;
      if (project) redirectURL += `&project_id=${encodeURIComponent(project)}`;
      
      console.log('Redirecting from search page to:', redirectURL);
      
      if (window.app && window.app.router) {
        window.app.router.navigate(redirectURL);
      } else {
        window.location.href = redirectURL;
      }
      return;
    }
    
    // If not redirecting, continue with normal initialization
    this.parseUrlParams();
    this.render();
    this.setupEventListeners();
    
    setTimeout(() => {
      if (this.searchQuery || this.selectedCategory || this.selectedProject) {
        this.waitForAppAndSearch();
      } else {
        this.isLoading = false;
        this.showInitialState();
      }
    }, 100);
  }
  
  disconnectedCallback() {
    this.isInitialized = false;
  }
  
  async waitForAppAndSearch() {
    let attempts = 0;
    const maxAttempts = 50;
    
    const checkApp = () => {
      if (window.app && window.app.apiClient) {
        this.performSearch();
        return;
      }
      
      attempts++;
      if (attempts >= maxAttempts) {
        this.performDirectSearch();
        return;
      }
      
      setTimeout(checkApp, 100);
    };
    
    checkApp();
  }
  
  async performDirectSearch() {
    try {
      this.isLoading = true;
      this.updateLoadingState();
      
      const params = {
        query: this.searchQuery || '',
        limit: this.pageSize,
        search_mode: this.searchMode
      };
      if (this.selectedCategory) params.category = this.selectedCategory;
      if (this.selectedProject) params.project_id = this.selectedProject;

      const result = await window.app.apiClient.get('/memories/search', params);
      this.searchResults = result.results || [];
      this.totalResults = result.total || this.searchResults.length;
      this.hasMore = this.searchResults.length >= this.pageSize;
      
    } catch (error) {
      console.error('Search failed:', error);
      this.searchResults = [];
      this.showError('Search failed. Please try again.');
    }
    
    this.isLoading = false;
    this.updateLoadingState();
    this.updateResultsDisplay();
  }
  
  parseUrlParams() {
    const urlParams = new URLSearchParams(window.location.search);
    this.searchQuery = urlParams.get('q') || '';
    this.selectedCategory = urlParams.get('category') || '';
    this.selectedProject = urlParams.get('project') || '';
    this.sortBy = urlParams.get('sort') || 'relevance';
    this.searchMode = urlParams.get('mode') || 'hybrid';
  }
  
  updateUrl() {
    const params = new URLSearchParams();
    if (this.searchQuery) params.set('q', this.searchQuery);
    if (this.selectedCategory) params.set('category', this.selectedCategory);
    if (this.selectedProject) params.set('project', this.selectedProject);
    if (this.sortBy !== 'relevance') params.set('sort', this.sortBy);
    if (this.searchMode !== 'hybrid') params.set('mode', this.searchMode);
    
    const newUrl = `${window.location.pathname}${params.toString() ? '?' + params.toString() : ''}`;
    window.history.replaceState({}, '', newUrl);
  }
  
  setupEventListeners() {
    // Search bar events
    this.addEventListener('search-submit', (e) => {
      this.searchQuery = e.detail.query;
      this.currentPage = 1;
      this.performSearch();
    });
    
    this.addEventListener('search-clear', () => {
      this.searchQuery = '';
      this.currentPage = 1;
      this.performSearch();
    });
    
    // Click events
    this.addEventListener('click', (e) => {
      const target = e.target;
      
      // Filter chips
      if (target.closest('.chroma-filter-chip')) {
        const chip = target.closest('.chroma-filter-chip');
        const filterType = chip.getAttribute('data-filter-type');
        const filterValue = chip.getAttribute('data-filter-value');
        this.handleFilterClick(filterType, filterValue, chip);
      }
      
      // Result cards
      if (target.closest('.chroma-result-card')) {
        const card = target.closest('.chroma-result-card');
        const memoryId = card.getAttribute('data-memory-id');
        if (memoryId) this.navigateToMemory(memoryId);
      }
      
      // Load more button
      if (target.closest('.chroma-load-more-btn')) {
        this.loadMore();
      }
      
      // Sort options
      if (target.closest('.chroma-sort-option')) {
        const option = target.closest('.chroma-sort-option');
        this.sortBy = option.getAttribute('data-sort');
        this.updateSortSelection();
        this.performSearch();
      }
      
      // Search mode options
      if (target.closest('.chroma-mode-option')) {
        const option = target.closest('.chroma-mode-option');
        this.searchMode = option.getAttribute('data-mode');
        this.updateModeSelection();
        this.performSearch();
      }
    });
    
    // Filter select changes
    this.addEventListener('change', (e) => {
      const target = e.target;
      
      if (target.classList.contains('chroma-category-select')) {
        this.selectedCategory = target.value;
        this.currentPage = 1;
        this.performSearch();
      }
      
      if (target.classList.contains('chroma-project-input')) {
        this.selectedProject = target.value;
      }
    });
    
    // Project input enter key
    this.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && e.target.classList.contains('chroma-project-input')) {
        this.selectedProject = e.target.value;
        this.currentPage = 1;
        this.performSearch();
      }
    });
  }
  
  handleFilterClick(filterType, filterValue, chip) {
    const isActive = chip.classList.contains('active');
    
    if (filterType === 'category') {
      this.selectedCategory = isActive ? '' : filterValue;
      this.querySelectorAll('.chroma-filter-chip[data-filter-type="category"]').forEach(c => {
        c.classList.remove('active');
      });
      if (!isActive) chip.classList.add('active');
    }
    
    this.currentPage = 1;
    this.performSearch();
  }
  
  navigateToMemory(memoryId) {
    if (window.app && window.app.router) {
      window.app.router.navigate(`/memory/${memoryId}`);
    } else {
      window.location.href = `/memory/${memoryId}`;
    }
  }
  
  async performSearch() {
    try {
      this.isLoading = true;
      this.updateLoadingState();
      this.updateUrl();
      
      if (!window.app || !window.app.apiClient) {
        await this.performDirectSearch();
        return;
      }
      
      const response = await window.app.apiClient.searchMemories(this.searchQuery, {
        category: this.selectedCategory || undefined,
        project_id: this.selectedProject || undefined,
        limit: this.pageSize,
        search_mode: this.searchMode
      });
      
      this.searchResults = response.results || [];
      this.totalResults = response.total || this.searchResults.length;
      this.hasMore = this.searchResults.length >= this.pageSize;
      
    } catch (error) {
      console.error('Search failed:', error);
      this.searchResults = [];
      this.showError('Search failed.');
    }
    
    this.isLoading = false;
    this.updateLoadingState();
    this.updateResultsDisplay();
  }
  
  async loadMore() {
    if (this.isLoading || !this.hasMore) return;
    
    try {
      this.isLoading = true;
      const loadMoreBtn = this.querySelector('.chroma-load-more-btn');
      if (loadMoreBtn) loadMoreBtn.classList.add('loading');
      
      this.currentPage++;
      const offset = (this.currentPage - 1) * this.pageSize;
      
      const response = await window.app.apiClient.searchMemories(this.searchQuery, {
        category: this.selectedCategory || undefined,
        project_id: this.selectedProject || undefined,
        limit: this.pageSize,
        offset: offset
      });
      
      const newResults = response.results || [];
      this.searchResults = [...this.searchResults, ...newResults];
      this.hasMore = newResults.length >= this.pageSize;
      
      this.appendResults(newResults);
      
    } catch (error) {
      console.error('Load more failed:', error);
      this.currentPage--;
    }
    
    this.isLoading = false;
    const loadMoreBtn = this.querySelector('.chroma-load-more-btn');
    if (loadMoreBtn) loadMoreBtn.classList.remove('loading');
    this.updateLoadMoreButton();
  }
  
  showError(message) {
    const resultsContainer = this.querySelector('.chroma-results-container');
    if (resultsContainer) {
      resultsContainer.innerHTML = `
        <div class="chroma-error-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <p>${message}</p>
          <button class="chroma-retry-btn" onclick="this.closest('search-page').performSearch()">다시 시도</button>
        </div>
      `;
    }
  }
  
  showInitialState() {
    const resultsContainer = this.querySelector('.chroma-results-container');
    if (resultsContainer) {
      resultsContainer.innerHTML = `
        <div class="chroma-initial-state">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="11" cy="11" r="8"/>
            <path d="m21 21-4.35-4.35"/>
          </svg>
          <h3>메모리 검색</h3>
          <p>검색어를 입력하거나 필터를 선택하여 메모리를 찾아보세요</p>
          <div class="chroma-search-tips">
            <span class="tip-item">💡 <kbd>Ctrl</kbd>+<kbd>K</kbd>로 빠른 검색</span>
            <span class="tip-item">🏷️ 카테고리 필터로 범위 좁히기</span>
          </div>
        </div>
      `;
    }
    this.updateResultsCount(0);
  }
  
  updateLoadingState() {
    const loadingElement = this.querySelector('.chroma-search-loading');
    const resultsContainer = this.querySelector('.chroma-results-container');
    
    if (loadingElement) {
      loadingElement.style.display = this.isLoading ? 'flex' : 'none';
    }
    
    if (resultsContainer && this.isLoading) {
      resultsContainer.style.opacity = '0.5';
      resultsContainer.style.pointerEvents = 'none';
    }
  }
  
  updateResultsDisplay() {
    const resultsContainer = this.querySelector('.chroma-results-container');
    
    if (resultsContainer) {
      resultsContainer.style.opacity = '1';
      resultsContainer.style.pointerEvents = 'auto';
    }
    
    this.updateResultsCount(this.totalResults);
    
    if (this.searchResults.length === 0) {
      this.showNoResults();
      return;
    }
    
    if (resultsContainer) {
      resultsContainer.innerHTML = this.searchResults.map(memory => this.renderResultCard(memory)).join('');
    }
    
    this.updateLoadMoreButton();
  }
  
  appendResults(newResults) {
    const resultsContainer = this.querySelector('.chroma-results-container');
    if (resultsContainer && newResults.length > 0) {
      const newHtml = newResults.map(memory => this.renderResultCard(memory)).join('');
      resultsContainer.insertAdjacentHTML('beforeend', newHtml);
    }
  }
  
  showNoResults() {
    const resultsContainer = this.querySelector('.chroma-results-container');
    if (resultsContainer) {
      resultsContainer.innerHTML = `
        <div class="chroma-no-results">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2z"/>
            <path d="M8 5v4"/>
            <path d="M16 5v4"/>
            <path d="M3 9h18"/>
          </svg>
          <h3>검색 결과가 없습니다</h3>
          <p>다른 검색어나 필터를 시도해보세요</p>
          <div class="chroma-suggestions-list">
            <button class="chroma-suggestion-btn" onclick="this.closest('search-page').clearFilters()">
              필터 초기화
            </button>
          </div>
        </div>
      `;
    }
  }
  
  clearFilters() {
    this.selectedCategory = '';
    this.selectedProject = '';
    this.querySelectorAll('.chroma-filter-chip').forEach(c => c.classList.remove('active'));
    this.querySelector('.chroma-category-select').value = '';
    this.querySelector('.chroma-project-input').value = '';
    this.performSearch();
  }
  
  updateResultsCount(count) {
    const countElement = this.querySelector('.chroma-results-count');
    if (countElement) {
      if (count === 0 && !this.searchQuery && !this.selectedCategory) {
        countElement.textContent = '';
      } else {
        countElement.textContent = `${count.toLocaleString()}개의 결과`;
      }
    }
  }
  
  updateSortSelection() {
    this.querySelectorAll('.chroma-sort-option').forEach(opt => {
      opt.classList.toggle('active', opt.getAttribute('data-sort') === this.sortBy);
    });
  }
  
  updateModeSelection() {
    this.querySelectorAll('.chroma-mode-option').forEach(opt => {
      opt.classList.toggle('active', opt.getAttribute('data-mode') === this.searchMode);
    });
  }
  
  updateLoadMoreButton() {
    const loadMoreContainer = this.querySelector('.chroma-load-more-container');
    if (loadMoreContainer) {
      loadMoreContainer.style.display = this.hasMore ? 'flex' : 'none';
    }
  }
  
  renderResultCard(memory) {
    const categoryIcons = {
      task: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="m9 12 2 2 4-4"/></svg>',
      bug: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m8 2 1.88 1.88"/><path d="M14.12 3.88 16 2"/><path d="M9 7.13v-1a3 3 0 1 1 6 0v1"/><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/><path d="M12 20v-9"/><path d="M6.53 9C4.6 8.8 3 7.1 3 5"/><path d="M6 13H2"/><path d="M3 21c0-2.1 1.7-3.9 3.8-4"/><path d="M20.97 5c0 2.1-1.6 3.8-3.5 4"/><path d="M22 13h-4"/><path d="M17.2 17c2.1.1 3.8 1.9 3.8 4"/></svg>',
      idea: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v1"/><path d="M12 21v1"/><path d="m4.93 4.93.7.7"/><path d="m18.36 18.36.7.7"/><path d="M2 12h1"/><path d="M21 12h1"/><path d="m4.93 19.07.7-.7"/><path d="m18.36 5.64.7-.7"/><circle cx="12" cy="12" r="4"/></svg>',
      decision: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="m9 12 2 2 4-4"/></svg>',
      incident: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.46 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      code_snippet: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16,18 22,12 16,6"/><polyline points="8,6 2,12 8,18"/></svg>'
    };
    
    const icon = categoryIcons[memory.category] || '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/></svg>';
    
    const content = this.escapeHtml(memory.content || '');
    const highlightedContent = this.highlightSearchTerms(content, this.searchQuery);
    const truncatedContent = highlightedContent.length > 250 
      ? highlightedContent.substring(0, 250) + '...' 
      : highlightedContent;
    
    const date = this.formatRelativeDate(memory.created_at);
    const score = memory.similarity_score 
      ? Math.round(memory.similarity_score * 100) 
      : null;
    
    return `
      <article class="chroma-result-card" data-memory-id="${memory.id}" tabindex="0" role="button" aria-label="View memory details">
        <div class="chroma-result-header">
          <div class="chroma-result-meta">
            <span class="chroma-result-category chroma-category-${memory.category || 'default'}">
              ${icon}
              <span>${memory.category || 'memory'}</span>
            </span>
            ${memory.project_id ? `<span class="chroma-result-project">${memory.project_id}</span>` : ''}
          </div>
          ${score !== null ? `
            <div class="chroma-result-score" title="Relevance score">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26"/>
              </svg>
              <span>${score}%</span>
            </div>
          ` : ''}
        </div>
        <div class="chroma-result-content">
          ${truncatedContent}
        </div>
        <div class="chroma-result-footer">
          ${memory.id ? `
            <span class="chroma-result-id" title="Memory ID: ${memory.id}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14,2 14,8 20,8"/>
              </svg>
              ID: ${memory.id.substring(0, 8)}...
            </span>
          ` : ''}
          <span class="chroma-result-date">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <polyline points="12,6 12,12 16,14"/>
            </svg>
            ${date}
          </span>
          <span class="chroma-result-source">${memory.source || 'unknown'}</span>
        </div>
      </article>
    `;
  }
  
  highlightSearchTerms(text, query) {
    if (!query || !query.trim()) return text;
    
    const terms = query.trim().split(/\s+/).filter(t => t.length > 1);
    let result = text;
    
    terms.forEach(term => {
      const regex = new RegExp(`(${term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
      result = result.replace(regex, '<mark>$1</mark>');
    });
    
    return result;
  }
  
  formatRelativeDate(dateStr) {
    if (!dateStr) return '';
    try {
      const date = new Date(dateStr);
      const now = new Date();
      const diffMs = now - date;
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMs / 3600000);
      const diffDays = Math.floor(diffMs / 86400000);
      
      if (diffMins < 1) return 'just now';
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays < 7) return `${diffDays}일 전`;
      
      return date.toLocaleDateString('ko-KR', { 
        year: 'numeric', 
        month: 'short', 
        day: 'numeric' 
      });
    } catch {
      return dateStr;
    }
  }
  
  escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
  
  getModeDescription() {
    const descriptions = {
      hybrid: 'Combines vector similarity and text matching to find the most relevant results.',
      exact: 'Finds memories that contain the exact search term. Ideal for searching specific error messages or IDs.',
      semantic: 'Finds semantically similar content. Useful for finding similar concepts or ideas.',
      fuzzy: 'Finds similar words even with typos. Use when you\'re unsure of the exact spelling.'
    };
    return descriptions[this.searchMode] || descriptions.hybrid;
  }
  
  render() {
    this.className = 'search-page chroma-search-page';
    
    this.innerHTML = `
      <div class="chroma-search-header">
        <div class="chroma-search-title">
          <h1>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8"/>
              <path d="m21 21-4.35-4.35"/>
            </svg>
            메모리 검색
          </h1>
          <p>AI 기반 벡터 검색으로 관련 메모리를 찾아보세요</p>
        </div>
        
        <div class="chroma-search-bar-wrapper">
          <chroma-search-bar 
            placeholder="Enter search query..." 
            value="${this.escapeHtml(this.searchQuery)}"
            variant="hero"
          ></chroma-search-bar>
        </div>
      </div>
      
      <div class="chroma-search-body">
        <aside class="chroma-search-sidebar">
          <div class="chroma-filter-section">
            <h3>카테고리</h3>
            <div class="chroma-filter-chips">
              <button class="chroma-filter-chip ${!this.selectedCategory ? 'active' : ''}" data-filter-type="category" data-filter-value="">
                전체
              </button>
              <button class="chroma-filter-chip ${this.selectedCategory === 'task' ? 'active' : ''}" data-filter-type="category" data-filter-value="task">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="m9 12 2 2 4-4"/></svg>
                Task
              </button>
              <button class="chroma-filter-chip ${this.selectedCategory === 'bug' ? 'active' : ''}" data-filter-type="category" data-filter-value="bug">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                Bug
              </button>
              <button class="chroma-filter-chip ${this.selectedCategory === 'idea' ? 'active' : ''}" data-filter-type="category" data-filter-value="idea">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v1"/><path d="M12 21v1"/></svg>
                Idea
              </button>
              <button class="chroma-filter-chip ${this.selectedCategory === 'decision' ? 'active' : ''}" data-filter-type="category" data-filter-value="decision">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="m9 12 2 2 4-4"/></svg>
                Decision
              </button>
              <button class="chroma-filter-chip ${this.selectedCategory === 'code_snippet' ? 'active' : ''}" data-filter-type="category" data-filter-value="code_snippet">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16,18 22,12 16,6"/><polyline points="8,6 2,12 8,18"/></svg>
                Code
              </button>
            </div>
          </div>
          
          <div class="chroma-filter-section">
            <h3>프로젝트</h3>
            <input 
              type="text" 
              class="chroma-project-input" 
              placeholder="Project ID..."
              value="${this.escapeHtml(this.selectedProject)}"
            >
          </div>
          
          <div class="chroma-filter-section">
            <h3>Search Mode</h3>
            <div class="chroma-mode-chips">
              <button class="chroma-mode-option ${this.searchMode === 'hybrid' ? 'active' : ''}" data-mode="hybrid" title="Vector + Text combined search">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v4"/><path d="M12 18v4"/><path d="m4.93 4.93 2.83 2.83"/><path d="m16.24 16.24 2.83 2.83"/><path d="M2 12h4"/><path d="M18 12h4"/><path d="m4.93 19.07 2.83-2.83"/><path d="m16.24 7.76 2.83-2.83"/></svg>
                Hybrid
              </button>
              <button class="chroma-mode-option ${this.searchMode === 'exact' ? 'active' : ''}" data-mode="exact" title="Exact text matching">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7V4h16v3"/><path d="M9 20h6"/><path d="M12 4v16"/></svg>
                Exact
              </button>
              <button class="chroma-mode-option ${this.searchMode === 'semantic' ? 'active' : ''}" data-mode="semantic" title="Semantic similarity search">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 1 0 10 10"/><path d="M12 12l8-8"/><circle cx="12" cy="12" r="2"/></svg>
                Semantic
              </button>
              <button class="chroma-mode-option ${this.searchMode === 'fuzzy' ? 'active' : ''}" data-mode="fuzzy" title="Fuzzy search with typo tolerance">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
                Fuzzy
              </button>
            </div>
            <p class="chroma-mode-description">${this.getModeDescription()}</p>
          </div>
        </aside>
        
        <main class="chroma-search-main">
          <div class="chroma-results-header">
            <span class="chroma-results-count"></span>
            <div class="chroma-sort-options">
              <button class="chroma-sort-option ${this.sortBy === 'relevance' ? 'active' : ''}" data-sort="relevance">관련도순</button>
              <button class="chroma-sort-option ${this.sortBy === 'recent' ? 'active' : ''}" data-sort="recent">최신순</button>
            </div>
          </div>
          
          <div class="chroma-search-loading" style="display: none;">
            <div class="chroma-loading-spinner"></div>
            <p>검색 중...</p>
          </div>
          
          <div class="chroma-results-container"></div>
          
          <div class="chroma-load-more-container" style="display: none;">
            <button class="chroma-load-more-btn">
              <span class="btn-text">더 보기</span>
              <span class="btn-loading">
                <svg class="spinner" width="16" height="16" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" fill="none" stroke-dasharray="32" stroke-linecap="round"/>
                </svg>
              </span>
            </button>
          </div>
        </main>
      </div>
    `;
  }
}

customElements.define('search-page', SearchPage);

export { SearchPage };
