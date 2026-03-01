/**
 * Analytics Page — Linear-style redesign
 * Chart.js powered charts, compact stat cards, 2-column grid layout
 */

const CATEGORY_COLORS_LIGHT = {
  decision: '#1a1a1a',
  bug: '#3d3d3d',
  code_snippet: '#555555',
  idea: '#6e6e6e',
  incident: '#878787',
  task: '#a0a0a0',
  'git-history': '#b8b8b8',
};

const CATEGORY_COLORS_DARK = {
  decision: '#e0e0e0',
  bug: '#c8c8c8',
  code_snippet: '#b0b0b0',
  idea: '#989898',
  incident: '#808080',
  task: '#686868',
  'git-history': '#505050',
};

function getCategoryColors() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  return isDark ? CATEGORY_COLORS_DARK : CATEGORY_COLORS_LIGHT;
}

class AnalyticsPage extends HTMLElement {
  constructor() {
    super();
    this.memories = [];
    this.totalMemoriesCount = 0; // Actual total count from API
    this.analytics = {};
    this.isLoading = false;
    this.charts = new Map();
    this.selectedTimeRange = '30d';
  }

  connectedCallback() {
    console.log('AnalyticsPage connected');
    this.render();
    this.setupEventListeners();

    // Slight delay for DOM to be fully rendered
    setTimeout(() => {
      this.loadAnalytics();
    }, 100);
  }

  disconnectedCallback() {
    // Clean up chart instances
    this.charts.forEach(chart => {
      if (chart.destroy) chart.destroy();
    });
    this.charts.clear();
  }

