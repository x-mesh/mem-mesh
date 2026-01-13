/**
 * Project Detail Page Web Component
 * Displays memories for a specific project
 */

class ProjectDetailPage extends HTMLElement {
  constructor() {
    super();
    this.projectId = null;
    this.projectInfo = null;
    this.memories = [];
    this.isLoading = false;
    this.currentPage = 1;
    this.pageSize = 20;
    this.totalMemories = 0;
    this.searchQuery = '';
    this.categoryFilter = '';
    this.sortBy = 'created_at';
    this.sortDirection = 'desc';
  }
  
  connectedCallback() {
    console.log('ProjectDetailPage connected');
    
    // Extract project ID from URL
    this.extractProjectId();
    
    this.render();
    this.setupEventListeners();
    
    // Load project data
    setTimeout(() => {
      this.loadProjectData();
    }, 100);
  }
  
  /**
   * Extract project ID from current URL
   */
  extractProjectId() {
    const path = window.location.pathname;
    const match = path.match(/\/project\/([^\/]+)/);
    if (match) {
      this.projectId = decodeURIComponent(match[1]);
    }
    
    console.log('Extracted project ID:', this.projectId);
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    // Back button
    const backBtn = this.querySelector('.back-btn');
    if (backBtn) {
      backBtn.addEventListener('click', () => {
        if (window.app && window.app.router) {
          window.app.router.navigate('/projects');
        } else {
          window.location.href = '/projects';
        }
      });
    }
    
    // Search input
    const searchInput = this.querySelector('.search-input');
    if (searchInput) {
      searchInput.addEventListener('input', this.handleSearch.bind(this));
    }
    
    // Category filter
    const categorySelect = this.querySelector('.category-select');
    if (categorySelect) {
      categorySelect.addEventListener('change', this.handleCategoryFilter.bind(this));
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
    
    // Refresh button
    const refreshBtn = this.querySelector('.refresh-btn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', this.loadProjectData.bind(this));
    }
    
    // Memory card clicks
    this.addEventListener('click', this.handleMemoryClick.bind(this));
    
    // Pagination
    this.addEventListener('click', this.handlePaginationClick.bind(this));
  }
  
  /**
   * Load project data and memories
   */
  async loadProjectData() {
    if (!this.projectId) {
      this.showError('No project ID specified');
      return;
    }
    
    try {
      this.setLoading(true);
      
      // Load all memories to get project info and filter by project
      let searchResult;
      
      if (window.app && window.app.apiClient) {
        searchResult = await window.app.apiClient.searchMemories('', { 
          limit: 1000 // Get all memories
        });
      } else {
        const response = await fetch('/api/memories/search?query=&limit=1000');
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        searchResult = await response.json();
      }
      
      if (searchResult && searchResult.results) {
        this.processProjectData(searchResult.results);
        this.renderProjectInfo();
        this.renderMemories();
        this.renderPagination();
      } else {
        this.showError('No memories found');
      }
      
    } catch (error) {
      console.error('Failed to load project data:', error);
      this.showError('Failed to load project data: ' + error.message);
    } finally {
      this.setLoading(false);
    }
  }
  
