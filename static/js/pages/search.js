/**
 * Search Page Component
 * Advanced search interface with filters and results
 */

class SearchPage extends HTMLElement {
  constructor() {
    super();
    this.searchQuery = '';
    this.selectedCategory = '';
    this.selectedProject = '';
    this.searchResults = [];
    this.isLoading = false;
    this.pageSize = 20;
    this.isInitialized = false;
  }
  
  connectedCallback() {
    if (this.isInitialized) {
      console.log('Search page already initialized, skipping...');
      return;
    }
    
    console.log('Search page connectedCallback called');
    this.isInitialized = true;
    this.parseUrlParams();
    this.render();
    this.setupEventListeners();
    
    // 초기 검색을 위해 약간의 지연 후 실행
    setTimeout(() => {
      // 쿼리가 있거나 필터가 설정된 경우에만 자동 검색
      if (this.searchQuery || this.selectedCategory || this.selectedProject) {
        this.waitForAppAndSearch();
      } else {
        // 쿼리가 없으면 로딩 상태를 false로 설정
        this.isLoading = false;
        this.updateLoadingState();
      }
    }, 100);
  }
  
  disconnectedCallback() {
    // Cleanup if needed
  }
  
  /**
   * Wait for app initialization and then perform search
   */
  async waitForAppAndSearch() {
    let attempts = 0;
    const maxAttempts = 50;
    
    const checkApp = () => {
      console.log(`Checking app initialization (attempt ${attempts + 1}/${maxAttempts})...`);
      
      if (window.app && window.app.apiClient) {
        console.log('App is ready, performing initial search...');
        this.performSearch();
        return true;
      }
      
      attempts++;
      if (attempts >= maxAttempts) {
        console.error('App initialization timeout, trying direct API call...');
        // 앱 초기화가 실패해도 직접 API 호출 시도
        this.performDirectSearch();
        return false;
      }
      
      setTimeout(checkApp, 100);
      return false;
    };
    
    checkApp();
  }
  
  /**
   * Perform direct search without app dependency
   */
  async performDirectSearch() {
    console.log('performDirectSearch called as fallback');
    
    try {
      this.isLoading = true;
      this.updateLoadingState();
      
      const url = new URL('/api/memories/search', window.location.origin);
      url.searchParams.append('query', this.searchQuery || '');
      if (this.selectedCategory) url.searchParams.append('category', this.selectedCategory);
      if (this.selectedProject) url.searchParams.append('project_id', this.selectedProject);
      url.searchParams.append('limit', this.pageSize.toString());
      
      console.log('Direct API call to:', url.toString());
      
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const result = await response.json();
      console.log('Direct search response:', result);
      
      this.searchResults = result.results || [];
      
    } catch (error) {
      console.error('Direct search failed:', error);
      this.searchResults = [];
      this.showError('Search failed. Please try again.');
    }
    
    // finally 블록 대신 명시적으로 처리
    console.log('Direct search completed, setting isLoading to false');
    this.isLoading = false;
    this.updateResultsDisplay();
  }
  
  /**
   * Parse URL parameters
   */
  parseUrlParams() {
    const urlParams = new URLSearchParams(window.location.search);
    this.searchQuery = urlParams.get('q') || '';
    this.selectedCategory = urlParams.get('category') || '';
    this.selectedProject = urlParams.get('project') || '';
  }
  