  /**
   * Setup event listeners
   */
  setupEventListeners() {
    const timeRangeSelect = this.querySelector('.time-range-select');
    if (timeRangeSelect) {
      timeRangeSelect.addEventListener('change', this.handleTimeRangeChange.bind(this));
    }

    const refreshBtn = this.querySelector('.refresh-btn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', this.loadAnalytics.bind(this));
    }
  }

  /**
   * Load analytics data
   */
  async loadAnalytics() {
    try {
      this.setLoading(true);

      let searchResult;

      searchResult = await window.app.apiClient.searchMemories('', { limit: 10000 });

      if (searchResult && searchResult.results) {
        this.memories = searchResult.results;
        this.totalMemoriesCount = searchResult.total || this.memories.length; // Use actual total from API
        console.log(`Loaded ${this.memories.length} of ${this.totalMemoriesCount} total memories for analytics`);
        this.processAnalytics();
        this.renderAnalytics();
        this.renderCharts();
      } else {
        console.warn('No results found in analytics search response:', searchResult);
        this.memories = [];
        this.totalMemoriesCount = 0;
        this.processAnalytics();
        this.renderAnalytics();
        this.renderCharts();
      }

    } catch (error) {
      console.error('Failed to load analytics:', error);
      this.showError('Failed to load analytics: ' + error.message);
    } finally {
      this.setLoading(false);
    }
  }

  /**
   * Process analytics from memories data
   */
  processAnalytics() {
    const now = new Date();
    const timeRangeMs = this.getTimeRangeMs();
    const cutoffDate = new Date(now.getTime() - timeRangeMs);

    // Filter memories by time range
    const filteredMemories = this.memories.filter(memory =>
      new Date(memory.created_at) >= cutoffDate
    );

    this.analytics = {
      overview: this.calculateOverview(filteredMemories),
      trends: this.calculateTrends(filteredMemories),
      categories: this.calculateCategories(filteredMemories),
      projects: this.calculateProjects(filteredMemories),
      productivity: this.calculateProductivity(filteredMemories),
      wordFrequency: this.calculateWordFrequency(filteredMemories),
      timeDistribution: this.calculateTimeDistribution(filteredMemories),
      topTags: this.calculateTopTags(filteredMemories)
    };
  }

  /**
   * Calculate overview statistics
   */
  calculateOverview(memories) {
    // Use actual total count from API, not filtered memories length
    const totalMemories = this.totalMemoriesCount || memories.length;
    const totalWords = memories.reduce((sum, m) => sum + (m.content?.split(/\s+/).length || 0), 0);
    const totalCharacters = memories.reduce((sum, m) => sum + (m.content?.length || 0), 0);
    const uniqueProjects = new Set(memories.map(m => m.project_id || 'default')).size;
    const uniqueCategories = new Set(memories.map(m => m.category)).size;

    // 태그 통계 계산 (tags가 배열인 경우만)
    const allTags = memories.flatMap(m => Array.isArray(m.tags) ? m.tags : []);
    const uniqueTags = new Set(allTags).size;

    const avgWordsPerMemory = memories.length > 0 ? Math.round(totalWords / memories.length) : 0;
    const avgCharsPerMemory = memories.length > 0 ? Math.round(totalCharacters / memories.length) : 0;

    // 성장률 계산 (최근 7일 vs 이전 7일)
    const now = new Date();
    const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    const fourteenDaysAgo = new Date(now.getTime() - 14 * 24 * 60 * 60 * 1000);

    const recentWeek = memories.filter(m => new Date(m.created_at) >= sevenDaysAgo).length;
    const previousWeek = memories.filter(m => {
      const date = new Date(m.created_at);
      return date >= fourteenDaysAgo && date < sevenDaysAgo;
    }).length;

    const growthRate = previousWeek > 0
      ? Math.round(((recentWeek - previousWeek) / previousWeek) * 100)
      : (recentWeek > 0 ? 100 : 0);

    return {
      totalMemories,
      totalWords,
      totalCharacters,
      uniqueProjects,
      uniqueCategories,
      uniqueTags,
      avgWordsPerMemory,
      avgCharsPerMemory,
      growthRate,
      recentWeekCount: recentWeek,
      previousWeekCount: previousWeek
    };
  }

  /**
   * Calculate trends over time
   */
  calculateTrends(memories) {
    const dailyCount = new Map();
    const dailyWords = new Map();

    memories.forEach(memory => {
      const date = new Date(memory.created_at).toISOString().split('T')[0];
      dailyCount.set(date, (dailyCount.get(date) || 0) + 1);
      dailyWords.set(date, (dailyWords.get(date) || 0) + (memory.content?.split(/\s+/).length || 0));
    });

    // Fill in missing dates
    const dates = [];
    const counts = [];
    const words = [];

    const now = new Date();
    const days = Math.min(30, Math.ceil(this.getTimeRangeMs() / (24 * 60 * 60 * 1000)));

    for (let i = days - 1; i >= 0; i--) {
      const date = new Date(now.getTime() - i * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
      dates.push(date);
      counts.push(dailyCount.get(date) || 0);
      words.push(dailyWords.get(date) || 0);
    }

    return { dates, counts, words };
  }

  /**
   * Calculate category distribution
   */
  calculateCategories(memories) {
    const categoryCount = new Map();
    const categoryWords = new Map();

    memories.forEach(memory => {
      const category = memory.category || 'unknown';
      categoryCount.set(category, (categoryCount.get(category) || 0) + 1);
      categoryWords.set(category, (categoryWords.get(category) || 0) + (memory.content?.split(/\s+/).length || 0));
    });

    return {
      labels: Array.from(categoryCount.keys()),
      counts: Array.from(categoryCount.values()),
      words: Array.from(categoryWords.values())
    };
  }

  /**
   * Calculate project statistics
   */
  calculateProjects(memories) {
    const projectStats = new Map();

    memories.forEach(memory => {
      const projectId = memory.project_id || 'default';
      if (!projectStats.has(projectId)) {
        projectStats.set(projectId, {
          name: projectId === 'default' ? 'Default' : projectId,
          count: 0,
          words: 0,
          categories: new Set(),
          tags: new Set()
        });
      }

      const stats = projectStats.get(projectId);
      stats.count++;
      stats.words += memory.content?.split(/\s+/).length || 0;
      stats.categories.add(memory.category);
      if (memory.tags && Array.isArray(memory.tags)) {
        memory.tags.forEach(tag => stats.tags.add(tag));
      }
    });

    return Array.from(projectStats.values()).map(stats => ({
      ...stats,
      categories: Array.from(stats.categories),
      tags: Array.from(stats.tags)
    }));
  }

  /**
   * Calculate productivity metrics
   */
  calculateProductivity(memories) {
    const hourlyCount = new Array(24).fill(0);
    const weeklyCount = new Array(7).fill(0);
    const monthlyCount = new Array(12).fill(0);

    memories.forEach(memory => {
      const date = new Date(memory.created_at);
      hourlyCount[date.getHours()]++;
      weeklyCount[date.getDay()]++;
      monthlyCount[date.getMonth()]++;
    });

    const peakHour = hourlyCount.indexOf(Math.max(...hourlyCount));
    const peakDay = weeklyCount.indexOf(Math.max(...weeklyCount));
    const peakMonth = monthlyCount.indexOf(Math.max(...monthlyCount));

    const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

    return {
      hourlyCount,
      weeklyCount,
      monthlyCount,
      peakHour,
      peakDay: dayNames[peakDay],
      peakMonth: monthNames[peakMonth],
      totalDays: new Set(memories.map(m => new Date(m.created_at).toDateString())).size
    };
  }

  /**
   * Calculate word frequency
   */
  calculateWordFrequency(memories) {
    const wordCount = new Map();
    const stopWords = new Set(['the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'can', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them']);

    memories.forEach(memory => {
      if (memory.content) {
        const words = memory.content.toLowerCase()
          .replace(/[^\w\s]/g, ' ')
          .split(/\s+/)
          .filter(word => word.length > 2 && !stopWords.has(word));

        words.forEach(word => {
          wordCount.set(word, (wordCount.get(word) || 0) + 1);
        });
      }
    });

    // Get top 20 words
    const sortedWords = Array.from(wordCount.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20);

    return {
      words: sortedWords.map(([word]) => word),
      counts: sortedWords.map(([, count]) => count)
    };
  }

  /**
   * Calculate time distribution
   */
  calculateTimeDistribution(memories) {
    const distribution = {
      morning: 0,    // 6-12
      afternoon: 0,  // 12-18
      evening: 0,    // 18-22
      night: 0       // 22-6
    };

    memories.forEach(memory => {
      const hour = new Date(memory.created_at).getHours();
      if (hour >= 6 && hour < 12) distribution.morning++;
      else if (hour >= 12 && hour < 18) distribution.afternoon++;
      else if (hour >= 18 && hour < 22) distribution.evening++;
      else distribution.night++;
    });

    return distribution;
  }

  /**
   * Calculate top tags
   */
  calculateTopTags(memories) {
    const tagCount = new Map();

    memories.forEach(memory => {
      if (Array.isArray(memory.tags)) {
        memory.tags.forEach(tag => {
          tagCount.set(tag, (tagCount.get(tag) || 0) + 1);
        });
      }
    });

    // Get top 20 tags
    const sortedTags = Array.from(tagCount.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20);

    return {
      tags: sortedTags.map(([tag]) => tag),
      counts: sortedTags.map(([, count]) => count)
    };
  }

  /**
   * Get time range in milliseconds
   */
  getTimeRangeMs() {
    switch (this.selectedTimeRange) {
      case '7d': return 7 * 24 * 60 * 60 * 1000;
      case '30d': return 30 * 24 * 60 * 60 * 1000;
      case '90d': return 90 * 24 * 60 * 60 * 1000;
      case '1y': return 365 * 24 * 60 * 60 * 1000;
      default: return 30 * 24 * 60 * 60 * 1000;
    }
  }

  /**
   * Handle time range change
   */
  handleTimeRangeChange(event) {
    this.selectedTimeRange = event.target.value;
    this.loadAnalytics();
  }

  /**
   * Set loading state
   */
  setLoading(loading) {
    this.isLoading = loading;

    const loadingEl = this.querySelector('.analytics-loading');
    const contentEl = this.querySelector('.analytics-content');

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
    const errorEl = this.querySelector('.analytics-error');
    if (errorEl) {
      errorEl.textContent = message;
      errorEl.style.display = 'block';
      setTimeout(() => {
        errorEl.style.display = 'none';
      }, 5000);
    }
  }

  /**
   * Render analytics data (overview + insights)
   */
  renderAnalytics() {
    this.renderOverview();
    this.renderInsights();
  }

  /**
   * Render overview stat cards
   */
  renderOverview() {
    const overview = this.analytics.overview;
    if (!overview) return;

    const stats = [
      { id: 'stat-total', value: overview.totalMemories.toLocaleString() },
      { id: 'stat-growth', value: null }, // handled specially
      { id: 'stat-projects', value: overview.uniqueProjects },
      { id: 'stat-avgwords', value: overview.avgWordsPerMemory },
    ];

    stats.forEach(stat => {
      if (stat.value === null) return;
      const el = this.querySelector(`#${stat.id}`);
      if (el) el.textContent = stat.value;
    });

    // Growth rate with color
    const growthEl = this.querySelector('#stat-growth');
    if (growthEl && overview.growthRate !== undefined) {
      const sign = overview.growthRate > 0 ? '+' : '';
      growthEl.textContent = `${sign}${overview.growthRate}%`;
      if (overview.growthRate > 0) growthEl.classList.add('positive');
      else if (overview.growthRate < 0) growthEl.classList.add('negative');
    }
  }

  /**
   * Render insights list
   */
  renderInsights() {
    const productivity = this.analytics.productivity;
    const categories = this.analytics.categories;
    const projects = this.analytics.projects;
    const overview = this.analytics.overview;
    const topTags = this.analytics.topTags;

    const insights = [];

    // Growth rate insights
    if (overview.growthRate !== undefined) {
      const trend = overview.growthRate > 0 ? 'increased' : (overview.growthRate < 0 ? 'decreased' : 'remained stable');
      insights.push(`Memory count ${trend} by ${Math.abs(overview.growthRate)}% in the last 7 days (${overview.recentWeekCount} vs ${overview.previousWeekCount})`);
    }

    // Peak productivity insights
    insights.push(`Your most productive hour is ${productivity.peakHour}:00`);
    insights.push(`You're most active on ${productivity.peakDay}s`);

    // Category insights
    if (categories.labels.length > 0) {
      const topCategory = categories.labels[categories.counts.indexOf(Math.max(...categories.counts))];
      const topCategoryCount = Math.max(...categories.counts);
      const topCategoryPercent = Math.round((topCategoryCount / overview.totalMemories) * 100);
      insights.push(`"${topCategory}" category accounts for ${topCategoryPercent}% of all memories`);
    }

    // Project insights
    if (projects.length > 0) {
      const topProject = projects.reduce((max, p) => p.count > max.count ? p : max);
      insights.push(`"${topProject.name}" is your most active project (${topProject.count} memories)`);
    }

    // Tag insights
    if (topTags && topTags.tags.length > 0) {
      const topTag = topTags.tags[0];
      const topTagCount = topTags.counts[0];
      insights.push(`"${topTag}" is your most used tag (${topTagCount} times)`);
    }

    // Productivity insights
    const avgPerDay = productivity.totalDays > 0 ? Math.round(overview.totalMemories / productivity.totalDays) : 0;
    if (avgPerDay > 0) {
      insights.push(`You create an average of ${avgPerDay} memories per day`);
    }

    // Content insights
    if (overview.avgWordsPerMemory > 0) {
      const contentLevel = overview.avgWordsPerMemory > 100 ? 'detailed' : (overview.avgWordsPerMemory > 50 ? 'moderate' : 'concise');
      insights.push(`You maintain ${contentLevel} records with an average of ${overview.avgWordsPerMemory} words per memory`);
    }

    const insightsContainer = this.querySelector('.analytics-insights-list');
    if (insightsContainer) {
      insightsContainer.innerHTML = insights.map(insight =>
        `<li class="analytics-insight-item">${insight}</li>`
      ).join('');
    }
  }

  // ── Chart.js rendering ──

  /**
   * Get Chart.js default options matching the theme
   */
  getChartDefaults() {
    const style = getComputedStyle(document.documentElement);
    const textMuted = style.getPropertyValue('--text-muted').trim() || '#a3a3a3';
    const textSecondary = style.getPropertyValue('--text-secondary').trim() || '#525252';
    const borderColor = style.getPropertyValue('--border-color').trim() || '#e5e5e5';
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const accentGray = isDark ? '#b0b0b0' : '#555555';
    const accentGrayAlpha = isDark ? 'rgba(176, 176, 176, 0.08)' : 'rgba(85, 85, 85, 0.08)';

    return { textMuted, textSecondary, borderColor, isDark, accentGray, accentGrayAlpha };
  }

  /**
   * Destroy existing chart before re-creating
   */
  destroyChart(key) {
    const existing = this.charts.get(key);
    if (existing) {
      existing.destroy();
      this.charts.delete(key);
    }
  }

  /**
   * Render all charts
   */
  renderCharts() {
    this.renderTrendChart();
    this.renderCategoryChart();
    this.renderProductivityChart();
    this.renderTagsChart();
  }

  /**
   * Render trend line chart
   */
  renderTrendChart() {
    const canvas = this.querySelector('#trend-chart');
    if (!canvas || !this.analytics.trends || !window.Chart) return;

    this.destroyChart('trend');

    const { dates, counts } = this.analytics.trends;
    if (counts.length === 0) return;

    const { textMuted, borderColor, accentGray, accentGrayAlpha } = this.getChartDefaults();

    // Format labels as short dates (MM/DD)
    const labels = dates.map(d => {
      const parts = d.split('-');
      return `${parseInt(parts[1])}/${parseInt(parts[2])}`;
    });

    const chart = new window.Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Memories',
          data: counts,
          borderColor: accentGray,
          backgroundColor: accentGrayAlpha,
          borderWidth: 2,
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: accentGray,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(0,0,0,0.8)',
            titleFont: { size: 11 },
            bodyFont: { size: 11 },
            padding: 8,
            cornerRadius: 4,
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: textMuted, font: { size: 10 }, maxTicksLimit: 8 },
            border: { color: borderColor },
          },
          y: {
            beginAtZero: true,
            grid: { color: borderColor + '40' },
            ticks: { color: textMuted, font: { size: 10 }, precision: 0 },
            border: { display: false },
          }
        }
      }
    });

    this.charts.set('trend', chart);
  }

  /**
   * Render category doughnut chart
   */
  renderCategoryChart() {
    const canvas = this.querySelector('#category-chart');
    if (!canvas || !this.analytics.categories || !window.Chart) return;

    this.destroyChart('category');

    const { labels, counts } = this.analytics.categories;
    if (counts.length === 0) return;

    const catColors = getCategoryColors();
    const colors = labels.map(l => catColors[l] || '#6b7280');

    const chart = new window.Chart(canvas, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{
          data: counts,
          backgroundColor: colors,
          borderWidth: 0,
          hoverOffset: 4,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '60%',
        plugins: {
          legend: {
            position: 'right',
            labels: {
              boxWidth: 10,
              boxHeight: 10,
              padding: 12,
              font: { size: 11 },
              color: getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim() || '#525252',
              usePointStyle: true,
              pointStyle: 'rectRounded',
            }
          },
          tooltip: {
            backgroundColor: 'rgba(0,0,0,0.8)',
            titleFont: { size: 11 },
            bodyFont: { size: 11 },
            padding: 8,
            cornerRadius: 4,
            callbacks: {
              label: (ctx) => {
                const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                const pct = total > 0 ? Math.round((ctx.parsed / total) * 100) : 0;
                return ` ${ctx.label}: ${ctx.parsed} (${pct}%)`;
              }
            }
          },
        },
      }
    });

    this.charts.set('category', chart);
  }

  /**
   * Render hourly productivity bar chart
   */
  renderProductivityChart() {
    const canvas = this.querySelector('#productivity-chart');
    if (!canvas || !this.analytics.productivity || !window.Chart) return;

    this.destroyChart('productivity');

    const { hourlyCount } = this.analytics.productivity;
    const { textMuted, borderColor, isDark } = this.getChartDefaults();

    const labels = Array.from({ length: 24 }, (_, i) => `${i}:00`);

    // Color bars by time of day — monotone tones
    const barColors = hourlyCount.map((_, h) => {
      if (isDark) {
        if (h >= 6 && h < 12) return '#d4d4d4';   // morning
        if (h >= 12 && h < 18) return '#b0b0b0';   // afternoon
        if (h >= 18 && h < 22) return '#8a8a8a';   // evening
        return '#606060';                            // night
      }
      if (h >= 6 && h < 12) return '#3d3d3d';   // morning
      if (h >= 12 && h < 18) return '#555555';   // afternoon
      if (h >= 18 && h < 22) return '#787878';   // evening
      return '#a0a0a0';                           // night
    });

    const chart = new window.Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Memories',
          data: hourlyCount,
          backgroundColor: barColors,
          borderRadius: 2,
          borderSkipped: false,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(0,0,0,0.8)',
            titleFont: { size: 11 },
            bodyFont: { size: 11 },
            padding: 8,
            cornerRadius: 4,
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: textMuted,
              font: { size: 10 },
              callback: (_, i) => i % 4 === 0 ? `${i}h` : '',
            },
            border: { color: borderColor },
          },
          y: {
            beginAtZero: true,
            grid: { color: borderColor + '40' },
            ticks: { color: textMuted, font: { size: 10 }, precision: 0 },
            border: { display: false },
          }
        }
      }
    });

    this.charts.set('productivity', chart);
  }

  /**
   * Render top tags horizontal bar chart
   */
  renderTagsChart() {
    const canvas = this.querySelector('#tags-chart');
    if (!canvas || !this.analytics.topTags || !window.Chart) return;

    this.destroyChart('tags');

    const { tags, counts } = this.analytics.topTags;
    if (tags.length === 0) return;

    const { textMuted, borderColor, accentGray } = this.getChartDefaults();

    // Show top 10
    const displayTags = tags.slice(0, 10);
    const displayCounts = counts.slice(0, 10);

    const chart = new window.Chart(canvas, {
      type: 'bar',
      data: {
        labels: displayTags,
        datasets: [{
          label: 'Count',
          data: displayCounts,
          backgroundColor: accentGray,
          borderRadius: 2,
          borderSkipped: false,
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(0,0,0,0.8)',
            titleFont: { size: 11 },
            bodyFont: { size: 11 },
            padding: 8,
            cornerRadius: 4,
          },
        },
        scales: {
          x: {
            beginAtZero: true,
            grid: { color: borderColor + '40' },
            ticks: { color: textMuted, font: { size: 10 }, precision: 0 },
            border: { display: false },
          },
          y: {
            grid: { display: false },
            ticks: { color: textMuted, font: { size: 11 } },
            border: { display: false },
          }
        }
      }
    });

    this.charts.set('tags', chart);
  }

  // ── Render ──

  render() {
    this.className = 'analytics';

    this.innerHTML = `
      <div class="analytics-toolbar">
        <span class="analytics-title">Analytics</span>
        <div class="analytics-actions">
          <select class="time-range-select">
            <option value="7d">7d</option>
            <option value="30d" selected>30d</option>
            <option value="90d">90d</option>
            <option value="1y">1y</option>
          </select>
          <button class="refresh-btn" title="Refresh">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"/></svg>
          </button>
        </div>
      </div>

      <div class="analytics-error" style="display:none;"></div>

      <div class="analytics-loading" style="display:none;">
        <div class="analytics-spinner"></div>
        <span>Analyzing memories...</span>
      </div>

      <div class="analytics-content">
        <div class="analytics-stats">
          <div class="analytics-stat-card">
            <span class="analytics-stat-label">Total Memories</span>
            <span class="analytics-stat-value" id="stat-total">0</span>
          </div>
          <div class="analytics-stat-card">
            <span class="analytics-stat-label">Growth (7d)</span>
            <span class="analytics-stat-value" id="stat-growth">0%</span>
          </div>
          <div class="analytics-stat-card">
            <span class="analytics-stat-label">Projects</span>
            <span class="analytics-stat-value" id="stat-projects">0</span>
          </div>
          <div class="analytics-stat-card">
            <span class="analytics-stat-label">Avg Words</span>
            <span class="analytics-stat-value" id="stat-avgwords">0</span>
          </div>
        </div>

        <div class="analytics-charts">
          <div class="analytics-chart-card">
            <span class="analytics-chart-title">Trend</span>
            <div class="analytics-chart-body"><canvas id="trend-chart"></canvas></div>
          </div>
          <div class="analytics-chart-card">
            <span class="analytics-chart-title">Categories</span>
            <div class="analytics-chart-body"><canvas id="category-chart"></canvas></div>
          </div>
          <div class="analytics-chart-card">
            <span class="analytics-chart-title">Hourly Activity</span>
            <div class="analytics-chart-body"><canvas id="productivity-chart"></canvas></div>
          </div>
          <div class="analytics-chart-card">
            <span class="analytics-chart-title">Top Tags</span>
            <div class="analytics-chart-body"><canvas id="tags-chart"></canvas></div>
          </div>
        </div>

        <div class="analytics-insights">
          <span class="analytics-insights-title">Insights</span>
          <ul class="analytics-insights-list"></ul>
        </div>
      </div>
    `;
  }
}

