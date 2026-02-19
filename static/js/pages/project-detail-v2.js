/**
 * Project Detail Page Web Component (Simplified Version)
 * Displays memories for a specific project
 */

class ProjectDetailPage extends HTMLElement {
  constructor() {
    super();
    this.projectId = null;
    this.projectInfo = null;
    this.memories = [];
    this.isLoading = false;
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
      
      searchResult = await window.app.apiClient.searchMemories('', { limit: 1000 });
      
      if (searchResult && searchResult.results) {
        this.processProjectData(searchResult.results);
        this.renderProjectInfo();
        this.renderMemories();
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
      
      projectMemories.forEach(memory => {
        categories.add(memory.category);
        if (memory.tags && Array.isArray(memory.tags)) {
          memory.tags.forEach(tag => tags.add(tag));
        }
        totalSize += memory.content?.length || 0;
      });
      
      this.projectInfo = {
        id: this.projectId,
        name: this.projectId === 'default' ? 'Default Project' : this.projectId,
        memory_count: projectMemories.length,
        categories: Array.from(categories),
        tags: Array.from(tags),
        total_size: totalSize,
        avg_memory_size: Math.round(totalSize / projectMemories.length)
      };
    } else {
      this.projectInfo = {
        id: this.projectId,
        name: this.projectId === 'default' ? 'Default Project' : this.projectId,
        memory_count: 0,
        categories: [],
        tags: [],
        total_size: 0,
        avg_memory_size: 0
      };
    }
    
    this.memories = projectMemories;
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
            <span class="stat-label">Categories</span>
            <span class="stat-value">${this.projectInfo.categories.length}</span>
          </div>
        </div>
      </div>
      
      ${this.projectInfo.categories.length > 0 ? `
        <div class="project-categories">
          <span class="categories-label">Categories:</span>
          ${this.projectInfo.categories.map(cat => `<span class="category-tag">${cat}</span>`).join('')}
        </div>
      ` : ''}
    `;
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
          <p>No memories found for this project</p>
        </div>
      `;
      return;
    }
    
    // Show first 10 memories
    const displayMemories = this.memories.slice(0, 10);
    
    container.innerHTML = `
      <h3>Recent Memories (${displayMemories.length} of ${this.memories.length})</h3>
      <div class="memories-grid">
        ${displayMemories.map(memory => `
          <div class="memory-card" data-memory-id="${memory.id}">
            <div class="memory-header">
              <span class="category-badge">${memory.category}</span>
              <span class="memory-date">${this.formatDate(memory.created_at)}</span>
            </div>
            <div class="memory-content">
              <p>${memory.content.substring(0, 150)}${memory.content.length > 150 ? '...' : ''}</p>
            </div>
            <div class="memory-footer">
              <span class="memory-size">${this.formatSize(memory.content?.length || 0)}</span>
            </div>
          </div>
        `).join('')}
      </div>
      ${this.memories.length > 10 ? `
        <div class="show-more">
          <button class="show-more-btn">Show More (${this.memories.length - 10} remaining)</button>
        </div>
      ` : ''}
    `;
    
    // Add click handlers for memory cards
    container.addEventListener('click', (event) => {
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
    });
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'project-detail-page';
    
    this.innerHTML = `
      <div class="page-header">
        <div class="page-header-main">
          <button class="back-btn">
            ← Back to Projects
          </button>
        </div>
      </div>
      
      <div class="error-message" style="display: none;"></div>
      
      <div class="loading-state" style="display: none;">
        <p>Loading project data...</p>
      </div>
      
      <div class="project-content">
        <div class="project-info"></div>
        <div class="memories-list"></div>
      </div>
    `;
  }
}

// Define the custom element
customElements.define('project-detail-page', ProjectDetailPage);