  /**
   * Update URL with current search state
   */
  updateUrl() {
    const params = new URLSearchParams();
    
    if (this.searchQuery) {
      params.set('q', this.searchQuery);
    }
    if (this.selectedCategory) {
      params.set('category', this.selectedCategory);
    }
    if (this.selectedProject) {
      params.set('project', this.selectedProject);
    }
    
    const newUrl = `${window.location.pathname}${params.toString() ? '?' + params.toString() : ''}`;
    window.history.replaceState({}, '', newUrl);
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    // Search form submission
    this.addEventListener('submit', (e) => {
      e.preventDefault();
      this.handleSearchSubmit();
    });
    
    // Click events
    this.addEventListener('click', (e) => {
      const target = e.target;
      
      if (target.classList.contains('search-btn')) {
        this.handleSearchSubmit();
      } else if (target.classList.contains('clear-btn')) {
        this.clearSearch();
      } else if (target.classList.contains('memory-item') || target.closest('.memory-item')) {
        const item = target.classList.contains('memory-item') ? target : target.closest('.memory-item');
        const memoryId = item.getAttribute('data-memory-id');
        if (memoryId) {
          this.navigateToMemory(memoryId);
        }
      }
    });
    
    // Filter changes
    this.addEventListener('change', (e) => {
      const target = e.target;
      
      if (target.classList.contains('category-filter')) {
        this.selectedCategory = target.value;
        console.log('Category filter changed to:', this.selectedCategory);
        // 앱이 준비되어 있으면 일반 검색, 아니면 직접 검색
        if (window.app && window.app.apiClient) {
          this.performSearch();
        } else {
          this.performDirectSearch();
        }
      } else if (target.classList.contains('project-filter')) {
        this.selectedProject = target.value;
        console.log('Project filter changed to:', this.selectedProject);
        // 앱이 준비되어 있으면 일반 검색, 아니면 직접 검색
        if (window.app && window.app.apiClient) {
          this.performSearch();
        } else {
          this.performDirectSearch();
        }
      }
    });
    
    // Enter key in search input
    this.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && e.target.classList.contains('search-input')) {
        e.preventDefault();
        this.handleSearchSubmit();
      }
    });
  }
  
  /**
   * Handle search submission
   */
  handleSearchSubmit() {
    const searchInput = this.querySelector('.search-input');
    if (searchInput) {
      this.searchQuery = searchInput.value.trim();
    }
    
    console.log('handleSearchSubmit called with query:', this.searchQuery);
    
    // 앱이 준비되어 있으면 일반 검색, 아니면 직접 검색
    if (window.app && window.app.apiClient) {
      this.performSearch();
    } else {
      this.performDirectSearch();
    }
  }
  
  /**
   * Clear search
   */
  clearSearch() {
    this.searchQuery = '';
    this.selectedCategory = '';
    this.selectedProject = '';
    
    const searchInput = this.querySelector('.search-input');
    const categoryFilter = this.querySelector('.category-filter');
    const projectFilter = this.querySelector('.project-filter');
    
    if (searchInput) searchInput.value = '';
    if (categoryFilter) categoryFilter.value = '';
    if (projectFilter) projectFilter.value = '';
    
    console.log('Search cleared, performing new search');
    
    // 앱이 준비되어 있으면 일반 검색, 아니면 직접 검색
    if (window.app && window.app.apiClient) {
      this.performSearch();
    } else {
      this.performDirectSearch();
    }
  }
  
  /**
   * Navigate to memory detail
   */
  navigateToMemory(memoryId) {
    if (window.app && window.app.router) {
      window.app.router.navigate(`/memory/${memoryId}`);
    } else {
      window.location.href = `/memory/${memoryId}`;
    }
  }
  
  /**
   * Perform search
   */
  async performSearch() {
    console.log('performSearch called with:', {
      query: this.searchQuery,
      category: this.selectedCategory,
      project: this.selectedProject,
      isLoading: this.isLoading
    });
    
    try {
      this.isLoading = true;
      this.updateLoadingState();
      this.updateUrl();
      
      if (!window.app || !window.app.apiClient) {
        throw new Error('API client not available');
      }
      
      console.log('Searching with query:', this.searchQuery, 'category:', this.selectedCategory, 'project:', this.selectedProject);
      
      const response = await window.app.apiClient.searchMemories(this.searchQuery, {
        category: this.selectedCategory || undefined,
        project_id: this.selectedProject || undefined,
        limit: this.pageSize
      });
      
      console.log('Search response:', response);
      
      this.searchResults = response.results || [];
      
    } catch (error) {
      console.error('Search failed:', error);
      this.searchResults = [];
      this.showError('Search failed. Please try again.');
    }
    
    // finally 블록 대신 명시적으로 처리
    console.log('Search completed, setting isLoading to false');
    this.isLoading = false;
    this.updateResultsDisplay();
  }
  
  /**
   * Show error message
   */
  showError(message) {
    const resultsContainer = this.querySelector('.results-container');
    if (resultsContainer) {
      resultsContainer.innerHTML = `
        <div class="error-message">
          <p>⚠️ ${message}</p>
        </div>
      `;
    }
  }
  
  /**
   * Update loading state
   */
  updateLoadingState() {
    console.log('updateLoadingState called, isLoading:', this.isLoading);
    
    // DOM이 아직 렌더링되지 않았을 수 있으므로 다음 틱에 실행
    setTimeout(() => {
      const loadingElement = this.querySelector('.search-loading');
      const resultsContainer = this.querySelector('.results-container');
      
      console.log('Loading element found:', !!loadingElement);
      console.log('Results container found:', !!resultsContainer);
      
      if (loadingElement) {
        loadingElement.style.display = this.isLoading ? 'flex' : 'none';
        console.log('Loading element display set to:', loadingElement.style.display);
      } else {
        console.warn('Loading element not found in DOM');
      }
      
      if (resultsContainer) {
        resultsContainer.style.opacity = this.isLoading ? '0.5' : '1';
        console.log('Results container opacity set to:', resultsContainer.style.opacity);
      } else {
        console.warn('Results container not found in DOM');
      }
    }, 0);
  }
  
  /**
   * Update results display
   */
  updateResultsDisplay() {
    console.log('updateResultsDisplay called with results:', this.searchResults.length);
    
    const resultsContainer = this.querySelector('.results-container');
    const resultsCount = this.querySelector('.results-count');
    
    if (resultsCount) {
      resultsCount.textContent = `${this.searchResults.length} results found`;
      console.log('Results count updated to:', resultsCount.textContent);
    }
    
    if (resultsContainer) {
      if (this.searchResults.length === 0) {
        resultsContainer.innerHTML = `
          <div class="no-results">
            <p>📭 No memories found</p>
            <p>Try adjusting your search terms or filters</p>
          </div>
        `;
        console.log('No results message displayed');
      } else {
        resultsContainer.innerHTML = this.searchResults.map(memory => this.renderMemoryItem(memory)).join('');
        console.log('Results rendered:', this.searchResults.length, 'items');
      }
    }
    
    // 로딩 상태 다시 업데이트
    this.updateLoadingState();
  }
  
  /**
   * Render a single memory item
   */
  renderMemoryItem(memory) {
    const categoryIcons = {
      task: '📋',
      bug: '🐛',
      idea: '💡',
      decision: '⚖️',
      incident: '🚨',
      code_snippet: '💻'
    };
    
    const icon = categoryIcons[memory.category] || '📝';
    const content = this.escapeHtml(memory.content || '');
    const truncatedContent = content.length > 200 ? content.substring(0, 200) + '...' : content;
    const date = this.formatDate(memory.created_at);
    const score = memory.similarity_score ? `${Math.round(memory.similarity_score * 100)}% match` : '';
    
    return `
      <div class="memory-item" data-memory-id="${memory.id}">
        <div class="memory-item-header">
          <span class="memory-category">${icon} ${memory.category || 'unknown'}</span>
          ${memory.project_id ? `<span class="memory-project">${memory.project_id}</span>` : ''}
          ${score ? `<span class="memory-score">${score}</span>` : ''}
        </div>
        <div class="memory-item-content">
          ${truncatedContent}
        </div>
        <div class="memory-item-footer">
          <span class="memory-date">${date}</span>
          <span class="memory-source">${memory.source || 'unknown'}</span>
        </div>
      </div>
    `;
  }
  
  /**
   * Format date
   */
  formatDate(dateStr) {
    if (!dateStr) return '';
    try {
      const date = new Date(dateStr);
      return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return dateStr;
    }
  }
  
  /**
   * Escape HTML
   */
  escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'search-page';
    
    this.innerHTML = `
      <div class="search-header">
        <h1>🔍 Search Memories</h1>
        <p>Find and explore your memory collection</p>
      </div>
      
      <div class="search-form">
        <div class="search-input-group">
          <input 
            type="text" 
            class="search-input" 
            placeholder="Search memories..." 
            value="${this.escapeHtml(this.searchQuery)}"
            autofocus
          >
          <button type="button" class="search-btn">Search</button>
          <button type="button" class="clear-btn">Clear</button>
        </div>
        
        <div class="search-filters">
          <select class="category-filter">
            <option value="">All Categories</option>
            <option value="task" ${this.selectedCategory === 'task' ? 'selected' : ''}>📋 Task</option>
            <option value="bug" ${this.selectedCategory === 'bug' ? 'selected' : ''}>🐛 Bug</option>
            <option value="idea" ${this.selectedCategory === 'idea' ? 'selected' : ''}>💡 Idea</option>
            <option value="decision" ${this.selectedCategory === 'decision' ? 'selected' : ''}>⚖️ Decision</option>
            <option value="incident" ${this.selectedCategory === 'incident' ? 'selected' : ''}>🚨 Incident</option>
            <option value="code_snippet" ${this.selectedCategory === 'code_snippet' ? 'selected' : ''}>💻 Code Snippet</option>
          </select>
          
          <input 
            type="text" 
            class="project-filter" 
            placeholder="Filter by project..."
            value="${this.escapeHtml(this.selectedProject)}"
          >
        </div>
      </div>
      
      <div class="search-results">
        <div class="results-header">
          <span class="results-count">Loading...</span>
        </div>
        
        <div class="search-loading" style="display: none;">
          <div class="loading-spinner"></div>
          <p>Searching...</p>
        </div>
        
        <div class="results-container">
          <div class="initial-message">
            <p>🔍 Enter a search term or browse all memories</p>
          </div>
        </div>
      </div>
    `;
  }
}

