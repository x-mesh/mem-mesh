/**
 * Analytics Page Web Component
 * Provides advanced analytics and insights for memories
 */

class AnalyticsPage extends HTMLElement {
  constructor() {
    super();
    this.memories = [];
    this.analytics = {};
    this.isLoading = false;
    this.charts = new Map();
    this.selectedTimeRange = '30d';
  }
  
  connectedCallback() {
    console.log('AnalyticsPage connected');
    this.render();
    this.setupEventListeners();
    
    // 약간의 지연 후 데이터 로드 (DOM이 완전히 렌더링된 후)
    setTimeout(() => {
      this.loadAnalytics();
    }, 100);
  }
  
  disconnectedCallback() {
    // Clean up charts
    this.charts.forEach(chart => {
      if (chart.destroy) chart.destroy();
    });
    this.charts.clear();
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    // Time range selector
    const timeRangeSelect = this.querySelector('.time-range-select');
    if (timeRangeSelect) {
      timeRangeSelect.addEventListener('change', this.handleTimeRangeChange.bind(this));
    }
    
    // Refresh button
    const refreshBtn = this.querySelector('.refresh-btn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', this.loadAnalytics.bind(this));
    }
    
    // Export button
    const exportBtn = this.querySelector('.export-btn');
    if (exportBtn) {
      exportBtn.addEventListener('click', this.handleExport.bind(this));
    }
    
