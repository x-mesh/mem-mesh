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
          <div class="stat-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M3 3V21H21V3H3Z" stroke="currentColor" stroke-width="2"/>
              <path d="M7 12L12 7L17 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <div class="stat-content">
            <div class="stat-number">${totalMemories.toLocaleString()}</div>
            <div class="stat-label">Total Memories</div>
          </div>
        </div>
        
        <div class="stat-card" data-type="project">
          <div class="stat-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M22 19C22 19.5304 21.7893 20.0391 21.4142 20.4142C21.0391 20.7893 20.5304 21 20 21H4C3.46957 21 2.96086 20.7893 2.58579 20.4142C2.21071 20.0391 2 19.5304 2 19V5C2 4.46957 2.21071 3.96086 2.58579 3.58579C2.96086 3.21071 3.46957 3 4 3H9L11 6H20C20.5304 6 21.0391 6.21071 21.4142 6.58579C21.7893 6.96086 22 7.46957 22 8V19Z" stroke="currentColor" stroke-width="2"/>
            </svg>
          </div>
          <div class="stat-content">
            <div class="stat-number">${totalProjects}</div>
            <div class="stat-label">Projects</div>
          </div>
        </div>
        
        <div class="stat-card" data-type="category">
          <div class="stat-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M20.59 13.41L13.42 20.58C13.2343 20.766 13.0137 20.9135 12.7709 21.0141C12.5281 21.1148 12.2678 21.1666 12.005 21.1666C11.7422 21.1666 11.4819 21.1148 11.2391 21.0141C10.9963 20.9135 10.7757 20.766 10.59 20.58L2 12V2H12L20.59 10.59C20.9625 10.9647 21.1716 11.4716 21.1716 12C21.1716 12.5284 20.9625 13.0353 20.59 13.41V13.41Z" stroke="currentColor" stroke-width="2"/>
              <circle cx="7" cy="7" r="1" fill="currentColor"/>
            </svg>
          </div>
          <div class="stat-content">
            <div class="stat-number">${totalCategories}</div>
            <div class="stat-label">Categories</div>
          </div>
        </div>
        
        <div class="stat-card" data-type="leadtime">
          <div class="stat-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/>
              <path d="M12 6V12L16 14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
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
          <svg class="refresh-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M1 4V10H7M23 20V14H17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M20.49 9C19.9828 7.56678 19.1209 6.28392 17.9845 5.27493C16.8482 4.26595 15.4745 3.56905 13.9917 3.24575C12.5089 2.92246 10.9652 2.98546 9.51691 3.42597C8.06861 3.86648 6.76302 4.66921 5.64 5.76L1 10M23 14L18.36 18.24C17.237 19.3308 15.9314 20.1335 14.4831 20.574C13.0348 21.0145 11.4911 21.0775 10.0083 20.7542C8.52547 20.431 7.1518 19.7341 6.01547 18.7251C4.87913 17.7161 4.01717 16.4332 3.51 15" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
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