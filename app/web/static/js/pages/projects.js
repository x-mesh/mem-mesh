/**
 * Projects Page Web Component
 * Displays project list and management interface
 */

import { showToast } from '../utils/toast-notifications.js';

class ProjectsPage extends HTMLElement {
  constructor() {
    super();
    this.projects = [];
    this.isLoading = false;
    this.currentSort = 'name';
    this.sortDirection = 'asc';
    this.searchQuery = '';
    this.autoShareSubs = new Map();
    this.overviewSchedules = new Map();
  }

  _autoShareSub(projectId) {
    return this.autoShareSubs.get(projectId);
  }

  _isAutoShareOn(projectId) {
    return Boolean(this.autoShareSubs.get(projectId)?.enabled);
  }

  _escapeHtml(text) {
    return String(text ?? '').replace(
      /[&<>"']/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    );
  }
  
  connectedCallback() {
    console.log('ProjectsPage connected');
    this.render();
    this.setupEventListeners();
    
    // 약간의 지연 후 데이터 로드 (DOM이 완전히 렌더링된 후)
    setTimeout(() => {
      this.loadProjects();
    }, 100);
  }

  disconnectedCallback() {
    this._stopMaintenancePoll();
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    // Search input
    const searchInput = this.querySelector('.search-input');
    if (searchInput) {
      searchInput.addEventListener('input', this.handleSearch.bind(this));
    }
    
    // Sort controls
    const sortSelect = this.querySelector('.sort-select');
    if (sortSelect) {
      sortSelect.addEventListener('change', this.handleSortChange.bind(this));
    }
    
    // Sort direction toggle
    const sortToggle = this.querySelector('.sort-toggle');
    if (sortToggle) {
      sortToggle.addEventListener('click', this.toggleSortDirection.bind(this));
    }
    
    // Refresh button
    const refreshBtn = this.querySelector('.refresh-btn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', this.loadProjects.bind(this));
    }
    
    // Export button
    const exportBtn = this.querySelector('.export-btn');
    if (exportBtn) {
      exportBtn.addEventListener('click', this.handleExport.bind(this));
    }
    
    // Project cards click events
    this.addEventListener('click', this.handleProjectClick.bind(this));
  }
  
  /**
   * Load projects data
   */
  async loadProjects() {
    try {
      this.setLoading(true);
      
      // 서버에서 집계된 프로젝트 정보를 가져옴 (효율적)
      const data = await window.app.apiClient.get('/projects');
      
      if (data && data.projects) {
        this.projects = data.projects;
        await this.loadAutoShare();
        await this.loadOverviewSchedules();
        await this.loadOverviewWorkerState();
        await this.loadCoverage();
        this.sortProjects();
        this.renderProjects();
        this.updateSummary();
        // Surface batches already running (or failed leftovers) on page load;
        // the poll self-terminates when nothing is active.
        this._startMaintenancePoll();
      } else {
        console.warn('No projects found in response:', data);
        this.projects = [];
        this.renderProjects();
        this.updateSummary();
      }
      
    } catch (error) {
      console.error('Failed to load projects:', error);
      this.showError('Failed to load projects: ' + error.message);
    } finally {
      this.setLoading(false);
    }
  }
  
  /**
   * Process memories to extract project information
   */
  processProjectsFromMemories(memories) {
    console.log('Processing memories for projects:', memories.length);
    
    const projectMap = new Map();
    
    memories.forEach(memory => {
      const projectId = memory.project_id || 'default';
      
      if (!projectMap.has(projectId)) {
        projectMap.set(projectId, {
          id: projectId,
          name: projectId === 'default' ? 'Default Project' : projectId,
          memory_count: 0,
          categories: new Set(),
          tags: new Set(),
          created_at: memory.created_at,
          updated_at: memory.created_at,
          total_size: 0
        });
      }
      
      const project = projectMap.get(projectId);
      project.memory_count++;
      project.categories.add(memory.category);
      if (memory.tags && Array.isArray(memory.tags)) {
        memory.tags.forEach(tag => project.tags.add(tag));
      }
      project.total_size += memory.content?.length || 0;
      
      // Update timestamps
      if (memory.created_at < project.created_at) {
        project.created_at = memory.created_at;
      }
      if (memory.created_at > project.updated_at) {
        project.updated_at = memory.created_at;
      }
    });
    
    // Convert sets to arrays and calculate additional metrics
    this.projects = Array.from(projectMap.values()).map(project => ({
      ...project,
      categories: Array.from(project.categories),
      tags: Array.from(project.tags),
      avg_memory_size: project.memory_count > 0 ? Math.round(project.total_size / project.memory_count) : 0
    }));
    
    console.log('Processed projects:', this.projects);
    
    this.sortProjects();
  }
  
  /**
   * Handle search input
   */
  handleSearch(event) {
    this.searchQuery = event.target.value.toLowerCase();
    this.renderProjects();
  }
  
  /**
   * Handle sort change
   */
  handleSortChange(event) {
    this.currentSort = event.target.value;
    this.sortProjects();
    this.renderProjects();
  }
  
  /**
   * Toggle sort direction
   */
  toggleSortDirection() {
    this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
    this.sortProjects();
    this.renderProjects();
    
    // Update toggle button
    const toggle = this.querySelector('.sort-toggle');
    if (toggle) {
      toggle.textContent = this.sortDirection === 'asc' ? '↑' : '↓';
    }
  }
  
  /**
   * Sort projects
   */
  sortProjects() {
    this.projects.sort((a, b) => {
      let aVal, bVal;
      
      switch (this.currentSort) {
        case 'name':
          aVal = a.name.toLowerCase();
          bVal = b.name.toLowerCase();
          break;
        case 'memory_count':
          aVal = a.memory_count;
          bVal = b.memory_count;
          break;
        case 'created_at':
          aVal = new Date(a.created_at);
          bVal = new Date(b.created_at);
          break;
        case 'updated_at':
          aVal = new Date(a.updated_at);
          bVal = new Date(b.updated_at);
          break;
        case 'total_size':
          aVal = a.total_size;
          bVal = b.total_size;
          break;
        default:
          aVal = a.name.toLowerCase();
          bVal = b.name.toLowerCase();
      }
      
      if (aVal < bVal) return this.sortDirection === 'asc' ? -1 : 1;
      if (aVal > bVal) return this.sortDirection === 'asc' ? 1 : -1;
      return 0;
    });
  }
  
  /**
   * Filter projects based on search query
   */
  getFilteredProjects() {
    if (!this.searchQuery) return this.projects;
    
    return this.projects.filter(project => 
      project.name.toLowerCase().includes(this.searchQuery) ||
      project.categories.some(cat => cat.toLowerCase().includes(this.searchQuery)) ||
      project.tags.some(tag => tag.toLowerCase().includes(this.searchQuery))
    );
  }
  
  /**
   * Handle project card clicks
   */
  handleProjectClick(event) {
    const maintRetryBtn = event.target.closest('.maint-retry-btn');
    if (maintRetryBtn) {
      event.stopPropagation();
      const projectId = maintRetryBtn.getAttribute('data-project-id');
      if (projectId) this.retryProjectMaintenance(projectId, maintRetryBtn);
      return;
    }

    // Clicking the progress area (anywhere but Retry) means "what's going on
    // with this batch?" — go to Curation → Activity, not the memories list.
    const maintProgress = event.target.closest('.maint-progress');
    if (maintProgress) {
      event.stopPropagation();
      const url = '/curation?tab=activity&filter=maintenance';
      if (window.app && window.app.router) {
        window.app.router.navigate(url);
      } else {
        window.location.href = url;
      }
      return;
    }

    const autoShareBtn = event.target.closest('.relay-autoshare-btn');
    if (autoShareBtn) {
      event.stopPropagation();
      const projectId = autoShareBtn.getAttribute('data-project-id');
      if (projectId) this.toggleAutoShare(projectId);
      return;
    }

    const overviewScheduleBtn = event.target.closest('.overview-schedule-btn');
    if (overviewScheduleBtn) {
      event.stopPropagation();
      if (!this._overviewTaskEnabled()) {
        showToast("Enable the 'overview' worker task in Settings → Worker tasks first", 'warning');
        return;
      }
      const projectId = overviewScheduleBtn.getAttribute('data-project-id');
      if (projectId) this.toggleOverviewSchedule(projectId);
      return;
    }

    const overviewBtn = event.target.closest('.overview-btn');
    if (overviewBtn) {
      event.stopPropagation();
      const projectId = overviewBtn.getAttribute('data-project-id');
      if (projectId) this.openOverviewModal(projectId);
      return;
    }

    const maintenanceBtn = event.target.closest('.maintenance-btn');
    if (maintenanceBtn) {
      event.stopPropagation();
      const projectId = maintenanceBtn.getAttribute('data-project-id');
      if (projectId) this.openMaintenanceModal(projectId);
      return;
    }

    const shareBtn = event.target.closest('.relay-share-btn');
    if (shareBtn) {
      event.stopPropagation();
      const projectId = shareBtn.getAttribute('data-project-id');
      if (projectId) this.shareProjectToRelay(projectId);
      return;
    }

    const viewBtn = event.target.closest('.view-btn');
    if (viewBtn) {
      event.stopPropagation();
      const projectId = viewBtn.getAttribute('data-project-id');
      if (projectId) {
        // Navigate to unified memories page with project filter
        if (window.app && window.app.router) {
          window.app.router.navigate(`/memories?view=project&project_id=${encodeURIComponent(projectId)}`);
        } else {
          // Fallback to direct navigation
          window.location.href = `/memories?view=project&project_id=${encodeURIComponent(projectId)}`;
        }
      }
      return;
    }
    
    const projectCard = event.target.closest('.project-card');
    if (projectCard) {
      const projectId = projectCard.getAttribute('data-project-id');
      if (projectId) {
        // Card click → project dashboard detail (/project/:id). The memories
        // list stays one click away via the View button above.
        if (window.app && window.app.router) {
          window.app.router.navigate(`/project/${encodeURIComponent(projectId)}`);
        } else {
          // Fallback to direct navigation
          window.location.href = `/project/${encodeURIComponent(projectId)}`;
        }
      }
    }
  }

  /**
   * Load which projects have continuous relay sharing enabled (best-effort —
   * relay may be unconfigured, in which case the endpoint returns an empty list).
   */
  async loadAutoShare() {
    try {
      const data = await window.app.apiClient.getRelayAutoShare();
      this.autoShareSubs = new Map(
        (data?.subscriptions || []).map(s => [s.project_id, s])
      );
    } catch {
      this.autoShareSubs = new Map();
    }
  }

  _isOverviewScheduleOn(projectId) {
    return Boolean(this.overviewSchedules?.get(projectId)?.enabled);
  }

  /** The per-project toggle is inert unless the global 'overview' worker task
   *  is enabled (Settings → Worker tasks), so gate the control on it. */
  _overviewTaskEnabled() {
    return this._overviewWorkerOn === true;
  }

  /** Which projects have scheduled overview auto-refresh enabled. */
  async loadOverviewSchedules() {
    try {
      const data = await window.app.apiClient.get('/projects/overview/schedules');
      this.overviewSchedules = new Map(
        (data?.schedules || []).map(s => [s.project_id, s])
      );
    } catch {
      this.overviewSchedules = new Map();
    }
  }

  /** Whether the global 'overview' worker task is on (drives toggle enablement). */
  async loadOverviewWorkerState() {
    try {
      const data = await window.app.apiClient.get('/settings/worker');
      const tasks = Array.isArray(data?.worker_tasks) ? data.worker_tasks : [];
      this._overviewWorkerOn = tasks.includes('overview');
    } catch {
      this._overviewWorkerOn = false;
    }
  }

  /** Toggle scheduled overview auto-refresh for a project. */
  async toggleOverviewSchedule(projectId) {
    const api = window.app?.apiClient;
    if (!api) { showToast('API not available', 'error'); return; }
    const enable = !this._isOverviewScheduleOn(projectId);
    try {
      const res = await api.put(
        `/projects/${encodeURIComponent(projectId)}/overview/schedule`,
        { enabled: enable }
      );
      if (!this.overviewSchedules) this.overviewSchedules = new Map();
      this.overviewSchedules.set(projectId, { project_id: projectId, enabled: !!res?.enabled });
      this.renderProjects();
      showToast(
        enable
          ? `"${projectId}" auto-summary on — Overview refreshes when the project is active`
          : `"${projectId}" auto-summary off`,
        enable ? 'success' : 'info'
      );
    } catch (error) {
      showToast(error?.data?.detail || error?.message || 'Failed to update auto-summary', 'error');
    }
  }

  /**
   * Toggle continuous relay sharing for a project.
   */
  async toggleAutoShare(projectId) {
    const api = window.app?.apiClient;
    if (!api) { showToast('API not available', 'error'); return; }
    const enable = !this._isAutoShareOn(projectId);
    try {
      const sub = await api.setRelayAutoShare(projectId, { enabled: enable });
      if (sub && sub.project_id) this.autoShareSubs.set(projectId, sub);
      this.renderProjects();
      showToast(
        enable
          ? `"${projectId}" continuous sharing on — new memories auto-share to relay`
          : `"${projectId}" continuous sharing off`,
        enable ? 'success' : 'info'
      );
    } catch (error) {
      showToast(error?.data?.detail || error?.message || 'Failed to update auto-share', 'error');
    }
  }

  /**
   * Status line shown under an enabled auto-share toggle: last error if any,
   * otherwise last sync time (or awaiting first sync).
   */
  _autoShareStatusHtml(projectId) {
    const sub = this._autoShareSub(projectId);
    if (!sub || !sub.enabled) return '';
    if (sub.last_error) {
      return `<div class="relay-autoshare-status error">⚠ ${this._escapeHtml(sub.last_error)}</div>`;
    }
    const label = sub.last_synced_at
      ? `Last synced ${this.formatDate(sub.last_synced_at)}`
      : 'Awaiting first sync';
    return `<div class="relay-autoshare-status">${this._escapeHtml(label)}</div>`;
  }

  /**
   * Queue every shareable memory in a project for relay delivery.
   */
  async shareProjectToRelay(projectId) {
    const api = window.app?.apiClient;
    if (!api) { showToast('API not available', 'error'); return; }
    if (!confirm(`Share all memories in "${projectId}" to the team relay?`)) return;
    try {
      const result = await api.shareRelayProject(projectId, { event_type: 'update' });
      const queued = result?.queued_count ?? 0;
      const skipped = (result?.skipped || []).length;
      const msg = skipped > 0
        ? `${queued} memories queued, ${skipped} skipped (secret/type gate)`
        : `${queued} memories queued for relay`;
      showToast(msg, skipped > 0 ? 'warning' : 'success');
    } catch (error) {
      // FastAPI returns {detail}; APIError surfaces it on .data.detail / .message.
      showToast(error?.data?.detail || error?.message || 'Failed to share project', 'error');
    }
  }

  /**
   * Open the project overview modal (LLM summary of recent memories).
   */
  async openOverviewModal(projectId) {
    const existing = document.querySelector('.overview-modal-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'maintenance-modal-overlay overview-modal-overlay';
    overlay.innerHTML = `
      <div class="maintenance-modal overview-modal" role="dialog" aria-modal="true">
        <div class="maintenance-modal-header">
          <h3>📋 ${this._escapeHtml(projectId)} · Overview</h3>
          <button class="overview-modal-close" aria-label="Close">&times;</button>
        </div>
        <div class="overview-body"><div class="overview-loading">Loading…</div></div>
        <div class="maintenance-modal-actions">
          <button class="secondary-button overview-cancel">Close</button>
          <button class="primary-button overview-generate" hidden>Generate</button>
        </div>
      </div>`;

    const close = () => overlay.remove();
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    overlay.querySelector('.overview-modal-close').addEventListener('click', close);
    overlay.querySelector('.overview-cancel').addEventListener('click', close);

    const body = overlay.querySelector('.overview-body');
    const genBtn = overlay.querySelector('.overview-generate');
    const api = window.app?.apiClient;

    const runGenerate = async () => {
      genBtn.disabled = true;
      body.innerHTML = '<div class="overview-loading">Summarizing recent memories…</div>';
      try {
        api?.invalidateCache?.(`/projects/${encodeURIComponent(projectId)}/overview`);
        const res = await api.post(`/projects/${encodeURIComponent(projectId)}/overview`, {});
        body.innerHTML = window.ProjectOverviewRender.html(res, { showGeneratedAt: true });
        genBtn.textContent = 'Regenerate';
        genBtn.disabled = false;
      } catch (error) {
        body.innerHTML = `<div class="overview-empty">${this._escapeHtml(error?.data?.detail || error?.message || 'Failed')}</div>`;
        genBtn.disabled = false;
      }
    };
    genBtn.addEventListener('click', runGenerate);

    document.body.appendChild(overlay);
    // Load cached first.
    try {
      api?.invalidateCache?.(`/projects/${encodeURIComponent(projectId)}/overview`);
      const cached = await api.get(`/projects/${encodeURIComponent(projectId)}/overview`);
      if (cached?.overview) {
        body.innerHTML = window.ProjectOverviewRender.html(cached, { showGeneratedAt: true });
        genBtn.textContent = cached.stale ? 'Refresh (memories changed)' : 'Regenerate';
        genBtn.hidden = false;
      } else {
        body.innerHTML = '<div class="overview-empty">No overview yet. Generate one from this project’s recent memories.</div>';
        genBtn.textContent = 'Generate';
        genBtn.hidden = false;
      }
    } catch (error) {
      body.innerHTML = `<div class="overview-empty">${this._escapeHtml(error?.message || 'Failed to load')}</div>`;
      genBtn.textContent = 'Generate';
      genBtn.hidden = false;
    }
  }

  /**
   * Open the batch maintenance modal for a project (enrich / improve / reconcile).
   */
  openMaintenanceModal(projectId) {
    const existing = document.querySelector('.maintenance-modal-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'maintenance-modal-overlay';
    overlay.innerHTML = `
      <div class="maintenance-modal" role="dialog" aria-modal="true">
        <div class="maintenance-modal-header">
          <h3>Project maintenance</h3>
          <button class="maintenance-modal-close" aria-label="Close">&times;</button>
        </div>
        <p class="maintenance-modal-sub">Run batch jobs over every canonical memory in
          <strong>${this._escapeHtml(projectId)}</strong>. Work runs in the background
          (relay worker) — this only queues it.</p>
        <label class="maintenance-op">
          <input type="checkbox" value="enrich" checked>
          <span><strong>Enrich</strong> — generate title/abstract/tags (safe, never changes content)</span>
        </label>
        <label class="maintenance-op">
          <input type="checkbox" value="reconcile" checked>
          <span><strong>Reconcile</strong> — find duplicates/conflicts → review in Curation (safe, proposals only)</span>
        </label>
        <label class="maintenance-op">
          <input type="checkbox" value="improve">
          <span><strong>Improve</strong> — rewrite content. Never auto-applied — proposes a diff you approve per memory.</span>
        </label>
        <label class="maintenance-force">
          <input type="checkbox" class="maintenance-force-cb">
          <span>Force re-run (re-enrich / re-propose even if already done)</span>
        </label>
        <label class="maintenance-force">
          <input type="checkbox" class="auto-enrich-cb" disabled>
          <span><strong>Continuous auto-enrich</strong> — keep new & backlog memories enriched automatically (worker sweeps every 12h)</span>
        </label>
        <div class="auto-enrich-hint maintenance-modal-note" style="display:none"></div>
        <div class="maintenance-modal-actions">
          <button class="maintenance-cancel secondary-button">Cancel</button>
          <button class="maintenance-run primary-button">Queue jobs</button>
        </div>
        <div class="maintenance-modal-note">Needs the relay worker running with the
          <code>maintenance</code>/<code>reconcile</code> tasks + a chat LLM. Results:
          Enrich → memory's AI box · Improve → <a href="/curation" data-route="/curation">Curation</a> · Reconcile → <a href="/curation" data-route="/curation">Curation</a>.</div>
      </div>`;

    const close = () => overlay.remove();
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    overlay.querySelector('.maintenance-modal-close').addEventListener('click', close);
    overlay.querySelector('.maintenance-cancel').addEventListener('click', close);
    overlay.querySelector('.maintenance-run').addEventListener('click', async () => {
      const ops = Array.from(overlay.querySelectorAll('.maintenance-op input:checked')).map(c => c.value);
      if (!ops.length) { showToast('Select at least one operation', 'warning'); return; }
      const force = overlay.querySelector('.maintenance-force-cb').checked;
      const runBtn = overlay.querySelector('.maintenance-run');
      runBtn.disabled = true;
      runBtn.textContent = 'Queueing…';
      try {
        await this.runProjectMaintenance(projectId, ops, force);
        close();
      } catch (_) {
        runBtn.disabled = false;
        runBtn.textContent = 'Queue jobs';
      }
    });

    overlay.querySelector('.auto-enrich-cb').addEventListener('change', async (e) => {
      const api = window.app?.apiClient;
      const enabled = e.target.checked;
      try {
        const r = await api.put(
          `/maintenance/auto-enrich/${encodeURIComponent(projectId)}`,
          { enabled },
        );
        showToast(r.enabled ? 'Auto-enrich on' : 'Auto-enrich off', 'success');
      } catch (err) {
        e.target.checked = !enabled;  // revert on failure
        showToast(err?.data?.detail || 'Auto-enrich toggle failed', 'error');
      }
    });

    document.body.appendChild(overlay);
    this._loadAutoEnrich(projectId, overlay);
  }

  async _loadAutoEnrich(projectId, overlay) {
    const api = window.app?.apiClient;
    const cb = overlay.querySelector('.auto-enrich-cb');
    const hint = overlay.querySelector('.auto-enrich-hint');
    if (!api || !cb) return;
    try {
      const s = await api.get(
        `/maintenance/auto-enrich/${encodeURIComponent(projectId)}`,
      );
      cb.checked = !!s.enabled;
      // Worker LLM is the hard prerequisite — gate the toggle on it.
      if (s.llm_configured) {
        cb.disabled = false;
      } else {
        cb.disabled = true;
        hint.style.display = '';
        hint.textContent = 'Worker LLM 미설정 — Settings → Worker LLM 설정 후 사용 가능합니다.';
      }
    } catch (_) { /* leave disabled */ }
  }

  async runProjectMaintenance(projectId, operations, force) {
    const api = window.app?.apiClient;
    if (!api) { showToast('API not available', 'error'); throw new Error('no api'); }
    try {
      const result = await api.post(
        `/maintenance/projects/${encodeURIComponent(projectId)}`,
        { operations, force },
      );
      const parts = [];
      for (const [op, n] of Object.entries(result?.enqueued || {})) {
        if (n > 0) parts.push(`${op}: ${n}`);
      }
      if (result?.reconcile) parts.push(`reconcile: ${result.reconcile.enqueued ?? 0}`);
      const msg = parts.length
        ? `Queued — ${parts.join(', ')}`
        : 'Nothing to queue (already done — use Force to re-run)';
      showToast(msg, parts.length ? 'success' : 'warning');
      this._startMaintenancePoll();
    } catch (error) {
      showToast(error?.data?.detail || error?.message || 'Maintenance failed', 'error');
      throw error;
    }
  }

  /**
   * Handle export
   */
  async handleExport() {
    try {
      const exportData = {
        projects: this.projects,
        exported_at: new Date().toISOString(),
        total_projects: this.projects.length,
        total_memories: this.projects.reduce((sum, p) => sum + p.memory_count, 0)
      };
      
      const blob = new Blob([JSON.stringify(exportData, null, 2)], {
        type: 'application/json'
      });
      
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `mem-mesh-projects-${new Date().toISOString().split('T')[0]}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      
    } catch (error) {
      console.error('Failed to export projects:', error);
      this.showError('Failed to export projects');
    }
  }
  
  /**
   * Set loading state
   */
  setLoading(loading) {
    this.isLoading = loading;
    
    const loadingEl = this.querySelector('.loading-state');
    const contentEl = this.querySelector('.projects-content');
    
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
      day: 'numeric'
    });
  }
  
  /**
   * Render projects list
   */
  renderProjects() {
    const container = this.querySelector('.projects-grid');
    if (!container) return;
    
    const filteredProjects = this.getFilteredProjects();
    
    if (filteredProjects.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <p>No projects found</p>
          ${this.searchQuery ? '<button class="clear-search-btn">Clear search</button>' : ''}
        </div>
      `;
      
      const clearBtn = container.querySelector('.clear-search-btn');
      if (clearBtn) {
        clearBtn.addEventListener('click', () => {
          const searchInput = this.querySelector('.search-input');
          if (searchInput) {
            searchInput.value = '';
            this.searchQuery = '';
            this.renderProjects();
          }
        });
      }
      return;
    }
    
    container.innerHTML = filteredProjects.map(project => `
      <div class="project-card" data-project-id="${project.id}">
        <div class="project-header">
          <h3 class="project-name">${project.name}</h3>
          <div class="project-stats">
            <span class="memory-count">${project.memory_count} memories</span>
            ${this.enrichBadge(project.id)}
          </div>
        </div>
        
        <div class="project-details">
          <div class="detail-row">
            <span class="label">Categories:</span>
            <div class="categories">
              ${project.categories.map(cat => `<span class="category-tag">${cat}</span>`).join('')}
            </div>
          </div>
          
          ${project.tags.length > 0 ? `
            <div class="detail-row">
              <span class="label">Tags:</span>
              <div class="tags">
                ${project.tags.slice(0, 5).map(tag => `<span class="tag">${tag}</span>`).join('')}
                ${project.tags.length > 5 ? `<span class="tag-more">+${project.tags.length - 5}</span>` : ''}
              </div>
            </div>
          ` : ''}
          
          <div class="detail-row">
            <span class="label">Total Size:</span>
            <span class="value">${this.formatSize(project.total_size)} (${project.memory_count} memories)</span>
          </div>
          
          <div class="detail-row">
            <span class="label">Avg Size:</span>
            <span class="value">${this.formatSize(project.avg_memory_size)} per memory</span>
          </div>
          
          <div class="detail-row">
            <span class="label">Created:</span>
            <span class="value">${this.formatDate(project.created_at)}</span>
          </div>
          
          <div class="detail-row">
            <span class="label">Updated:</span>
            <span class="value">${this.formatDate(project.updated_at)}</span>
          </div>
        </div>
        
        <div class="project-actions">
          <button class="view-btn" data-project-id="${project.id}">View Memories</button>
          <button class="overview-btn" data-project-id="${project.id}" title="LLM summary of this project's recent memories">📋 Overview</button>
          <button class="maintenance-btn" data-project-id="${project.id}" title="Enrich / Improve / Reconcile all memories in this project">🔧 Maintenance</button>
          <button class="relay-share-btn" data-project-id="${project.id}">Share to relay</button>
          <button class="relay-autoshare-btn ${this._isAutoShareOn(project.id) ? 'on' : ''}" data-project-id="${project.id}">
            ${this._isAutoShareOn(project.id) ? '● Auto-share on' : '○ Auto-share off'}
          </button>
          <button class="overview-schedule-btn ${this._isOverviewScheduleOn(project.id) ? 'on' : ''}${this._overviewTaskEnabled() ? '' : ' disabled'}" data-project-id="${project.id}" title="${this._overviewTaskEnabled() ? "Auto-refresh this project's Overview on a schedule (only when it has recent activity)" : "Enable the 'overview' worker task in Settings to use auto-summary"}">
            ${this._isOverviewScheduleOn(project.id) ? '● Auto-summary on' : '○ Auto-summary off'}
          </button>
        </div>
        ${this._autoShareStatusHtml(project.id)}
        ${this._maintenanceProgressHtml(project.id)}
      </div>
    `).join('');
  }

  // ── Maintenance batch progress on cards ──────────────────────────────────

  /**
   * Per-operation progress rows for a project's maintenance batches. Shown
   * while jobs are active (pending/processing) or dead-lettered; a batch that
   * finished clean disappears. Counting mirrors curation.js's worker card:
   * done+stale are resolved, cancelled is ignored.
   */
  _maintenanceProgressHtml(projectId) {
    const ops = (this._maintByProject || {})[projectId];
    if (!ops) return '';
    const rows = Object.entries(ops).map(([op, c]) => {
      const done = (c.done || 0) + (c.stale || 0);
      const failed = c.dead_letter || 0;
      const active = (c.pending || 0) + (c.processing || 0);
      const total = done + failed + active;
      if (!total || (!active && !failed)) return '';
      const pct = Math.round((done / total) * 100);
      const retryBtn = failed && op !== 'reconcile'
        ? `<button class="maint-retry-btn" data-project-id="${this._escapeHtml(projectId)}" title="Requeue this project's failed jobs">Retry</button>`
        : '';
      return `
        <div class="maint-progress-row">
          <span class="maint-progress-op">${this._escapeHtml(op)}</span>
          <div class="maint-progress-bar"><div class="maint-progress-fill${failed ? ' has-failed' : ''}" style="width:${pct}%"></div></div>
          <span class="maint-progress-label">${done} / ${total}${active ? '' : ' done'}${failed ? ` · <span class="maint-progress-failed">${failed} failed</span>` : ''}</span>
          ${retryBtn}
        </div>`;
    }).filter(Boolean).join('');
    if (!rows) return '';
    return `<div class="maint-progress" data-project-id="${this._escapeHtml(projectId)}" title="View batch details in Curation → Activity">${rows}</div>`;
  }

  /**
   * Update card progress in place — a full renderProjects() every 3s would
   * swallow in-flight clicks and flicker the grid.
   */
  _updateMaintProgressNodes() {
    this.querySelectorAll('.project-card').forEach((card) => {
      const pid = card.getAttribute('data-project-id');
      if (!pid) return;
      const html = this._maintenanceProgressHtml(pid);
      const existing = card.querySelector('.maint-progress');
      if (existing) {
        if (html) existing.outerHTML = html;
        else existing.remove();
      } else if (html) {
        card.insertAdjacentHTML('beforeend', html);
      }
    });
  }

  /**
   * Start the 3s progress poll if not already running/in-flight (idempotent).
   * ``_maintPollBusy`` (not just the timer handle) guards this: the timer is
   * cleared at the START of each tick before the awaited fetch, so without a
   * separate busy flag a call landing mid-fetch (e.g. right after queueing a
   * new batch) would pass the timer check and spawn a second concurrent loop.
   */
  _startMaintenancePoll() {
    if (this._maintPollTimer || this._maintPollBusy) return;
    this._maintPollFailures = 0;
    this._pollMaintenanceStatus();
  }

  _stopMaintenancePoll() {
    if (this._maintPollTimer) {
      clearTimeout(this._maintPollTimer);
      this._maintPollTimer = null;
    }
  }

  /**
   * One poll tick: fetch all projects' queue counts in a single request and
   * reschedule only while something is still active — the poll terminates
   * itself when every batch has drained (recursive setTimeout, no overlap).
   * A transient fetch failure must NOT be mistaken for "nothing active" (that
   * would silently stop the poll on the very first hiccup) — it keeps polling
   * up to a few consecutive failures before giving up.
   */
  async _pollMaintenanceStatus() {
    this._maintPollTimer = null;
    if (!this.isConnected) return;
    this._maintPollBusy = true;
    const api = window.app?.apiClient;
    let anyActive = true; // stay alive unless a successful poll proves otherwise
    if (api && !document.hidden) {
      try {
        // Status polls must bypass APIClient's permanent GET cache.
        api.invalidateCache?.('/maintenance/status');
        const res = await api.get('/maintenance/status?by_project=true');
        this._maintByProject = res?.queue_by_project || {};
        this._updateMaintProgressNodes();
        this._maintPollFailures = 0;
        anyActive = Object.values(this._maintByProject || {}).some((ops) =>
          Object.values(ops).some((c) => (c.pending || 0) + (c.processing || 0) > 0)
        );
      } catch (_) {
        this._maintPollFailures = (this._maintPollFailures || 0) + 1;
        // Give up after repeated failures — a permanently broken endpoint
        // shouldn't poll forever; queueing a new batch restarts the poll.
        anyActive = this._maintPollFailures < 5;
      }
    }
    this._maintPollBusy = false;
    if (anyActive && this.isConnected) {
      this._maintPollTimer = setTimeout(() => this._pollMaintenanceStatus(), 3000);
    }
  }

  /** Requeue a project's dead-lettered enrich/improve jobs from its card. */
  async retryProjectMaintenance(projectId, btn) {
    const api = window.app?.apiClient;
    if (!api) { showToast('API not available', 'error'); return; }
    if (btn) btn.disabled = true;
    try {
      const res = await api.post('/maintenance/retry', { project_id: projectId });
      showToast(`Requeued ${res?.retried ?? 0} failed job(s)`, 'success');
      this._startMaintenancePoll();
    } catch (error) {
      showToast(error?.data?.detail || error?.message || 'Retry failed', 'error');
      if (btn) btn.disabled = false;
    }
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'projects-page page-container';
    
    this.innerHTML = `
      <div class="page-header">
        <div class="page-header-main">
          <h1 class="page-title">Projects</h1>
        </div>
        <div class="page-header-actions">
          <button class="refresh-btn secondary-button"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"/></svg> Refresh</button>
          <button class="export-btn secondary-button"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7,10 12,15 17,10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Export</button>
        </div>
      </div>
      
      <div class="error-message" style="display: none;"></div>
      
      <div class="projects-controls">
        <div class="search-section">
          <input 
            type="text" 
            class="search-input" 
            placeholder="Search projects, categories, or tags..."
          />
        </div>
        
        <div class="sort-section">
          <label>Sort by:</label>
          <select class="sort-select">
            <option value="name">Name</option>
            <option value="memory_count">Memory Count</option>
            <option value="total_size">Total Size</option>
            <option value="created_at">Created Date</option>
            <option value="updated_at">Updated Date</option>
          </select>
          <button class="sort-toggle">↑</button>
        </div>
      </div>
      
      <div class="loading-state" style="display: none;">
        <div class="loading-spinner"></div>
        <p>Loading projects...</p>
      </div>
      
      <div class="projects-content">
        <div class="projects-summary">
          <div class="summary-card">
            <span class="summary-label">Total Projects</span>
            <span class="summary-value" id="total-projects">0</span>
          </div>
          <div class="summary-card">
            <span class="summary-label">Total Memories</span>
            <span class="summary-value" id="total-memories">0</span>
          </div>
          <div class="summary-card">
            <span class="summary-label">Average per Project</span>
            <span class="summary-value" id="avg-memories">0</span>
          </div>
          <div class="summary-card" title="Memories with an LLM title/abstract. Injection works without it (structural fallback) — enrichment raises summary quality.">
            <span class="summary-label">✨ Enriched</span>
            <span class="summary-value" id="enrich-coverage">–</span>
          </div>
        </div>
        
        <div class="projects-grid"></div>
      </div>
    `;
    
    // Update summary when projects are loaded
    this.updateSummary();
  }
  
  /**
   * Update summary statistics
   */
  updateSummary() {
    const totalProjects = this.querySelector('#total-projects');
    const totalMemories = this.querySelector('#total-memories');
    const avgMemories = this.querySelector('#avg-memories');

    if (totalProjects) totalProjects.textContent = this.projects.length;

    const memoryCount = this.projects.reduce((sum, p) => sum + p.memory_count, 0);
    if (totalMemories) totalMemories.textContent = memoryCount;

    const avg = this.projects.length > 0 ? Math.round(memoryCount / this.projects.length) : 0;
    if (avgMemories) avgMemories.textContent = avg;

    const enrichEl = this.querySelector('#enrich-coverage');
    if (enrichEl) {
      const cov = this.coverage?.enrichment;
      enrichEl.textContent = cov
        ? `${cov.enriched_count}/${cov.total_memories} (${(cov.coverage_ratio * 100).toFixed(1)}%)`
        : '–';
    }
  }

  /** Enrichment coverage — 사용자가 "개선되고 있는지" 볼 수 있는 지표.
   *  실패해도 페이지는 정상 동작(배지만 생략). */
  async loadCoverage() {
    try {
      this.coverage = await window.app.apiClient.get('/stats/coverage');
      this.coverageByProject = {};
      for (const row of this.coverage?.enrichment?.by_project || []) {
        this.coverageByProject[row.project_id] = row;
      }
    } catch (error) {
      console.warn('coverage load failed:', error);
      this.coverage = null;
      this.coverageByProject = {};
    }
  }

  enrichBadge(projectId) {
    const row = this.coverageByProject?.[projectId];
    if (!row || !row.total) return '';
    const pct = (row.coverage_ratio * 100).toFixed(row.coverage_ratio >= 0.1 ? 0 : 1);
    return `<span class="enrich-badge" title="${row.enriched}/${row.total} memories enriched (LLM title/abstract)">✨ ${pct}%</span>`;
  }
}

// Define the custom element
customElements.define('projects-page', ProjectsPage);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .error-message {
    background: var(--error-bg);
    color: var(--error-text);
    border: 1px solid var(--error-color);
    border-radius: var(--border-radius);
    padding: 1rem;
    margin-bottom: 1rem;
  }
  
  .projects-controls {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
    gap: 1rem;
  }
  
  .search-section {
    flex: 1;
  }
  
  .search-input {
    width: 100%;
    max-width: 400px;
    padding: 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 1rem;
  }
  
  .search-input:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px var(--primary-color-alpha);
  }
  
  .sort-section {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
    color: var(--text-secondary);
  }
  
  .sort-select {
    padding: 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    background: var(--bg-primary);
    color: var(--text-primary);
  }
  
  .sort-toggle {
    background: none;
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    padding: 0.5rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 1rem;
    width: 2rem;
    height: 2rem;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .sort-toggle:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
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
  
  .projects-summary {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
  }
  
  .summary-card {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 1.5rem;
    text-align: center;
  }
  
  .summary-label {
    display: block;
    font-size: 0.875rem;
    color: var(--text-secondary);
    margin-bottom: 0.5rem;
  }
  
  .summary-value {
    display: block;
    font-size: 2rem;
    font-weight: bold;
    color: var(--primary-color);
  }
  
  .projects-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
    gap: 1.5rem;
  }
  
  .project-card {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 1.5rem;
    cursor: pointer;
    transition: var(--transition);
  }
  
  .project-card:hover {
    border-color: var(--primary-color);
    box-shadow: 0 4px 12px var(--shadow-color);
  }
  
  .project-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1rem;
  }
  