  /**
   * Process project data from memories
   */
  processProjectData(allMemories) {
    // Filter memories for this project
    const projectMemories = allMemories.filter(memory => {
      const memoryProjectId = memory.project_id || 'default';
      return memoryProjectId === this.projectId;
    });
    
    console.log(`Found ${projectMemories.length} memories for project ${this.projectId}`);
    
    // Calculate project info
    if (projectMemories.length > 0) {
      const categories = new Set();
      const tags = new Set();
      let totalSize = 0;
      let earliestDate = projectMemories[0].created_at;
      let latestDate = projectMemories[0].created_at;
      
      projectMemories.forEach(memory => {
        categories.add(memory.category);
        if (memory.tags && Array.isArray(memory.tags)) {
          memory.tags.forEach(tag => tags.add(tag));
        }
        totalSize += memory.content?.length || 0;
        
        if (memory.created_at < earliestDate) {
          earliestDate = memory.created_at;
        }
        if (memory.created_at > latestDate) {
          latestDate = memory.created_at;
        }
      });
      
      this.projectInfo = {
        id: this.projectId,
        name: this.projectId === 'default' ? 'Default Project' : this.projectId,
        memory_count: projectMemories.length,
        categories: Array.from(categories),
        tags: Array.from(tags),
        total_size: totalSize,
        avg_memory_size: Math.round(totalSize / projectMemories.length),
        created_at: earliestDate,
        updated_at: latestDate
      };
    } else {
      this.projectInfo = {
        id: this.projectId,
        name: this.projectId === 'default' ? 'Default Project' : this.projectId,
        memory_count: 0,
        categories: [],
        tags: [],
        total_size: 0,
        avg_memory_size: 0,
        created_at: null,
        updated_at: null
      };
    }
    
    this.memories = projectMemories;
    this.totalMemories = projectMemories.length;
    this.applyFiltersAndSort();
  }
  
  /**
   * Apply filters and sorting
   */
  applyFiltersAndSort() {
    let filtered = [...this.memories];
    
    // Apply search filter
    if (this.searchQuery) {
      const query = this.searchQuery.toLowerCase();
      filtered = filtered.filter(memory => 
        memory.content.toLowerCase().includes(query) ||
        (memory.tags && memory.tags.some(tag => tag.toLowerCase().includes(query)))
      );
    }
    
    // Apply category filter
    if (this.categoryFilter) {
      filtered = filtered.filter(memory => memory.category === this.categoryFilter);
    }
    
    // Apply sorting
    filtered.sort((a, b) => {
      let aVal, bVal;
      
      switch (this.sortBy) {
        case 'created_at':
          aVal = new Date(a.created_at);
          bVal = new Date(b.created_at);
          break;
        case 'content_length':
          aVal = a.content?.length || 0;
          bVal = b.content?.length || 0;
          break;
        case 'category':
          aVal = a.category;
          bVal = b.category;
          break;
        default:
          aVal = new Date(a.created_at);
          bVal = new Date(b.created_at);
      }
      
      if (aVal < bVal) return this.sortDirection === 'asc' ? -1 : 1;
      if (aVal > bVal) return this.sortDirection === 'asc' ? 1 : -1;
      return 0;
    });
    
    this.filteredMemories = filtered;
  }
  
  /**
   * Get paginated memories
   */
  getPaginatedMemories() {
    const startIndex = (this.currentPage - 1) * this.pageSize;
    const endIndex = startIndex + this.pageSize;
    return this.filteredMemories.slice(startIndex, endIndex);
  }
  
  /**
   * Handle search input
   */
  handleSearch(event) {
    this.searchQuery = event.target.value;
    this.currentPage = 1;
    this.applyFiltersAndSort();
    this.renderMemories();
    this.renderPagination();
  }
  
  /**
   * Handle category filter
   */
  handleCategoryFilter(event) {
    this.categoryFilter = event.target.value;
    this.currentPage = 1;
    this.applyFiltersAndSort();
    this.renderMemories();
    this.renderPagination();
  }
  
  /**
   * Handle sort change
   */
  handleSortChange(event) {
    this.sortBy = event.target.value;
    this.applyFiltersAndSort();
    this.renderMemories();
  }
  
  /**
   * Toggle sort direction
   */
  toggleSortDirection() {
    this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
    this.applyFiltersAndSort();
    this.renderMemories();
    
    const toggle = this.querySelector('.sort-toggle');
    if (toggle) {
      toggle.textContent = this.sortDirection === 'asc' ? '↑' : '↓';
    }
  }
  
