/**
 * Work Tracking Page Component
 * Pin/Session 기반 작업 추적 대시보드
 */

import { showToast } from '../utils/toast-notifications.js';

class WorkPage extends HTMLElement {
  constructor() {
    super();
    this.pins = [];
    this.sessions = [];
    this.projects = [];
    this.stats = null;
    this.selectedProject = null;
    this.isLoading = true;
    this.currentView = 'kanban';
    this.completedPinsLimit = 10;
    this.activeSession = null;
    this.sessionHistory = [];
    // Phase 3: Filters
    this.filters = {
      importance: null,
      tags: [],
      dateRange: null,
      search: '',
      sortBy: 'importance', // importance, date, status
      sortDir: 'desc'
    };
    // Phase 3: Batch selection
    this.selectedPinIds = new Set();
    this.batchMode = false;
    // IME composition state
    this._isComposing = false;
    this._searchDebounceTimer = null;
  }

  connectedCallback() {
    this.render();
    this.loadData();
  }

  async loadData() {
    this.isLoading = true;
    this.updateLoadingState();

    try {
      const api = window.app.apiClient;
      const [pinsData, projectsData, sessionsData] = await Promise.all([
        api.get('/work/pins', { limit: 100 }),
        api.get('/work/projects'),
        api.get('/work/sessions', { limit: 20 })
      ]);

      this.pins = pinsData.pins || [];
      this.projects = projectsData.projects || [];
      this.sessions = sessionsData.sessions || [];

      // 활성 세션 찾기
      this.activeSession = this.sessions.find(s => s.status === 'active') || null;
      this.sessionHistory = this.sessions.filter(s => s.status !== 'active');

      // 프로젝트 통계 로드
      let projectId = this.selectedProject;
      if (!projectId && this.projects.length > 0) {
        projectId = this.projects[0].id;
      }
      if (!projectId && this.pins.length > 0) {
        projectId = this.pins[0].project_id;
      }
      if (projectId) {
        try {
          this.stats = await api.get(`/work/projects/${projectId}/stats`);
        } catch { /* stats load failure is non-critical */ }
      }

    } catch (error) {
      showToast(`Failed to load work data: ${error.message}`, 'error');
    } finally {
      this.isLoading = false;
      this.render();
      this.updateProjectFilter();
    }
  }

  updateProjectFilter() {
    const projectFilter = this.querySelector('#project-filter');
    if (projectFilter && projectFilter.setOptions) {
      let projectOptions = [{ value: '', text: 'All Projects' }];
      if (this.projects && this.projects.length > 0) {
        projectOptions = projectOptions.concat(
          this.projects.map(p => ({ value: p.id, text: p.id }))
        );
      } else if (this.pins && this.pins.length > 0) {
        const projectIds = [...new Set(this.pins.map(p => p.project_id))];
        projectOptions = projectOptions.concat(
          projectIds.map(id => ({ value: id, text: id }))
        );
      }
      projectFilter.setOptions(projectOptions);
    }

    this.updateTagFilter();
  }

  updateTagFilter() {
    const tagFilter = this.querySelector('#filter-tag');
    if (tagFilter && tagFilter.setOptions) {
      const allTags = [...new Set(this.pins.flatMap(p => p.tags || []))].sort();
      const tagOptions = [{ value: '', text: 'All Tags' }].concat(
        allTags.map(t => ({ value: t, text: t }))
      );
      tagFilter.setOptions(tagOptions);

      // 현재 선택된 태그가 있으면 복원
      if (this.filters.tags.length > 0) {
        tagFilter.setValue(this.filters.tags[0]);
      }
    }
  }

  updateLoadingState() {
    const content = this.querySelector('.work-content');
    if (content) {
      content.style.opacity = this.isLoading ? '0.5' : '1';
    }
  }

  render() {
    this.innerHTML = `
      <div class="work-page chroma-page page-container">
        <div class="page-header">
          <div class="page-header-main">
            <h1 class="page-title">Work Tracking</h1>
            <p class="page-subtitle">Pin-based Task Tracking and Session Management</p>
          </div>
          <div class="page-header-actions">
            <div class="project-filter-container">
              <label for="project-filter" class="filter-label">Project:</label>
              <searchable-combobox id="project-filter" placeholder="All Projects">
                ${this.renderProjectOptions()}
              </searchable-combobox>
            </div>
            <button class="btn btn-primary" id="new-pin-btn">
              <svg viewBox="0 0 24 24" fill="none" width="16" height="16">
                <path d="M12 5V19M5 12H19" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
              New Pin
            </button>
          </div>
        </div>

        <div class="work-content">
          ${this.isLoading ? this.renderLoading() : this.renderContent()}
        </div>
      </div>

      ${this.renderNewPinModal()}
      ${this.renderEditPinModal()}
      ${this.renderSessionEndModal()}
    `;

    this.attachEventListeners();
  }

  renderLoading() {
    return `
      <div class="loading-container">
        <div class="loading-spinner"></div>
        <p>Loading work data...</p>
      </div>
    `;
  }

  renderContent() {
    return `
      <!-- Active Session Banner -->
      ${this.renderSessionBanner()}

      <!-- Stats Cards -->
      <div class="work-stats-grid">
        ${this.renderStatsCards()}
      </div>

      <!-- Filter Bar (stable — not re-rendered on filter change) -->
      ${this.renderFilterBar()}

      <!-- Pins Area (re-rendered on filter/sort change) -->
      <div class="pins-area">
        ${this.renderPinsArea()}
      </div>

      <!-- Session History -->
      ${this.renderSessionHistory()}
    `;
  }

