/**
 * Work Tracking Page Component
 * Pin/Session 기반 작업 추적 대시보드
 */

class WorkPage extends HTMLElement {
  constructor() {
    super();
    this.pins = [];
    this.sessions = [];
    this.projects = [];
    this.stats = null;
    this.selectedProject = null; // null = 전체, 'project-id' = 특정 프로젝트
    this.isLoading = true;
    this.currentView = 'kanban'; // kanban, list
  }

  connectedCallback() {
    this.render();
    this.loadData();
  }

  async loadData() {
    this.isLoading = true;
    this.updateLoadingState();

    try {
      // 병렬로 데이터 로드
      const [pinsRes, projectsRes] = await Promise.all([
        fetch('/api/work/pins?limit=50'),
        fetch('/api/work/projects')
      ]);

      if (pinsRes.ok) {
        const pinsData = await pinsRes.json();
        this.pins = pinsData.pins || [];
        console.log('Loaded pins:', this.pins.length, 'pins');
      }

      if (projectsRes.ok) {
        const projectsData = await projectsRes.json();
        this.projects = projectsData.projects || [];
        console.log('Loaded projects:', this.projects.length, 'projects');
      }

      // 프로젝트 통계 로드
      let projectId = this.selectedProject;
      
      // 선택된 프로젝트가 없으면 첫 번째 프로젝트 사용
      if (!projectId && this.projects.length > 0) {
        projectId = this.projects[0].id;
      }
      
      // 프로젝트가 없으면 pins에서 추출
      if (!projectId && this.pins.length > 0) {
        projectId = this.pins[0].project_id;
      }
      
      // 프로젝트 ID가 있으면 통계 로드
      if (projectId) {
        const statsRes = await fetch(`/api/work/projects/${projectId}/stats`);
        if (statsRes.ok) {
          this.stats = await statsRes.json();
          console.log('Loaded stats for project:', projectId, this.stats);
        } else {
          console.error('Failed to load stats:', statsRes.status);
        }
      } else {
        console.warn('No project ID available for stats');
      }

    } catch (error) {
      console.error('Failed to load work data:', error);
    } finally {
      this.isLoading = false;
      this.render();
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
      <div class="work-page chroma-page">
        <div class="work-header">
          <div class="header-content">
            <h1 class="page-title">Work Tracking</h1>
            <p class="page-subtitle">Pin 기반 작업 추적 및 세션 관리</p>
          </div>
          <div class="header-actions">
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
      <!-- Stats Cards -->
      <div class="work-stats-grid">
        ${this.renderStatsCards()}
      </div>

      <!-- Kanban Board -->
      <div class="kanban-section">
        <div class="section-header">
          <h2>Active Pins</h2>
          <div class="view-toggle">
            <button class="view-btn ${this.currentView === 'kanban' ? 'active' : ''}" data-view="kanban">Kanban</button>
            <button class="view-btn ${this.currentView === 'list' ? 'active' : ''}" data-view="list">List</button>
          </div>
        </div>
        ${this.currentView === 'kanban' ? this.renderKanbanBoard() : this.renderListView()}
      </div>
    `;
  }

  // SVG Icons (모노톤)
  static icons = {
    pin: `<svg viewBox="0 0 24 24" fill="none" width="20" height="20"><path d="M12 2L12 8M12 8L8 12V14H10L12 22L14 14H16V12L12 8Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    progress: `<svg viewBox="0 0 24 24" fill="none" width="20" height="20"><path d="M12 2V6M12 18V22M4.93 4.93L7.76 7.76M16.24 16.24L19.07 19.07M2 12H6M18 12H22M4.93 19.07L7.76 16.24M16.24 7.76L19.07 4.93" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
    check: `<svg viewBox="0 0 24 24" fill="none" width="20" height="20"><path d="M20 6L9 17L4 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    clock: `<svg viewBox="0 0 24 24" fill="none" width="20" height="20"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.5"/><path d="M12 7V12L15 15" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
    star: `<svg viewBox="0 0 24 24" fill="none" width="12" height="12"><path d="M12 2L14.09 8.26L21 9.27L16 14.14L17.18 21.02L12 17.77L6.82 21.02L8 14.14L3 9.27L9.91 8.26L12 2Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>`,
    starFilled: `<svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12"><path d="M12 2L14.09 8.26L21 9.27L16 14.14L17.18 21.02L12 17.77L6.82 21.02L8 14.14L3 9.27L9.91 8.26L12 2Z"/></svg>`,
    upload: `<svg viewBox="0 0 24 24" fill="none" width="14" height="14"><path d="M12 15V3M12 3L8 7M12 3L16 7M4 17V19C4 20.1 4.9 21 6 21H18C19.1 21 20 20.1 20 19V17" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    checkSmall: `<svg viewBox="0 0 24 24" fill="none" width="14" height="14"><path d="M20 6L9 17L4 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`
  };

  renderProjectOptions() {
    // 프로젝트 목록 추출 (pins에서 unique project_id)
    const projectIds = [...new Set(this.pins.map(p => p.project_id))];
    
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
    if (!this.selectedProject) {
      return this.pins; // 전체 표시
    }
    return this.pins.filter(p => p.project_id === this.selectedProject);
  }

  renderStatsCards() {
    // 필터링된 pins로 통계 계산
    const filteredPins = this.getFilteredPins();
    const openPins = filteredPins.filter(p => p.status === 'open').length;
    const inProgressPins = filteredPins.filter(p => p.status === 'in_progress').length;
    const completedPins = filteredPins.filter(p => p.status === 'completed').length;
    
    // 평균 Lead Time 계산
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
    const completedPins = filteredPins.filter(p => p.status === 'completed').slice(0, 10);

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
            <span class="column-count">${completedPins.length}</span>
          </div>
          <div class="column-content">
            ${completedPins.map(pin => this.renderPinCard(pin)).join('')}
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

    return `
      <div class="pin-card" data-pin-id="${pin.id}" data-status="${pin.status}">
        <div class="pin-project-badge">${this.escapeHtml(pin.project_id)}</div>
        <div class="pin-header">
          <span class="pin-importance" title="Importance: ${pin.importance}">${this.renderImportanceStars(pin.importance)}</span>
          ${pin.status !== 'completed' ? `
            <button class="pin-action-btn complete-btn" data-pin-id="${pin.id}" title="Complete">${WorkPage.icons.checkSmall}</button>
          ` : ''}
        </div>
        <div class="pin-content">${this.escapeHtml(pin.content)}</div>
        ${tags.length > 0 ? `
          <div class="pin-tags">
            ${tags.map(tag => `<span class="pin-tag">${this.escapeHtml(tag)}</span>`).join('')}
          </div>
        ` : ''}
        <div class="pin-footer">
          <span class="pin-time">${this.formatTime(pin.created_at)}</span>
          ${pin.importance >= 4 && pin.status === 'completed' ? `
            <button class="pin-action-btn promote-btn" data-pin-id="${pin.id}" title="Promote to Memory">${WorkPage.icons.upload}</button>
          ` : ''}
        </div>
      </div>
    `;
  }

  renderPinListItem(pin) {
    const statusClass = pin.status.replace('_', '-');

    return `
      <div class="pin-list-item ${statusClass}" data-pin-id="${pin.id}">
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
          ${pin.status !== 'completed' ? `
            <button class="btn-icon complete-btn" data-pin-id="${pin.id}">${WorkPage.icons.checkSmall}</button>
          ` : ''}
          ${pin.importance >= 4 && pin.status === 'completed' ? `
            <button class="btn-icon promote-btn" data-pin-id="${pin.id}">${WorkPage.icons.upload}</button>
          ` : ''}
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
                  <option value="1">● Low</option>
                  <option value="2">●●</option>
                  <option value="3" selected>●●● Medium</option>
                  <option value="4">●●●●</option>
                  <option value="5">●●●●● High</option>
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

  attachEventListeners() {
    // Project filter
    const projectFilter = this.querySelector('#project-filter');
    if (projectFilter) {
      projectFilter.addEventListener('change', (e) => {
        this.selectedProject = e.detail.value || null;
        console.log('Project filter changed:', this.selectedProject);
        this.render();
      });
    }

    // New Pin button
    const newPinBtn = this.querySelector('#new-pin-btn');
    if (newPinBtn) {
      newPinBtn.addEventListener('click', () => this.showNewPinModal());
    }

    // Modal controls
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

    // View toggle
    const viewBtns = this.querySelectorAll('.view-btn');
    viewBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        this.currentView = btn.dataset.view;
        this.render();
      });
    });

    // Complete buttons
    const completeBtns = this.querySelectorAll('.complete-btn');
    completeBtns.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.completePin(btn.dataset.pinId);
      });
    });

    // Promote buttons
    const promoteBtns = this.querySelectorAll('.promote-btn');
    promoteBtns.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.promotePin(btn.dataset.pinId);
      });
    });
  }

  showNewPinModal() {
    const modal = this.querySelector('#new-pin-modal');
    if (modal) modal.style.display = 'flex';
  }

  hideNewPinModal() {
    const modal = this.querySelector('#new-pin-modal');
    if (modal) modal.style.display = 'none';
  }

  async handleNewPin(e) {
    e.preventDefault();

    const content = this.querySelector('#pin-content').value;
    const projectId = this.querySelector('#pin-project').value || 'default';
    const importance = parseInt(this.querySelector('#pin-importance').value);
    const tagsInput = this.querySelector('#pin-tags').value;
    const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(t => t) : [];

    try {
      const response = await fetch('/api/work/pins', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content,
          project_id: projectId,
          importance,
          tags
        })
      });

      if (response.ok) {
        this.hideNewPinModal();
        this.loadData();
      } else {
        const error = await response.json();
        alert(`Failed to create pin: ${error.detail}`);
      }
    } catch (error) {
      console.error('Failed to create pin:', error);
      alert('Failed to create pin');
    }
  }

  async completePin(pinId) {
    try {
      const response = await fetch(`/api/work/pins/${pinId}/complete`, {
        method: 'PUT'
      });

      if (response.ok) {
        const result = await response.json();
        if (result.suggest_promotion) {
          if (confirm(result.promotion_message)) {
            await this.promotePin(pinId);
          }
        }
        this.loadData();
      }
    } catch (error) {
      console.error('Failed to complete pin:', error);
    }
  }

  async promotePin(pinId) {
    try {
      const response = await fetch(`/api/work/pins/${pinId}/promote`, {
        method: 'POST'
      });

      if (response.ok) {
        const result = await response.json();
        alert(result.message);
        this.loadData();
      }
    } catch (error) {
      console.error('Failed to promote pin:', error);
    }
  }

  formatTime(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    const now = new Date();
    const diff = now - date;
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const days = Math.floor(hours / 24);

    if (days > 0) return `${days}d ago`;
    if (hours > 0) return `${hours}h ago`;
    return 'Just now';
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

customElements.define('work-page', WorkPage);

export { WorkPage };
