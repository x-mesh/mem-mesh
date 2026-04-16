/**
 * Dashboard Preview Component
 * Chroma-style dashboard mockup with modern card design
 * Requirements: 4.1, 4.2, 4.3
 */

class DashboardPreview extends HTMLElement {
  constructor() {
    super();
    this.isInteractive = this.hasAttribute('interactive');
    this.mockData = this.generateMockData();
  }

  connectedCallback() {
    this.render();
    if (this.isInteractive) {
      this.setupInteractions();
    }
  }

  /**
   * Generate mock data for dashboard preview
   */
  generateMockData() {
    return {
      stats: {
        totalMemories: 1247,
        totalProjects: 23,
        totalCategories: 7, // git-history 추가로 7개
        avgLeadTime: 2.4
      },
      recentActivity: [
        { 
          type: 'qa-pair', 
          title: 'Q: MCP 서버 타임아웃 문제 해결 방법?', 
          time: '2분 전', 
          category: 'bug',
          isQA: true,
          question: 'MCP 서버 타임아웃 문제 해결 방법?',
          answer: 'stdin 읽기 타임아웃을 해결하고 direct 모드로 변경하여 안정성 향상'
        },
        { 
          type: 'qa-pair', 
          title: 'Q: Q&A 쌍 관리 시스템 구축 방법?', 
          time: '15분 전', 
          category: 'idea',
          isQA: true,
          question: 'Q&A 쌍 관리 시스템 구축 방법?',
          answer: 'JSON 구조로 질문-답변을 연결하고 자동 저장 Hook 구현'
        },
        { type: 'memory', title: '버그 수정: 검색 결과 정렬', time: '1시간 전', category: 'bug' },
        { type: 'memory', title: '새로운 기능 아이디어', time: '3시간 전', category: 'idea' }
      ],
      chartData: {
        categories: {
          task: 45,
          bug: 12,
          idea: 28,
          decision: 15,
          code_snippet: 8,
          incident: 3,
          'git-history': 6
        },
        weeklyActivity: [12, 19, 15, 27, 22, 18, 24]
      }
    };
  }

  /**
   * Setup interactive behaviors
   */
  setupInteractions() {
    this.addEventListener('click', this.handleClick.bind(this));
    
    // Add hover effects for cards
    const cards = this.querySelectorAll('.preview-card, .stat-card, .activity-item');
    cards.forEach(card => {
      card.addEventListener('mouseenter', this.handleCardHover.bind(this));
      card.addEventListener('mouseleave', this.handleCardLeave.bind(this));
    });
  }

  /**
   * Handle click events
   */
  handleClick(event) {
    const target = event.target.closest('[data-action]');
    if (!target) return;

    const action = target.getAttribute('data-action');
    
    switch (action) {
      case 'view-dashboard':
        this.navigateTo('/dashboard');
        break;
      case 'view-memories':
        this.navigateTo('/search');
        break;
      case 'view-projects':
        this.navigateTo('/projects');
        break;
      case 'view-analytics':
        this.navigateTo('/analytics');
        break;
    }
  }

  /**
   * Handle card hover
   */
  handleCardHover(event) {
    const card = event.currentTarget;
    card.style.transform = 'translateY(-4px)';
    card.style.boxShadow = '0 8px 25px rgba(0, 0, 0, 0.15)';
  }

  /**
   * Handle card leave
   */
  handleCardLeave(event) {
    const card = event.currentTarget;
    card.style.transform = '';
    card.style.boxShadow = '';
  }

  /**
   * Navigate to route
   */
  navigateTo(route) {
    if (window.app && window.app.router) {
      window.app.router.navigate(route);
    } else {
      // Fallback for preview mode
      console.log(`Navigate to: ${route}`);
    }
  }

