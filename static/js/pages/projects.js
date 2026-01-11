/**
 * Projects Page Web Component
 * Displays project list and management interface
 */

class ProjectsPage extends HTMLElement {
  constructor() {
    super();
    this.projects = [];
    this.isLoading = false;
    this.currentSort = 'name';
    this.sortDirection = 'asc';
    this.searchQuery = '';
  }
  
  connectedCallback() {
    console.log('ProjectsPage connected');
    this.render();
    this.setupEventListeners();
    
    // 약간의 지연 후 데이터 로드 (DOM이 완전히 렌더링된 후)
    setTimeout(() => {
      this.loadProjects();
    }, 100);
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    // Search input
    const searchInput = this.querySelector('.search-input');
    if (searchInput) {
      searchInput.addEventListener('input', this.handleSearch.bind(this));
    }
    
    // Sort controls
    const sortSelect = this.querySelector('.sort-select');
    if (sortSelect) {
      sortSelect.addEventListener('change', this.handleSortChange.bind(this));
    }
    
    // Sort direction toggle
    const sortToggle = this.querySelector('.sort-toggle');
    if (sortToggle) {
      sortToggle.addEventListener('click', this.toggleSortDirection.bind(this));
    }
    
    // Refresh button
    const refreshBtn = this.querySelector('.refresh-btn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', this.loadProjects.bind(this));
    }
    
    // Export button
    const exportBtn = this.querySelector('.export-btn');
    if (exportBtn) {
      exportBtn.addEventListener('click', this.handleExport.bind(this));
    }
    
