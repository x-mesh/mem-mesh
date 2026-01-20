/**
 * Monitoring Dashboard Page
 * 검색 성능 모니터링 대시보드
 */

export class MonitoringPage extends HTMLElement {
  constructor() {
    super();
    this.charts = {};
    this.currentTab = 'overview';
    this.dateRange = 'last_24h';
    this.refreshInterval = null;
  }

  connectedCallback() {
    this.render();
    this.loadData();
    this.startAutoRefresh();
  }

  disconnectedCallback() {
    this.stopAutoRefresh();
    this.destroyCharts();
  }

  render() {
    this.innerHTML = `
      <div class="monitoring-page">
        <header class="monitoring-header">
          <div class="header-content">
            <h1>📊 Performance Monitoring</h1>
            <p class="subtitle">검색 품질 및 성능 실시간 모니터링</p>
          </div>
          <div class="header-actions">
            <select id="date-range" class="date-range-select">
              <option value="last_1h">최근 1시간</option>
              <option value="last_24h" selected>최근 24시간</option>
              <option value="last_7d">최근 7일</option>
              <option value="last_30d">최근 30일</option>
            </select>
            <button id="refresh-btn" class="refresh-btn" title="새로고침">
              🔄 새로고침
            </button>
          </div>
        </header>

        <!-- Summary Cards -->
        <section class="summary-cards">
          <div class="summary-card" id="card-searches">
            <div class="card-icon">🔍</div>
            <div class="card-content">
              <span class="card-value" id="total-searches">-</span>
              <span class="card-label">총 검색</span>
            </div>
          </div>
          <div class="summary-card" id="card-similarity">
            <div class="card-icon">📈</div>
            <div class="card-content">
              <span class="card-value" id="avg-similarity">-</span>
              <span class="card-label">평균 유사도</span>
            </div>
          </div>
          <div class="summary-card" id="card-response">
            <div class="card-icon">⚡</div>
            <div class="card-content">
              <span class="card-value" id="avg-response">-</span>
              <span class="card-label">평균 응답시간</span>
            </div>
          </div>
          <div class="summary-card" id="card-no-results">
            <div class="card-icon">⚠️</div>
            <div class="card-content">
              <span class="card-value" id="no-results-rate">-</span>
              <span class="card-label">결과없음 비율</span>
            </div>
          </div>
        </section>

        <!-- Tab Navigation -->
        <nav class="tab-nav">
          <button class="tab-btn active" data-tab="overview">개요</button>
          <button class="tab-btn" data-tab="quality">검색 품질</button>
          <button class="tab-btn" data-tab="queries">쿼리 분석</button>
          <button class="tab-btn" data-tab="embedding">임베딩 성능</button>
        </nav>

        <!-- Tab Content -->
        <div class="tab-content">
          <!-- Overview Tab -->
          <div id="tab-overview" class="tab-panel active">
            <div class="charts-grid">
              <div class="chart-container">
                <h3>검색 품질 추이</h3>
                <canvas id="similarity-chart"></canvas>
              </div>
              <div class="chart-container">
                <h3>응답 시간 추이</h3>
                <canvas id="response-time-chart"></canvas>
              </div>
              <div class="chart-container">
                <h3>검색량 추이</h3>
                <canvas id="search-volume-chart"></canvas>
              </div>
              <div class="chart-container">
                <h3>결과없음 비율 추이</h3>
                <canvas id="no-results-chart"></canvas>
              </div>
            </div>
          </div>

          <!-- Search Quality Tab (NEW) -->
          <div id="tab-quality" class="tab-panel hidden">
            <div class="quality-grid">
              <!-- Quality Summary Cards -->
              <div class="quality-summary">
                <div class="summary-card small">
                  <span class="card-value" id="quality-total-searches">-</span>
                  <span class="card-label">총 검색</span>
                </div>
                <div class="summary-card small">
                  <span class="card-value" id="quality-avg-results">-</span>
                  <span class="card-label">평균 결과 수</span>
                </div>
                <div class="summary-card small">
                  <span class="card-value" id="quality-avg-score">-</span>
                  <span class="card-label">평균 점수</span>
                </div>
                <div class="summary-card small">
                  <span class="card-value" id="quality-zero-rate">-</span>
                  <span class="card-label">Zero-Result 비율</span>
                </div>
                <div class="summary-card small">
                  <span class="card-value" id="quality-low-score-rate">-</span>
                  <span class="card-label">낮은 점수 비율</span>
                </div>
              </div>

              <!-- Source Performance -->
              <div class="chart-container wide">
                <h3>📊 검색 소스별 성능</h3>
                <div id="source-stats-table"></div>
              </div>

              <!-- Hourly Trend -->
              <div class="chart-container wide">
                <h3>📈 시간대별 검색 트렌드</h3>
                <canvas id="quality-trend-chart"></canvas>
              </div>

              <!-- Project Stats -->
              <div class="chart-container wide">
                <h3>🗂️ 프로젝트별 검색 통계</h3>
                <div id="project-stats-table"></div>
              </div>

              <!-- Cache Performance -->
              <div class="chart-container">
                <h3>💾 캐시 성능</h3>
                <div id="cache-stats">
                  <div class="cache-metric">
                    <span class="metric-label">총 작업</span>
                    <span class="metric-value" id="cache-total-ops">-</span>
                  </div>
                  <div class="cache-metric">
                    <span class="metric-label">캐시 히트</span>
                    <span class="metric-value" id="cache-hits">-</span>
                  </div>
                  <div class="cache-metric">
                    <span class="metric-label">히트율</span>
                    <span class="metric-value" id="cache-hit-rate-detail">-</span>
                  </div>
                  <div class="cache-metric">
                    <span class="metric-label">평균 시간</span>
                    <span class="metric-value" id="cache-avg-time">-</span>
                  </div>
                </div>
                <canvas id="cache-performance-chart"></canvas>
              </div>

              <!-- Popular Queries -->
              <div class="chart-container">
                <h3>🔥 인기 검색어 (최근 24시간)</h3>
                <div id="quality-popular-queries" class="queries-list"></div>
              </div>
            </div>
          </div>

          <!-- Queries Tab -->
          <div id="tab-queries" class="tab-panel hidden">
            <div class="queries-grid">
              <div class="queries-section">
                <h3>🔥 인기 검색어 Top 10</h3>
                <div id="top-queries" class="queries-list"></div>
              </div>
              <div class="queries-section">
                <h3>⚠️ 개선 필요 쿼리 (낮은 유사도)</h3>
                <div id="low-similarity-queries" class="queries-list"></div>
              </div>
              <div class="queries-section">
                <h3>❌ 결과없음 쿼리</h3>
                <div id="no-results-queries" class="queries-list"></div>
              </div>
              <div class="queries-section">
                <h3>📏 쿼리 길이 분포</h3>
                <canvas id="query-length-chart"></canvas>
              </div>
            </div>
          </div>

          <!-- Embedding Tab -->
          <div id="tab-embedding" class="tab-panel hidden">
            <div class="embedding-grid">
              <div class="embedding-summary">
                <div class="summary-card small">
                  <span class="card-value" id="total-embeddings">-</span>
                  <span class="card-label">총 임베딩</span>
                </div>
                <div class="summary-card small">
                  <span class="card-value" id="avg-embedding-time">-</span>
                  <span class="card-label">평균 생성시간</span>
                </div>
                <div class="summary-card small">
                  <span class="card-value" id="cache-hit-rate">-</span>
                  <span class="card-label">캐시 히트율</span>
                </div>
              </div>
              <div class="chart-container wide">
                <h3>임베딩 생성 시간 추이</h3>
                <canvas id="embedding-time-chart"></canvas>
              </div>
              <div class="chart-container">
                <h3>작업 유형별 분포</h3>
                <canvas id="operation-type-chart"></canvas>
              </div>
            </div>
          </div>
        </div>

        <!-- Recent Searches -->
        <section class="recent-searches">
          <h3>📋 최근 검색</h3>
          <div id="recent-searches-list" class="searches-table"></div>
        </section>
      </div>
    `;

    this.setupEventListeners();
  }