  /**
   * Handle memory card clicks
   */
  handleMemoryClick(event) {
    const memoryCard = event.target.closest('.memory-card');
    if (memoryCard) {
      const memoryId = memoryCard.getAttribute('data-memory-id');
      if (memoryId) {
        if (window.app && window.app.router) {
          window.app.router.navigate(`/memory/${memoryId}`);
        } else {
          window.location.href = `/memory/${memoryId}`;
        }
      }
    }
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
        this.renderMemories();
        this.renderPagination();
        
        // Scroll to top
        this.scrollIntoView({ behavior: 'smooth' });
      }
    }
  }
  
  /**
   * Set loading state
   */
  setLoading(loading) {
    this.isLoading = loading;
    
    const loadingEl = this.querySelector('.loading-state');
    const contentEl = this.querySelector('.project-content');
    
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
   * Format file size
   */
  formatSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }
  
  /**
   * Format date
   */
  formatDate(dateString) {
    return new Date(dateString).toLocaleDateString('ko-KR', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  }
  
  /**
   * Get category color
   */
  getCategoryColor(category) {
    const colors = {
      task: '#22c55e',
      bug: '#ef4444',
      idea: '#f59e0b',
      decision: '#3b82f6',
      code_snippet: '#a855f7',
      incident: '#ef4444',
      'git-history': '#6366f1'
    };
    return colors[category] || '#64748b';
  }
  
  /**
   * Render project info
   */
  renderProjectInfo() {
    if (!this.projectInfo) return;
    
    const infoContainer = this.querySelector('.project-info');
    if (!infoContainer) return;
    
    infoContainer.innerHTML = `
      <div class="project-header">
        <h1>${this.projectInfo.name}</h1>
        <div class="project-stats">
          <div class="stat-item">
            <span class="stat-label">Memories</span>
            <span class="stat-value">${this.projectInfo.memory_count}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Total Size</span>
            <span class="stat-value">${this.formatSize(this.projectInfo.total_size)}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Avg Size</span>
            <span class="stat-value">${this.formatSize(this.projectInfo.avg_memory_size)}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Categories</span>
            <span class="stat-value">${this.projectInfo.categories.length}</span>
          </div>
        </div>
      </div>
      
      ${this.projectInfo.categories.length > 0 ? `
        <div class="project-categories">
          <span class="categories-label">Categories:</span>
          <div class="categories-list">
            ${this.projectInfo.categories.map(cat => `
              <span class="category-tag" style="background: ${this.getCategoryColor(cat)}">${cat}</span>
            `).join('')}
          </div>
        </div>
      ` : ''}
      
      ${this.projectInfo.tags.length > 0 ? `
        <div class="project-tags">
          <span class="tags-label">Tags:</span>
          <div class="tags-list">
            ${this.projectInfo.tags.slice(0, 10).map(tag => `<span class="tag">${tag}</span>`).join('')}
            ${this.projectInfo.tags.length > 10 ? `<span class="tag-more">+${this.projectInfo.tags.length - 10} more</span>` : ''}
          </div>
        </div>
      ` : ''}
    `;
  }
  
  /**
   * Render memories list
   */
  renderMemories() {
    const container = this.querySelector('.memories-grid');
    if (!container) return;
    
    const paginatedMemories = this.getPaginatedMemories();
    
    if (paginatedMemories.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <p>No memories found</p>
          ${this.searchQuery || this.categoryFilter ? '<button class="clear-filters-btn">Clear filters</button>' : ''}
        </div>
      `;
      
      const clearBtn = container.querySelector('.clear-filters-btn');
      if (clearBtn) {
        clearBtn.addEventListener('click', () => {
          const searchInput = this.querySelector('.search-input');
          const categorySelect = this.querySelector('.category-select');
          
          if (searchInput) searchInput.value = '';
          if (categorySelect) categorySelect.value = '';
          
          this.searchQuery = '';
          this.categoryFilter = '';
          this.currentPage = 1;
          this.applyFiltersAndSort();
          this.renderMemories();
          this.renderPagination();
        });
      }
      return;
    }
    
    container.innerHTML = paginatedMemories.map(memory => `
      <div class="memory-card" data-memory-id="${memory.id}">
        <div class="memory-header">
          <div class="memory-meta">
            <span class="category-badge" style="background: ${this.getCategoryColor(memory.category)}">${memory.category}</span>
            <span class="memory-date">${this.formatDate(memory.created_at)}</span>
          </div>
          <div class="memory-size">${this.formatSize(memory.content?.length || 0)}</div>
        </div>
        
        <div class="memory-content">
          <p>${memory.content.substring(0, 200)}${memory.content.length > 200 ? '...' : ''}</p>
        </div>
        
        ${memory.tags && memory.tags.length > 0 ? `
          <div class="memory-tags">
            ${memory.tags.slice(0, 5).map(tag => `<span class="tag">${tag}</span>`).join('')}
            ${memory.tags.length > 5 ? `<span class="tag-more">+${memory.tags.length - 5}</span>` : ''}
          </div>
        ` : ''}
      </div>
    `).join('');
  }
  
  /**
   * Render pagination
   */
  renderPagination() {
    const container = this.querySelector('.pagination');
    if (!container) return;
    
    const totalPages = Math.ceil(this.filteredMemories.length / this.pageSize);
    
    if (totalPages <= 1) {
      container.innerHTML = '';
      return;
    }
    
    let paginationHTML = '';
    
    // Previous button
    if (this.currentPage > 1) {
      paginationHTML += `<button class="page-btn" data-page="${this.currentPage - 1}">Previous</button>`;
    }
    
    // Page numbers
    const startPage = Math.max(1, this.currentPage - 2);
    const endPage = Math.min(totalPages, this.currentPage + 2);
    
    if (startPage > 1) {
      paginationHTML += `<button class="page-btn" data-page="1">1</button>`;
      if (startPage > 2) {
        paginationHTML += `<span class="page-ellipsis">...</span>`;
      }
    }
    
    for (let i = startPage; i <= endPage; i++) {
      paginationHTML += `<button class="page-btn ${i === this.currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
    }
    
    if (endPage < totalPages) {
      if (endPage < totalPages - 1) {
        paginationHTML += `<span class="page-ellipsis">...</span>`;
      }
      paginationHTML += `<button class="page-btn" data-page="${totalPages}">${totalPages}</button>`;
    }
    
    // Next button
    if (this.currentPage < totalPages) {
      paginationHTML += `<button class="page-btn" data-page="${this.currentPage + 1}">Next</button>`;
    }
    
    container.innerHTML = paginationHTML;
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'project-detail-page';
    
    this.innerHTML = `
      <div class="page-header">
        <button class="back-btn">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M19 12H5M12 19L5 12L12 5"/>
          </svg>
          Back to Projects
        </button>
        
        <div class="header-actions">
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
      
      <div class="loading-state" style="display: none;">
        <div class="loading-spinner"></div>
        <p>Loading project data...</p>
      </div>
      
      <div class="project-content">
        <div class="project-info"></div>
        
        <div class="memories-controls">
          <div class="search-section">
            <input 
              type="text" 
              class="search-input" 
              placeholder="Search memories..."
            />
          </div>
          
          <div class="filter-section">
            <select class="category-select">
              <option value="">All Categories</option>
              <option value="task">Task</option>
              <option value="bug">Bug</option>
              <option value="idea">Idea</option>
              <option value="decision">Decision</option>
              <option value="code_snippet">Code Snippet</option>
              <option value="incident">Incident</option>
              <option value="git-history">Git History</option>
            </select>
          </div>
          
          <div class="sort-section">
            <label>Sort by:</label>
            <select class="sort-select">
              <option value="created_at">Date Created</option>
              <option value="content_length">Content Length</option>
              <option value="category">Category</option>
            </select>
            <button class="sort-toggle">↓</button>
          </div>
        </div>
        
        <div class="memories-grid"></div>
        
        <div class="pagination"></div>
      </div>
    `;
  }
}