    // Project cards click events
    this.addEventListener('click', this.handleProjectClick.bind(this));
  }
  
  /**
   * Load projects data
   */
  async loadProjects() {
    try {
      this.setLoading(true);
      
      // Get all memories and group by project
      let searchResult;
      
      if (window.app && window.app.apiClient) {
        // Use app API client if available
        searchResult = await window.app.apiClient.searchMemories('', { 
          limit: 1000 // Get all memories to analyze projects
        });
      } else {
        // Direct API call as fallback
        console.log('App not ready, using direct API call');
        const response = await fetch('/api/memories/search?query=&limit=1000');
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        searchResult = await response.json();
      }
      
      if (searchResult && searchResult.results) {
        this.processProjectsFromMemories(searchResult.results);
        this.renderProjects();
        this.updateSummary();
      } else {
        console.warn('No results found in search response:', searchResult);
        this.projects = [];
        this.renderProjects();
        this.updateSummary();
      }
      
    } catch (error) {
      console.error('Failed to load projects:', error);
      this.showError('Failed to load projects: ' + error.message);
    } finally {
      this.setLoading(false);
    }
  }
  
  /**
   * Process memories to extract project information
   */
  processProjectsFromMemories(memories) {
    console.log('Processing memories for projects:', memories.length);
    
    const projectMap = new Map();
    
    memories.forEach(memory => {
      const projectId = memory.project_id || 'default';
      
      if (!projectMap.has(projectId)) {
        projectMap.set(projectId, {
          id: projectId,
          name: projectId === 'default' ? 'Default Project' : projectId,
          memory_count: 0,
          categories: new Set(),
          tags: new Set(),
          created_at: memory.created_at,
          updated_at: memory.created_at,
          total_size: 0
        });
      }
      
      const project = projectMap.get(projectId);
      project.memory_count++;
      project.categories.add(memory.category);
      if (memory.tags && Array.isArray(memory.tags)) {
        memory.tags.forEach(tag => project.tags.add(tag));
      }
      project.total_size += memory.content?.length || 0;
      
      // Update timestamps
      if (memory.created_at < project.created_at) {
        project.created_at = memory.created_at;
      }
      if (memory.created_at > project.updated_at) {
        project.updated_at = memory.created_at;
      }
    });
    
    // Convert sets to arrays and calculate additional metrics
    this.projects = Array.from(projectMap.values()).map(project => ({
      ...project,
      categories: Array.from(project.categories),
      tags: Array.from(project.tags),
      avg_memory_size: project.memory_count > 0 ? Math.round(project.total_size / project.memory_count) : 0
    }));
    
    console.log('Processed projects:', this.projects);
    
    this.sortProjects();
  }
  
  /**
   * Handle search input
   */
  handleSearch(event) {
    this.searchQuery = event.target.value.toLowerCase();
    this.renderProjects();
  }
  
  /**
   * Handle sort change
   */
  handleSortChange(event) {
    this.currentSort = event.target.value;
    this.sortProjects();
    this.renderProjects();
  }
  
  /**
   * Toggle sort direction
   */
  toggleSortDirection() {
    this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
    this.sortProjects();
    this.renderProjects();
    
    // Update toggle button
    const toggle = this.querySelector('.sort-toggle');
    if (toggle) {
      toggle.textContent = this.sortDirection === 'asc' ? '↑' : '↓';
    }
  }
  
  /**
   * Sort projects
   */
  sortProjects() {
    this.projects.sort((a, b) => {
      let aVal, bVal;
      
      switch (this.currentSort) {
        case 'name':
          aVal = a.name.toLowerCase();
          bVal = b.name.toLowerCase();
          break;
        case 'memory_count':
          aVal = a.memory_count;
          bVal = b.memory_count;
          break;
        case 'created_at':
          aVal = new Date(a.created_at);
          bVal = new Date(b.created_at);
          break;
        case 'updated_at':
          aVal = new Date(a.updated_at);
          bVal = new Date(b.updated_at);
          break;
        case 'total_size':
          aVal = a.total_size;
          bVal = b.total_size;
          break;
        default:
          aVal = a.name.toLowerCase();
          bVal = b.name.toLowerCase();
      }
      
      if (aVal < bVal) return this.sortDirection === 'asc' ? -1 : 1;
      if (aVal > bVal) return this.sortDirection === 'asc' ? 1 : -1;
      return 0;
    });
  }
  
  /**
   * Filter projects based on search query
   */
  getFilteredProjects() {
    if (!this.searchQuery) return this.projects;
    
    return this.projects.filter(project => 
      project.name.toLowerCase().includes(this.searchQuery) ||
      project.categories.some(cat => cat.toLowerCase().includes(this.searchQuery)) ||
      project.tags.some(tag => tag.toLowerCase().includes(this.searchQuery))
    );
  }
  
  /**
   * Handle project card clicks
   */
  handleProjectClick(event) {
    const projectCard = event.target.closest('.project-card');
    if (projectCard) {
      const projectId = projectCard.getAttribute('data-project-id');
      if (projectId) {
        // Navigate to project detail (search with project filter)
        const searchParams = new URLSearchParams();
        if (projectId !== 'default') {
          searchParams.set('project', projectId);
        }
        
        if (window.app && window.app.router) {
          window.app.router.navigate(`/search?${searchParams.toString()}`);
        } else {
          // Fallback to direct navigation
          window.location.href = `/search?${searchParams.toString()}`;
        }
      }
    }
  }
  
  /**
   * Handle export
   */
  async handleExport() {
    try {
      const exportData = {
        projects: this.projects,
        exported_at: new Date().toISOString(),
        total_projects: this.projects.length,
        total_memories: this.projects.reduce((sum, p) => sum + p.memory_count, 0)
      };
      
      const blob = new Blob([JSON.stringify(exportData, null, 2)], {
        type: 'application/json'
      });
      
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `mem-mesh-projects-${new Date().toISOString().split('T')[0]}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      
    } catch (error) {
      console.error('Failed to export projects:', error);
      this.showError('Failed to export projects');
    }
  }
  
  /**
   * Set loading state
   */
  setLoading(loading) {
    this.isLoading = loading;
    
    const loadingEl = this.querySelector('.loading-state');
    const contentEl = this.querySelector('.projects-content');
    
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
      day: 'numeric'
    });
  }
  
  /**
   * Render projects list
   */
  renderProjects() {
    const container = this.querySelector('.projects-grid');
    if (!container) return;
    
    const filteredProjects = this.getFilteredProjects();
    
    if (filteredProjects.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <p>No projects found</p>
          ${this.searchQuery ? '<button class="clear-search-btn">Clear search</button>' : ''}
        </div>
      `;
      
      const clearBtn = container.querySelector('.clear-search-btn');
      if (clearBtn) {
        clearBtn.addEventListener('click', () => {
          const searchInput = this.querySelector('.search-input');
          if (searchInput) {
            searchInput.value = '';
            this.searchQuery = '';
            this.renderProjects();
          }
        });
      }
      return;
    }
    
    container.innerHTML = filteredProjects.map(project => `
      <div class="project-card" data-project-id="${project.id}">
        <div class="project-header">
          <h3 class="project-name">${project.name}</h3>
          <div class="project-stats">
            <span class="memory-count">${project.memory_count} memories</span>
          </div>
        </div>
        
        <div class="project-details">
          <div class="detail-row">
            <span class="label">Categories:</span>
            <div class="categories">
              ${project.categories.map(cat => `<span class="category-tag">${cat}</span>`).join('')}
            </div>
          </div>
          
          ${project.tags.length > 0 ? `
            <div class="detail-row">
              <span class="label">Tags:</span>
              <div class="tags">
                ${project.tags.slice(0, 5).map(tag => `<span class="tag">${tag}</span>`).join('')}
                ${project.tags.length > 5 ? `<span class="tag-more">+${project.tags.length - 5}</span>` : ''}
              </div>
            </div>
          ` : ''}
          
          <div class="detail-row">
            <span class="label">Size:</span>
            <span class="value">${this.formatSize(project.total_size)}</span>
          </div>
          
          <div class="detail-row">
            <span class="label">Created:</span>
            <span class="value">${this.formatDate(project.created_at)}</span>
          </div>
          
          <div class="detail-row">
            <span class="label">Updated:</span>
            <span class="value">${this.formatDate(project.updated_at)}</span>
          </div>
        </div>
        
        <div class="project-actions">
          <button class="view-btn" data-project-id="${project.id}">View Memories</button>
        </div>
      </div>
    `).join('');
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'projects-page';
    
    this.innerHTML = `
      <div class="page-header">
        <h1>Projects</h1>
        <div class="header-actions">
          <button class="refresh-btn secondary-button"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"/></svg> Refresh</button>
          <button class="export-btn secondary-button"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7,10 12,15 17,10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Export</button>
        </div>
      </div>
      
      <div class="error-message" style="display: none;"></div>
      
      <div class="projects-controls">
        <div class="search-section">
          <input 
            type="text" 
            class="search-input" 
            placeholder="Search projects, categories, or tags..."
          />
        </div>
        
        <div class="sort-section">
          <label>Sort by:</label>
          <select class="sort-select">
            <option value="name">Name</option>
            <option value="memory_count">Memory Count</option>
            <option value="total_size">Total Size</option>
            <option value="created_at">Created Date</option>
            <option value="updated_at">Updated Date</option>
          </select>
          <button class="sort-toggle">↑</button>
        </div>
      </div>
      
      <div class="loading-state" style="display: none;">
        <div class="loading-spinner"></div>
        <p>Loading projects...</p>
      </div>
      
      <div class="projects-content">
        <div class="projects-summary">
          <div class="summary-card">
            <span class="summary-label">Total Projects</span>
            <span class="summary-value" id="total-projects">0</span>
          </div>
          <div class="summary-card">
            <span class="summary-label">Total Memories</span>
            <span class="summary-value" id="total-memories">0</span>
          </div>
          <div class="summary-card">
            <span class="summary-label">Average per Project</span>
            <span class="summary-value" id="avg-memories">0</span>
          </div>
        </div>
        
        <div class="projects-grid"></div>
      </div>
    `;
    
    // Update summary when projects are loaded
    this.updateSummary();
  }
  
  /**
   * Update summary statistics
   */
  updateSummary() {
    const totalProjects = this.querySelector('#total-projects');
    const totalMemories = this.querySelector('#total-memories');
    const avgMemories = this.querySelector('#avg-memories');
    
    if (totalProjects) totalProjects.textContent = this.projects.length;
    
    const memoryCount = this.projects.reduce((sum, p) => sum + p.memory_count, 0);
    if (totalMemories) totalMemories.textContent = memoryCount;
    
    const avg = this.projects.length > 0 ? Math.round(memoryCount / this.projects.length) : 0;
    if (avgMemories) avgMemories.textContent = avg;
  }
}