  setupEventListeners() {
    // Date range selector
    const dateRange = this.querySelector('#date-range');
    dateRange?.addEventListener('change', (e) => {
      this.dateRange = e.target.value;
      this.loadData();
    });

    // Refresh button
    const refreshBtn = this.querySelector('#refresh-btn');
    refreshBtn?.addEventListener('click', () => this.loadData());

    // Tab navigation
    const tabBtns = this.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
      btn.addEventListener('click', (e) => {
        const tab = e.target.dataset.tab;
        this.switchTab(tab);
      });
    });
  }

  switchTab(tab) {
    this.currentTab = tab;

    // Update tab buttons
    this.querySelectorAll('.tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });

    // Update tab panels
    this.querySelectorAll('.tab-panel').forEach(panel => {
      panel.classList.toggle('active', panel.id === `tab-${tab}`);
      panel.classList.toggle('hidden', panel.id !== `tab-${tab}`);
    });
  }

  getDateRange() {
    const now = new Date();
    let start;

    switch (this.dateRange) {
      case 'last_1h':
        start = new Date(now - 60 * 60 * 1000);
        break;
      case 'last_24h':
        start = new Date(now - 24 * 60 * 60 * 1000);
        break;
      case 'last_7d':
        start = new Date(now - 7 * 24 * 60 * 60 * 1000);
        break;
      case 'last_30d':
        start = new Date(now - 30 * 24 * 60 * 60 * 1000);
        break;
      default:
        start = new Date(now - 24 * 60 * 60 * 1000);
    }

    return {
      start_date: start.toISOString(),
      end_date: now.toISOString(),
      aggregation: this.dateRange === 'last_1h' || this.dateRange === 'last_24h' ? 'hourly' : 'daily'
    };
  }

  async loadData() {
    try {
      const range = this.getDateRange();
      
      // Load all data in parallel
      const [searchMetrics, queryAnalysis, embeddingMetrics, recentSearches, qualityStats, projectStats, cacheStats] = await Promise.all([
        this.fetchSearchMetrics(range),
        this.fetchQueryAnalysis(),
        this.fetchEmbeddingMetrics(range),
        this.fetchRecentSearches(),
        this.fetchSearchQualityStats(),
        this.fetchProjectSearchStats(),
        this.fetchCachePerformanceStats()
      ]);

      this.updateSummaryCards(searchMetrics);
      this.updateCharts(searchMetrics, embeddingMetrics);
      this.updateQueryAnalysis(queryAnalysis);
      this.updateEmbeddingStats(embeddingMetrics);
      this.updateRecentSearches(recentSearches);
      this.updateSearchQualityTab(qualityStats, projectStats, cacheStats);

    } catch (error) {
      console.error('Failed to load monitoring data:', error);
      this.showError('데이터 로드 실패');
    }
  }

  async fetchSearchMetrics(range) {
    const params = new URLSearchParams({
      start_date: range.start_date,
      end_date: range.end_date,
      aggregation: range.aggregation
    });
    const response = await fetch(`/api/monitoring/search/metrics?${params}`);
    if (!response.ok) throw new Error('Failed to fetch search metrics');
    return response.json();
  }

  async fetchQueryAnalysis() {
    const days = this.dateRange === 'last_30d' ? 30 : this.dateRange === 'last_7d' ? 7 : 1;
    const response = await fetch(`/api/monitoring/search/queries?days=${days}&limit=100`);
    if (!response.ok) throw new Error('Failed to fetch query analysis');
    return response.json();
  }

  async fetchEmbeddingMetrics(range) {
    const params = new URLSearchParams({
      start_date: range.start_date,
      end_date: range.end_date
    });
    const response = await fetch(`/api/monitoring/embedding/metrics?${params}`);
    if (!response.ok) throw new Error('Failed to fetch embedding metrics');
    return response.json();
  }

  async fetchRecentSearches() {
    const response = await fetch('/api/monitoring/search/recent?limit=20');
    if (!response.ok) throw new Error('Failed to fetch recent searches');
    return response.json();
  }

  async fetchSearchQualityStats() {
    const hours = this.dateRange === 'last_1h' ? 1 : 
                  this.dateRange === 'last_24h' ? 24 : 
                  this.dateRange === 'last_7d' ? 168 : 24;
    const response = await fetch(`/api/monitoring/search/quality-stats?hours=${hours}`);
    if (!response.ok) throw new Error('Failed to fetch search quality stats');
    return response.json();
  }

  async fetchProjectSearchStats() {
    const hours = this.dateRange === 'last_1h' ? 1 : 
                  this.dateRange === 'last_24h' ? 24 : 
                  this.dateRange === 'last_7d' ? 168 : 24;
    const response = await fetch(`/api/monitoring/search/project-stats?hours=${hours}`);
    if (!response.ok) throw new Error('Failed to fetch project search stats');
    return response.json();
  }

  async fetchCachePerformanceStats() {
    const hours = this.dateRange === 'last_1h' ? 1 : 
                  this.dateRange === 'last_24h' ? 24 : 
                  this.dateRange === 'last_7d' ? 168 : 24;
    const response = await fetch(`/api/monitoring/cache/performance-stats?hours=${hours}`);
    if (!response.ok) throw new Error('Failed to fetch cache performance stats');
    return response.json();
  }

  updateSummaryCards(data) {
    const summary = data.summary;
    
    this.querySelector('#total-searches').textContent = summary.total_searches.toLocaleString();
    this.querySelector('#avg-similarity').textContent = (summary.avg_similarity * 100).toFixed(1) + '%';
    this.querySelector('#avg-response').textContent = summary.avg_response_time_ms.toFixed(0) + 'ms';
    this.querySelector('#no-results-rate').textContent = summary.no_results_rate.toFixed(1) + '%';

    // Color coding based on thresholds
    const similarityCard = this.querySelector('#card-similarity');
    similarityCard.classList.toggle('warning', summary.avg_similarity < 0.5);
    similarityCard.classList.toggle('good', summary.avg_similarity >= 0.7);

    const responseCard = this.querySelector('#card-response');
    responseCard.classList.toggle('warning', summary.avg_response_time_ms > 1000);
    responseCard.classList.toggle('good', summary.avg_response_time_ms < 200);

    const noResultsCard = this.querySelector('#card-no-results');
    noResultsCard.classList.toggle('warning', summary.no_results_rate > 20);
    noResultsCard.classList.toggle('good', summary.no_results_rate < 5);
  }

  updateCharts(searchData, embeddingData) {
    const timeseries = searchData.timeseries;
    const labels = timeseries.map(d => this.formatTime(d.period));

    // Similarity Chart
    this.createOrUpdateChart('similarity-chart', {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: '평균 유사도',
          data: timeseries.map(d => (d.avg_similarity * 100).toFixed(1)),
          borderColor: '#10b981',
          backgroundColor: 'rgba(16, 185, 129, 0.1)',
          fill: true,
          tension: 0.4
        }]
      },
      options: this.getChartOptions('유사도 (%)', 0, 100)
    });

    // Response Time Chart
    this.createOrUpdateChart('response-time-chart', {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: '평균 응답시간',
          data: timeseries.map(d => d.avg_response_time_ms),
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59, 130, 246, 0.1)',
          fill: true,
          tension: 0.4
        }]
      },
      options: this.getChartOptions('응답시간 (ms)')
    });

    // Search Volume Chart
    this.createOrUpdateChart('search-volume-chart', {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: '검색 수',
          data: timeseries.map(d => d.total_searches),
          backgroundColor: '#8b5cf6',
          borderRadius: 4
        }]
      },
      options: this.getChartOptions('검색 수')
    });

    // No Results Chart
    this.createOrUpdateChart('no-results-chart', {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: '결과없음 비율',
          data: timeseries.map(d => d.no_results_rate),
          borderColor: '#ef4444',
          backgroundColor: 'rgba(239, 68, 68, 0.1)',
          fill: true,
          tension: 0.4
        }]
      },
      options: this.getChartOptions('비율 (%)', 0, 100)
    });

    // Embedding Time Chart
    if (embeddingData.timeseries.length > 0) {
      const embLabels = embeddingData.timeseries.map(d => this.formatTime(d.period));
      this.createOrUpdateChart('embedding-time-chart', {
        type: 'line',
        data: {
          labels: embLabels,
          datasets: [{
            label: '평균 생성시간',
            data: embeddingData.timeseries.map(d => d.avg_time_ms),
            borderColor: '#f59e0b',
            backgroundColor: 'rgba(245, 158, 11, 0.1)',
            fill: true,
            tension: 0.4
          }]
        },
        options: this.getChartOptions('시간 (ms)')
      });
    }

    // Operation Type Chart
    if (embeddingData.by_operation.length > 0) {
      this.createOrUpdateChart('operation-type-chart', {
        type: 'doughnut',
        data: {
          labels: embeddingData.by_operation.map(d => d.operation),
          datasets: [{
            data: embeddingData.by_operation.map(d => d.count),
            backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444']
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'bottom' }
          }
        }
      });
    }
  }

  updateQueryAnalysis(data) {
    // Top Queries
    const topQueriesEl = this.querySelector('#top-queries');
    topQueriesEl.innerHTML = data.top_queries.slice(0, 10).map((q, i) => `
      <div class="query-item">
        <span class="rank">${i + 1}</span>
        <span class="query">${this.escapeHtml(q.query)}</span>
        <span class="count">${q.count}회</span>
      </div>
    `).join('') || '<p class="empty">데이터 없음</p>';

    // Low Similarity Queries
    const lowSimEl = this.querySelector('#low-similarity-queries');
    lowSimEl.innerHTML = data.low_similarity_queries.slice(0, 10).map(q => `
      <div class="query-item warning">
        <span class="query">${this.escapeHtml(q.query)}</span>
        <span class="similarity">${(q.avg_similarity * 100).toFixed(1)}%</span>
      </div>
    `).join('') || '<p class="empty">데이터 없음</p>';

    // No Results Queries
    const noResultsEl = this.querySelector('#no-results-queries');
    noResultsEl.innerHTML = data.no_results_queries.slice(0, 10).map(q => `
      <div class="query-item error">
        <span class="query">${this.escapeHtml(q.query)}</span>
        <span class="count">${q.count}회</span>
      </div>
    `).join('') || '<p class="empty">데이터 없음</p>';

    // Query Length Distribution
    const dist = data.length_distribution;
    if (Object.keys(dist).length > 0) {
      this.createOrUpdateChart('query-length-chart', {
        type: 'bar',
        data: {
          labels: ['짧은 쿼리', '중간 쿼리', '긴 쿼리'],
          datasets: [{
            label: '검색 수',
            data: [
              dist.short?.count || 0,
              dist.medium?.count || 0,
              dist.long?.count || 0
            ],
            backgroundColor: ['#10b981', '#3b82f6', '#8b5cf6']
          }]
        },
        options: this.getChartOptions('검색 수')
      });
    }
  }

  updateEmbeddingStats(data) {
    const summary = data.summary;
    
    this.querySelector('#total-embeddings').textContent = 
      (summary.total_embeddings || 0).toLocaleString();
    this.querySelector('#avg-embedding-time').textContent = 
      (summary.avg_time_per_embedding_ms || 0).toFixed(1) + 'ms';
    this.querySelector('#cache-hit-rate').textContent = 
      (summary.cache_hit_rate || 0).toFixed(1) + '%';
  }

  updateRecentSearches(searches) {
    const container = this.querySelector('#recent-searches-list');
    
    if (searches.length === 0) {
      container.innerHTML = '<p class="empty">최근 검색 없음</p>';
      return;
    }

    container.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>시간</th>
            <th>쿼리</th>
            <th>결과 수</th>
            <th>유사도</th>
            <th>응답시간</th>
          </tr>
        </thead>
        <tbody>
          ${searches.map(s => `
            <tr>
              <td>${this.formatTime(s.timestamp)}</td>
              <td class="query-cell">${this.escapeHtml(s.query)}</td>
              <td>${s.result_count}</td>
              <td>${s.avg_similarity_score ? (s.avg_similarity_score * 100).toFixed(1) + '%' : '-'}</td>
              <td>${s.response_time_ms}ms</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
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
      plugins: {
        legend: { display: false }
      },
      scales: {
        y: {
          beginAtZero: true,
          min: min,
          max: max,
          title: { display: true, text: yLabel }
        },
        x: {
          ticks: { maxRotation: 45, minRotation: 45 }
        }
      }
    };
  }

  formatTime(isoString) {
    const date = new Date(isoString);
    if (this.dateRange === 'last_1h' || this.dateRange === 'last_24h') {
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
    // Simple error display
    console.error(message);
  }

  startAutoRefresh() {
    this.refreshInterval = setInterval(() => this.loadData(), 60000); // 1분마다
  }

  stopAutoRefresh() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
      this.refreshInterval = null;
    }
  }

  updateSearchQualityTab(qualityStats, projectStats, cacheStats) {
    // Update quality summary cards
    const summary = qualityStats.summary;
    this.querySelector('#quality-total-searches').textContent = summary.total_searches.toLocaleString();
    this.querySelector('#quality-avg-results').textContent = summary.avg_results_per_search.toFixed(2);
    this.querySelector('#quality-avg-score').textContent = (summary.avg_similarity_score * 100).toFixed(1) + '%';
    this.querySelector('#quality-zero-rate').textContent = summary.zero_result_rate.toFixed(1) + '%';
    this.querySelector('#quality-low-score-rate').textContent = summary.low_score_rate.toFixed(1) + '%';

    // Update source stats table
    const sourceTable = this.querySelector('#source-stats-table');
    if (qualityStats.by_source.length > 0) {
      sourceTable.innerHTML = `
        <table class="data-table">
          <thead>
            <tr>
              <th>소스</th>
              <th>검색 수</th>
              <th>평균 결과</th>
              <th>평균 응답시간</th>
            </tr>
          </thead>
          <tbody>
            ${qualityStats.by_source.map(s => `
              <tr>
                <td><span class="badge">${s.source}</span></td>
                <td>${s.count.toLocaleString()}</td>
                <td>${s.avg_results.toFixed(2)}</td>
                <td>${s.avg_response_time_ms.toFixed(0)}ms</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    } else {
      sourceTable.innerHTML = '<p class="empty">데이터 없음</p>';
    }

    // Update quality trend chart
    if (qualityStats.trend.length > 0) {
      const trendLabels = qualityStats.trend.map(t => this.formatTime(t.hour)).reverse();
      this.createOrUpdateChart('quality-trend-chart', {
        type: 'line',
        data: {
          labels: trendLabels,
          datasets: [
            {
              label: '검색 수',
              data: qualityStats.trend.map(t => t.search_count).reverse(),
              borderColor: '#3b82f6',
              backgroundColor: 'rgba(59, 130, 246, 0.1)',
              yAxisID: 'y',
              tension: 0.4
            },
            {
              label: '평균 점수',
              data: qualityStats.trend.map(t => (t.avg_score * 100).toFixed(1)).reverse(),
              borderColor: '#10b981',
              backgroundColor: 'rgba(16, 185, 129, 0.1)',
              yAxisID: 'y1',
              tension: 0.4
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: { legend: { position: 'top' } },
          scales: {
            y: {
              type: 'linear',
              display: true,
              position: 'left',
              title: { display: true, text: '검색 수' }
            },
            y1: {
              type: 'linear',
              display: true,
              position: 'right',
              title: { display: true, text: '평균 점수 (%)' },
              grid: { drawOnChartArea: false }
            }
          }
        }
      });
    }

    // Update project stats table
    const projectTable = this.querySelector('#project-stats-table');
    if (projectStats.length > 0) {
      projectTable.innerHTML = `
        <table class="data-table">
          <thead>
            <tr>
              <th>프로젝트</th>
              <th>검색 수</th>
              <th>평균 결과</th>
              <th>평균 점수</th>
              <th>평균 응답시간</th>
              <th>Zero-Result 비율</th>
              <th>액션</th>
            </tr>
          </thead>
          <tbody>
            ${projectStats.map(p => `
              <tr>
                <td><strong>${this.escapeHtml(p.project_id)}</strong></td>
                <td>${p.search_count.toLocaleString()}</td>
                <td>${p.avg_results.toFixed(2)}</td>
                <td>${(p.avg_score * 100).toFixed(1)}%</td>
                <td>${p.avg_response_time_ms.toFixed(0)}ms</td>
                <td class="${p.zero_result_rate > 20 ? 'text-warning' : ''}">${p.zero_result_rate.toFixed(1)}%</td>
                <td>
                  <button class="btn-link view-project-btn" data-project="${this.escapeHtml(p.project_id)}">
                    상세보기 →
                  </button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
      
      // Add click handlers for view buttons
      this.querySelectorAll('.view-project-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const projectId = e.target.dataset.project;
          window.location.hash = `#/project-analytics?project=${encodeURIComponent(projectId)}`;
        });
      });
    } else {
      projectTable.innerHTML = '<p class="empty">프로젝트별 데이터 없음</p>';
    }

    // Update cache stats
    const cache = cacheStats.embedding_cache;
    this.querySelector('#cache-total-ops').textContent = cache.total_operations.toLocaleString();
    this.querySelector('#cache-hits').textContent = cache.cache_hits.toLocaleString();
    this.querySelector('#cache-hit-rate-detail').textContent = cache.hit_rate.toFixed(1) + '%';
    this.querySelector('#cache-avg-time').textContent = cache.avg_time_ms.toFixed(1) + 'ms';

    // Cache performance chart
    this.createOrUpdateChart('cache-performance-chart', {
      type: 'doughnut',
      data: {
        labels: ['캐시 히트', '캐시 미스'],
        datasets: [{
          data: [cache.cache_hits, cache.cache_misses],
          backgroundColor: ['#10b981', '#ef4444']
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'bottom' },
          tooltip: {
            callbacks: {
              label: function(context) {
                const label = context.label || '';
                const value = context.parsed || 0;
                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                const percentage = ((value / total) * 100).toFixed(1);
                return `${label}: ${value.toLocaleString()} (${percentage}%)`;
              }
            }
          }
        }
      }
    });

    // Update popular queries
    const popularQueriesEl = this.querySelector('#quality-popular-queries');
    if (qualityStats.popular_queries.length > 0) {
      popularQueriesEl.innerHTML = qualityStats.popular_queries.map((q, i) => `
        <div class="query-item">
          <span class="rank">${i + 1}</span>
          <span class="query">${this.escapeHtml(q.query)}</span>
          <span class="count">${q.count}회 (평균 ${q.avg_results.toFixed(1)}개 결과)</span>
        </div>
      `).join('');
    } else {
      popularQueriesEl.innerHTML = '<p class="empty">인기 검색어 데이터 없음 (쿼리 해싱 활성화됨)</p>';
    }
  }

  destroyCharts() {
    Object.values(this.charts).forEach(chart => chart?.destroy());
    this.charts = {};
  }
}

customElements.define('monitoring-page', MonitoringPage);