  renderPinsArea() {
    return `
      <div class="kanban-section">
        <div class="section-header">
          <h2>Active Pins</h2>
          <div class="section-header-actions">
            ${this.batchMode ? `
              <span class="batch-count">${this.selectedPinIds.size} selected</span>
              <button class="btn btn-sm btn-secondary" id="batch-complete-btn" ${this.selectedPinIds.size === 0 ? 'disabled' : ''}>Complete</button>
              <button class="btn btn-sm btn-danger" id="batch-delete-btn" ${this.selectedPinIds.size === 0 ? 'disabled' : ''}>Delete</button>
              <button class="btn btn-sm btn-secondary" id="batch-cancel-btn">Cancel</button>
            ` : `
              <button class="btn btn-sm btn-secondary" id="batch-mode-btn">Select</button>
            `}
            <div class="view-toggle">
              <button class="view-btn ${this.currentView === 'kanban' ? 'active' : ''}" data-view="kanban">Kanban</button>
              <button class="view-btn ${this.currentView === 'list' ? 'active' : ''}" data-view="list">List</button>
            </div>
          </div>
        </div>
        ${this.currentView === 'kanban' ? this.renderKanbanBoard() : this.renderListView()}
      </div>
    `;
  }

  /**
   * 핀 목록만 업데이트 (filter bar, search input 유지)
   */
  updatePinsOnly() {
    const pinsArea = this.querySelector('.pins-area');
    if (pinsArea) {
      pinsArea.innerHTML = this.renderPinsArea();
      this.attachPinsAreaEventListeners();
    }
    // stats도 갱신
    const statsGrid = this.querySelector('.work-stats-grid');
    if (statsGrid) {
      statsGrid.innerHTML = this.renderStatsCards();
    }
  }