// Define the custom element
customElements.define('project-detail-page', ProjectDetailPage);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .project-detail-page {
    padding: var(--space-6) 0;
    max-width: 1200px;
    margin: 0 auto;
  }
  
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border-color);
  }
  
  .back-btn {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: none;
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    padding: 0.5rem 1rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    transition: var(--transition);
  }
  
  .back-btn:hover {
    background: var(--bg-secondary);
  }
  
  .back-btn svg {
    stroke: currentColor;
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
  
  .project-info {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 2rem;
    margin-bottom: 2rem;
  }
  
  .project-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1.5rem;
  }
  
  .project-header h1 {
    margin: 0;
    color: var(--text-primary);
    font-size: 2rem;
  }
  
  .project-stats {
    display: flex;
    gap: 2rem;
  }
  
  .stat-item {
    text-align: center;
  }
  
  .stat-label {
    display: block;
    font-size: 0.75rem;
    color: var(--text-secondary);
    margin-bottom: 0.25rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  
  .stat-value {
    display: block;
    font-size: 1.5rem;
    font-weight: bold;
    color: var(--primary-color);
  }
  
  .project-categories,
  .project-tags {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1rem;
  }
  
  .project-categories:last-child,
  .project-tags:last-child {
    margin-bottom: 0;
  }
  
  .categories-label,
  .tags-label {
    font-size: 0.875rem;
    color: var(--text-secondary);
    font-weight: 500;
    min-width: 80px;
  }
  
  .categories-list,
  .tags-list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  
  .category-tag {
    color: white;
    padding: 0.25rem 0.75rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
    font-weight: 500;
  }
  
  .tag {
    background: var(--bg-secondary);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
  }
  
  .tag-more {
    background: var(--bg-tertiary);
    color: var(--text-muted);
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
    font-style: italic;
  }
  
  .memories-controls {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
    gap: 1rem;
    flex-wrap: wrap;
  }
  
  .search-section {
    flex: 1;
    min-width: 200px;
  }
  
  .search-input {
    width: 100%;
    max-width: 400px;
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
  
  .filter-section,
  .sort-section {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
    color: var(--text-secondary);
  }
  
  .category-select,
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
  
  .memories-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
    gap: 1.5rem;
    margin-bottom: 2rem;
  }
  
  .memory-card {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 1.5rem;
    cursor: pointer;
    transition: var(--transition);
  }
  
  .memory-card:hover {
    border-color: var(--primary-color);
    box-shadow: 0 4px 12px var(--shadow-color);
  }
  
  .memory-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1rem;
  }
  
  .memory-meta {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  
  .category-badge {
    color: white;
    padding: 0.25rem 0.75rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: capitalize;
  }
  
  .memory-date {
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  
  .memory-size {
    font-size: 0.75rem;
    color: var(--text-muted);
    font-weight: 500;
  }
  
  .memory-content {
    margin-bottom: 1rem;
  }
  
  .memory-content p {
    margin: 0;
    color: var(--text-primary);
    line-height: 1.5;
    font-size: 0.875rem;
  }
  
  .memory-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
  }
  
  .empty-state {
    grid-column: 1 / -1;
    text-align: center;
    padding: 4rem;
    color: var(--text-muted);
  }
  
  .empty-state p {
    margin: 0 0 1rem 0;
    font-size: 1.125rem;
  }
  
  .clear-filters-btn {
    background: var(--primary-color);
    color: white;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
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
  
  .page-btn {
    background: var(--bg-secondary);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
    padding: 0.5rem 0.75rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    transition: var(--transition);
  }
  
  .page-btn:hover {
    background: var(--bg-tertiary);
  }
  
  .page-btn.active {
    background: var(--primary-color);
    color: white;
    border-color: var(--primary-color);
  }
  
  .page-ellipsis {
    color: var(--text-muted);
    padding: 0.5rem;
    font-size: 0.875rem;
  }
  
  /* Responsive design */
  @media (max-width: 768px) {
    .project-detail-page {
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
    
    .project-header {
      flex-direction: column;
      gap: 1rem;
    }
    
    .project-stats {
      justify-content: space-around;
      width: 100%;
    }
    
    .memories-controls {
      flex-direction: column;
      align-items: stretch;
    }
    
    .filter-section,
    .sort-section {
      justify-content: space-between;
    }
    
    .memories-grid {
      grid-template-columns: 1fr;
    }
    
    .pagination {
      flex-wrap: wrap;
    }
  }
`;

document.head.appendChild(style);

export { ProjectDetailPage };