  .project-name {
    margin: 0;
    color: var(--text-primary);
    font-size: 1.25rem;
  }
  
  .project-stats {
    text-align: right;
  }
  
  .memory-count {
    background: var(--primary-color);
    color: var(--bg-primary);
    padding: 0.25rem 0.75rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.875rem;
    font-weight: 500;
  }

  .enrich-badge {
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.8rem;
    margin-left: 0.375rem;
    white-space: nowrap;
  }
  
  .project-details {
    margin-bottom: 1rem;
  }
  
  .detail-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.75rem;
    font-size: 0.875rem;
  }
  
  .detail-row:last-child {
    margin-bottom: 0;
  }
  
  .label {
    color: var(--text-secondary);
    font-weight: 500;
  }
  
  .value {
    color: var(--text-primary);
  }
  
  .categories,
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
  }
  
  .category-tag {
    background: var(--primary-color);
    color: var(--bg-primary);
    padding: 0.125rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
    font-weight: 500;
  }
  
  .tag {
    background: var(--bg-secondary);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
    padding: 0.125rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
  }
  
  .tag-more {
    background: var(--bg-tertiary);
    color: var(--text-muted);
    padding: 0.125rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
    font-style: italic;
  }
  
  .project-actions {
    border-top: 1px solid var(--border-color);
    padding-top: 1rem;
    display: flex;
    justify-content: center;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .maintenance-btn, .overview-btn {
    background: transparent;
    color: var(--text-secondary);
    border: 1px solid var(--border-color);
    padding: 0.5rem 0.75rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
    transition: var(--transition);
  }

  .maintenance-btn:hover, .overview-btn:hover {
    border-color: var(--primary-color);
    color: var(--primary-color);
  }

  .overview-modal { max-width: 640px; }
  .overview-body { max-height: 60vh; overflow: auto; }
  .overview-loading, .overview-empty { color: var(--text-secondary); font-size: 0.875rem; padding: 1rem 0; }

  /* Shared overview render (.ov-*) — modal + memory-detail sidebar */
  .ov-stale { font-size: 0.78rem; color: var(--warning-text, #92400e); background: var(--warning-bg, #fef3c7); border-radius: 6px; padding: 6px 10px; margin-bottom: 10px; }
  .ov-summary { font-size: 0.9rem; line-height: 1.6; color: var(--text-primary); margin: 0 0 12px; }
  .ov-themes { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
  .ov-theme { font-size: 0.72rem; padding: 2px 9px; border-radius: 999px; background: var(--bg-tertiary); color: var(--text-secondary); }
  .ov-section { margin-bottom: 12px; }
  .ov-h { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-secondary); margin-bottom: 5px; font-weight: 600; }
  .ov-list { margin: 0; padding-left: 1.1rem; display: flex; flex-direction: column; gap: 4px; }
  .ov-list li { font-size: 0.83rem; line-height: 1.5; color: var(--text-primary); }
  .ov-issues .ov-h { color: var(--error-color, #ef4444); }
  .ov-src { text-decoration: none; color: var(--primary-color); font-weight: 600; margin-right: 2px; }
  .ov-src:hover { text-decoration: underline; }
  .ov-foot { font-size: 0.72rem; color: var(--text-muted); margin-top: 10px; border-top: 1px solid var(--border-color); padding-top: 8px; }

  .maintenance-modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    padding: 1rem;
  }

  .maintenance-modal {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    max-width: 520px;
    width: 100%;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
  }

  .maintenance-modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.5rem;
  }

  .maintenance-modal-header h3 { margin: 0; font-size: 1.05rem; }

  .maintenance-modal-close {
    background: none; border: none; font-size: 1.4rem;
    line-height: 1; cursor: pointer; color: var(--text-muted);
  }

  .maintenance-modal-sub {
    font-size: 0.85rem; color: var(--text-secondary); margin: 0 0 1rem;
  }

  .maintenance-op, .maintenance-force {
    display: flex; gap: 0.6rem; align-items: flex-start;
    padding: 0.5rem 0; font-size: 0.875rem; cursor: pointer;
  }

  .maintenance-op span strong { color: var(--text-primary); }
  .maintenance-op span { color: var(--text-secondary); }

  .maintenance-force {
    border-top: 1px solid var(--border-color);
    margin-top: 0.5rem; padding-top: 0.75rem;
    color: var(--text-muted);
  }

  .maintenance-modal-actions {
    display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 1rem;
  }

  .maintenance-modal-note {
    margin-top: 0.75rem; font-size: 0.75rem; color: var(--text-muted);
    line-height: 1.5;
  }

  .maintenance-modal-note code {
    background: var(--bg-tertiary); padding: 0 3px; border-radius: 3px;
  }

  .relay-share-btn {
    background: transparent;
    color: var(--primary-color);
    border: 1px solid var(--primary-color);
    padding: 0.5rem 1rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
    transition: var(--transition);
  }

  .relay-share-btn:hover {
    background: var(--primary-color);
    color: var(--bg-primary);
  }

  .relay-autoshare-btn {
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border-color);
    padding: 0.5rem 0.75rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.8125rem;
    font-weight: 500;
    transition: var(--transition);
  }

  .relay-autoshare-btn:hover {
    border-color: var(--primary-color);
    color: var(--primary-color);
  }

  .relay-autoshare-btn.on {
    background: var(--success-color, #16a34a);
    color: #fff;
    border-color: var(--success-color, #16a34a);
  }

  .overview-schedule-btn {
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border-color);
    padding: 0.5rem 0.75rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.8125rem;
    font-weight: 500;
    transition: var(--transition);
  }

  .overview-schedule-btn:hover {
    border-color: var(--primary-color);
    color: var(--primary-color);
  }

  .overview-schedule-btn.on {
    background: var(--primary-color);
    color: var(--bg-primary);
    border-color: var(--primary-color);
  }

  .overview-schedule-btn.disabled,
  .overview-schedule-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .overview-schedule-btn.disabled:hover,
  .overview-schedule-btn:disabled:hover {
    border-color: var(--border-color);
    color: var(--text-muted);
  }

  .relay-autoshare-status {
    margin-top: 0.5rem;
    font-size: 0.75rem;
    color: var(--text-muted);
    text-align: center;
  }

  .relay-autoshare-status.error {
    color: var(--error-color, #ef4444);
  }

  .maint-progress {
    margin-top: 0.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    cursor: pointer;
    border-radius: var(--border-radius);
    padding: 2px 4px;
  }

  .maint-progress:hover {
    background: var(--bg-tertiary);
  }

  .maint-progress-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.75rem;
    color: var(--text-muted);
  }

  .maint-progress-op {
    min-width: 56px;
    font-weight: 600;
    text-transform: capitalize;
  }

  .maint-progress-bar {
    flex: 1;
    height: 6px;
    border-radius: 999px;
    background: var(--bg-tertiary);
    overflow: hidden;
  }

  .maint-progress-fill {
    height: 100%;
    border-radius: 999px;
    background: var(--success-color, #16a34a);
    transition: width 0.4s ease;
  }

  .maint-progress-fill.has-failed {
    background: linear-gradient(90deg, var(--success-color, #16a34a), var(--error-color, #ef4444));
  }

  .maint-progress-label {
    white-space: nowrap;
  }

  .maint-progress-failed {
    color: var(--error-color, #ef4444);
  }

  .maint-retry-btn {
    padding: 2px 8px;
    font-size: 0.72rem;
    border: 1px solid var(--warning-color, #d97706);
    color: var(--warning-color, #d97706);
    background: transparent;
    border-radius: var(--border-radius);
    cursor: pointer;
  }

  .maint-retry-btn:hover {
    background: var(--warning-color, #d97706);
    color: #fff;
  }

  .maint-retry-btn:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .view-btn {
    background: var(--primary-color);
    color: var(--bg-primary);
    border: none;
    padding: 0.5rem 1rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
    transition: var(--transition);
  }
  
  .view-btn:hover {
    background: var(--primary-hover);
  }
  
  .empty-state {
    grid-column: 1 / -1;
    text-align: center;
    padding: 4rem;
    color: var(--text-muted);
  }
  
  .empty-state p {
    margin: 0 0 1rem 0;
    font-size: 1.125rem;
  }
  
  .clear-search-btn {
    background: var(--primary-color);
    color: var(--bg-primary);
    border: none;
    padding: 0.5rem 1rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
  }
  
  .clear-search-btn:hover {
    background: var(--primary-hover);
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
  
  /* Responsive design */
  @media (max-width: 768px) {
    .projects-page {
      padding: var(--space-4) 0; /* 모바일에서 상하 패딩 줄임 */
    }
    
    .projects-controls {
      flex-direction: column;
      align-items: stretch;
    }
    
    .sort-section {
      justify-content: space-between;
    }
    
    .projects-summary {
      grid-template-columns: 1fr;
    }
    
    .projects-grid {
      grid-template-columns: 1fr;
    }
  }
`;

document.head.appendChild(style);

export { ProjectsPage };