  // SVG Icons
  static icons = {
    pin: `<svg viewBox="0 0 24 24" fill="none" width="20" height="20"><path d="M12 2L12 8M12 8L8 12V14H10L12 22L14 14H16V12L12 8Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    progress: `<svg viewBox="0 0 24 24" fill="none" width="20" height="20"><path d="M12 2V6M12 18V22M4.93 4.93L7.76 7.76M16.24 16.24L19.07 19.07M2 12H6M18 12H22M4.93 19.07L7.76 16.24M16.24 7.76L19.07 4.93" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
    check: `<svg viewBox="0 0 24 24" fill="none" width="20" height="20"><path d="M20 6L9 17L4 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    clock: `<svg viewBox="0 0 24 24" fill="none" width="20" height="20"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.5"/><path d="M12 7V12L15 15" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
    star: `<svg viewBox="0 0 24 24" fill="none" width="12" height="12"><path d="M12 2L14.09 8.26L21 9.27L16 14.14L17.18 21.02L12 17.77L6.82 21.02L8 14.14L3 9.27L9.91 8.26L12 2Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>`,
    starFilled: `<svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12"><path d="M12 2L14.09 8.26L21 9.27L16 14.14L17.18 21.02L12 17.77L6.82 21.02L8 14.14L3 9.27L9.91 8.26L12 2Z"/></svg>`,
    upload: `<svg viewBox="0 0 24 24" fill="none" width="14" height="14"><path d="M12 15V3M12 3L8 7M12 3L16 7M4 17V19C4 20.1 4.9 21 6 21H18C19.1 21 20 20.1 20 19V17" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    checkSmall: `<svg viewBox="0 0 24 24" fill="none" width="14" height="14"><path d="M20 6L9 17L4 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    edit: `<svg viewBox="0 0 24 24" fill="none" width="14" height="14"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    trash: `<svg viewBox="0 0 24 24" fill="none" width="14" height="14"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    session: `<svg viewBox="0 0 24 24" fill="none" width="16" height="16"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    stop: `<svg viewBox="0 0 24 24" fill="none" width="14" height="14"><rect x="6" y="6" width="12" height="12" rx="2" stroke="currentColor" stroke-width="1.5"/></svg>`,
    filter: `<svg viewBox="0 0 24 24" fill="none" width="14" height="14"><path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    search: `<svg viewBox="0 0 24 24" fill="none" width="14" height="14"><circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="1.5"/><path d="M21 21l-4.35-4.35" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`
  };

  renderProjectOptions() {
    let projectIds = [];
    if (this.projects && this.projects.length > 0) {
      projectIds = this.projects.map(p => p.id);
    } else {
      projectIds = [...new Set(this.pins.map(p => p.project_id))];
    }
    return `
      <option value="" ${!this.selectedProject ? 'selected' : ''}>All Projects</option>
      ${projectIds.map(projectId => `
        <option value="${projectId}" ${this.selectedProject === projectId ? 'selected' : ''}>
          ${projectId}
        </option>
      `).join('')}
    `;
  }

  getFilteredPins() {
    let pins = this.pins;

    // Project filter
    if (this.selectedProject) {
      pins = pins.filter(p => p.project_id === this.selectedProject);
    }

    // Importance filter
    if (this.filters.importance !== null) {
      pins = pins.filter(p => p.importance >= this.filters.importance);
    }

    // Tag filter
    if (this.filters.tags.length > 0) {
      pins = pins.filter(p =>
        this.filters.tags.some(tag => (p.tags || []).includes(tag))
      );
    }

    // Search filter
    if (this.filters.search) {
      const q = this.filters.search.toLowerCase();
      pins = pins.filter(p =>
        p.content.toLowerCase().includes(q) ||
        p.project_id.toLowerCase().includes(q) ||
        (p.tags || []).some(t => t.toLowerCase().includes(q))
      );
    }

    // Date range filter
    if (this.filters.dateRange) {
      const now = Date.now();
      const ranges = { '1d': 86400000, '7d': 604800000, '30d': 2592000000 };
      const ms = ranges[this.filters.dateRange];
      if (ms) {
        pins = pins.filter(p => now - new Date(p.created_at).getTime() <= ms);
      }
    }

    // Sorting
    pins = [...pins].sort((a, b) => {
      let cmp = 0;
      if (this.filters.sortBy === 'importance') {
        cmp = a.importance - b.importance;
      } else if (this.filters.sortBy === 'date') {
        cmp = new Date(a.created_at) - new Date(b.created_at);
      } else if (this.filters.sortBy === 'status') {
        const order = { open: 0, in_progress: 1, completed: 2 };
        cmp = (order[a.status] || 0) - (order[b.status] || 0);
      }
      return this.filters.sortDir === 'desc' ? -cmp : cmp;
    });

    return pins;
  }

  // ===== Session Banner (Phase 2) =====

  renderSessionBanner() {
    if (!this.activeSession) return '';

    const elapsed = this.getElapsedTime(this.activeSession.started_at);
    const pinCount = this.pins.filter(p => p.session_id === this.activeSession.id).length;

    return `
      <div class="session-banner">
        <div class="session-banner-info">
          ${WorkPage.icons.session}
          <div class="session-banner-text">
            <span class="session-banner-title">Active Session</span>
            <span class="session-banner-meta">${this.escapeHtml(this.activeSession.project_id)} &middot; ${elapsed} &middot; ${pinCount} pins</span>
          </div>
        </div>
        <button class="btn btn-sm btn-secondary" id="end-session-btn">
          ${WorkPage.icons.stop} End Session
        </button>
      </div>
    `;
  }

  renderSessionEndModal() {
    return `
      <div class="modal-overlay" id="end-session-modal" style="display: none;">
        <div class="modal-content">
          <div class="modal-header">
            <h3>End Session</h3>
            <button class="modal-close" id="close-session-modal">&times;</button>
          </div>
          <form id="end-session-form">
            <div class="form-group">
              <label for="session-summary">Session Summary (optional)</label>
              <textarea id="session-summary" rows="3" placeholder="What did you accomplish in this session?"></textarea>
            </div>
            <div class="form-actions">
              <button type="button" class="btn btn-secondary" id="cancel-session-end">Cancel</button>
              <button type="submit" class="btn btn-primary">End Session</button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  // ===== Session History (Phase 2) =====

  renderSessionHistory() {
    if (this.sessionHistory.length === 0) return '';

    return `
      <div class="session-history-section">
        <div class="section-header">
          <h2>Session History</h2>
          <span class="section-count">${this.sessionHistory.length}</span>
        </div>
        <div class="session-history-list">
          ${this.sessionHistory.slice(0, 10).map(s => this.renderSessionItem(s)).join('')}
        </div>
      </div>
    `;
  }

  renderSessionItem(session) {
    const duration = session.started_at && session.ended_at
      ? this.getTimeDiff(session.started_at, session.ended_at)
      : '-';
    const pinCount = this.pins.filter(p => p.session_id === session.id).length;

    return `
      <div class="session-item" data-session-id="${session.id}">
        <div class="session-item-info">
          <span class="session-item-project">${this.escapeHtml(session.project_id)}</span>
          <span class="session-item-meta">${this.formatTime(session.started_at)} &middot; ${duration} &middot; ${pinCount} pins</span>
          ${session.summary ? `<p class="session-item-summary">${this.escapeHtml(session.summary)}</p>` : ''}
        </div>
        <button class="btn btn-sm btn-secondary session-pins-toggle" data-session-id="${session.id}">Pins</button>
      </div>
    `;
  }

  // ===== Filter Bar (Phase 3) =====

  renderFilterBar() {
    const allTags = [...new Set(this.pins.flatMap(p => p.tags || []))].sort();

    return `
      <div class="filter-bar">
        <div class="filter-bar-left">
          <div class="filter-search">
            ${WorkPage.icons.search}
            <input type="text" id="pin-search" placeholder="Search pins..." value="${this.escapeHtml(this.filters.search)}">
          </div>
          <select id="filter-importance" class="filter-select">
            <option value="">All Importance</option>
            <option value="1" ${this.filters.importance === 1 ? 'selected' : ''}>1+</option>
            <option value="2" ${this.filters.importance === 2 ? 'selected' : ''}>2+</option>
            <option value="3" ${this.filters.importance === 3 ? 'selected' : ''}>3+</option>
            <option value="4" ${this.filters.importance === 4 ? 'selected' : ''}>4+</option>
            <option value="5" ${this.filters.importance === 5 ? 'selected' : ''}>5</option>
          </select>
          <select id="filter-date" class="filter-select">
            <option value="">All Time</option>
            <option value="1d" ${this.filters.dateRange === '1d' ? 'selected' : ''}>Last 24h</option>
            <option value="7d" ${this.filters.dateRange === '7d' ? 'selected' : ''}>Last 7 days</option>
            <option value="30d" ${this.filters.dateRange === '30d' ? 'selected' : ''}>Last 30 days</option>
          </select>
          <searchable-combobox id="filter-tag" placeholder="All Tags" class="filter-tag-combobox">
            <option value="" selected>All Tags</option>
            ${allTags.map(t => `<option value="${this.escapeHtml(t)}">${this.escapeHtml(t)}</option>`).join('')}
          </searchable-combobox>
        </div>
        <div class="filter-bar-right">
          <select id="sort-by" class="filter-select">
            <option value="importance" ${this.filters.sortBy === 'importance' ? 'selected' : ''}>Sort: Importance</option>
            <option value="date" ${this.filters.sortBy === 'date' ? 'selected' : ''}>Sort: Date</option>
            <option value="status" ${this.filters.sortBy === 'status' ? 'selected' : ''}>Sort: Status</option>
          </select>
          <button class="btn btn-sm btn-secondary" id="sort-dir-btn" title="Toggle sort direction">
            ${this.filters.sortDir === 'desc' ? '↓' : '↑'}
          </button>
        </div>
      </div>
    `;
  }

  renderStatsCards() {
    const filteredPins = this.getFilteredPins();
    const openPins = filteredPins.filter(p => p.status === 'open').length;
    const inProgressPins = filteredPins.filter(p => p.status === 'in_progress').length;
    const completedPins = filteredPins.filter(p => p.status === 'completed').length;

    const completedWithLeadTime = filteredPins.filter(p => p.status === 'completed' && p.lead_time_hours != null);
    const avgLeadTime = completedWithLeadTime.length > 0
      ? completedWithLeadTime.reduce((sum, p) => sum + p.lead_time_hours, 0) / completedWithLeadTime.length
      : null;

    return `
      <div class="stat-card open">
        <div class="stat-icon">${WorkPage.icons.pin}</div>
        <div class="stat-info">
          <div class="stat-number">${openPins}</div>
          <div class="stat-label">Open</div>
        </div>
      </div>
      <div class="stat-card in-progress">
        <div class="stat-icon">${WorkPage.icons.progress}</div>
        <div class="stat-info">
          <div class="stat-number">${inProgressPins}</div>
          <div class="stat-label">In Progress</div>
        </div>
      </div>
      <div class="stat-card completed">
        <div class="stat-icon">${WorkPage.icons.check}</div>
        <div class="stat-info">
          <div class="stat-number">${completedPins}</div>
          <div class="stat-label">Completed</div>
        </div>
      </div>
      <div class="stat-card lead-time">
        <div class="stat-icon">${WorkPage.icons.clock}</div>
        <div class="stat-info">
          <div class="stat-number">${avgLeadTime ? avgLeadTime.toFixed(1) + 'h' : '-'}</div>
          <div class="stat-label">Avg Lead Time</div>
        </div>
      </div>
    `;
  }

  renderKanbanBoard() {
    const filteredPins = this.getFilteredPins();
    const openPins = filteredPins.filter(p => p.status === 'open');
    const inProgressPins = filteredPins.filter(p => p.status === 'in_progress');
    const allCompleted = filteredPins.filter(p => p.status === 'completed');
    const completedPins = allCompleted.slice(0, this.completedPinsLimit);
    const hasMore = allCompleted.length > this.completedPinsLimit;

    return `
      <div class="kanban-board">
        <div class="kanban-column" data-status="open">
          <div class="column-header">
            <span class="column-title">Open</span>
            <span class="column-count">${openPins.length}</span>
          </div>
          <div class="column-content">
            ${openPins.map(pin => this.renderPinCard(pin)).join('')}
          </div>
        </div>
        <div class="kanban-column" data-status="in_progress">
          <div class="column-header">
            <span class="column-title">In Progress</span>
            <span class="column-count">${inProgressPins.length}</span>
          </div>
          <div class="column-content">
            ${inProgressPins.map(pin => this.renderPinCard(pin)).join('')}
          </div>
        </div>
        <div class="kanban-column" data-status="completed">
          <div class="column-header">
            <span class="column-title">Completed</span>
            <span class="column-count">${allCompleted.length}</span>
          </div>
          <div class="column-content">
            ${completedPins.map(pin => this.renderPinCard(pin)).join('')}
            ${hasMore ? `
              <button class="btn btn-sm btn-secondary load-more-btn" id="load-more-completed">
                Show more (${allCompleted.length - this.completedPinsLimit} remaining)
              </button>
            ` : ''}
          </div>
        </div>
      </div>
    `;
  }

  renderListView() {
    const filteredPins = this.getFilteredPins();
    return `
      <div class="pins-list">
        ${filteredPins.map(pin => this.renderPinListItem(pin)).join('')}
        ${filteredPins.length === 0 ? '<p class="empty-message">No pins yet. Create your first pin!</p>' : ''}
      </div>
    `;
  }

  renderImportanceStars(importance) {
    return Array(importance).fill(WorkPage.icons.starFilled).join('');
  }

  renderPinCard(pin) {
    const tags = pin.tags || [];
    const isSelected = this.selectedPinIds.has(pin.id);

    return `
      <div class="pin-card ${isSelected ? 'selected' : ''}" 
           data-pin-id="${pin.id}" 
           data-status="${pin.status}"
           draggable="${!this.batchMode}">
        <div class="pin-header">
          ${this.batchMode ? `
            <input type="checkbox" class="pin-checkbox" data-pin-id="${pin.id}" ${isSelected ? 'checked' : ''}>
          ` : ''}
          <div class="pin-project-badge">${this.escapeHtml(pin.project_id)}</div>
          <span class="pin-importance" title="Importance: ${pin.importance}">${this.renderImportanceStars(pin.importance)}</span>
          <div class="pin-card-actions">
            <button class="pin-action-btn edit-btn" data-pin-id="${pin.id}" title="Edit">${WorkPage.icons.edit}</button>
            ${pin.status !== 'completed' ? `
              <button class="pin-action-btn complete-btn" data-pin-id="${pin.id}" title="Complete">${WorkPage.icons.checkSmall}</button>
            ` : ''}
            ${pin.importance >= 4 && pin.status === 'completed' ? `
              <button class="pin-action-btn promote-btn" data-pin-id="${pin.id}" title="Promote to Memory">${WorkPage.icons.upload}</button>
            ` : ''}
            <button class="pin-action-btn delete-btn" data-pin-id="${pin.id}" title="Delete">${WorkPage.icons.trash}</button>
          </div>
        </div>
        <div class="pin-content">${this.escapeHtml(pin.content)}</div>
        ${tags.length > 0 ? `
          <div class="pin-tags">
            ${tags.map(tag => `<span class="pin-tag">${this.escapeHtml(tag)}</span>`).join('')}
          </div>
        ` : ''}
        <div class="pin-footer">
          <span class="pin-time">${this.formatTime(pin.created_at)}</span>
        </div>
      </div>
    `;
  }

  renderPinListItem(pin) {
    const statusClass = pin.status.replace('_', '-');
    const isSelected = this.selectedPinIds.has(pin.id);

    return `
      <div class="pin-list-item ${statusClass} ${isSelected ? 'selected' : ''}" data-pin-id="${pin.id}">
        ${this.batchMode ? `
          <input type="checkbox" class="pin-checkbox" data-pin-id="${pin.id}" ${isSelected ? 'checked' : ''}>
        ` : ''}
        <div class="pin-status-indicator"></div>
        <div class="pin-main">
          <div class="pin-content">${this.escapeHtml(pin.content)}</div>
          <div class="pin-meta">
            <span class="pin-importance">${this.renderImportanceStars(pin.importance)}</span>
            <span class="pin-project">${pin.project_id}</span>
            <span class="pin-time">${this.formatTime(pin.created_at)}</span>
          </div>
        </div>
        <div class="pin-actions">
          <button class="btn-icon edit-btn" data-pin-id="${pin.id}" title="Edit">${WorkPage.icons.edit}</button>
          ${pin.status !== 'completed' ? `
            <button class="btn-icon complete-btn" data-pin-id="${pin.id}">${WorkPage.icons.checkSmall}</button>
          ` : ''}
          ${pin.importance >= 4 && pin.status === 'completed' ? `
            <button class="btn-icon promote-btn" data-pin-id="${pin.id}">${WorkPage.icons.upload}</button>
          ` : ''}
          <button class="btn-icon delete-btn" data-pin-id="${pin.id}" title="Delete">${WorkPage.icons.trash}</button>
        </div>
      </div>
    `;
  }

  renderNewPinModal() {
    return `
      <div class="modal-overlay" id="new-pin-modal" style="display: none;">
        <div class="modal-content">
          <div class="modal-header">
            <h3>New Pin</h3>
            <button class="modal-close" id="close-modal">&times;</button>
          </div>
          <form id="new-pin-form">
            <div class="form-group">
              <label for="pin-content">Content</label>
              <textarea id="pin-content" rows="3" placeholder="What are you working on?" required></textarea>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label for="pin-project">Project</label>
                <input type="text" id="pin-project" value="default" placeholder="Project ID">
              </div>
              <div class="form-group">
                <label for="pin-importance">Importance</label>
                <select id="pin-importance">
                  <option value="1">1 - Low</option>
                  <option value="2">2</option>
                  <option value="3" selected>3 - Medium</option>
                  <option value="4">4</option>
                  <option value="5">5 - High</option>
                </select>
              </div>
            </div>
            <div class="form-group">
              <label for="pin-tags">Tags (comma separated)</label>
              <input type="text" id="pin-tags" placeholder="bug, feature, urgent">
            </div>
            <div class="form-actions">
              <button type="button" class="btn btn-secondary" id="cancel-pin">Cancel</button>
              <button type="submit" class="btn btn-primary">Create Pin</button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  renderEditPinModal() {
    return `
      <div class="modal-overlay" id="edit-pin-modal" style="display: none;">
        <div class="modal-content">
          <div class="modal-header">
            <h3>Edit Pin</h3>
            <button class="modal-close" id="close-edit-modal">&times;</button>
          </div>
          <form id="edit-pin-form">
            <input type="hidden" id="edit-pin-id">
            <div class="form-group">
              <label for="edit-pin-content">Content</label>
              <textarea id="edit-pin-content" rows="3" required></textarea>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label for="edit-pin-importance">Importance</label>
                <select id="edit-pin-importance">
                  <option value="1">1 - Low</option>
                  <option value="2">2</option>
                  <option value="3">3 - Medium</option>
                  <option value="4">4</option>
                  <option value="5">5 - High</option>
                </select>
              </div>
              <div class="form-group">
                <label for="edit-pin-status">Status</label>
                <select id="edit-pin-status">
                  <option value="open">Open</option>
                  <option value="in_progress">In Progress</option>
                  <option value="completed">Completed</option>
                </select>
              </div>
            </div>
            <div class="form-group">
              <label for="edit-pin-tags">Tags (comma separated)</label>
              <input type="text" id="edit-pin-tags">
            </div>
            <div class="form-actions">
              <button type="button" class="btn btn-secondary" id="cancel-edit-pin">Cancel</button>
              <button type="submit" class="btn btn-primary">Save</button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  /**
   * 콘텐츠만 업데이트 (프로젝트 필터 유지)
   */
  updateContent() {
    const workContent = this.querySelector('.work-content');
    if (workContent) {
      workContent.innerHTML = this.isLoading ? this.renderLoading() : this.renderContent();
      this.attachContentEventListeners();
    }
  }

  /**
   * 콘텐츠 영역 이벤트 리스너 (filter bar + pins area)
   */
  attachContentEventListeners() {
    // Session end button
    const endSessionBtn = this.querySelector('#end-session-btn');
    if (endSessionBtn) {
      endSessionBtn.addEventListener('click', () => this.showSessionEndModal());
    }

    // Session pins toggle
    this.querySelectorAll('.session-pins-toggle').forEach(btn => {
      btn.addEventListener('click', () => this.toggleSessionPins(btn.dataset.sessionId));
    });

    // ===== Filter bar listeners (stable, not re-rendered on filter change) =====
    this.attachFilterBarListeners();

    // ===== Pins area listeners =====
    this.attachPinsAreaEventListeners();
  }

  /**
   * Filter bar 이벤트 리스너 — IME 한글 조합 안전
   */
  attachFilterBarListeners() {
    const searchInput = this.querySelector('#pin-search');
    if (searchInput) {
      // IME composition tracking
      searchInput.addEventListener('compositionstart', () => {
        this._isComposing = true;
      });
      searchInput.addEventListener('compositionend', (e) => {
        this._isComposing = false;
        this.filters.search = e.target.value;
        this.updatePinsOnly();
      });
      searchInput.addEventListener('input', (e) => {
        if (this._isComposing) return; // IME 조합 중이면 무시
        clearTimeout(this._searchDebounceTimer);
        this._searchDebounceTimer = setTimeout(() => {
          this.filters.search = e.target.value;
          this.updatePinsOnly();
        }, 150);
      });
    }

    // Filter: importance
    const impFilter = this.querySelector('#filter-importance');
    if (impFilter) {
      impFilter.addEventListener('change', (e) => {
        this.filters.importance = e.target.value ? parseInt(e.target.value) : null;
        this.updatePinsOnly();
      });
    }

    // Filter: date
    const dateFilter = this.querySelector('#filter-date');
    if (dateFilter) {
      dateFilter.addEventListener('change', (e) => {
        this.filters.dateRange = e.target.value || null;
        this.updatePinsOnly();
      });
    }

    // Filter: tag (searchable-combobox)
    const tagFilter = this.querySelector('#filter-tag');
    if (tagFilter) {
      tagFilter.addEventListener('change', (e) => {
        const val = e.detail?.value ?? e.target?.value ?? '';
        this.filters.tags = val ? [val] : [];
        this.updatePinsOnly();
      });
    }

    // Sort
    const sortBy = this.querySelector('#sort-by');
    if (sortBy) {
      sortBy.addEventListener('change', (e) => {
        this.filters.sortBy = e.target.value;
        this.updatePinsOnly();
      });
    }
    const sortDirBtn = this.querySelector('#sort-dir-btn');
    if (sortDirBtn) {
      sortDirBtn.addEventListener('click', () => {
        this.filters.sortDir = this.filters.sortDir === 'desc' ? 'asc' : 'desc';
        sortDirBtn.textContent = this.filters.sortDir === 'desc' ? '↓' : '↑';
        this.updatePinsOnly();
      });
    }
  }

  /**
   * Pins area 이벤트 리스너 (kanban/list + batch)
   */
  attachPinsAreaEventListeners() {
    // View toggle
    this.querySelectorAll('.view-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this.currentView = btn.dataset.view;
        this.updatePinsOnly();
      });
    });