// Define the custom element
customElements.define('projects-page', ProjectsPage);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .projects-page {
    padding: 2rem;
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
  
  .page-header h1 {
    margin: 0;
    color: var(--text-primary);
  }
  
  .header-actions {
    display: flex;
    gap: 1rem;
  }
  
  .error-message {
    background: var(--error-bg);
    color: var(--error-text);
    border: 1px solid var(--error-color);
    border-radius: var(--border-radius);
    padding: 1rem;
    margin-bottom: 1rem;
  }
  
  .projects-controls {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
    gap: 1rem;
  }
  
  .search-section {
    flex: 1;
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
  
  .sort-section {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
    color: var(--text-secondary);
  }
  
  .sort-select {
    padding: 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    background: var(--bg-primary);
    color: var(--text-primary);
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
  
  .projects-summary {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
  }
  
  .summary-card {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 1.5rem;
    text-align: center;
  }
  
  .summary-label {
    display: block;
    font-size: 0.875rem;
    color: var(--text-secondary);
    margin-bottom: 0.5rem;
  }
  
  .summary-value {
    display: block;
    font-size: 2rem;
    font-weight: bold;
    color: var(--primary-color);
  }
  
  .projects-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
    gap: 1.5rem;
  }
  
  .project-card {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 1.5rem;
    cursor: pointer;
    transition: var(--transition);
  }
  
  .project-card:hover {
    border-color: var(--primary-color);
    box-shadow: 0 4px 12px var(--shadow-color);
  }
  
  .project-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1rem;
  }
  
  .project-name {
    margin: 0;
    color: var(--text-primary);
    font-size: 1.25rem;
  }
  
  .project-stats {
    text-align: right;
  }
  
  .memory-count {
    background: var(--primary-color);
    color: white;
    padding: 0.25rem 0.75rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.875rem;
    font-weight: 500;
  }
  
  .project-details {
    margin-bottom: 1rem;
  }
  
  .detail-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.75rem;
    font-size: 0.875rem;
  }
  
  .detail-row:last-child {
    margin-bottom: 0;
  }
  
  .label {
    color: var(--text-secondary);
    font-weight: 500;
  }
  
  .value {
    color: var(--text-primary);
  }
  
  .categories,
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
  }
  
  .category-tag {
    background: var(--secondary-color);
    color: white;
    padding: 0.125rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
    font-weight: 500;
  }
  
  .tag {
    background: var(--bg-secondary);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
    padding: 0.125rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
  }
  
  .tag-more {
    background: var(--bg-tertiary);
    color: var(--text-muted);
    padding: 0.125rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
    font-style: italic;
  }
  
  .project-actions {
    border-top: 1px solid var(--border-color);
    padding-top: 1rem;
    text-align: center;
  }
  
  .view-btn {
    background: var(--primary-color);
    color: white;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
    transition: var(--transition);
  }
  
  .view-btn:hover {
    background: var(--primary-hover);
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
  
  .clear-search-btn {
    background: var(--primary-color);
    color: white;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
  }
  
  .clear-search-btn:hover {
    background: var(--primary-hover);
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
  
  .secondary-button svg {
    width: 16px;
    height: 16px;
    stroke: currentColor;
  }
  
  .secondary-button:hover {
    background: var(--bg-tertiary);
  }
  
  /* Responsive design */
  @media (max-width: 768px) {
    .projects-page {
      padding: 1rem;
    }
    
    .page-header {
      flex-direction: column;
      align-items: flex-start;
      gap: 1rem;
    }
    
    .header-actions {
      align-self: stretch;
      justify-content: space-between;
    }
    
    .projects-controls {
      flex-direction: column;
      align-items: stretch;
    }
    
    .sort-section {
      justify-content: space-between;
    }
    
    .projects-summary {
      grid-template-columns: 1fr;
    }
    
    .projects-grid {
      grid-template-columns: 1fr;
    }
  }
`;

document.head.appendChild(style);

export { ProjectsPage };