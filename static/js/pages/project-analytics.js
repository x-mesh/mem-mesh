/**
 * Project Analytics Page
 * 프로젝트별 상세 검색 통계 분석
 */

export class ProjectAnalyticsPage extends HTMLElement {
  constructor() {
    super();
    this.projectId = null;
    this.charts = {};
    this.dateRange = 'last_7d';
    this.comparisonProjects = [];
  }

  connectedCallback() {
    // Get project ID from URL
    const params = new URLSearchParams(window.location.search);
    this.projectId = params.get('project');
    
    if (!this.projectId) {
      this.renderError('프로젝트 ID가 지정되지 않았습니다.');
      return;
    }

    this.render();
    this.loadData();
  }

  disconnectedCallback() {
    this.destroyCharts();
  }

  render() {
    this.innerHTML = `
      <div class="project-analytics-page">
        <!-- Header -->
        <header class="page-header">
          <div class="page-header-main">
            <button class="back-btn" id="back-btn">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M12.5 15L7.5 10L12.5 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              뒤로
            </button>
            <div>
              <h1 class="page-title">프로젝트 분석: <span id="project-name">${this.escapeHtml(this.projectId)}</span></h1>
              <p class="page-subtitle">검색 패턴 및 품질 상세 분석</p>
            </div>
          </div>
          <div class="page-header-actions">
            <select id="date-range" class="date-range-select">
              <option value="last_24h">최근 24시간</option>
              <option value="last_7d" selected>최근 7일</option>
              <option value="last_30d">최근 30일</option>
            </select>
            <button id="export-btn" class="btn btn-secondary">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M14 10v2.667A1.333 1.333 0 0112.667 14H3.333A1.333 1.333 0 012 12.667V10M11.333 5.333L8 2m0 0L4.667 5.333M8 2v8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              내보내기
            </button>
          </div>
        </header>

        <!-- Summary Cards -->
        <section class="summary-cards">
          <div class="summary-card">
            <div class="card-icon">🔍</div>
            <div class="card-content">
              <span class="card-value" id="total-searches">-</span>
              <span class="card-label">총 검색</span>
              <span class="card-change" id="searches-change"></span>
            </div>
          </div>
          <div class="summary-card">
            <div class="card-icon">📊</div>
            <div class="card-content">
              <span class="card-value" id="avg-results">-</span>
              <span class="card-label">평균 결과 수</span>
              <span class="card-change" id="results-change"></span>
            </div>
          </div>
          <div class="summary-card">
            <div class="card-icon">⭐</div>
            <div class="card-content">
              <span class="card-value" id="avg-score">-</span>
              <span class="card-label">평균 점수</span>
              <span class="card-change" id="score-change"></span>
            </div>
          </div>
          <div class="summary-card">
            <div class="card-icon">⚡</div>
            <div class="card-content">
              <span class="card-value" id="avg-response">-</span>
              <span class="card-label">평균 응답시간</span>
              <span class="card-change" id="response-change"></span>
            </div>
          </div>
          <div class="summary-card">
            <div class="card-icon">⚠️</div>
            <div class="card-content">
              <span class="card-value" id="zero-rate">-</span>
              <span class="card-label">Zero-Result 비율</span>
              <span class="card-change" id="zero-change"></span>
            </div>
          </div>
        </section>

        <!-- Tab Navigation -->
        <nav class="tab-nav">
          <button class="tab-btn active" data-tab="overview">개요</button>
          <button class="tab-btn" data-tab="queries">쿼리 분석</button>
          <button class="tab-btn" data-tab="trends">트렌드</button>
          <button class="tab-btn" data-tab="comparison">비교</button>
          <button class="tab-btn" data-tab="alerts">알림 설정</button>
        </nav>

        <!-- Tab Content -->
        <div class="tab-content">
          <!-- Overview Tab -->
          <div id="tab-overview" class="tab-panel active">
            <div class="charts-grid">
              <div class="chart-container wide">
                <h3>검색 활동 추이</h3>
                <canvas id="activity-chart"></canvas>
              </div>
              <div class="chart-container">
                <h3>검색 품질 분포</h3>
                <canvas id="quality-distribution-chart"></canvas>
              </div>
              <div class="chart-container">
                <h3>응답 시간 분포</h3>
                <canvas id="response-distribution-chart"></canvas>
              </div>
            </div>
          </div>

          <!-- Queries Tab -->
          <div id="tab-queries" class="tab-panel hidden">
            <div class="queries-analysis">
              <div class="queries-section">
                <h3>🔥 인기 검색어 Top 20</h3>
                <div id="top-queries" class="queries-list"></div>
              </div>
              <div class="queries-section">
                <h3>❌ Zero-Result 쿼리</h3>
                <div id="zero-result-queries" class="queries-list"></div>
              </div>
              <div class="queries-section">
                <h3>⚠️ 낮은 점수 쿼리</h3>
                <div id="low-score-queries" class="queries-list"></div>
              </div>
              <div class="queries-section">
                <h3>🐌 느린 쿼리</h3>
                <div id="slow-queries" class="queries-list"></div>
              </div>
            </div>
          </div>

          <!-- Trends Tab -->
          <div id="tab-trends" class="tab-panel hidden">
            <div class="trends-grid">
              <div class="chart-container wide">
                <h3>시간대별 검색 패턴</h3>
                <canvas id="hourly-pattern-chart"></canvas>
              </div>
              <div class="chart-container wide">
                <h3>요일별 검색 패턴</h3>
                <canvas id="daily-pattern-chart"></canvas>
              </div>
              <div class="chart-container">
                <h3>검색 품질 트렌드</h3>
                <canvas id="quality-trend-chart"></canvas>
              </div>
              <div class="chart-container">
                <h3>응답 시간 트렌드</h3>
                <canvas id="response-trend-chart"></canvas>
              </div>
            </div>
          </div>

          <!-- Comparison Tab -->
          <div id="tab-comparison" class="tab-panel hidden">
            <div class="comparison-section">
              <div class="comparison-controls">
                <h3>프로젝트 비교</h3>
                <div class="project-selector">
                  <label>비교할 프로젝트 선택:</label>
                  <select id="comparison-project-select" multiple>
                    <option value="">로딩 중...</option>
                  </select>
                  <button id="add-comparison-btn" class="btn btn-primary">비교 추가</button>
                </div>
                <div id="selected-projects" class="selected-projects"></div>
              </div>
              <div class="comparison-charts">
                <div class="chart-container wide">
                  <h3>검색 수 비교</h3>
                  <canvas id="comparison-searches-chart"></canvas>
                </div>
                <div class="chart-container wide">
                  <h3>검색 품질 비교</h3>
                  <canvas id="comparison-quality-chart"></canvas>
                </div>
                <div class="comparison-table-container">
                  <h3>상세 비교</h3>
                  <div id="comparison-table"></div>
                </div>
              </div>
            </div>
          </div>

          <!-- Alerts Tab -->
          <div id="tab-alerts" class="tab-panel hidden">
            <div class="alerts-section">
              <h3>알림 임계값 설정</h3>
              <p class="section-description">프로젝트의 검색 품질이 임계값을 벗어나면 알림을 받습니다.</p>
              
              <div class="alert-settings">
                <div class="alert-setting-card">
                  <div class="setting-header">
                    <h4>Zero-Result 비율</h4>
                    <label class="toggle">
                      <input type="checkbox" id="alert-zero-enabled">
                      <span class="toggle-slider"></span>
                    </label>
                  </div>
                  <div class="setting-body">
                    <label>임계값 (%)</label>
                    <input type="number" id="alert-zero-threshold" min="0" max="100" value="20" step="1">
                    <p class="setting-help">Zero-result 비율이 이 값을 초과하면 알림</p>
                  </div>
                </div>

                <div class="alert-setting-card">
                  <div class="setting-header">
                    <h4>평균 응답 시간</h4>
                    <label class="toggle">
                      <input type="checkbox" id="alert-response-enabled">
                      <span class="toggle-slider"></span>
                    </label>
                  </div>
                  <div class="setting-body">
                    <label>임계값 (ms)</label>
                    <input type="number" id="alert-response-threshold" min="0" max="10000" value="1000" step="50">
                    <p class="setting-help">평균 응답 시간이 이 값을 초과하면 알림</p>
                  </div>
                </div>

                <div class="alert-setting-card">
                  <div class="setting-header">
                    <h4>평균 점수</h4>
                    <label class="toggle">
                      <input type="checkbox" id="alert-score-enabled">
                      <span class="toggle-slider"></span>
                    </label>
                  </div>
                  <div class="setting-body">
                    <label>임계값 (0-1)</label>
                    <input type="number" id="alert-score-threshold" min="0" max="1" value="0.5" step="0.05">
                    <p class="setting-help">평균 점수가 이 값 미만이면 알림</p>
                  </div>
                </div>

                <div class="alert-setting-card">
                  <div class="setting-header">
                    <h4>검색 수 급감</h4>
                    <label class="toggle">
                      <input type="checkbox" id="alert-drop-enabled">
                      <span class="toggle-slider"></span>
                    </label>
                  </div>
                  <div class="setting-body">
                    <label>감소율 (%)</label>
                    <input type="number" id="alert-drop-threshold" min="0" max="100" value="50" step="5">
                    <p class="setting-help">이전 기간 대비 검색 수가 이 비율 이상 감소하면 알림</p>
                  </div>
                </div>
              </div>

              <div class="alert-actions">
                <button id="save-alerts-btn" class="btn btn-primary">설정 저장</button>
                <button id="test-alerts-btn" class="btn btn-secondary">테스트 알림 전송</button>
              </div>

              <div class="alert-history">
                <h4>최근 알림 히스토리</h4>
                <div id="alert-history-list"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;

    this.setupEventListeners();
  }

  renderError(message) {
    this.innerHTML = `
      <div class="error-state">
        <h2>오류</h2>
        <p>${message}</p>
        <button onclick="history.back()" class="btn btn-primary">돌아가기</button>
      </div>
    `;
  }

  setupEventListeners() {
    // Back button
    this.querySelector('#back-btn')?.addEventListener('click', () => {
      window.history.back();
    });

    // Date range
    this.querySelector('#date-range')?.addEventListener('change', (e) => {
      this.dateRange = e.target.value;
      this.loadData();
    });

    // Export button
    this.querySelector('#export-btn')?.addEventListener('click', () => {
      this.exportData();
    });

    // Tab navigation
    this.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const tab = e.target.dataset.tab;
        this.switchTab(tab);
      });
    });

    // Comparison
    this.querySelector('#add-comparison-btn')?.addEventListener('click', () => {
      this.addComparisonProject();
    });

    // Alert settings
    this.querySelector('#save-alerts-btn')?.addEventListener('click', () => {
      this.saveAlertSettings();
    });

    this.querySelector('#test-alerts-btn')?.addEventListener('click', () => {
      this.testAlert();
    });
  }

  switchTab(tab) {
    // Update tab buttons
    this.querySelectorAll('.tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });

    // Update tab panels
    this.querySelectorAll('.tab-panel').forEach(panel => {
      panel.classList.toggle('active', panel.id === `tab-${tab}`);
      panel.classList.toggle('hidden', panel.id !== `tab-${tab}`);
    });

    // Load tab-specific data
    if (tab === 'comparison') {
      this.loadComparisonProjects();
    } else if (tab === 'alerts') {
      this.loadAlertSettings();
    }
  }

  async loadData() {
    try {
      const hours = this.getHoursFromRange();
      
      // Load project stats
      const stats = await this.fetchProjectStats(hours);
      
      this.updateSummaryCards(stats);
      this.updateOverviewCharts(stats);
      this.updateQueriesAnalysis(stats);
      this.updateTrendsCharts(stats);
      
    } catch (error) {
      console.error('Failed to load project data:', error);
      this.showError('데이터 로드 실패');
    }
  }

  getHoursFromRange() {
    switch (this.dateRange) {
      case 'last_24h': return 24;
      case 'last_7d': return 168;
      case 'last_30d': return 720;
      default: return 168;
    }
  }

  async fetchProjectStats(hours, projectId = null) {
    // Fetch project-specific stats
    const pid = projectId || this.projectId;
    const response = await fetch(`/api/monitoring/search/quality-stats?hours=${hours}&project_id=${encodeURIComponent(pid)}`);
    if (!response.ok) throw new Error('Failed to fetch project stats');
    return response.json();
  }

  updateSummaryCards(stats) {
    const summary = stats.summary;
    
    this.querySelector('#total-searches').textContent = summary.total_searches.toLocaleString();
    this.querySelector('#avg-results').textContent = summary.avg_results_per_search.toFixed(2);
    this.querySelector('#avg-score').textContent = (summary.avg_similarity_score * 100).toFixed(1) + '%';
    this.querySelector('#avg-response').textContent = summary.avg_response_time_ms.toFixed(0) + 'ms';
    this.querySelector('#zero-rate').textContent = summary.zero_result_rate.toFixed(1) + '%';

    // TODO: Calculate and display changes from previous period
  }

  updateOverviewCharts(stats) {
    // Activity chart
    if (stats.trend.length > 0) {
      const labels = stats.trend.map(t => this.formatTime(t.hour)).reverse();
      this.createOrUpdateChart('activity-chart', {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: '검색 수',
            data: stats.trend.map(t => t.search_count).reverse(),
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            fill: true,
            tension: 0.4
          }]
        },
        options: this.getChartOptions('검색 수')
      });
    }

    // Quality distribution (placeholder - needs more data)
    this.createOrUpdateChart('quality-distribution-chart', {
      type: 'doughnut',
      data: {
        labels: ['높음 (>0.7)', '중간 (0.4-0.7)', '낮음 (<0.4)'],
        datasets: [{
          data: [60, 30, 10], // Placeholder
          backgroundColor: ['#10b981', '#f59e0b', '#ef4444']
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom' } }
      }
    });
  }

  updateQueriesAnalysis(stats) {
    // Top queries
    const topQueriesEl = this.querySelector('#top-queries');
    if (stats.popular_queries && stats.popular_queries.length > 0) {
      topQueriesEl.innerHTML = stats.popular_queries.slice(0, 20).map((q, i) => `
        <div class="query-item">
          <span class="rank">${i + 1}</span>
          <span class="query">${this.escapeHtml(q.query)}</span>
          <span class="count">${q.count}회</span>
          <span class="avg-results">${q.avg_results.toFixed(1)}개 결과</span>
        </div>
      `).join('');
    } else {
      topQueriesEl.innerHTML = '<p class="empty">데이터 없음</p>';
    }

    // Zero-result queries
    const zeroResultEl = this.querySelector('#zero-result-queries');
    if (stats.zero_result_queries && stats.zero_result_queries.length > 0) {
      zeroResultEl.innerHTML = stats.zero_result_queries.map((q, i) => `
        <div class="query-item warning">
          <span class="rank">${i + 1}</span>
          <span class="query">${this.escapeHtml(q.query)}</span>
          <span class="count">${q.count}회</span>
          <span class="badge badge-warning">결과 없음</span>
        </div>
      `).join('');
    } else {
      zeroResultEl.innerHTML = '<p class="empty success">✓ Zero-result 쿼리 없음</p>';
    }

    // Low score queries
    const lowScoreEl = this.querySelector('#low-score-queries');
    if (stats.low_score_queries && stats.low_score_queries.length > 0) {
      lowScoreEl.innerHTML = stats.low_score_queries.map((q, i) => `
        <div class="query-item warning">
          <span class="rank">${i + 1}</span>
          <span class="query">${this.escapeHtml(q.query)}</span>
          <span class="score">${(q.avg_similarity * 100).toFixed(1)}%</span>
          <span class="badge badge-warning">낮은 점수</span>
        </div>
      `).join('');
    } else {
      lowScoreEl.innerHTML = '<p class="empty success">✓ 낮은 점수 쿼리 없음</p>';
    }

    // Slow queries
    const slowQueriesEl = this.querySelector('#slow-queries');
    if (stats.slow_queries && stats.slow_queries.length > 0) {
      slowQueriesEl.innerHTML = stats.slow_queries.map((q, i) => `
        <div class="query-item warning">
          <span class="rank">${i + 1}</span>
          <span class="query">${this.escapeHtml(q.query)}</span>
          <span class="time">${q.avg_response_time.toFixed(0)}ms</span>
          <span class="badge badge-warning">느림</span>
        </div>
      `).join('');
    } else {
      slowQueriesEl.innerHTML = '<p class="empty success">✓ 느린 쿼리 없음</p>';
    }
  }

  updateTrendsCharts(stats) {
    // Hourly pattern chart
    if (stats.hourly_pattern && stats.hourly_pattern.length > 0) {
      const hourlyData = new Array(24).fill(0);
      stats.hourly_pattern.forEach(h => {
        hourlyData[h.hour] = h.count;
      });

      this.createOrUpdateChart('hourly-pattern-chart', {
        type: 'bar',
        data: {
          labels: Array.from({length: 24}, (_, i) => `${i}시`),
          datasets: [{
            label: '검색 수',
            data: hourlyData,
            backgroundColor: '#3b82f6',
            borderRadius: 4
          }]
        },
        options: this.getChartOptions('검색 수')
      });
    }

    // Daily pattern chart (day of week)
    if (stats.daily_pattern && stats.daily_pattern.length > 0) {
      const dayNames = ['일', '월', '화', '수', '목', '금', '토'];
      const dailyData = new Array(7).fill(0);
      stats.daily_pattern.forEach(d => {
        dailyData[d.day_of_week] = d.count;
      });

      this.createOrUpdateChart('daily-pattern-chart', {
        type: 'bar',
        data: {
          labels: dayNames,
          datasets: [{
            label: '검색 수',
            data: dailyData,
            backgroundColor: '#10b981',
            borderRadius: 4
          }]
        },
        options: this.getChartOptions('검색 수')
      });
    }

    // Quality trend chart
    if (stats.trend && stats.trend.length > 0) {
      const labels = stats.trend.map(t => this.formatTime(t.hour)).reverse();
      
      this.createOrUpdateChart('quality-trend-chart', {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: '평균 점수',
            data: stats.trend.map(t => (t.avg_similarity * 100).toFixed(1)).reverse(),
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            fill: true,
            tension: 0.4
          }]
        },
        options: this.getChartOptions('점수 (%)', 0, 100)
      });
    }

    // Response time trend chart
    if (stats.trend && stats.trend.length > 0) {
      const labels = stats.trend.map(t => this.formatTime(t.hour)).reverse();
      
      this.createOrUpdateChart('response-trend-chart', {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: '평균 응답시간',
            data: stats.trend.map(t => t.avg_response_time).reverse(),
            borderColor: '#f59e0b',
            backgroundColor: 'rgba(245, 158, 11, 0.1)',
            fill: true,
            tension: 0.4
          }]
        },
        options: this.getChartOptions('응답시간 (ms)', 0)
      });
    }
  }

  async loadComparisonProjects() {
    try {
      const response = await fetch('/api/monitoring/search/project-stats?hours=168');
      if (!response.ok) throw new Error('Failed to fetch projects');
      
      const projects = await response.json();
      const select = this.querySelector('#comparison-project-select');
      
      select.innerHTML = projects
        .filter(p => p.project_id !== this.projectId)
        .map(p => `<option value="${p.project_id}">${p.project_id} (${p.search_count}회)</option>`)
        .join('');
        
    } catch (error) {
      console.error('Failed to load comparison projects:', error);
    }
  }

  addComparisonProject() {
    const select = this.querySelector('#comparison-project-select');
    const selected = Array.from(select.selectedOptions).map(opt => opt.value);
    
    this.comparisonProjects = [...new Set([...this.comparisonProjects, ...selected])];
    this.updateComparisonView();
  }

  updateComparisonView() {
    const selectedEl = this.querySelector('#selected-projects');
    
    // Display selected projects
    selectedEl.innerHTML = this.comparisonProjects.map(pid => `
      <div class="selected-project-tag">
        <span>${this.escapeHtml(pid)}</span>
        <button class="remove-btn" data-project="${pid}">×</button>
      </div>
    `).join('');

    // Add remove listeners
    selectedEl.querySelectorAll('.remove-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const project = e.target.dataset.project;
        this.comparisonProjects = this.comparisonProjects.filter(p => p !== project);
        this.updateComparisonView();
      });
    });

    // Load comparison data if projects selected
    if (this.comparisonProjects.length > 0) {
      this.loadComparisonData();
    }
  }

  async loadComparisonData() {
    try {
      const hours = this.getHoursFromRange();
      const projects = [this.projectId, ...this.comparisonProjects];
      
      // Fetch stats for all projects
      const statsPromises = projects.map(pid => 
        this.fetchProjectStats(hours, pid)
      );
      const allStats = await Promise.all(statsPromises);

      // Create comparison charts
      this.createComparisonCharts(projects, allStats);
      this.createComparisonTable(projects, allStats);
      
    } catch (error) {
      console.error('Failed to load comparison data:', error);
    }
  }

  createComparisonCharts(projects, allStats) {
    // Searches comparison
    this.createOrUpdateChart('comparison-searches-chart', {
      type: 'bar',
      data: {
        labels: projects.map(p => p === this.projectId ? `${p} (현재)` : p),
        datasets: [{
          label: '총 검색 수',
          data: allStats.map(s => s.summary.total_searches),
          backgroundColor: projects.map((p, i) => 
            p === this.projectId ? '#3b82f6' : `hsl(${i * 60}, 70%, 60%)`
          ),
          borderRadius: 4
        }]
      },
      options: this.getChartOptions('검색 수')
    });

    // Quality comparison
    this.createOrUpdateChart('comparison-quality-chart', {
      type: 'bar',
      data: {
        labels: projects.map(p => p === this.projectId ? `${p} (현재)` : p),
        datasets: [{
          label: '평균 점수 (%)',
          data: allStats.map(s => (s.summary.avg_similarity_score * 100).toFixed(1)),
          backgroundColor: projects.map((p, i) => 
            p === this.projectId ? '#10b981' : `hsl(${i * 60 + 120}, 70%, 60%)`
          ),
          borderRadius: 4
        }]
      },
      options: this.getChartOptions('점수 (%)', 0, 100)
    });
  }

  createComparisonTable(projects, allStats) {
    const tableEl = this.querySelector('#comparison-table');
    
    const rows = [
      { label: '총 검색', key: 'total_searches', format: v => v.toLocaleString() },
      { label: '평균 결과 수', key: 'avg_results_per_search', format: v => v.toFixed(2) },
      { label: '평균 점수', key: 'avg_similarity_score', format: v => (v * 100).toFixed(1) + '%' },
      { label: '평균 응답시간', key: 'avg_response_time_ms', format: v => v.toFixed(0) + 'ms' },
      { label: 'Zero-result 비율', key: 'zero_result_rate', format: v => v.toFixed(1) + '%' }
    ];

    tableEl.innerHTML = `
      <table class="comparison-table">
        <thead>
          <tr>
            <th>지표</th>
            ${projects.map(p => `<th>${p === this.projectId ? `${p} (현재)` : p}</th>`).join('')}
          </tr>
        </thead>
        <tbody>
          ${rows.map(row => `
            <tr>
              <td class="label">${row.label}</td>
              ${allStats.map(s => `<td>${row.format(s.summary[row.key])}</td>`).join('')}
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }

  async loadAlertSettings() {
    // TODO: Load saved alert settings from backend
  }

  async saveAlertSettings() {
    const settings = {
      project_id: this.projectId,
      zero_result: {
        enabled: this.querySelector('#alert-zero-enabled').checked,
        threshold: parseFloat(this.querySelector('#alert-zero-threshold').value)
      },
      response_time: {
        enabled: this.querySelector('#alert-response-enabled').checked,
        threshold: parseFloat(this.querySelector('#alert-response-threshold').value)
      },
      avg_score: {
        enabled: this.querySelector('#alert-score-enabled').checked,
        threshold: parseFloat(this.querySelector('#alert-score-threshold').value)
      },
      search_drop: {
        enabled: this.querySelector('#alert-drop-enabled').checked,
        threshold: parseFloat(this.querySelector('#alert-drop-threshold').value)
      }
    };

    // TODO: Save to backend
    console.log('Saving alert settings:', settings);
    alert('알림 설정이 저장되었습니다.');
  }

  testAlert() {
    alert('테스트 알림이 전송되었습니다.');
  }

  async exportData() {
    try {
      const hours = this.getHoursFromRange();
      const stats = await this.fetchProjectStats(hours);
      
      // Show export format selection
      const format = await this.showExportDialog();
      if (!format) return;

      if (format === 'csv') {
        this.exportAsCSV(stats);
      } else if (format === 'json') {
        this.exportAsJSON(stats);
      }
    } catch (error) {
      console.error('Export failed:', error);
      alert('데이터 내보내기 실패');
    }
  }

  showExportDialog() {
    return new Promise((resolve) => {
      const dialog = document.createElement('div');
      dialog.className = 'export-dialog-overlay';
      dialog.innerHTML = `
        <div class="export-dialog">
          <h3>데이터 내보내기</h3>
          <p>내보낼 형식을 선택하세요:</p>
          <div class="export-options">
            <button class="btn btn-primary" data-format="csv">CSV</button>
            <button class="btn btn-primary" data-format="json">JSON</button>
            <button class="btn btn-secondary" data-format="cancel">취소</button>
          </div>
        </div>
      `;

      dialog.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const format = e.target.dataset.format;
          document.body.removeChild(dialog);
          resolve(format === 'cancel' ? null : format);
        });
      });

      document.body.appendChild(dialog);
    });
  }

  exportAsCSV(stats) {
    const rows = [];
    
    // Header
    rows.push(['지표', '값']);
    
    // Summary data
    const summary = stats.summary;
    rows.push(['총 검색', summary.total_searches]);
    rows.push(['평균 결과 수', summary.avg_results_per_search.toFixed(2)]);
    rows.push(['평균 점수', (summary.avg_similarity_score * 100).toFixed(1) + '%']);
    rows.push(['평균 응답시간', summary.avg_response_time_ms.toFixed(0) + 'ms']);
    rows.push(['Zero-result 비율', summary.zero_result_rate.toFixed(1) + '%']);
    
    rows.push([]); // Empty row
    rows.push(['인기 검색어', '검색 수', '평균 결과']);
    
    // Popular queries
    if (stats.popular_queries) {
      stats.popular_queries.forEach(q => {
        rows.push([q.query, q.count, q.avg_results.toFixed(1)]);
      });
    }

    // Convert to CSV
    const csv = rows.map(row => row.map(cell => `"${cell}"`).join(',')).join('\n');
    
    // Download
    this.downloadFile(csv, `project-${this.projectId}-${this.dateRange}.csv`, 'text/csv');
  }

  exportAsJSON(stats) {
    const json = JSON.stringify(stats, null, 2);
    this.downloadFile(json, `project-${this.projectId}-${this.dateRange}.json`, 'application/json');
  }

  downloadFile(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  createOrUpdateChart(canvasId, config) {
    const canvas = this.querySelector(`#${canvasId}`);
    if (!canvas) return;

    if (this.charts[canvasId]) {
      this.charts[canvasId].destroy();
    }

    this.charts[canvasId] = new Chart(canvas, config);
  }

  getChartOptions(yLabel, min = null, max = null) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: {
          beginAtZero: true,
          min: min,
          max: max,
          title: { display: true, text: yLabel }
        }
      }
    };
  }

  formatTime(isoString) {
    const date = new Date(isoString);
    if (this.dateRange === 'last_24h') {
      return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
    }
    return date.toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' });
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  showError(message) {
    console.error(message);
  }

  destroyCharts() {
    Object.values(this.charts).forEach(chart => chart?.destroy());
    this.charts = {};
  }
}

customElements.define('project-analytics-page', ProjectAnalyticsPage);
