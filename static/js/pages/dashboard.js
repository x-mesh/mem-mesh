/**
 * Dashboard Page Component
 * Main dashboard showing statistics and recent memories
 */

class DashboardPage extends HTMLElement {
  constructor() {
    super();
    this.stats = null;
    this.recentMemories = [];
    this.isLoading = true;
    this.isInitialized = false; // 중복 초기화 방지
  }
  
  connectedCallback() {
    if (this.isInitialized) {
      console.log('Dashboard already initialized, skipping...');
      return;
    }
    
    this.isInitialized = true;
    this.setupEventListeners();
    this.render();
    
    // 앱이 완전히 초기화될 때까지 기다린 후 데이터 로드
    this.waitForAppAndLoadData();
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
  
  disconnectedCallback() {
    this.removeEventListeners();
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    this.addEventListener('click', this.handleClick.bind(this));
    
    // Listen for memory selection events
    this.addEventListener('memory-select', this.handleMemorySelect.bind(this));
    
    // Listen for refresh events
    window.addEventListener('data-refresh', this.loadData.bind(this));
  }
  
  /**
   * Remove event listeners
   */
  removeEventListeners() {
    window.removeEventListener('data-refresh', this.loadData);
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
          window.app.router.navigate('/search');
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
          // Navigate to search with category filter
          window.app.router.navigate('/search?category=all');
          break;
        case 'project':
          window.app.router.navigate('/projects');
          break;
        default:
          window.app.router.navigate('/search');
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
   * Create statistics cards
   */
  createStatsCards() {
    if (!this.stats) {
      return '<div class="loading-placeholder">Loading statistics...</div>';
    }
    
    const totalMemories = this.stats.total_memories || 0;
    const totalProjects = this.stats.unique_projects || 0;
    const totalCategories = Object.keys(this.stats.categories_breakdown || {}).length;
    const avgLeadTime = this.stats.average_lead_time || 0;
    
    return `
      <div class="stats-grid">
        <div class="stat-card" data-type="total">
          <div class="stat-icon">📊</div>
          <div class="stat-content">
            <div class="stat-number">${totalMemories.toLocaleString()}</div>
            <div class="stat-label">Total Memories</div>
          </div>
        </div>
        
        <div class="stat-card" data-type="project">
          <div class="stat-icon">📁</div>
          <div class="stat-content">
            <div class="stat-number">${totalProjects}</div>
            <div class="stat-label">Projects</div>
          </div>
        </div>
        
        <div class="stat-card" data-type="category">
          <div class="stat-icon">🏷️</div>
          <div class="stat-content">
            <div class="stat-number">${totalCategories}</div>
            <div class="stat-label">Categories</div>
          </div>
        </div>
        
        <div class="stat-card" data-type="leadtime">
          <div class="stat-icon">⏱️</div>
          <div class="stat-content">
            <div class="stat-number">${avgLeadTime.toFixed(1)}d</div>
            <div class="stat-label">Avg Lead Time</div>
          </div>
        </div>
      </div>
    `;
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
    
    const categoryColors = {
      task: '#2563eb',
      bug: '#ef4444',
      idea: '#f59e0b',
      decision: '#8b5cf6',
      incident: '#ef4444',
      code_snippet: '#10b981'
    };
    
    const categoryIcons = {
      task: '📋',
      bug: '🐛',
      idea: '💡',
      decision: '⚖️',
      incident: '🚨',
      code_snippet: '💻'
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
      const icon = categoryIcons[category] || '📝';
      
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
    
    return `
      <div class="recent-memories-list">
        ${this.recentMemories.slice(0, 5).map(memory => `
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
   * Escape HTML
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'dashboard-page';
    
    this.innerHTML = `
      <div class="dashboard-header">
        <div class="header-content">
          <h1>Dashboard</h1>
          <p class="header-subtitle">Overview of your memory collection</p>
        </div>
        <button class="refresh-btn" title="Refresh data">
          <span class="refresh-icon">🔄</span>
          Refresh
        </button>
      </div>
      
      <div class="dashboard-content">
        <!-- Statistics Section -->
        <section class="dashboard-section">
          <div class="section-header">
            <h2>Statistics</h2>
          </div>
          ${this.createStatsCards()}
        </section>
        
        <!-- Charts Section -->
        <section class="dashboard-section">
          <div class="section-header">
            <h2>Category Distribution</h2>
          </div>
          ${this.createCategoryChart()}
        </section>
        
        <!-- Recent Memories Section -->
        <section class="dashboard-section">
          <div class="section-header">
            <h2>Recent Memories</h2>
            <button class="view-all-btn" data-section="memories">View All</button>
          </div>
          ${this.createRecentMemories()}
        </section>
        
        <!-- Projects Overview Section -->
        <section class="dashboard-section">
          <div class="section-header">
            <h2>Top Projects</h2>
            <button class="view-all-btn" data-section="projects">View All</button>
          </div>
          ${this.createProjectOverview()}
        </section>
      </div>
    `;
    
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
}

// Define the custom element
customElements.define('dashboard-page', DashboardPage);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .dashboard-page {
    padding: 2rem;
    max-width: 1200px;
    margin: 0 auto;
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
    font-size: 1rem;
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
    font-size: 2rem;
    opacity: 0.8;
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
    font-size: 1rem;
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
  
  /* Responsive Design */
  @media (max-width: 768px) {
    .dashboard-page {
      padding: 1rem;
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