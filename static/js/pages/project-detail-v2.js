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
        <button class="back-btn">
          ← Back to Projects
        </button>
      </div>
      
      <div class="error-message" style="display: none; background: #fee; color: #c00; padding: 1rem; margin: 1rem 0; border-radius: 4px;"></div>
      
      <div class="loading-state" style="display: none; text-align: center; padding: 2rem;">
        <p>Loading project data...</p>
      </div>
      
      <div class="project-content">
        <div class="project-info" style="background: #f9f9f9; padding: 2rem; margin: 1rem 0; border-radius: 8px;"></div>
        <div class="memories-list" style="margin: 2rem 0;"></div>
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
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  }
  
  .back-btn {
    background: #f0f0f0;
    border: 1px solid #ccc;
    padding: 0.5rem 1rem;
    border-radius: 4px;
    cursor: pointer;
    margin-bottom: 1rem;
    font-size: 0.9rem;
  }
  
  .back-btn:hover {
    background: #e0e0e0;
  }
  
  .project-info {
    background: #f9f9f9 !important;
    padding: 1.5rem !important;
    margin: 0.5rem 0 !important;
    border-radius: 8px !important;
  }
  
  .project-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
  }
  
  .project-header h1 {
    margin: 0;
    color: #333;
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
    color: #666;
    margin-bottom: 0.25rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  
  .stat-value {
    display: block;
    font-size: 1.25rem;
    font-weight: bold;
    color: #007acc;
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
    color: #666;
    font-weight: 500;
  }
  
  .category-tag {
    background: #f5f5f5;
    color: #666 !important;
    padding: 0.2rem 0.6rem;
    border-radius: 12px;
    font-size: 0.7rem;
    font-weight: 500;
    text-transform: capitalize;
    border: 1px solid #e0e0e0;
  }
  
  .memories-list {
    margin: 1rem 0 !important;
  }
  
  .memories-list h3 {
    color: #333;
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
    background: white;
    border: 1px solid #e0e0e0;
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
    border-color: #ccc;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  }
  
  .memory-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 0.75rem;
  }
  
  .category-badge {U
    background: #f8f9fa;
    color: #6c757d !important;
    padding: 0.25rem 0.6rem;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 500;
    text-transform: capitalize;
    border: 1px solid #e9ecef;
  }
  
  .memory-date {
    font-size: 0.7rem;
    color: #999;
    text-align: right;
  }
  
  .memory-content {
    flex: 1;
    margin-bottom: 0.75rem;
    padding: 0 0.25rem;
  }
  
  .memory-content p {
    margin: 0;
    color: #555;
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
    border-top: 1px solid #f0f0f0;
  }
  
  .memory-size {
    font-size: 0.7rem;
    color: #999;
    font-weight: 500;
  }
  
  .empty-state {
    text-align: center;
    padding: 2rem;
    color: #999;
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
    background: #007acc;
    color: white;
    border: none;
    padding: 0.6rem 1.2rem;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.85rem;
  }
  
  .show-more-btn:hover {
    background: #005a9e;
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