// Define the custom element
customElements.define('analytics-page', AnalyticsPage);

// Add component styles
const style = document.createElement('style');
style.textContent = `
/* ── Analytics — Linear-style ── */

.analytics {
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 60px);
  max-width: 960px;
  margin: 0 auto;
  padding: 0 var(--space-4);
}

/* ── Toolbar ── */

.analytics-toolbar {
  display: flex;
  align-items: center;
  padding: var(--space-4) 0 var(--space-2);
  gap: var(--space-3);
}

.analytics-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  flex: 1;
}

.analytics-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.analytics-actions .time-range-select {
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-xs);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
  color: var(--text-secondary);
  cursor: pointer;
  outline: none;
}

.analytics-actions .time-range-select:hover {
  border-color: var(--border-hover, var(--border-color));
}

.analytics-actions .refresh-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 80ms ease;
}

.analytics-actions .refresh-btn:hover {
  border-color: var(--border-hover, var(--border-color));
  color: var(--text-secondary);
  background: var(--bg-secondary);
}

/* ── Error ── */

.analytics-error {
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-3);
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
}

/* ── Loading ── */

.analytics-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-16) 0;
  color: var(--text-muted);
  font-size: var(--text-sm);
}

.analytics-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--border-color);
  border-top-color: var(--text-secondary);
  border-radius: 50%;
  animation: analytics-spin 0.8s linear infinite;
}

@keyframes analytics-spin {
  to { transform: rotate(360deg); }
}

/* ── Stats Row ── */

.analytics-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
  padding: var(--space-3) 0;
}

.analytics-stat-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-3);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
}

.analytics-stat-label {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--text-muted);
  white-space: nowrap;
}

.analytics-stat-value {
  font-size: var(--text-lg, 18px);
  font-weight: var(--font-bold, 700);
  color: var(--text-primary);
  line-height: 1;
}

.analytics-stat-value.positive {
  color: var(--text-secondary);
}

.analytics-stat-value.negative {
  color: var(--text-muted);
}

/* ── Charts Grid ── */

.analytics-charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
  padding: var(--space-2) 0;
}

.analytics-chart-card {
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.analytics-chart-title {
  display: block;
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-muted);
  border-bottom: 1px solid var(--border-color);
}

.analytics-chart-body {
  position: relative;
  height: 220px;
  padding: var(--space-3);
}

.analytics-chart-body canvas {
  width: 100% !important;
  height: 100% !important;
}

/* ── Insights ── */

.analytics-insights {
  padding: var(--space-3) 0 var(--space-6);
}

.analytics-insights-title {
  display: block;
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-muted);
  padding-bottom: var(--space-2);
}

.analytics-insights-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.analytics-insight-item {
  padding: 5px 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border-color);
  line-height: 1.5;
}

.analytics-insight-item:last-child {
  border-bottom: none;
}

/* ── Responsive ── */

@media (max-width: 640px) {
  .analytics {
    padding: 0 var(--space-3);
  }

  .analytics-stats {
    grid-template-columns: 1fr 1fr;
  }

  .analytics-charts {
    grid-template-columns: 1fr;
  }

  .analytics-chart-body {
    height: 200px;
  }
}

/* ── Reduced motion ── */

@media (prefers-reduced-motion: reduce) {
  .analytics-spinner {
    animation: none;
  }
}
`;

document.head.appendChild(style);

export { AnalyticsPage };