    // Complete buttons
    this.querySelectorAll('.complete-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.completePin(btn.dataset.pinId);
      });
    });

    // Promote buttons
    this.querySelectorAll('.promote-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.promotePin(btn.dataset.pinId);
      });
    });

    // Edit buttons
    this.querySelectorAll('.edit-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.showEditPinModal(btn.dataset.pinId);
      });
    });

    // Delete buttons
    this.querySelectorAll('.delete-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.deletePin(btn.dataset.pinId);
      });
    });

    // Load more completed
    const loadMoreBtn = this.querySelector('#load-more-completed');
    if (loadMoreBtn) {
      loadMoreBtn.addEventListener('click', () => {
        this.completedPinsLimit += 10;
        this.updatePinsOnly();
      });
    }

    // Batch mode
    const batchModeBtn = this.querySelector('#batch-mode-btn');
    if (batchModeBtn) {
      batchModeBtn.addEventListener('click', () => {
        this.batchMode = true;
        this.selectedPinIds.clear();
        this.updatePinsOnly();
      });
    }
    const batchCancelBtn = this.querySelector('#batch-cancel-btn');
    if (batchCancelBtn) {
      batchCancelBtn.addEventListener('click', () => {
        this.batchMode = false;
        this.selectedPinIds.clear();
        this.updatePinsOnly();
      });
    }
    const batchCompleteBtn = this.querySelector('#batch-complete-btn');
    if (batchCompleteBtn) {
      batchCompleteBtn.addEventListener('click', () => this.batchComplete());
    }
    const batchDeleteBtn = this.querySelector('#batch-delete-btn');
    if (batchDeleteBtn) {
      batchDeleteBtn.addEventListener('click', () => this.batchDelete());
    }

    // Pin checkboxes (batch mode)
    this.querySelectorAll('.pin-checkbox').forEach(cb => {
      cb.addEventListener('change', (e) => {
        const pinId = e.target.dataset.pinId;
        if (e.target.checked) {
          this.selectedPinIds.add(pinId);
        } else {
          this.selectedPinIds.delete(pinId);
        }
        const countEl = this.querySelector('.batch-count');
        if (countEl) countEl.textContent = `${this.selectedPinIds.size} selected`;
        const bcBtn = this.querySelector('#batch-complete-btn');
        const bdBtn = this.querySelector('#batch-delete-btn');
        if (bcBtn) bcBtn.disabled = this.selectedPinIds.size === 0;
        if (bdBtn) bdBtn.disabled = this.selectedPinIds.size === 0;
      });
    });

    // Drag and Drop for Kanban
    if (!this.batchMode) {
      this.attachDragAndDropListeners();
    }
  }

  attachEventListeners() {
    // Project filter
    const projectFilter = this.querySelector('#project-filter');
    if (projectFilter) {
      projectFilter.addEventListener('change', (e) => {
        this.selectedProject = e.detail.value || null;
        this.updateContent();
      });
    }

    // New Pin button
    const newPinBtn = this.querySelector('#new-pin-btn');
    if (newPinBtn) {
      newPinBtn.addEventListener('click', () => this.showNewPinModal());
    }

    // New Pin Modal controls
    const closeModal = this.querySelector('#close-modal');
    const cancelPin = this.querySelector('#cancel-pin');
    const modal = this.querySelector('#new-pin-modal');
    if (closeModal) closeModal.addEventListener('click', () => this.hideNewPinModal());
    if (cancelPin) cancelPin.addEventListener('click', () => this.hideNewPinModal());
    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) this.hideNewPinModal();
      });
    }

    // New Pin form
    const form = this.querySelector('#new-pin-form');
    if (form) {
      form.addEventListener('submit', (e) => this.handleNewPin(e));
    }

    // Edit Pin Modal controls
    const closeEditModal = this.querySelector('#close-edit-modal');
    const cancelEditPin = this.querySelector('#cancel-edit-pin');
    const editModal = this.querySelector('#edit-pin-modal');
    if (closeEditModal) closeEditModal.addEventListener('click', () => this.hideEditPinModal());
    if (cancelEditPin) cancelEditPin.addEventListener('click', () => this.hideEditPinModal());
    if (editModal) {
      editModal.addEventListener('click', (e) => {
        if (e.target === editModal) this.hideEditPinModal();
      });
    }

    // Edit Pin form
    const editForm = this.querySelector('#edit-pin-form');
    if (editForm) {
      editForm.addEventListener('submit', (e) => this.handleEditPin(e));
    }

    // Session End Modal controls
    const closeSessionModal = this.querySelector('#close-session-modal');
    const cancelSessionEnd = this.querySelector('#cancel-session-end');
    const sessionModal = this.querySelector('#end-session-modal');
    if (closeSessionModal) closeSessionModal.addEventListener('click', () => this.hideSessionEndModal());
    if (cancelSessionEnd) cancelSessionEnd.addEventListener('click', () => this.hideSessionEndModal());
    if (sessionModal) {
      sessionModal.addEventListener('click', (e) => {
        if (e.target === sessionModal) this.hideSessionEndModal();
      });
    }

    // Session End form
    const sessionForm = this.querySelector('#end-session-form');
    if (sessionForm) {
      sessionForm.addEventListener('submit', (e) => this.handleEndSession(e));
    }

    // Content event listeners
    this.attachContentEventListeners();
  }

  // ===== Modal helpers =====

  showNewPinModal() {
    const modal = this.querySelector('#new-pin-modal');
    if (modal) modal.style.display = 'flex';
  }

  hideNewPinModal() {
    const modal = this.querySelector('#new-pin-modal');
    if (modal) modal.style.display = 'none';
  }

  showEditPinModal(pinId) {
    const pin = this.pins.find(p => p.id === pinId);
    if (!pin) return;

    this.querySelector('#edit-pin-id').value = pin.id;
    this.querySelector('#edit-pin-content').value = pin.content;
    this.querySelector('#edit-pin-importance').value = pin.importance;
    this.querySelector('#edit-pin-status').value = pin.status;
    this.querySelector('#edit-pin-tags').value = (pin.tags || []).join(', ');

    const modal = this.querySelector('#edit-pin-modal');
    if (modal) modal.style.display = 'flex';
  }

  hideEditPinModal() {
    const modal = this.querySelector('#edit-pin-modal');
    if (modal) modal.style.display = 'none';
  }

  showSessionEndModal() {
    const modal = this.querySelector('#end-session-modal');
    if (modal) modal.style.display = 'flex';
  }

  hideSessionEndModal() {
    const modal = this.querySelector('#end-session-modal');
    if (modal) modal.style.display = 'none';
  }

  // ===== API actions =====

  async handleNewPin(e) {
    e.preventDefault();
    const content = this.querySelector('#pin-content').value;
    const projectId = this.querySelector('#pin-project').value || 'default';
    const importance = parseInt(this.querySelector('#pin-importance').value);
    const tagsInput = this.querySelector('#pin-tags').value;
    const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(t => t) : [];

    try {
      const newPin = await window.app.apiClient.post('/work/pins', {
        content, project_id: projectId, importance, tags
      });
      this.hideNewPinModal();
      // Optimistic: add to local state
      this.pins.unshift(newPin);
      this.updatePinsOnly();
      showToast('Pin created', 'success');
    } catch (error) {
      showToast(`Failed to create pin: ${error.message}`, 'error');
    }
  }

  async handleEditPin(e) {
    e.preventDefault();
    const pinId = this.querySelector('#edit-pin-id').value;
    const content = this.querySelector('#edit-pin-content').value;
    const importance = parseInt(this.querySelector('#edit-pin-importance').value);
    const status = this.querySelector('#edit-pin-status').value;
    const tagsInput = this.querySelector('#edit-pin-tags').value;
    const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(t => t) : [];

    try {
      const updated = await window.app.apiClient.put(`/work/pins/${pinId}`, {
        content, importance, status, tags
      });
      // Optimistic: update local
      const idx = this.pins.findIndex(p => p.id === pinId);
      if (idx !== -1) this.pins[idx] = { ...this.pins[idx], ...updated };
      this.hideEditPinModal();
      this.updatePinsOnly();
      showToast('Pin updated', 'success');
    } catch (error) {
      showToast(`Failed to update pin: ${error.message}`, 'error');
    }
  }

  async completePin(pinId) {
    // Optimistic update
    const pin = this.pins.find(p => p.id === pinId);
    if (!pin) return;
    const oldStatus = pin.status;
    pin.status = 'completed';
    this.updatePinsOnly();

    try {
      const result = await window.app.apiClient.put(`/work/pins/${pinId}/complete`);
      const idx = this.pins.findIndex(p => p.id === pinId);
      if (idx !== -1) this.pins[idx] = { ...this.pins[idx], ...result };

      if (result.suggest_promotion) {
        const toast = window.app?.toastNotifications;
        if (toast) {
          toast.show('Promote this pin to a permanent memory?', {
            type: 'info',
            title: 'Promote Pin',
            persistent: true,
            actions: [
              { label: 'Promote', primary: true, callback: () => this.promotePin(pinId) },
              { label: 'Skip', callback: () => {} }
            ]
          });
        }
      } else {
        showToast('Pin completed', 'success');
      }
      this.updatePinsOnly();
    } catch (error) {
      pin.status = oldStatus;
      this.updatePinsOnly();
      showToast(`Failed to complete pin: ${error.message}`, 'error');
    }
  }

  async promotePin(pinId) {
    try {
      const result = await window.app.apiClient.post(`/work/pins/${pinId}/promote`);
      showToast(result.message || 'Pin promoted to memory', 'success');
    } catch (error) {
      showToast(`Failed to promote pin: ${error.message}`, 'error');
    }
  }

  async deletePin(pinId) {
    // Optimistic: remove from local
    const idx = this.pins.findIndex(p => p.id === pinId);
    if (idx === -1) return;
    const removed = this.pins.splice(idx, 1)[0];
    this.updatePinsOnly();

    try {
      await window.app.apiClient.delete(`/work/pins/${pinId}`);
      showToast('Pin deleted', 'success');
    } catch (error) {
      this.pins.splice(idx, 0, removed);
      this.updatePinsOnly();
      showToast(`Failed to delete pin: ${error.message}`, 'error');
    }
  }

  // ===== Session actions =====

  async handleEndSession(e) {
    e.preventDefault();
    if (!this.activeSession) return;

    const summary = this.querySelector('#session-summary')?.value || '';

    try {
      await window.app.apiClient.post(
        `/work/sessions/${this.activeSession.id}/end`,
        null,
        summary ? { summary } : {}
      );
      this.hideSessionEndModal();
      showToast('Session ended', 'success');
      await this.loadData();
    } catch (error) {
      showToast(`Failed to end session: ${error.message}`, 'error');
    }
  }

  async toggleSessionPins(sessionId) {
    const existingList = this.querySelector(`.session-pins-list[data-session-id="${sessionId}"]`);
    if (existingList) {
      existingList.remove();
      return;
    }

    try {
      const data = await window.app.apiClient.get('/work/pins', { session_id: sessionId, limit: 50 });
      const pins = data.pins || [];
      const sessionItem = this.querySelector(`.session-item[data-session-id="${sessionId}"]`);
      if (!sessionItem) return;

      const listEl = document.createElement('div');
      listEl.className = 'session-pins-list';
      listEl.dataset.sessionId = sessionId;
      listEl.innerHTML = pins.length === 0
        ? '<p class="empty-message">No pins in this session</p>'
        : pins.map(p => `
          <div class="session-pin-item">
            <span class="session-pin-status ${p.status.replace('_', '-')}"></span>
            <span class="session-pin-content">${this.escapeHtml(p.content)}</span>
            <span class="session-pin-importance">${this.renderImportanceStars(p.importance)}</span>
          </div>
        `).join('');

      sessionItem.after(listEl);
    } catch (error) {
      showToast(`Failed to load session pins: ${error.message}`, 'error');
    }
  }

  // ===== Batch actions (Phase 3) =====

  async batchComplete() {
    if (this.selectedPinIds.size === 0) return;
    const ids = [...this.selectedPinIds];

    // Optimistic
    ids.forEach(id => {
      const pin = this.pins.find(p => p.id === id);
      if (pin) pin.status = 'completed';
    });
    this.batchMode = false;
    this.selectedPinIds.clear();
    this.updatePinsOnly();

    let failed = 0;
    for (const id of ids) {
      try {
        await window.app.apiClient.put(`/work/pins/${id}/complete`);
      } catch {
        failed++;
      }
    }

    if (failed > 0) {
      showToast(`${ids.length - failed} completed, ${failed} failed`, 'warning');
      await this.loadData();
    } else {
      showToast(`${ids.length} pins completed`, 'success');
    }
  }

  async batchDelete() {
    if (this.selectedPinIds.size === 0) return;
    const ids = [...this.selectedPinIds];

    // Optimistic
    this.pins = this.pins.filter(p => !ids.includes(p.id));
    this.batchMode = false;
    this.selectedPinIds.clear();
    this.updatePinsOnly();

    let failed = 0;
    for (const id of ids) {
      try {
        await window.app.apiClient.delete(`/work/pins/${id}`);
      } catch {
        failed++;
      }
    }

    if (failed > 0) {
      showToast(`${ids.length - failed} deleted, ${failed} failed`, 'warning');
      await this.loadData();
    } else {
      showToast(`${ids.length} pins deleted`, 'success');
    }
  }

  // ===== Utility =====

  formatTime(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    const now = new Date();
    const diff = now - date;
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const days = Math.floor(hours / 24);
    if (days > 0) return `${days}d ago`;
    if (hours > 0) return `${hours}h ago`;
    const minutes = Math.floor(diff / (1000 * 60));
    if (minutes > 0) return `${minutes}m ago`;
    return 'Just now';
  }

  getElapsedTime(isoString) {
    if (!isoString) return '';
    const diff = Date.now() - new Date(isoString).getTime();
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
  }

  getTimeDiff(start, end) {
    const diff = new Date(end) - new Date(start);
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // ===== Drag and Drop =====

  attachDragAndDropListeners() {
    this.querySelectorAll('.pin-card').forEach(card => {
      card.addEventListener('dragstart', (e) => this.handleDragStart(e));
      card.addEventListener('dragend', (e) => this.handleDragEnd(e));
    });

    this.querySelectorAll('.kanban-column').forEach(column => {
      column.addEventListener('dragover', (e) => this.handleDragOver(e));
      column.addEventListener('drop', (e) => this.handleDrop(e));
      column.addEventListener('dragleave', (e) => this.handleDragLeave(e));
      column.addEventListener('dragenter', (e) => this.handleDragEnter(e));
    });
  }

  handleDragStart(e) {
    const card = e.target.closest('.pin-card');
    if (!card) return;
    card.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', card.dataset.pinId);
  }

  handleDragEnd(e) {
    const card = e.target.closest('.pin-card');
    if (!card) return;
    card.classList.remove('dragging');
    this.querySelectorAll('.kanban-column').forEach(col => col.classList.remove('drag-over'));
  }

  handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }

  handleDragEnter(e) {
    const column = e.target.closest('.kanban-column');
    if (column) column.classList.add('drag-over');
  }

  handleDragLeave(e) {
    const column = e.target.closest('.kanban-column');
    if (column && !column.contains(e.relatedTarget)) {
      column.classList.remove('drag-over');
    }
  }

  async handleDrop(e) {
    e.preventDefault();
    const column = e.target.closest('.kanban-column');
    if (!column) return;
    column.classList.remove('drag-over');

    const pinId = e.dataTransfer.getData('text/plain');
    const newStatus = column.dataset.status;
    if (!pinId || !newStatus) return;

    const pin = this.pins.find(p => p.id === pinId);
    if (!pin || pin.status === newStatus) return;

    await this.updatePinStatus(pinId, newStatus);
  }

  async updatePinStatus(pinId, newStatus) {
    const pin = this.pins.find(p => p.id === pinId);
    if (!pin) return;

    const oldStatus = pin.status;
    pin.status = newStatus;
    this.updatePinsOnly();

    try {
      await window.app.apiClient.patch(`/work/pins/${pinId}`, { status: newStatus });
      showToast(`Pin moved to ${newStatus.replace('_', ' ')}`, 'success');
    } catch (error) {
      pin.status = oldStatus;
      this.updatePinsOnly();
      showToast(`Failed to update pin status: ${error.message}`, 'error');
    }
  }
}

customElements.define('work-page', WorkPage);

export { WorkPage };