// Add basic styles
const style = document.createElement('style');
style.textContent = `
  .project-detail-page {
    padding: 1rem;
    max-width: 1200px;
    margin: 0 auto;
    font-family: var(--font-body);
  }
  
  .project-detail-page .error-message {
    background: var(--error-bg);
    color: var(--error-color);
    padding: 1rem;
    margin: 1rem 0;
    border-radius: 4px;
    border: 1px solid var(--error-color);
  }
  
  .project-detail-page .loading-state {
    text-align: center;
    padding: 2rem;
    color: var(--text-muted);
  }
  
  .back-btn {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    padding: 0.5rem 1rem;
    border-radius: 4px;
    cursor: pointer;
    margin-bottom: 1rem;
    font-size: 0.9rem;
    color: var(--text-primary);
  }
  
  .back-btn:hover {
    background: var(--bg-tertiary);
  }
  
  .project-info {
    background: var(--card-bg) !important;
    padding: 1.5rem !important;
    margin: 0.5rem 0 !important;
    border-radius: 8px !important;
    border: 1px solid var(--border-color);
  }
  
  .project-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
  }
  
  .project-header h1 {
    margin: 0;
    color: var(--text-primary);
    font-size: 1.75rem;
  }
  
  .project-stats {
    display: flex;
    gap: 1.5rem;
  }
  
  .stat-item {
    text-align: center;
  }
  
  .stat-label {
    display: block;
    font-size: 0.7rem;
    color: var(--text-secondary);
    margin-bottom: 0.25rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  
  .stat-value {
    display: block;
    font-size: 1.25rem;
    font-weight: bold;
    color: var(--primary-color);
  }
  
  .project-categories {
    margin-top: 0.75rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  
  .categories-label {
    font-size: 0.85rem;
    color: var(--text-secondary);
    font-weight: 500;
  }
  
  .category-tag {
    background: var(--bg-tertiary);
    color: var(--text-secondary) !important;
    padding: 0.2rem 0.6rem;
    border-radius: 12px;
    font-size: 0.7rem;
    font-weight: 500;
    border: 1px solid var(--border-color);
  }
  
  .memories-list {
    margin: 1rem 0 !important;
  }
  
  .memories-list h3 {
    color: var(--text-primary);
    margin-bottom: 0.75rem;
    font-size: 1.1rem;
  }
  
  .memories-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 1.25rem;
    margin-bottom: 0.75rem;
  }
  
  .memory-card {
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 1.25rem;
    cursor: pointer;
    transition: all 0.2s ease;
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 180px;
  }
  
  .memory-card:hover {
    border-color: var(--border-hover);
    box-shadow: var(--shadow-md);
  }
  
  .memory-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 0.75rem;
  }
  
  .category-badge {
    background: var(--status-item-bg);
    color: var(--text-secondary) !important;
    padding: 0.25rem 0.6rem;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 500;
    border: 1px solid var(--border-color);
  }
  
  .memory-date {
    font-size: 0.7rem;
    color: var(--text-muted);
    text-align: right;
  }
  
  .memory-content {
    flex: 1;
    margin-bottom: 0.75rem;
    padding: 0 0.25rem;
  }
  
  .memory-content p {
    margin: 0;
    color: var(--text-secondary);
    line-height: 1.5;
    font-size: 0.85rem;
    text-align: justify;
    word-break: break-word;
    hyphens: auto;
  }
  
  .memory-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 0.5rem;
    border-top: 1px solid var(--border-color);
  }
  
  .memory-size {
    font-size: 0.7rem;
    color: var(--text-muted);
    font-weight: 500;
  }
  
  .empty-state {
    text-align: center;
    padding: 2rem;
    color: var(--text-muted);
  }
  
  .empty-state p {
    margin: 0;
    font-size: 1rem;
  }
  
  .show-more {
    text-align: center;
    margin-top: 0.75rem;
  }
  
  .show-more-btn {
    background: var(--primary-color);
    color: var(--bg-primary);
    border: none;
    padding: 0.6rem 1.2rem;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.85rem;
  }
  
  .show-more-btn:hover {
    background: var(--primary-hover);
  }
  
  @media (max-width: 768px) {
    .project-detail-page {
      padding: 1rem;
    }
    
    .project-header {
      flex-direction: column;
      align-items: flex-start;
      gap: 1rem;
    }
    
    .project-stats {
      justify-content: space-around;
      width: 100%;
    }
    
    .memories-grid {
      grid-template-columns: 1fr;
    }
  }
`;

document.head.appendChild(style);

export { ProjectDetailPage };