  /**
   * Create statistics cards
   */
  createStatsCards() {
    const { stats } = this.mockData;
    
    return `
      <div class="stats-grid">
        <div class="stat-card" data-action="view-memories">
          <div class="stat-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M9 12L11 14L15 10M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" stroke-width="2"/>
            </svg>
          </div>
          <div class="stat-content">
            <div class="stat-number">${stats.totalMemories.toLocaleString()}</div>
            <div class="stat-label">Total Memories</div>
            <div class="stat-trend">+12% this month</div>
          </div>
        </div>

        <div class="stat-card" data-action="view-projects">
          <div class="stat-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M22 19C22 19.5304 21.7893 20.0391 21.4142 20.4142C21.0391 20.7893 20.5304 21 20 21H4C3.46957 21 2.96086 20.7893 2.58579 20.4142C2.21071 20.0391 2 19.5304 2 19V5C2 4.46957 2.21071 3.96086 2.58579 3.58579C2.96086 3.21071 3.46957 3 4 3H9L11 6H20C20.5304 6 21.0391 6.21071 21.4142 6.58579C21.7893 6.96086 22 7.46957 22 8V19Z" stroke="currentColor" stroke-width="2"/>
            </svg>
          </div>
          <div class="stat-content">
            <div class="stat-number">${stats.totalProjects}</div>
            <div class="stat-label">Active Projects</div>
            <div class="stat-trend">+3 new projects</div>
          </div>
        </div>

        <div class="stat-card" data-action="view-analytics">
          <div class="stat-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M20.59 13.41L13.42 20.58C13.2343 20.766 13.0137 20.9135 12.7709 21.0141C12.5281 21.1148 12.2678 21.1666 12.005 21.1666C11.7422 21.1666 11.4819 21.1148 11.2391 21.0141C10.9963 20.9135 10.7757 20.766 10.59 20.58L2 12V2H12L20.59 10.59C20.9625 10.9647 21.1716 11.4716 21.1716 12C21.1716 12.5284 20.9625 13.0353 20.59 13.41V13.41Z" stroke="currentColor" stroke-width="2"/>
              <circle cx="7" cy="7" r="1" fill="currentColor"/>
            </svg>
          </div>
          <div class="stat-content">
            <div class="stat-number">${stats.totalCategories}</div>
            <div class="stat-label">Categories</div>
            <div class="stat-trend">Well organized</div>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/>
              <path d="M12 6V12L16 14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <div class="stat-content">
            <div class="stat-number">${stats.avgLeadTime}d</div>
            <div class="stat-label">Avg Lead Time</div>
            <div class="stat-trend">-0.3d improved</div>
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Create mini chart visualization
   */
  createMiniChart() {
    const { chartData } = this.mockData;
    const categories = chartData.categories;
    const total = Object.values(categories).reduce((sum, count) => sum + count, 0);
    
    // Create simple bar chart
    const maxValue = Math.max(...Object.values(categories));
    
    return `
      <div class="mini-chart">
        <div class="chart-header">
          <h4>Memory Distribution</h4>
          <span class="chart-total">${total} total</span>
        </div>
        <div class="chart-bars">
          ${Object.entries(categories).map(([category, count]) => {
            const percentage = (count / maxValue) * 100;
            const categoryColor = this.getCategoryColor(category);
            
            return `
              <div class="chart-bar-item">
                <div class="chart-bar-label">
                  <span class="category-dot" style="background: ${categoryColor}"></span>
                  <span class="category-name">${category}</span>
                  <span class="category-count">${count}</span>
                </div>
                <div class="chart-bar-track">
                  <div class="chart-bar-fill" style="width: ${percentage}%; background: ${categoryColor}"></div>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
  }

  /**
   * Create activity timeline
   */
  createActivityTimeline() {
    const { recentActivity } = this.mockData;
    
    return `
      <div class="activity-timeline">
        <div class="timeline-header">
          <h4>Recent Activity</h4>
          <button class="view-all-btn" data-action="view-memories">View All</button>
        </div>
        <div class="timeline-items">
          ${recentActivity.map(activity => {
            if (activity.isQA) {
              return `
                <div class="activity-item qa-activity">
                  <div class="activity-icon qa-icon">
                    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                  </div>
                  <div class="activity-content">
                    <div class="activity-title qa-title">${activity.question}</div>
                    <div class="qa-answer-preview">${activity.answer}</div>
                    <div class="activity-meta">
                      <span class="activity-type qa-badge">Q&A</span>
                      <span class="activity-category">${activity.category}</span>
                      <span class="activity-time">${activity.time}</span>
                    </div>
                  </div>
                </div>
              `;
            } else {
              return `
                <div class="activity-item">
                  <div class="activity-icon">
                    ${this.getCategoryIcon(activity.category)}
                  </div>
                  <div class="activity-content">
                    <div class="activity-title">${activity.title}</div>
                    <div class="activity-meta">
                      <span class="activity-type">${activity.type}</span>
                      <span class="activity-category">${activity.category}</span>
                      <span class="activity-time">${activity.time}</span>
                    </div>
                  </div>
                </div>
              `;
            }
          }).join('')}
        </div>
      </div>
    `;
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
   * Get category icon
   */
  getCategoryIcon(category) {
    const icons = {
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
      code_snippet: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M16 18L22 12L16 6M8 6L2 12L8 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>`,
      incident: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M12 9V13M12 17H12.01M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" stroke-width="2"/>
                </svg>`,
      'git-history': `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                       <path d="M9 12L11 14L15 10M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" stroke-width="2"/>
                       <path d="M8 12L10 14L16 8" stroke="currentColor" stroke-width="1"/>
                     </svg>`
    };
    return icons[category] || icons.task;
  }

  /**
   * Render the component
   */
  render() {
    this.className = 'dashboard-preview';
    
    this.innerHTML = `
      <div class="preview-container">
        <div class="preview-header">
          <div class="preview-title">
            <h3>Dashboard Overview</h3>
            <p>Get insights into your memory collection and activity</p>
          </div>
          ${this.isInteractive ? `
            <button class="preview-cta" data-action="view-dashboard">
              <span>Open Dashboard</span>
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M5 12H19M19 12L12 5M19 12L12 19" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </button>
          ` : ''}
        </div>

        <div class="preview-content">
          <!-- Statistics Cards -->
          <section class="preview-section">
            ${this.createStatsCards()}
          </section>

          <!-- Charts and Activity -->
          <section class="preview-section preview-grid">
            <div class="preview-card chart-card">
              ${this.createMiniChart()}
            </div>
            
            <div class="preview-card activity-card">
              ${this.createActivityTimeline()}
            </div>
          </section>

          <!-- Quick Actions -->
          ${this.isInteractive ? `
            <section class="preview-section">
              <div class="quick-actions">
                <h4>Quick Actions</h4>
                <div class="action-buttons">
                  <button class="action-btn" data-action="view-memories">
                    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="2"/>
                      <path d="M21 21L16.65 16.65" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    <span>Search Memories</span>
                  </button>
                  <button class="action-btn" data-action="view-projects">
                    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M22 19C22 19.5304 21.7893 20.0391 21.4142 20.4142C21.0391 20.7893 20.5304 21 20 21H4C3.46957 21 2.96086 20.7893 2.58579 20.4142C2.21071 20.0391 2 19.5304 2 19V5C2 4.46957 2.21071 3.96086 2.58579 3.58579C2.96086 3.21071 3.46957 3 4 3H9L11 6H20C20.5304 6 21.0391 6.21071 21.4142 6.58579C21.7893 6.96086 22 7.46957 22 8V19Z" stroke="currentColor" stroke-width="2"/>
                    </svg>
                    <span>Browse Projects</span>
                  </button>
                  <button class="action-btn" data-action="view-analytics">
                    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M3 3V21H21V3H3Z" stroke="currentColor" stroke-width="2"/>
                      <path d="M7 12L12 7L17 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    <span>View Analytics</span>
                  </button>
                </div>
              </div>
            </section>
          ` : ''}
        </div>
      </div>
    `;
  }
}

// Define the custom element
customElements.define('dashboard-preview', DashboardPreview);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  /* Dashboard Preview Component Styles */
  .dashboard-preview {
    width: 100%;
    max-width: 1200px;
    margin: 0 auto;
  }

  .preview-container {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    overflow: hidden;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
  }

  [data-theme="dark"] .preview-container {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  }

  .preview-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-6);
    border-bottom: 1px solid var(--border-color);
    background: linear-gradient(135deg, var(--bg-primary) 0%, var(--bg-secondary) 100%);
  }

  .preview-title h3 {
    font-size: var(--text-xl);
    font-weight: var(--font-semibold);
    color: var(--text-primary);
    margin: 0 0 var(--space-1) 0;
  }

  .preview-title p {
    font-size: var(--text-sm);
    color: var(--text-secondary);
    margin: 0;
  }

  .preview-cta {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    background: var(--text-primary);
    color: var(--bg-primary);
    border: none;
    border-radius: var(--radius-md);
    font-size: var(--text-sm);
    font-weight: var(--font-medium);
    cursor: pointer;
    transition: all 200ms ease;
  }

  .preview-cta:hover {
    background: var(--text-secondary);
    transform: translateX(2px);
  }

  .preview-cta svg {
    width: 16px;
    height: 16px;
    transition: transform 200ms ease;
  }

  .preview-cta:hover svg {
    transform: translateX(2px);
  }

  .preview-content {
    padding: var(--space-6);
  }

  .preview-section {
    margin-bottom: var(--space-8);
  }

  .preview-section:last-child {
    margin-bottom: 0;
  }

  .preview-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-6);
  }

  .preview-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    padding: var(--space-4);
    transition: all 200ms ease;
  }

  .preview-card:hover {
    border-color: var(--border-hover);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  }

  [data-theme="dark"] .preview-card:hover {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  }

  /* Statistics Grid */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: var(--space-4);
  }

  .stat-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    padding: var(--space-4);
    display: flex;
    align-items: center;
    gap: var(--space-3);
    cursor: pointer;
    transition: all 200ms ease;
  }

  .stat-card:hover {
    border-color: var(--border-hover);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  }

  [data-theme="dark"] .stat-card:hover {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  }

  .stat-icon {
    width: 48px;
    height: 48px;
    background: var(--bg-primary);
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-secondary);
    flex-shrink: 0;
  }

  .stat-icon svg {
    width: 24px;
    height: 24px;
  }

  .stat-content {
    flex: 1;
  }

  .stat-number {
    font-size: var(--text-2xl);
    font-weight: var(--font-semibold);
    color: var(--text-primary);
    line-height: 1;
    margin-bottom: var(--space-1);
  }

  .stat-label {
    font-size: var(--text-sm);
    color: var(--text-secondary);
    font-weight: var(--font-medium);
    margin-bottom: var(--space-1);
  }

  .stat-trend {
    font-size: var(--text-xs);
    color: var(--success);
    font-weight: var(--font-medium);
  }

  /* Mini Chart */
  .mini-chart {
    height: 100%;
  }

  .chart-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--space-4);
  }

  .chart-header h4 {
    font-size: var(--text-base);
    font-weight: var(--font-semibold);
    color: var(--text-primary);
    margin: 0;
  }

  .chart-total {
    font-size: var(--text-xs);
    color: var(--text-muted);
    font-weight: var(--font-medium);
  }

  .chart-bars {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .chart-bar-item {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .chart-bar-label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-xs);
  }

  .category-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .category-name {
    flex: 1;
    color: var(--text-primary);
    font-weight: var(--font-medium);
  }

  .category-count {
    color: var(--text-muted);
    font-weight: var(--font-medium);
  }

  .chart-bar-track {
    height: 6px;
    background: var(--bg-primary);
    border-radius: 3px;
    overflow: hidden;
  }

  .chart-bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 300ms ease;
  }

  /* Activity Timeline */
  .activity-timeline {
    height: 100%;
  }

  .timeline-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--space-4);
  }

  .timeline-header h4 {
    font-size: var(--text-base);
    font-weight: var(--font-semibold);
    color: var(--text-primary);
    margin: 0;
  }

  .view-all-btn {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    background: none;
    border: none;
    cursor: pointer;
    font-weight: var(--font-medium);
    transition: color 150ms ease;
  }

  .view-all-btn:hover {
    color: var(--text-primary);
  }

  .timeline-items {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .activity-item {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    padding: var(--space-2);
    border-radius: var(--radius-md);
    transition: background 150ms ease;
  }

  .activity-item:hover {
    background: var(--bg-primary);
  }

  .activity-icon {
    width: 32px;
    height: 32px;
    background: var(--bg-primary);
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-secondary);
    flex-shrink: 0;
  }

  .activity-icon svg {
    width: 16px;
    height: 16px;
  }

  .activity-content {
    flex: 1;
    min-width: 0;
  }

  .activity-title {
    font-size: var(--text-sm);
    font-weight: var(--font-medium);
    color: var(--text-primary);
    margin-bottom: var(--space-1);
    line-height: 1.4;
  }

  .activity-meta {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-xs);
    color: var(--text-muted);
  }

  .activity-type {
    font-weight: var(--font-medium);
  }

  .activity-time {
    opacity: 0.8;
  }

  /* Q&A Activity Styles */
  .activity-item.qa-activity {
    border-left: 3px solid var(--primary-color);
    padding-left: var(--space-3);
  }

  .activity-icon.qa-icon {
    background: linear-gradient(135deg, var(--primary-color), var(--primary-hover));
    color: white;
  }

  .activity-title.qa-title {
    font-weight: var(--font-semibold);
    color: var(--primary-color);
  }

  .qa-answer-preview {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    margin: var(--space-1) 0;
    line-height: 1.4;
    font-style: italic;
  }

  .qa-badge {
    background: var(--primary-color);
    color: white;
    padding: 0.125rem 0.375rem;
    border-radius: var(--radius-sm);
    font-size: var(--text-xs);
    font-weight: var(--font-medium);
  }

  .activity-category {
    font-weight: var(--font-medium);
    color: var(--text-muted);
  }

  /* Quick Actions */
  .quick-actions h4 {
    font-size: var(--text-base);
    font-weight: var(--font-semibold);
    color: var(--text-primary);
    margin: 0 0 var(--space-4) 0;
  }

  .action-buttons {
    display: flex;
    gap: var(--space-3);
    flex-wrap: wrap;
  }

  .action-btn {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    font-size: var(--text-sm);
    font-weight: var(--font-medium);
    color: var(--text-primary);
    cursor: pointer;
    transition: all 150ms ease;
    flex: 1;
    min-width: 140px;
    justify-content: center;
  }

  .action-btn:hover {
    background: var(--bg-tertiary);
    border-color: var(--border-hover);
    transform: translateY(-1px);
  }

  .action-btn svg {
    width: 16px;
    height: 16px;
  }

  /* Responsive Design */
  @media (max-width: 1024px) {
    .preview-grid {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 768px) {
    .preview-header {
      flex-direction: column;
      gap: var(--space-4);
      align-items: flex-start;
    }

    .preview-content {
      padding: var(--space-4);
    }

    .stats-grid {
      grid-template-columns: 1fr;
      gap: var(--space-3);
    }

    .stat-card {
      padding: var(--space-3);
    }

    .stat-number {
      font-size: var(--text-xl);
    }

    .action-buttons {
      flex-direction: column;
    }

    .action-btn {
      min-width: auto;
    }
  }

  @media (max-width: 480px) {
    .preview-header {
      padding: var(--space-4);
    }

    .preview-content {
      padding: var(--space-3);
    }

    .preview-section {
      margin-bottom: var(--space-6);
    }

    .stat-icon {
      width: 40px;
      height: 40px;
    }

    .stat-icon svg {
      width: 20px;
      height: 20px;
    }

    .stat-number {
      font-size: var(--text-lg);
    }
  }
`;

document.head.appendChild(style);

export { DashboardPreview };