// Define the custom element
customElements.define('search-page', SearchPage);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .search-page {
    padding: 2rem;
    max-width: 1000px;
    margin: 0 auto;
  }
  
  .search-header {
    text-align: center;
    margin-bottom: 2rem;
  }
  
  .search-header h1 {
    margin: 0 0 0.5rem 0;
    font-size: 2rem;
    color: var(--text-primary);
  }
  
  .search-header p {
    margin: 0;
    color: var(--text-secondary);
  }
  
  .search-form {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 1.5rem;
    margin-bottom: 2rem;
  }
  
  .search-input-group {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
  }
  
  .search-input {
    flex: 1;
    padding: 0.75rem 1rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-size: 1rem;
  }
  
  .search-input:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
  }
  
  .search-btn {
    padding: 0.75rem 1.5rem;
    background: var(--primary-color);
    color: white;
    border: none;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 1rem;
    font-weight: 500;
    transition: var(--transition);
  }
  
  .search-btn:hover {
    background: var(--primary-hover);
  }
  
  .clear-btn {
    padding: 0.75rem 1rem;
    background: var(--bg-secondary);
    color: var(--text-secondary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 1rem;
    transition: var(--transition);
  }
  
  .clear-btn:hover {
    background: var(--error-color);
    color: white;
    border-color: var(--error-color);
  }
  
  .search-filters {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
  }
  
  .category-filter,
  .project-filter {
    padding: 0.5rem 1rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-size: 0.875rem;
    min-width: 150px;
  }
  
  .project-filter {
    flex: 1;
    max-width: 300px;
  }
  
  .search-results {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    overflow: hidden;
  }
  
  .results-header {
    padding: 1rem 1.5rem;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
  }
  
  .results-count {
    font-weight: 500;
    color: var(--text-primary);
  }
  
  .search-loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 3rem;
    color: var(--text-muted);
  }
  
  .loading-spinner {
    width: 2rem;
    height: 2rem;
    border: 2px solid var(--border-color);
    border-top: 2px solid var(--primary-color);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-bottom: 1rem;
  }
  
  @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }
  
  .results-container {
    padding: 1rem;
  }
  
  .no-results {
    text-align: center;
    padding: 3rem;
    color: var(--text-muted);
  }
  
  .no-results p {
    margin: 0.5rem 0;
  }
  
  .error-message {
    text-align: center;
    padding: 2rem;
    color: var(--error-color);
  }
  
  .memory-item {
    padding: 1rem 1.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    margin-bottom: 0.75rem;
    background: var(--bg-secondary);
    cursor: pointer;
    transition: var(--transition);
  }
  
  .memory-item:last-child {
    margin-bottom: 0;
  }
  
  .memory-item:hover {
    border-color: var(--primary-color);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    transform: translateY(-1px);
  }
  
  .memory-item-header {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
  }
  
  .memory-category {
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--text-secondary);
    text-transform: capitalize;
    background: var(--bg-tertiary);
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
  }
  
  .memory-project {
    font-size: 0.75rem;
    font-weight: 500;
    color: white;
    background: var(--primary-color);
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
  }
  
  .memory-score {
    font-size: 0.75rem;
    color: var(--success-color);
    font-weight: 500;
    margin-left: auto;
  }
  
  .memory-item-content {
    font-size: 0.9375rem;
    color: var(--text-primary);
    line-height: 1.6;
    margin-bottom: 0.75rem;
  }
  
  .memory-item-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  
  /* Responsive Design */
  @media (max-width: 768px) {
    .search-page {
      padding: 1rem;
    }
    
    .search-input-group {
      flex-direction: column;
    }
    
    .search-btn,
    .clear-btn {
      width: 100%;
    }
    
    .search-filters {
      flex-direction: column;
    }
    
    .category-filter,
    .project-filter {
      width: 100%;
      max-width: none;
    }
    
    .memory-item-header {
      flex-direction: column;
      align-items: flex-start;
      gap: 0.5rem;
    }
    
    .memory-score {
      margin-left: 0;
    }
  }
`;

document.head.appendChild(style);

export { SearchPage };