    // Tab navigation
    const tabButtons = this.querySelectorAll('.tab-button');
    tabButtons.forEach(button => {
      button.addEventListener('click', this.handleTabClick.bind(this));
    });
  }
  
  /**
   * Load analytics data
   */
  async loadAnalytics() {
    try {
      this.setLoading(true);
      
      // Get all memories for analysis
      let searchResult;
      
      if (window.app && window.app.apiClient) {
        // Use app API client if available
        searchResult = await window.app.apiClient.searchMemories('', { 
          limit: 1000 // Get all memories
        });
      } else {
        // Direct API call as fallback
        console.log('App not ready, using direct API call for analytics');
        const response = await fetch('/api/memories/search?query=&limit=1000');
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        searchResult = await response.json();
      }
      
      if (searchResult && searchResult.results) {
        this.memories = searchResult.results;
        this.processAnalytics();
        this.renderAnalytics();
        this.renderCharts();
      } else {
        console.warn('No results found in analytics search response:', searchResult);
        this.memories = [];
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
      timeDistribution: this.calculateTimeDistribution(filteredMemories)
    };
  }
  
  /**
   * Calculate overview statistics
   */
  calculateOverview(memories) {
    const totalMemories = memories.length;
    const totalWords = memories.reduce((sum, m) => sum + (m.content?.split(/\s+/).length || 0), 0);
    const totalCharacters = memories.reduce((sum, m) => sum + (m.content?.length || 0), 0);
    const uniqueProjects = new Set(memories.map(m => m.project_id || 'default')).size;
    const uniqueCategories = new Set(memories.map(m => m.category)).size;
    const uniqueTags = new Set(memories.flatMap(m => m.tags || [])).size;
    
    const avgWordsPerMemory = totalMemories > 0 ? Math.round(totalWords / totalMemories) : 0;
    const avgCharsPerMemory = totalMemories > 0 ? Math.round(totalCharacters / totalMemories) : 0;
    
    return {
      totalMemories,
      totalWords,
      totalCharacters,
      uniqueProjects,
      uniqueCategories,
      uniqueTags,
      avgWordsPerMemory,
      avgCharsPerMemory
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
   * Handle tab click
   */
  handleTabClick(event) {
    const tabId = event.target.getAttribute('data-tab');
    
    // Update active tab
    this.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');
    
    // Show corresponding content
    this.querySelectorAll('.tab-content').forEach(content => {
      content.style.display = content.id === `${tabId}-tab` ? 'block' : 'none';
    });
    
    // Render charts for the active tab
    setTimeout(() => this.renderCharts(), 100);
  }
  
  /**
   * Handle export
   */
  async handleExport() {
    try {
      const exportData = {
        analytics: this.analytics,
        timeRange: this.selectedTimeRange,
        exported_at: new Date().toISOString(),
        total_memories_analyzed: this.memories.length
      };
      
      const blob = new Blob([JSON.stringify(exportData, null, 2)], {
        type: 'application/json'
      });
      
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `mem-mesh-analytics-${this.selectedTimeRange}-${new Date().toISOString().split('T')[0]}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      
    } catch (error) {
      console.error('Failed to export analytics:', error);
      this.showError('Failed to export analytics');
    }
  }
  
  /**
   * Set loading state
   */
  setLoading(loading) {
    this.isLoading = loading;
    
    const loadingEl = this.querySelector('.loading-state');
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
   * Render analytics data
   */
  renderAnalytics() {
    this.renderOverview();
    this.renderInsights();
  }
  
  /**
   * Render overview statistics
   */
  renderOverview() {
    const overview = this.analytics.overview;
    
    const stats = [
      { label: 'Total Memories', value: overview.totalMemories, id: 'total-memories' },
      { label: 'Total Words', value: overview.totalWords.toLocaleString(), id: 'total-words' },
      { label: 'Unique Projects', value: overview.uniqueProjects, id: 'unique-projects' },
      { label: 'Categories Used', value: overview.uniqueCategories, id: 'unique-categories' },
      { label: 'Avg Words/Memory', value: overview.avgWordsPerMemory, id: 'avg-words' },
      { label: 'Total Tags', value: overview.uniqueTags, id: 'unique-tags' }
    ];
    
    stats.forEach(stat => {
      const element = this.querySelector(`#${stat.id}`);
      if (element) element.textContent = stat.value;
    });
  }
  
  /**
   * Render insights
   */
  renderInsights() {
    const productivity = this.analytics.productivity;
    const categories = this.analytics.categories;
    const projects = this.analytics.projects;
    
    const insights = [];
    
    // Peak productivity insights
    insights.push(`Your most productive hour is ${productivity.peakHour}:00`);
    insights.push(`You're most active on ${productivity.peakDay}s`);
    insights.push(`${productivity.peakMonth} is your most productive month`);
    
    // Category insights
    if (categories.labels.length > 0) {
      const topCategory = categories.labels[categories.counts.indexOf(Math.max(...categories.counts))];
      insights.push(`Your most used category is "${topCategory}"`);
    }
    
    // Project insights
    if (projects.length > 0) {
      const topProject = projects.reduce((max, p) => p.count > max.count ? p : max);
      insights.push(`"${topProject.name}" is your most active project`);
    }
    
    // Productivity insights
    const avgPerDay = productivity.totalDays > 0 ? Math.round(this.analytics.overview.totalMemories / productivity.totalDays) : 0;
    insights.push(`You create an average of ${avgPerDay} memories per day`);
    
    const insightsContainer = this.querySelector('.insights-list');
    if (insightsContainer) {
      insightsContainer.innerHTML = insights.map(insight => 
        `<li class="insight-item"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16,17 21,12 16,7"/><line x1="21" y1="12" x2="9" y2="12"/></svg> ${insight}</li>`
      ).join('');
    }
  }
  
  /**
   * Render charts (simplified canvas-based charts)
   */
  renderCharts() {
    this.renderTrendChart();
    this.renderCategoryChart();
    this.renderProductivityChart();
    this.renderWordCloudChart();
  }
  
  /**
   * Render trend chart
   */
  renderTrendChart() {
    const canvas = this.querySelector('#trend-chart');
    if (!canvas || !this.analytics.trends) return;
    
    const ctx = canvas.getContext('2d');
    const { dates, counts } = this.analytics.trends;
    
    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    if (counts.length === 0) return;
    
    const padding = 40;
    const width = canvas.width - 2 * padding;
    const height = canvas.height - 2 * padding;
    const maxCount = Math.max(...counts, 1);
    
    // Draw axes
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padding, padding);
    ctx.lineTo(padding, canvas.height - padding);
    ctx.lineTo(canvas.width - padding, canvas.height - padding);
    ctx.stroke();
    
    // Draw line
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 2;
    ctx.beginPath();
    
    counts.forEach((count, index) => {
      const x = padding + (index / (counts.length - 1)) * width;
      const y = canvas.height - padding - (count / maxCount) * height;
      
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    
    ctx.stroke();
    
    // Draw points
    ctx.fillStyle = '#3b82f6';
    counts.forEach((count, index) => {
      const x = padding + (index / (counts.length - 1)) * width;
      const y = canvas.height - padding - (count / maxCount) * height;
      
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, 2 * Math.PI);
      ctx.fill();
    });
  }
  
  /**
   * Render category chart (simple bar chart)
   */
  renderCategoryChart() {
    const canvas = this.querySelector('#category-chart');
    if (!canvas || !this.analytics.categories) return;
    
    const ctx = canvas.getContext('2d');
    const { labels, counts } = this.analytics.categories;
    
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    if (counts.length === 0) return;
    
    const padding = 40;
    const width = canvas.width - 2 * padding;
    const height = canvas.height - 2 * padding;
    const maxCount = Math.max(...counts, 1);
    const barWidth = width / labels.length * 0.8;
    const barSpacing = width / labels.length * 0.2;
    
    const colors = ['#3b82f6', '#ef4444', '#f59e0b', '#8b5cf6', '#10b981', '#f97316'];
    
    counts.forEach((count, index) => {
      const x = padding + index * (barWidth + barSpacing) + barSpacing / 2;
      const barHeight = (count / maxCount) * height;
      const y = canvas.height - padding - barHeight;
      
      ctx.fillStyle = colors[index % colors.length];
      ctx.fillRect(x, y, barWidth, barHeight);
      
      // Draw label
      ctx.fillStyle = '#374151';
      ctx.font = '12px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(labels[index], x + barWidth / 2, canvas.height - padding + 20);
      
      // Draw count
      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 12px sans-serif';
      ctx.fillText(count.toString(), x + barWidth / 2, y + barHeight / 2 + 4);
    });
  }
  
  /**
   * Render productivity chart (hourly distribution)
   */
  renderProductivityChart() {
    const canvas = this.querySelector('#productivity-chart');
    if (!canvas || !this.analytics.productivity) return;
    
    const ctx = canvas.getContext('2d');
    const { hourlyCount } = this.analytics.productivity;
    
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    const padding = 40;
    const width = canvas.width - 2 * padding;
    const height = canvas.height - 2 * padding;
    const maxCount = Math.max(...hourlyCount, 1);
    const barWidth = width / 24;
    
    hourlyCount.forEach((count, hour) => {
      const x = padding + hour * barWidth;
      const barHeight = (count / maxCount) * height;
      const y = canvas.height - padding - barHeight;
      
      // Color based on time of day
      let color = '#64748b'; // Default
      if (hour >= 6 && hour < 12) color = '#f59e0b'; // Morning
      else if (hour >= 12 && hour < 18) color = '#3b82f6'; // Afternoon
      else if (hour >= 18 && hour < 22) color = '#8b5cf6'; // Evening
      else color = '#1f2937'; // Night
      
      ctx.fillStyle = color;
      ctx.fillRect(x, y, barWidth * 0.8, barHeight);
      
      // Draw hour label every 4 hours
      if (hour % 4 === 0) {
        ctx.fillStyle = '#374151';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(hour.toString(), x + barWidth * 0.4, canvas.height - padding + 15);
      }
    });
  }
  
  /**
   * Render word cloud chart (simplified)
   */
  renderWordCloudChart() {
    const container = this.querySelector('.word-cloud');
    if (!container || !this.analytics.wordFrequency) return;
    
    const { words, counts } = this.analytics.wordFrequency;
    const maxCount = Math.max(...counts, 1);
    
    container.innerHTML = words.map((word, index) => {
      const size = Math.max(12, (counts[index] / maxCount) * 32);
      const opacity = 0.6 + (counts[index] / maxCount) * 0.4;
      
      return `<span class="word-item" style="font-size: ${size}px; opacity: ${opacity}">${word}</span>`;
    }).join(' ');
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'analytics-page';
    
    this.innerHTML = `
      <div class="page-header">
        <h1>Analytics</h1>
        <div class="header-controls">
          <select class="time-range-select">
            <option value="7d">Last 7 days</option>
            <option value="30d" selected>Last 30 days</option>
            <option value="90d">Last 90 days</option>
            <option value="1y">Last year</option>
          </select>
          <button class="refresh-btn secondary-button"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"/></svg> Refresh</button>
          <button class="export-btn secondary-button"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7,10 12,15 17,10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Export</button>
        </div>
      </div>
      
      <div class="error-message" style="display: none;"></div>
      
      <div class="loading-state" style="display: none;">
        <div class="loading-spinner"></div>
        <p>Analyzing memories...</p>
      </div>
      
      <div class="analytics-content">
        <div class="overview-stats">
          <div class="stat-card">
            <span class="stat-label">Total Memories</span>
            <span class="stat-value" id="total-memories">0</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">Total Words</span>
            <span class="stat-value" id="total-words">0</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">Unique Projects</span>
            <span class="stat-value" id="unique-projects">0</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">Categories Used</span>
            <span class="stat-value" id="unique-categories">0</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">Avg Words/Memory</span>
            <span class="stat-value" id="avg-words">0</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">Total Tags</span>
            <span class="stat-value" id="unique-tags">0</span>
          </div>
        </div>
        
        <div class="insights-section">
          <h2><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16,17 21,12 16,7"/><line x1="21" y1="12" x2="9" y2="12"/></svg> Insights</h2>
          <ul class="insights-list"></ul>
        </div>
        
        <div class="tabs-container">
          <div class="tabs-header">
            <button class="tab-button active" data-tab="trends"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/></svg> Trends</button>
            <button class="tab-button" data-tab="categories"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg> Categories</button>
            <button class="tab-button" data-tab="productivity"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12,6 12,12 16,14"/></svg> Productivity</button>
            <button class="tab-button" data-tab="words"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10,9 9,9 8,9"/></svg> Word Analysis</button>
          </div>
          
          <div class="tabs-content">
            <div id="trends-tab" class="tab-content">
              <h3>Memory Creation Trends</h3>
              <div class="chart-container">
                <canvas id="trend-chart" width="800" height="300"></canvas>
              </div>
            </div>
            
            <div id="categories-tab" class="tab-content" style="display: none;">
              <h3>Category Distribution</h3>
              <div class="chart-container">
                <canvas id="category-chart" width="800" height="300"></canvas>
              </div>
            </div>
            
            <div id="productivity-tab" class="tab-content" style="display: none;">
              <h3>Hourly Productivity</h3>
              <div class="chart-container">
                <canvas id="productivity-chart" width="800" height="300"></canvas>
              </div>
              <div class="productivity-legend">
                <span class="legend-item"><span class="legend-color morning"></span> Morning (6-12)</span>
                <span class="legend-item"><span class="legend-color afternoon"></span> Afternoon (12-18)</span>
                <span class="legend-item"><span class="legend-color evening"></span> Evening (18-22)</span>
                <span class="legend-item"><span class="legend-color night"></span> Night (22-6)</span>
              </div>
            </div>
            
            <div id="words-tab" class="tab-content" style="display: none;">
              <h3>Most Frequent Words</h3>
              <div class="word-cloud"></div>
            </div>
          </div>
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
  .analytics-page {
    padding: var(--space-6) 0; /* 상하 패딩만 유지, 좌우는 main-content에서 처리 */
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
  
  .header-controls {
    display: flex;
    align-items: center;
    gap: 1rem;
  }
  
  .time-range-select {
    padding: 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    background: var(--bg-primary);
    color: var(--text-primary);
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
  
  .overview-stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
  }
  
  .stat-card {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 1.5rem;
    text-align: center;
  }
  
  .stat-label {
    display: block;
    font-size: 0.875rem;
    color: var(--text-secondary);
    margin-bottom: 0.5rem;
  }
  
  .stat-value {
    display: block;
    font-size: 2rem;
    font-weight: bold;
    color: var(--primary-color);
  }
  
  .insights-section {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 1.5rem;
    margin-bottom: 2rem;
  }
  
  .insights-section h2 {
    margin: 0 0 1rem 0;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  
  .insights-section h2 svg {
    width: 20px;
    height: 20px;
    stroke: currentColor;
  }
  
  .insights-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  
  .insight-item {
    padding: 0.5rem 0;
    color: var(--text-secondary);
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  
  .insight-item svg {
    width: 16px;
    height: 16px;
    stroke: currentColor;
    flex-shrink: 0;
  }
  
  .insight-item:last-child {
    border-bottom: none;
  }
  
  .tabs-container {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    overflow: hidden;
  }
  
  .tabs-header {
    display: flex;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
  }
  
  .tab-button {
    background: none;
    border: none;
    padding: 1rem 1.5rem;
    cursor: pointer;
    color: var(--text-secondary);
    font-size: 0.875rem;
    font-weight: 500;
    transition: var(--transition);
    border-right: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  
  .tab-button svg {
    width: 16px;
    height: 16px;
    stroke: currentColor;
  }
  
  .tab-button:last-child {
    border-right: none;
  }
  
  .tab-button:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }
  
  .tab-button.active {
    background: var(--primary-color);
    color: white;
  }
  
  .tabs-content {
    padding: 2rem;
  }
  
  .tab-content h3 {
    margin: 0 0 1.5rem 0;
    color: var(--text-primary);
  }
  
  .chart-container {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 1rem;
    margin-bottom: 1rem;
    overflow-x: auto;
  }
  
  .chart-container canvas {
    max-width: 100%;
    height: auto;
  }
  
  .productivity-legend {
    display: flex;
    justify-content: center;
    gap: 2rem;
    flex-wrap: wrap;
  }
  
  .legend-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
    color: var(--text-secondary);
  }
  
  .legend-color {
    width: 16px;
    height: 16px;
    border-radius: 2px;
  }
  
  .legend-color.morning { background: #f59e0b; }
  .legend-color.afternoon { background: #3b82f6; }
  .legend-color.evening { background: #8b5cf6; }
  .legend-color.night { background: #1f2937; }
  
  .word-cloud {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 2rem;
    text-align: center;
    line-height: 2;
  }
  
  .word-item {
    display: inline-block;
    margin: 0.25rem;
    color: var(--primary-color);
    font-weight: 500;
    cursor: default;
    transition: var(--transition);
  }
  
  .word-item:hover {
    color: var(--primary-hover);
    transform: scale(1.1);
  }
  
  /* Responsive design */
  @media (max-width: 768px) {
    .analytics-page {
      padding: var(--space-4) 0; /* 모바일에서 상하 패딩 줄임 */
    }
    
    .page-header {
      flex-direction: column;
      align-items: flex-start;
      gap: 1rem;
    }
    
    .header-controls {
      align-self: stretch;
      justify-content: space-between;
    }
    
    .overview-stats {
      grid-template-columns: repeat(2, 1fr);
    }
    
    .tabs-header {
      flex-wrap: wrap;
    }
    
    .tab-button {
      flex: 1;
      min-width: 120px;
    }
    
    .tabs-content {
      padding: 1rem;
    }
    
    .productivity-legend {
      gap: 1rem;
    }
    
    .chart-container canvas {
      width: 100%;
    }
  }
  
  @media (max-width: 480px) {
    .overview-stats {
      grid-template-columns: 1fr;
    }
    
    .stat-value {
      font-size: 1.5rem;
    }
  }
`;

document.head.appendChild(style);

export { AnalyticsPage };