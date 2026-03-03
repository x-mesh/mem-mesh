/**
 * Work Tracking Page — Linear-style compact list redesign
 * Replaces legacy card/kanban UI with 1-line rows, filter chips,
 * Cmd+K command palette, keyboard shortcuts, and peek panel.
 */

import { showToast } from '../utils/toast-notifications.js';
import '../components/searchable-combobox.js';

/* ── helpers ──────────────────────────────────────────────── */

function esc(text) {
  if (text == null) return '';
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function relTime(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'Just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  if (d < 30) return `${Math.floor(d / 7)}w ago`;
  return `${Math.floor(d / 30)}mo ago`;
}

function truncate(text, max = 120) {
  if (!text) return '';
  const clean = text.replace(/#{1,6}\s+/g, '').replace(/\*\*(.*?)\*\*/g, '$1').replace(/\n/g, ' ').trim();
  return clean.length > max ? clean.substring(0, max) + '...' : clean;
}

function highlight(text, query) {
  if (!query || !text) return esc(text);
  const escaped = esc(text);
  const terms = query.trim().split(/\s+/).filter(t => t.length >= 2);
  if (!terms.length) return escaped;
  const pattern = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  return escaped.replace(new RegExp(`(${pattern})`, 'gi'), '<mark>$1</mark>');
}

function elapsedStr(isoString) {
  if (!isoString) return '';
  const diff = Date.now() - new Date(isoString).getTime();
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function timeDiff(start, end) {
  const diff = new Date(end) - new Date(start);
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

/* Monotone palette — matches dashboard cat-bg-* grayscale convention */
const IMP_LIGHT = ['', '#b8b8b8', '#a0a0a0', '#878787', '#555555', '#2d2d2d'];
const IMP_DARK  = ['', '#505050', '#686868', '#808080', '#b0b0b0', '#e0e0e0'];
const SD_LIGHT  = { open: '#a0a0a0', in_progress: '#6e6e6e', completed: '#3d3d3d' };
const SD_DARK   = { open: '#686868', in_progress: '#a0a0a0', completed: '#c8c8c8' };

function isDark() { return document.documentElement.getAttribute('data-theme') === 'dark'; }
function impColor(level) { return (isDark() ? IMP_DARK : IMP_LIGHT)[level] || (isDark() ? IMP_DARK : IMP_LIGHT)[3]; }
function statusColor(status) { return (isDark() ? SD_DARK : SD_LIGHT)[status] || '#878787'; }

/* ── Component ────────────────────────────────────────────── */

class WorkPage extends HTMLElement {
  constructor() {
    super();
    this.pins = [];
    this.sessions = [];
    this.projects = [];
    this.activeSession = null;
    this.selectedProject = null;
    this.filters = { importance: null, tags: [], search: '', sortBy: 'importance', sortDir: 'desc' };
    this.selectedPinIds = new Set();
    this.currentView = 'kanban';
    this.page = 0;
    this.pageSize = 50;
    this.hasMore = true;
    this._boundKeydown = null;
    this._searchTimer = null;
    this._isComposing = false;
    this._peekId = null;
    this._peekData = null;
    this._isInitialized = false;
  }

  connectedCallback() {
    if (this._isInitialized) return;
    this._isInitialized = true;
    this.render();
    this.setupEventListeners();
    this.loadData();
  }

  disconnectedCallback() {
    if (this._boundKeydown) {
      document.removeEventListener('keydown', this._boundKeydown);
      this._boundKeydown = null;
    }
    clearTimeout(this._searchTimer);
    this._searchTimer = null;
  }

  /* ── Data loading ────────────────────────────────────────── */

  async loadData() {
    this.renderPinList(true); // skeleton
    try {
      const api = window.app?.apiClient;
      if (!api) return;
      const [pinsData, projectsData, sessionsData] = await Promise.allSettled([
        api.get('/work/pins', { limit: 100 }),
        api.get('/work/projects'),
        api.get('/work/sessions', { limit: 20 })
      ]);

      this.pins = pinsData.status === 'fulfilled' ? (pinsData.value.pins || []) : [];
      this.projects = projectsData.status === 'fulfilled' ? (projectsData.value.projects || []) : [];
      this.sessions = sessionsData.status === 'fulfilled' ? (sessionsData.value.sessions || []) : [];
      this.activeSession = this.sessions.find(s => s.status === 'active') || null;
    } catch { /* ignore */ }

    this.renderContent();
    this.updateProjectCombo();
  }

  getFilteredPins() {
    let pins = this.pins;
    if (this.selectedProject) pins = pins.filter(p => p.project_id === this.selectedProject);
    if (this.filters.importance !== null) pins = pins.filter(p => p.importance >= this.filters.importance);
    if (this.filters.tags.length > 0) pins = pins.filter(p => this.filters.tags.some(tag => (p.tags || []).includes(tag)));
    if (this.filters.search) {
      const q = this.filters.search.toLowerCase();
      pins = pins.filter(p =>
        (p.content || '').toLowerCase().includes(q) ||
        (p.project_id || '').toLowerCase().includes(q) ||
        (p.tags || []).some(t => t.toLowerCase().includes(q))
      );
    }
    pins = [...pins].sort((a, b) => {
      let cmp = 0;
      if (this.filters.sortBy === 'importance') cmp = a.importance - b.importance;
      else if (this.filters.sortBy === 'date') cmp = new Date(a.created_at) - new Date(b.created_at);
      else if (this.filters.sortBy === 'status') {
        const order = { open: 0, in_progress: 1, completed: 2 };
        cmp = (order[a.status] || 0) - (order[b.status] || 0);
      }
      return this.filters.sortDir === 'desc' ? -cmp : cmp;
    });
    return pins;
  }

  resetAndLoad() {
    this.page = 0;
    this.hasMore = true;
    this.renderContent();
  }

  updateProjectCombo() {
    const combo = this.querySelector('.wk-proj-combo');
    if (!combo || !combo.setOptions) return;
    const projectIds = this.projects.length > 0
      ? this.projects.map(p => p.id)
      : [...new Set(this.pins.map(p => p.project_id).filter(Boolean))];
    const opts = [{ value: '', text: 'All Projects' }];
    projectIds.forEach(id => opts.push({ value: id, text: id }));
    combo.setOptions(opts);
    if (this.selectedProject) combo.setValue(this.selectedProject);

    // Also update tag filter combo
    const tagCombo = this.querySelector('.wk-tag-combo');
    if (tagCombo && tagCombo.setOptions) {
      const allTags = [...new Set(this.pins.flatMap(p => p.tags || []))].sort();
      const tagOpts = [{ value: '', text: 'All Tags' }];
      allTags.forEach(t => tagOpts.push({ value: t, text: t }));
      tagCombo.setOptions(tagOpts);
    }
  }

  /* ── Render skeleton ─────────────────────────────────────── */

  render() {
    this.className = 'wk page-container';
    this.innerHTML = `
      <div class="wk-toolbar">
        <h1 class="wk-title">Work</h1>
        <div class="wk-search-wrap">
          <svg class="wk-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
          <input class="wk-search-input" type="text" placeholder="Search pins... (${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl+'}K)" />
        </div>
        <searchable-combobox class="wk-proj-combo" placeholder="All Projects">
          <option value="">All Projects</option>
        </searchable-combobox>
        <select class="wk-imp-select" title="Importance filter">
          <option value="">All Importance</option>
          <option value="1">1+</option>
          <option value="2">2+</option>
          <option value="3">3+</option>
          <option value="4">4+</option>
          <option value="5">5 only</option>
        </select>
        <searchable-combobox class="wk-tag-combo" placeholder="All Tags">
          <option value="">All Tags</option>
        </searchable-combobox>
        <select class="wk-sort-select">
          <option value="importance">Sort: Importance</option>
          <option value="date">Sort: Date</option>
          <option value="status">Sort: Status</option>
        </select>
        <button class="wk-sort-dir-btn" title="Toggle sort direction">${this.filters.sortDir === 'desc' ? '↓' : '↑'}</button>
        <div class="wk-view-toggle">
          <button class="wk-view-btn${this.currentView === 'list' ? ' active' : ''}" data-view="list" title="List view">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
          </button>
          <button class="wk-view-btn${this.currentView === 'kanban' ? ' active' : ''}" data-view="kanban" title="Kanban view">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="18" rx="1"/><rect x="14" y="3" width="7" height="10" rx="1"/></svg>
          </button>
        </div>
        <button class="wk-new-btn" title="New Pin (n)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          New Pin
        </button>
      </div>
      <div class="wk-session-banner"></div>
      <div class="wk-batch-bar" style="display:none"></div>
      <div class="wk-chips"></div>
      <div class="wk-stats-bar"></div>
      <div class="wk-content-area">
        <div class="wk-list"></div>
        <div class="wk-peek-panel" style="display:none"></div>
      </div>
      <div class="wk-footer"></div>
    `;
  }

  /* ── Render content (called after data load) ─────────────── */

  renderContent() {
    this.renderSessionBanner();
    this.renderChips();
    this.renderStatsBar();
    this.renderPinList(false);
    this.renderSessionHistory();
    this.renderFooter();
    this.renderBatchBar();
  }

  /* ── Stats bar ───────────────────────────────────────────── */

  renderStatsBar() {
    const bar = this.querySelector('.wk-stats-bar');
    if (!bar) return;
    const pins = this.getFilteredPins();
    const open = pins.filter(p => p.status === 'open').length;
    const prog = pins.filter(p => p.status === 'in_progress').length;
    const done = pins.filter(p => p.status === 'completed').length;
    bar.innerHTML = `
      <span class="wk-stat"><span class="wk-stat-dot" style="background:${statusColor('open')}"></span>Open: ${open}</span>
      <span class="wk-stat"><span class="wk-stat-dot" style="background:${statusColor('in_progress')}"></span>In Progress: ${prog}</span>
      <span class="wk-stat"><span class="wk-stat-dot" style="background:${statusColor('completed')}"></span>Completed: ${done}</span>
      <span class="wk-stat" style="margin-left:auto;color:var(--text-muted)">Total: ${pins.length}</span>
    `;
  }

  /* ── Session banner ──────────────────────────────────────── */

  renderSessionBanner() {
    const container = this.querySelector('.wk-session-banner');
    if (!container) return;
    if (!this.activeSession) { container.innerHTML = ''; return; }

    const elapsed = elapsedStr(this.activeSession.started_at);
    const pinCount = this.pins.filter(p => p.session_id === this.activeSession.id).length;

    container.innerHTML = `
      <div class="wk-session-inner">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
        <span class="wk-session-text">
          <strong>${esc(this.activeSession.project_id)}</strong> · ${elapsed} · ${pinCount} pins
        </span>
        <button class="wk-session-end-btn">End Session</button>
      </div>
    `;
  }

  /* ── Filter chips ────────────────────────────────────────── */

  renderChips() {
    const container = this.querySelector('.wk-chips');
    if (!container) return;

    const chips = [];
    if (this.selectedProject) chips.push({ key: 'project', label: `project:${this.selectedProject}` });
    if (this.filters.importance !== null) chips.push({ key: 'importance', label: `imp≥${this.filters.importance}` });
    if (this.filters.tags.length > 0) chips.push({ key: 'tags', label: `#${this.filters.tags[0]}` });
    if (this.filters.search) chips.push({ key: 'search', label: `"${this.filters.search}"` });

    if (chips.length === 0) { container.innerHTML = ''; return; }

    container.innerHTML = chips.map(c =>
      `<span class="wk-chip" data-filter="${c.key}">${esc(c.label)} <button class="wk-chip-remove" data-filter="${c.key}">&times;</button></span>`
    ).join('') + '<button class="wk-clear-all-btn">Clear all</button>';
  }

  removeFilter(key) {
    if (key === 'search') {
      this.filters.search = '';
      const input = this.querySelector('.wk-search-input');
      if (input) input.value = '';
    } else if (key === 'project') {
      this.selectedProject = null;
      const combo = this.querySelector('.wk-proj-combo');
      if (combo) combo.setValue('', 'All Projects');
    } else if (key === 'importance') {
      this.filters.importance = null;
      const sel = this.querySelector('.wk-imp-select');
      if (sel) sel.value = '';
    } else if (key === 'tags') {
      this.filters.tags = [];
      const combo = this.querySelector('.wk-tag-combo');
      if (combo) combo.setValue('', 'All Tags');
    }
    this.resetAndLoad();
  }

  clearAllFilters() {
    this.filters = { importance: null, tags: [], search: '', sortBy: this.filters.sortBy, sortDir: this.filters.sortDir };
    this.selectedProject = null;
    const input = this.querySelector('.wk-search-input');
    if (input) input.value = '';
    const projCombo = this.querySelector('.wk-proj-combo');
    if (projCombo) projCombo.setValue('', 'All Projects');
    const impSel = this.querySelector('.wk-imp-select');
    if (impSel) impSel.value = '';
    const tagCombo = this.querySelector('.wk-tag-combo');
    if (tagCombo) tagCombo.setValue('', 'All Tags');
    this.resetAndLoad();
  }

  /* ── Build single row ────────────────────────────────────── */

  buildPinRow(pin) {
    const content = truncate(pin.content);
    const contentHtml = this.filters.search ? highlight(content, this.filters.search) : esc(content);
    const time = relTime(pin.created_at);
    const tags = (pin.tags || []).slice(0, 2);
    const isSelected = this.selectedPinIds.has(pin.id);
    const ic = impColor(pin.importance);
    const sc = statusColor(pin.status);
    const statusLabel = pin.status === 'in_progress' ? 'In Progress' : pin.status.charAt(0).toUpperCase() + pin.status.slice(1);

    return `
      <div class="wk-row${isSelected ? ' wk-selected' : ''}" data-pin-id="${esc(pin.id)}" data-status="${esc(pin.status)}" role="button" tabindex="0">
        <label class="wk-checkbox-wrap" onclick="event.stopPropagation()">
          <input type="checkbox" class="wk-checkbox" data-id="${esc(pin.id)}" ${isSelected ? 'checked' : ''} />
        </label>
        <span class="wk-imp-badge" style="background:${ic}" title="Importance: ${pin.importance}">${pin.importance}</span>
        <span class="wk-row-content">${contentHtml}</span>
        <span class="wk-row-project">${esc(pin.project_id)}</span>
        ${tags.length ? `<span class="wk-row-tags">${tags.map(t => `<span class="wk-tag">#${esc(t)}</span>`).join('')}</span>` : ''}
        <span class="wk-status-dot" style="background:${sc}" title="${statusLabel}"></span>
        <span class="wk-row-time">${time}</span>
        <span class="wk-row-actions">
          ${pin.status !== 'completed' ? `<button class="wk-action-btn wk-complete-btn" data-id="${esc(pin.id)}" title="Complete (c)">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17L4 12"/></svg>
          </button>` : ''}
          <button class="wk-action-btn wk-edit-btn" data-id="${esc(pin.id)}" title="Edit (Enter)">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
          ${pin.importance >= 4 && pin.status === 'completed' ? `<button class="wk-action-btn wk-promote-btn" data-id="${esc(pin.id)}" title="Promote to Memory">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 15V3M12 3L8 7M12 3L16 7M4 17V19C4 20.1 4.9 21 6 21H18C19.1 21 20 20.1 20 19V17"/></svg>
          </button>` : ''}
          <button class="wk-action-btn wk-delete-btn" data-id="${esc(pin.id)}" title="Delete">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
          </button>
        </span>
      </div>`;
  }

  /* ── Render pin list / kanban ─────────────────────────────── */

  renderPinList(skeleton = false) {
    const container = this.querySelector('.wk-list');
    if (!container) return;

    if (skeleton) {
      container.innerHTML = Array.from({ length: 8 }, () =>
        '<div class="wk-row wk-skeleton"><div class="wk-sk-line" style="width:' + (40 + Math.random() * 50) + '%"></div></div>'
      ).join('');
      return;
    }

    if (this.currentView === 'kanban') {
      container.innerHTML = this.renderKanbanBoard();
      return;
    }

    const pins = this.getFilteredPins();
    if (pins.length === 0) {
      const hasFilters = this.filters.search || this.selectedProject || this.filters.importance !== null || this.filters.tags.length > 0;
      container.innerHTML = `
        <div class="wk-empty">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          <p>${hasFilters ? 'No pins match your filters' : 'No pins yet. Press <kbd>n</kbd> to create one.'}</p>
          ${hasFilters ? '<button class="wk-clear-all-btn">Clear filters</button>' : ''}
        </div>`;
      return;
    }

    container.innerHTML = pins.map(p => this.buildPinRow(p)).join('');
  }

  renderKanbanBoard() {
    const pins = this.getFilteredPins();
    const groups = { open: [], in_progress: [], completed: [] };
    pins.forEach(p => { if (groups[p.status]) groups[p.status].push(p); });

    const renderCol = (status, label, color, items) => {
      return `
        <div class="wk-kanban-col" data-status="${status}">
          <div class="wk-kanban-col-header">
            <span class="wk-kanban-col-dot" style="background:${color}"></span>
            <span class="wk-kanban-col-title">${label}</span>
            <span class="wk-kanban-col-count">${items.length}</span>
          </div>
          <div class="wk-kanban-col-content">
            ${items.map(pin => `
              <div class="wk-kanban-card" data-pin-id="${esc(pin.id)}" data-status="${esc(pin.status)}" draggable="true">
                <div class="wk-kanban-card-top">
                  <span class="wk-imp-badge" style="background:${impColor(pin.importance)}">${pin.importance}</span>
                  <span class="wk-kanban-card-content">${esc(truncate(pin.content, 80))}</span>
                </div>
                <div class="wk-kanban-card-bottom">
                  <span class="wk-kanban-card-project">${esc(pin.project_id)}</span>
                  <span class="wk-kanban-card-time">${relTime(pin.created_at)}</span>
                </div>
              </div>
            `).join('') || '<div class="wk-kanban-empty">No items</div>'}
          </div>
        </div>`;
    };

    return `<div class="wk-kanban">
      ${renderCol('open', 'Open', statusColor('open'), groups.open)}
      ${renderCol('in_progress', 'In Progress', statusColor('in_progress'), groups.in_progress)}
      ${renderCol('completed', 'Completed', statusColor('completed'), groups.completed)}
    </div>`;
  }

  /* ── Session history ─────────────────────────────────────── */

  renderSessionHistory() {
    const footer = this.querySelector('.wk-footer');
    if (!footer) return;

    const sessionHistory = this.sessions.filter(s => s.status !== 'active');
    if (sessionHistory.length === 0) return;

    // Insert before footer
    let historyEl = this.querySelector('.wk-session-history');
    if (!historyEl) {
      historyEl = document.createElement('div');
      historyEl.className = 'wk-session-history';
      footer.before(historyEl);
    }

    historyEl.innerHTML = `
      <button class="wk-session-history-toggle">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
        Session History (${sessionHistory.length})
        <svg class="wk-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      <div class="wk-session-list" style="display:none">
        ${sessionHistory.slice(0, 10).map(s => {
          const duration = s.started_at && s.ended_at ? timeDiff(s.started_at, s.ended_at) : '-';
          return `
            <div class="wk-session-item" data-session-id="${esc(s.id)}">
              <strong>${esc(s.project_id)}</strong>
              <span class="wk-session-item-meta">${relTime(s.started_at)} · ${duration}</span>
              ${s.summary ? `<span class="wk-session-item-summary">${esc(truncate(s.summary, 80))}</span>` : ''}
              <button class="wk-session-pins-btn" data-session-id="${esc(s.id)}">Pins</button>
            </div>`;
        }).join('')}
      </div>
    `;
  }

  /* ── Footer ──────────────────────────────────────────────── */

  renderFooter() {
    const footer = this.querySelector('.wk-footer');
    if (!footer) return;
    const pins = this.getFilteredPins();

    footer.innerHTML = `
      <span class="wk-count">${pins.length} pins</span>
      <button class="wk-shortcuts-hint" title="Keyboard shortcuts (?)"><kbd>?</kbd> Shortcuts</button>
    `;
  }

  /* ── Batch bar ───────────────────────────────────────────── */

  renderBatchBar() {
    const bar = this.querySelector('.wk-batch-bar');
    if (!bar) return;
    if (this.selectedPinIds.size === 0) { bar.style.display = 'none'; return; }

    bar.style.display = 'flex';
    bar.innerHTML = `
      <span class="wk-batch-count">${this.selectedPinIds.size} selected</span>
      <button class="wk-batch-complete-btn">Complete</button>
      <button class="wk-batch-delete-btn">Delete</button>
      <button class="wk-batch-cancel-btn">Clear</button>
    `;
  }

  /* ── Event delegation ────────────────────────────────────── */

  setupEventListeners() {
    // ── Click delegation ──
    this.addEventListener('click', (e) => {
      const target = e.target;

      // Chip remove
      const chipRemove = target.closest('.wk-chip-remove');
      if (chipRemove) { this.removeFilter(chipRemove.dataset.filter); return; }
      if (target.closest('.wk-clear-all-btn')) { this.clearAllFilters(); return; }

      // View toggle
      const viewBtn = target.closest('.wk-view-btn');
      if (viewBtn) {
        this.currentView = viewBtn.dataset.view;
        this.querySelectorAll('.wk-view-btn').forEach(b => b.classList.toggle('active', b === viewBtn));
        this.renderPinList(false);
        return;
      }

      // New pin
      if (target.closest('.wk-new-btn')) { this.openNewPinOverlay(); return; }

      // Sort direction
      if (target.closest('.wk-sort-dir-btn')) {
        this.filters.sortDir = this.filters.sortDir === 'desc' ? 'asc' : 'desc';
        target.closest('.wk-sort-dir-btn').textContent = this.filters.sortDir === 'desc' ? '↓' : '↑';
        this.resetAndLoad();
        return;
      }

      // Session end
      if (target.closest('.wk-session-end-btn')) { this.openEndSessionOverlay(); return; }

      // Session history toggle
      if (target.closest('.wk-session-history-toggle')) {
        const list = this.querySelector('.wk-session-list');
        if (list) list.style.display = list.style.display === 'none' ? 'block' : 'none';
        return;
      }

      // Session pins toggle
      const sessionPinsBtn = target.closest('.wk-session-pins-btn');
      if (sessionPinsBtn) { this.toggleSessionPins(sessionPinsBtn.dataset.sessionId); return; }

      // Pin actions (stop propagation from row click)
      const completeBtn = target.closest('.wk-complete-btn');
      if (completeBtn) { e.stopPropagation(); this.completePin(completeBtn.dataset.id); return; }
      const editBtn = target.closest('.wk-edit-btn');
      if (editBtn) { e.stopPropagation(); this.openEditPinOverlay(editBtn.dataset.id); return; }
      const promoteBtn = target.closest('.wk-promote-btn');
      if (promoteBtn) { e.stopPropagation(); this.promotePin(promoteBtn.dataset.id); return; }
      const deleteBtn = target.closest('.wk-delete-btn');
      if (deleteBtn) { e.stopPropagation(); this.deletePin(deleteBtn.dataset.id); return; }

      // Peek panel actions
      if (target.closest('.wk-peek-close')) { this.closePeek(); return; }
      if (target.closest('.wk-peek-edit')) {
        const id = target.closest('.wk-peek-edit').dataset.id;
        if (id) { this.closePeek(); this.openEditPinOverlay(id); }
        return;
      }
      if (target.closest('.wk-peek-complete')) {
        const id = target.closest('.wk-peek-complete').dataset.id;
        if (id) { this.closePeek(); this.completePin(id); }
        return;
      }
      if (target.closest('.wk-peek-promote')) {
        const id = target.closest('.wk-peek-promote').dataset.id;
        if (id) { this.closePeek(); this.promotePin(id); }
        return;
      }
      if (target.closest('.wk-peek-delete')) {
        const id = target.closest('.wk-peek-delete').dataset.id;
        if (id) { this.closePeek(); this.deletePin(id); }
        return;
      }

      // Batch bar
      if (target.closest('.wk-batch-complete-btn')) { this.batchComplete(); return; }
      if (target.closest('.wk-batch-delete-btn')) { this.batchDelete(); return; }
      if (target.closest('.wk-batch-cancel-btn')) { this.selectedPinIds.clear(); this.renderBatchBar(); this.renderPinList(false); return; }

      // Shortcuts hint
      if (target.closest('.wk-shortcuts-hint')) { this.toggleShortcutsHelp(); return; }

      // Kanban card click → open peek
      const kanbanCard = target.closest('.wk-kanban-card');
      if (kanbanCard) {
        const id = kanbanCard.dataset.pinId;
        if (id) this.openPeek(id);
        return;
      }

      // Row click → navigate or peek
      const row = target.closest('.wk-row');
      if (row) {
        const id = row.dataset.pinId;
        if (id) this.openPeek(id);
        return;
      }
    });

    // ── Change delegation ──
    this.addEventListener('change', (e) => {
      const target = e.target;
      // Checkbox
      if (target.matches('.wk-checkbox')) {
        const id = target.dataset.id;
        if (target.checked) this.selectedPinIds.add(id);
        else this.selectedPinIds.delete(id);
        const row = target.closest('.wk-row');
        if (row) row.classList.toggle('wk-selected', target.checked);
        this.renderBatchBar();
        return;
      }
      // Importance filter
      if (target.matches('.wk-imp-select')) {
        this.filters.importance = target.value ? parseInt(target.value) : null;
        this.resetAndLoad();
        return;
      }
      // Sort
      if (target.matches('.wk-sort-select')) {
        this.filters.sortBy = target.value;
        this.resetAndLoad();
        return;
      }
      // Project combo
      if (target.closest('.wk-proj-combo')) {
        this.selectedProject = e.detail?.value || null;
        this.resetAndLoad();
        return;
      }
      // Tag combo
      if (target.closest('.wk-tag-combo')) {
        const val = e.detail?.value ?? '';
        this.filters.tags = val ? [val] : [];
        this.resetAndLoad();
        return;
      }
    });

    // ── Input delegation (search with debounce) ──
    this.addEventListener('input', (e) => {
      if (e.target.matches('.wk-search-input')) {
        if (this._isComposing) return;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => {
          this.filters.search = e.target.value;
          this.resetAndLoad();
        }, 300);
      }
    });

    // IME composition
    this.addEventListener('compositionstart', () => { this._isComposing = true; });
    this.addEventListener('compositionend', (e) => {
      this._isComposing = false;
      if (e.target.matches('.wk-search-input')) {
        this.filters.search = e.target.value;
        this.resetAndLoad();
      }
    });

    // ── Drag and drop (kanban) ──
    this.addEventListener('dragstart', (e) => {
      const card = e.target.closest('.wk-kanban-card');
      if (!card) return;
      card.classList.add('wk-dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', card.dataset.pinId);
    });
    this.addEventListener('dragend', (e) => {
      const card = e.target.closest('.wk-kanban-card');
      if (card) card.classList.remove('wk-dragging');
      this.querySelectorAll('.wk-kanban-col').forEach(col => col.classList.remove('wk-drag-over'));
    });
    this.addEventListener('dragover', (e) => {
      if (e.target.closest('.wk-kanban-col')) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
      }
    });
    this.addEventListener('dragenter', (e) => {
      const col = e.target.closest('.wk-kanban-col');
      if (col) col.classList.add('wk-drag-over');
    });
    this.addEventListener('dragleave', (e) => {
      const col = e.target.closest('.wk-kanban-col');
      if (col && !col.contains(e.relatedTarget)) col.classList.remove('wk-drag-over');
    });
    this.addEventListener('drop', (e) => {
      e.preventDefault();
      const col = e.target.closest('.wk-kanban-col');
      if (!col) return;
      col.classList.remove('wk-drag-over');
      const pinId = e.dataTransfer.getData('text/plain');
      const newStatus = col.dataset.status;
      if (pinId && newStatus) this.updatePinStatus(pinId, newStatus);
    });

    // ── Keyboard shortcuts ──
    this._boundKeydown = (e) => {
      if (!this.isConnected) return;

      // Cmd+K → focus search
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        const input = this.querySelector('.wk-search-input');
        if (input) input.focus();
        return;
      }

      // Shortcuts overlay
      const shortcutsEl = document.querySelector('.wk-shortcuts-overlay');
      if (shortcutsEl) {
        if (e.key === 'Escape' || e.key === '?') shortcutsEl.remove();
        return;
      }

      // Skip in input/textarea
      if (e.target.matches('input, select, textarea, .combobox-input') && e.key !== 'Escape') return;

      // Skip when overlay is open
      if (document.querySelector('.wk-modal-overlay')) return;

      const rows = Array.from(this.querySelectorAll('.wk-row'));
      const curIdx = rows.findIndex(r => r.classList.contains('wk-kbd-selected'));

      // j/k or Arrow navigation
      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault();
        const next = curIdx < rows.length - 1 ? curIdx + 1 : 0;
        rows.forEach(r => r.classList.remove('wk-kbd-selected'));
        if (rows[next]) { rows[next].classList.add('wk-kbd-selected'); rows[next].scrollIntoView({ block: 'nearest' }); }
      }
      if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault();
        const prev = curIdx > 0 ? curIdx - 1 : rows.length - 1;
        rows.forEach(r => r.classList.remove('wk-kbd-selected'));
        if (rows[prev]) { rows[prev].classList.add('wk-kbd-selected'); rows[prev].scrollIntoView({ block: 'nearest' }); }
      }

      // Enter → edit selected
      if (e.key === 'Enter') {
        const sel = this.querySelector('.wk-row.wk-kbd-selected');
        if (sel) { this.openEditPinOverlay(sel.dataset.pinId); }
      }

      // x → toggle checkbox
      if (e.key === 'x') {
        const sel = this.querySelector('.wk-row.wk-kbd-selected');
        if (sel) {
          const id = sel.dataset.pinId;
          const isSelected = this.selectedPinIds.has(id);
          if (isSelected) this.selectedPinIds.delete(id);
          else this.selectedPinIds.add(id);
          sel.classList.toggle('wk-selected', !isSelected);
          const cb = sel.querySelector('.wk-checkbox');
          if (cb) cb.checked = !isSelected;
          this.renderBatchBar();
        }
      }

      // c → complete selected
      if (e.key === 'c') {
        const sel = this.querySelector('.wk-row.wk-kbd-selected');
        if (sel && sel.dataset.status !== 'completed') {
          this.completePin(sel.dataset.pinId);
        }
      }

      // Space → peek toggle
      if (e.key === ' ') {
        e.preventDefault();
        const sel = this.querySelector('.wk-row.wk-kbd-selected');
        if (sel) {
          const id = sel.dataset.pinId;
          if (this._peekId === id) this.closePeek();
          else this.openPeek(id);
        }
      }

      // n → new pin
      if (e.key === 'n') { this.openNewPinOverlay(); }

      // 1/2 → view toggle
      if (e.key === '1') {
        this.currentView = 'list';
        this.querySelectorAll('.wk-view-btn').forEach(b => b.classList.toggle('active', b.dataset.view === 'list'));
        this.renderPinList(false);
      }
      if (e.key === '2') {
        this.currentView = 'kanban';
        this.querySelectorAll('.wk-view-btn').forEach(b => b.classList.toggle('active', b.dataset.view === 'kanban'));
        this.renderPinList(false);
      }

      // ? → shortcuts help
      if (e.key === '?') { this.toggleShortcutsHelp(); }

      // Escape → close peek / clear selection
      if (e.key === 'Escape') {
        if (this._peekId) { this.closePeek(); }
        else if (this.selectedPinIds.size > 0) {
          this.selectedPinIds.clear();
          this.renderBatchBar();
          this.renderPinList(false);
        }
      }
    };
    document.addEventListener('keydown', this._boundKeydown);
  }

  /* ── Peek panel ──────────────────────────────────────────── */

  openPeek(pinId) {
    if (this._peekId === pinId) { this.closePeek(); return; }
    this._peekId = pinId;

    const pin = this.pins.find(p => p.id === pinId);
    if (!pin) { this.closePeek(); return; }
    this._peekData = pin;

    const panel = this.querySelector('.wk-peek-panel');
    if (!panel) return;
    panel.style.display = 'block';
    this.querySelector('.wk-content-area')?.classList.add('wk-peek-open');
    this.renderPeekPanel();
  }

  closePeek() {
    this._peekId = null;
    this._peekData = null;
    const panel = this.querySelector('.wk-peek-panel');
    if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }
    this.querySelector('.wk-content-area')?.classList.remove('wk-peek-open');
  }

  renderPeekPanel() {
    const panel = this.querySelector('.wk-peek-panel');
    if (!panel || !this._peekData) return;

    const p = this._peekData;
    const ic = impColor(p.importance);
    const sc = statusColor(p.status);
    const statusLabel = p.status === 'in_progress' ? 'In Progress' : p.status.charAt(0).toUpperCase() + p.status.slice(1);
    const tags = Array.isArray(p.tags) ? p.tags : [];

    panel.innerHTML = `
      <div class="wk-peek-header">
        <span class="wk-imp-badge" style="background:${ic}">${p.importance}</span>
        <span class="wk-peek-status"><span class="wk-status-dot" style="background:${sc}"></span>${statusLabel}</span>
        <button class="wk-action-btn wk-peek-close" title="Close">&times;</button>
      </div>
      <div class="wk-peek-meta">
        <span class="wk-peek-project">${esc(p.project_id)}</span>
        <span class="wk-peek-time">${relTime(p.created_at)}</span>
        ${p.lead_time_hours ? `<span class="wk-peek-lead">Lead: ${p.lead_time_hours.toFixed(1)}h</span>` : ''}
      </div>
      ${tags.length ? `<div class="wk-peek-tags">${tags.map(t => `<span class="wk-tag">#${esc(t)}</span>`).join('')}</div>` : ''}
      <div class="wk-peek-body">${this._renderMarkdown(p.content || '')}</div>
      <div class="wk-peek-actions">
        ${p.status !== 'completed' ? `<button class="wk-peek-action-btn wk-peek-complete" data-id="${esc(p.id)}">Complete</button>` : ''}
        <button class="wk-peek-action-btn wk-peek-edit" data-id="${esc(p.id)}">Edit</button>
        ${p.importance >= 4 && p.status === 'completed' ? `<button class="wk-peek-action-btn wk-peek-promote" data-id="${esc(p.id)}">Promote</button>` : ''}
        <button class="wk-peek-action-btn wk-peek-delete" data-id="${esc(p.id)}">Delete</button>
      </div>
      <div class="wk-peek-footer">
        <span class="wk-peek-id">${p.id.substring(0, 8)}...</span>
      </div>
    `;
  }

  _renderMarkdown(text) {
    return esc(text)
      .replace(/^### (.+)$/gm, '<h4>$1</h4>')
      .replace(/^## (.+)$/gm, '<h3>$1</h3>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/^- (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
      .replace(/\n\n/g, '<br><br>')
      .replace(/\n/g, '<br>');
  }

  /* ── Overlay modals ──────────────────────────────────────── */

  openNewPinOverlay() {
    this._removeOverlays();
    const projectOpts = this.projects.length > 0
      ? this.projects.map(p => p.id)
      : [...new Set(this.pins.map(p => p.project_id).filter(Boolean))];
    const defaultProject = this.selectedProject || (projectOpts.length > 0 ? projectOpts[0] : 'default');

    const overlay = document.createElement('div');
    overlay.className = 'wk-modal-overlay';
    overlay.innerHTML = `
      <div class="wk-modal">
        <div class="wk-modal-header">
          <h3>New Pin</h3>
          <button class="wk-modal-close">&times;</button>
        </div>
        <form class="wk-modal-form" id="wk-new-pin-form">
          <div class="wk-form-group">
            <label>Content</label>
            <textarea name="content" rows="3" placeholder="What are you working on?" required></textarea>
          </div>
          <div class="wk-form-row">
            <div class="wk-form-group">
              <label>Project</label>
              <input type="text" name="project" value="${esc(defaultProject)}" placeholder="Project ID" />
            </div>
            <div class="wk-form-group">
              <label>Importance</label>
              <select name="importance">
                <option value="1">1 - Low</option>
                <option value="2">2</option>
                <option value="3" selected>3 - Medium</option>
                <option value="4">4</option>
                <option value="5">5 - High</option>
              </select>
            </div>
          </div>
          <div class="wk-form-group">
            <label>Tags (comma separated)</label>
            <input type="text" name="tags" placeholder="bug, feature, urgent" />
          </div>
          <div class="wk-form-actions">
            <button type="button" class="wk-modal-cancel">Cancel</button>
            <button type="submit" class="wk-modal-submit">Create Pin</button>
          </div>
        </form>
      </div>
    `;
    document.body.appendChild(overlay);

    // Focus textarea
    setTimeout(() => overlay.querySelector('textarea')?.focus(), 50);

    // Events
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay || e.target.closest('.wk-modal-close') || e.target.closest('.wk-modal-cancel')) {
        overlay.remove();
      }
    });
    overlay.querySelector('form').addEventListener('submit', (e) => {
      e.preventDefault();
      this.handleNewPin(overlay);
    });
  }

  openEditPinOverlay(pinId) {
    const pin = this.pins.find(p => p.id === pinId);
    if (!pin) return;

    this._removeOverlays();
    const overlay = document.createElement('div');
    overlay.className = 'wk-modal-overlay';
    overlay.innerHTML = `
      <div class="wk-modal">
        <div class="wk-modal-header">
          <h3>Edit Pin</h3>
          <button class="wk-modal-close">&times;</button>
        </div>
        <form class="wk-modal-form" id="wk-edit-pin-form" data-pin-id="${esc(pin.id)}">
          <div class="wk-form-group">
            <label>Content</label>
            <textarea name="content" rows="3" required>${esc(pin.content)}</textarea>
          </div>
          <div class="wk-form-row">
            <div class="wk-form-group">
              <label>Importance</label>
              <select name="importance">
                ${[1,2,3,4,5].map(i => `<option value="${i}" ${pin.importance === i ? 'selected' : ''}>${i}${i===1?' - Low':i===3?' - Medium':i===5?' - High':''}</option>`).join('')}
              </select>
            </div>
            <div class="wk-form-group">
              <label>Status</label>
              <select name="status">
                <option value="open" ${pin.status === 'open' ? 'selected' : ''}>Open</option>
                <option value="in_progress" ${pin.status === 'in_progress' ? 'selected' : ''}>In Progress</option>
                <option value="completed" ${pin.status === 'completed' ? 'selected' : ''}>Completed</option>
              </select>
            </div>
          </div>
          <div class="wk-form-group">
            <label>Tags (comma separated)</label>
            <input type="text" name="tags" value="${esc((pin.tags || []).join(', '))}" />
          </div>
          <div class="wk-form-actions">
            <button type="button" class="wk-modal-cancel">Cancel</button>
            <button type="submit" class="wk-modal-submit">Save</button>
          </div>
        </form>
      </div>
    `;
    document.body.appendChild(overlay);
    setTimeout(() => overlay.querySelector('textarea')?.focus(), 50);

    overlay.addEventListener('click', (e) => {
      if (e.target === overlay || e.target.closest('.wk-modal-close') || e.target.closest('.wk-modal-cancel')) {
        overlay.remove();
      }
    });
    overlay.querySelector('form').addEventListener('submit', (e) => {
      e.preventDefault();
      this.handleEditPin(overlay);
    });
  }

  openEndSessionOverlay() {
    if (!this.activeSession) return;
    this._removeOverlays();

    const overlay = document.createElement('div');
    overlay.className = 'wk-modal-overlay';
    overlay.innerHTML = `
      <div class="wk-modal" style="max-width:400px">
        <div class="wk-modal-header">
          <h3>End Session</h3>
          <button class="wk-modal-close">&times;</button>
        </div>
        <form class="wk-modal-form" id="wk-end-session-form">
          <div class="wk-form-group">
            <label>Summary (optional)</label>
            <textarea name="summary" rows="2" placeholder="What did you accomplish?"></textarea>
          </div>
          <div class="wk-form-actions">
            <button type="button" class="wk-modal-cancel">Cancel</button>
            <button type="submit" class="wk-modal-submit">End Session</button>
          </div>
        </form>
      </div>
    `;
    document.body.appendChild(overlay);
    setTimeout(() => overlay.querySelector('textarea')?.focus(), 50);

    overlay.addEventListener('click', (e) => {
      if (e.target === overlay || e.target.closest('.wk-modal-close') || e.target.closest('.wk-modal-cancel')) {
        overlay.remove();
      }
    });
    overlay.querySelector('form').addEventListener('submit', (e) => {
      e.preventDefault();
      this.handleEndSession(overlay);
    });
  }

  _removeOverlays() {
    document.querySelectorAll('.wk-modal-overlay').forEach(el => el.remove());
  }

  /* ── API actions ─────────────────────────────────────────── */

  async handleNewPin(overlay) {
    const form = overlay.querySelector('form');
    const content = form.querySelector('[name=content]').value;
    const project_id = form.querySelector('[name=project]').value || 'default';
    const importance = parseInt(form.querySelector('[name=importance]').value);
    const tagsInput = form.querySelector('[name=tags]').value;
    const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(t => t) : [];

    try {
      const newPin = await window.app.apiClient.post('/work/pins', { content, project_id, importance, tags });
      overlay.remove();
      this.pins.unshift(newPin);
      this.renderContent();
      this.updateProjectCombo();
      showToast('Pin created', 'success');
    } catch (error) {
      showToast(`Failed to create pin: ${error.message}`, 'error');
    }
  }

  async handleEditPin(overlay) {
    const form = overlay.querySelector('form');
    const pinId = form.dataset.pinId;
    const content = form.querySelector('[name=content]').value;
    const importance = parseInt(form.querySelector('[name=importance]').value);
    const status = form.querySelector('[name=status]').value;
    const tagsInput = form.querySelector('[name=tags]').value;
    const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(t => t) : [];

    try {
      const updated = await window.app.apiClient.put(`/work/pins/${pinId}`, { content, importance, status, tags });
      overlay.remove();
      const idx = this.pins.findIndex(p => p.id === pinId);
      if (idx !== -1) this.pins[idx] = { ...this.pins[idx], ...updated };
      this.renderContent();
      showToast('Pin updated', 'success');
    } catch (error) {
      showToast(`Failed to update pin: ${error.message}`, 'error');
    }
  }

  async completePin(pinId) {
    const pin = this.pins.find(p => p.id === pinId);
    if (!pin) return;
    const oldStatus = pin.status;
    pin.status = 'completed';
    this.renderContent();

    try {
      const result = await window.app.apiClient.put(`/work/pins/${pinId}/complete`);
      const idx = this.pins.findIndex(p => p.id === pinId);
      if (idx !== -1) this.pins[idx] = { ...this.pins[idx], ...result };

      if (result.suggest_promotion) {
        const toast = window.app?.toastNotifications;
        if (toast) {
          toast.show('Promote this pin to a permanent memory?', {
            type: 'info', title: 'Promote Pin', persistent: true,
            actions: [
              { label: 'Promote', primary: true, callback: () => this.promotePin(pinId) },
              { label: 'Skip', callback: () => {} }
            ]
          });
        }
      } else {
        showToast('Pin completed', 'success');
      }
      this.renderContent();
    } catch (error) {
      pin.status = oldStatus;
      this.renderContent();
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
    const idx = this.pins.findIndex(p => p.id === pinId);
    if (idx === -1) return;
    const removed = this.pins.splice(idx, 1)[0];
    this.selectedPinIds.delete(pinId);
    if (this._peekId === pinId) this.closePeek();
    this.renderContent();

    try {
      await window.app.apiClient.delete(`/work/pins/${pinId}`);
      showToast('Pin deleted', 'success');
    } catch (error) {
      this.pins.splice(idx, 0, removed);
      this.renderContent();
      showToast(`Failed to delete pin: ${error.message}`, 'error');
    }
  }

  async updatePinStatus(pinId, newStatus) {
    const pin = this.pins.find(p => p.id === pinId);
    if (!pin || pin.status === newStatus) return;
    const oldStatus = pin.status;
    pin.status = newStatus;
    this.renderContent();

    try {
      await window.app.apiClient.patch(`/work/pins/${pinId}`, { status: newStatus });
      showToast(`Pin moved to ${newStatus.replace('_', ' ')}`, 'success');
    } catch (error) {
      pin.status = oldStatus;
      this.renderContent();
      showToast(`Failed to update pin status: ${error.message}`, 'error');
    }
  }

  /* ── Session actions ─────────────────────────────────────── */

  async handleEndSession(overlay) {
    if (!this.activeSession) return;
    const summary = overlay.querySelector('[name=summary]')?.value || '';

    try {
      await window.app.apiClient.post(
        `/work/sessions/${this.activeSession.id}/end`,
        summary ? { summary } : {}
      );
      overlay.remove();
      showToast('Session ended', 'success');
      await this.loadData();
    } catch (error) {
      showToast(`Failed to end session: ${error.message}`, 'error');
    }
  }

  async toggleSessionPins(sessionId) {
    const existing = this.querySelector(`.wk-session-pins-list[data-session-id="${sessionId}"]`);
    if (existing) { existing.remove(); return; }

    try {
      const data = await window.app.apiClient.get('/work/pins', { session_id: sessionId, limit: 50 });
      const pins = data.pins || [];
      const sessionItem = this.querySelector(`.wk-session-item[data-session-id="${sessionId}"]`);
      if (!sessionItem) return;

      const listEl = document.createElement('div');
      listEl.className = 'wk-session-pins-list';
      listEl.dataset.sessionId = sessionId;
      listEl.innerHTML = pins.length === 0
        ? '<span class="wk-session-pins-empty">No pins</span>'
        : pins.map(p => {
            return `<div class="wk-session-pin-item">
              <span class="wk-status-dot" style="background:${statusColor(p.status)}"></span>
              <span>${esc(truncate(p.content, 80))}</span>
              <span class="wk-imp-badge" style="background:${impColor(p.importance)};font-size:0.625rem">${p.importance}</span>
            </div>`;
          }).join('');
      sessionItem.after(listEl);
    } catch (error) {
      showToast(`Failed to load session pins: ${error.message}`, 'error');
    }
  }

  /* ── Batch actions ───────────────────────────────────────── */

  async batchComplete() {
    if (this.selectedPinIds.size === 0) return;
    const ids = [...this.selectedPinIds];
    ids.forEach(id => { const pin = this.pins.find(p => p.id === id); if (pin) pin.status = 'completed'; });
    this.selectedPinIds.clear();
    this.renderContent();

    let failed = 0;
    for (const id of ids) {
      try { await window.app.apiClient.put(`/work/pins/${id}/complete`); } catch { failed++; }
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
    this.pins = this.pins.filter(p => !ids.includes(p.id));
    this.selectedPinIds.clear();
    this.renderContent();

    let failed = 0;
    for (const id of ids) {
      try { await window.app.apiClient.delete(`/work/pins/${id}`); } catch { failed++; }
    }
    if (failed > 0) {
      showToast(`${ids.length - failed} deleted, ${failed} failed`, 'warning');
      await this.loadData();
    } else {
      showToast(`${ids.length} pins deleted`, 'success');
    }
  }

  /* ── Shortcuts help ──────────────────────────────────────── */

  toggleShortcutsHelp() {
    const existing = document.querySelector('.wk-shortcuts-overlay');
    if (existing) { existing.remove(); return; }

    const overlay = document.createElement('div');
    overlay.className = 'wk-shortcuts-overlay';
    overlay.innerHTML = `
      <div class="wk-shortcuts-panel">
        <h3>Keyboard Shortcuts</h3>
        <div class="wk-shortcuts-grid">
          <kbd>j</kbd><span>Move down</span>
          <kbd>k</kbd><span>Move up</span>
          <kbd>Space</kbd><span>Toggle peek panel</span>
          <kbd>Enter</kbd><span>Edit selected pin</span>
          <kbd>x</kbd><span>Toggle selection</span>
          <kbd>c</kbd><span>Complete selected pin</span>
          <kbd>n</kbd><span>New pin</span>
          <kbd>1</kbd><span>List view</span>
          <kbd>2</kbd><span>Kanban view</span>
          <kbd>${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl+'}K</kbd><span>Focus search</span>
          <kbd>?</kbd><span>Toggle this help</span>
          <kbd>Esc</kbd><span>Close panel / clear</span>
        </div>
        <button class="wk-shortcuts-close">Close</button>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay || e.target.closest('.wk-shortcuts-close')) overlay.remove();
    });
  }
}

customElements.define('work-page', WorkPage);
export { WorkPage };

/* ── Styles (injected once) ──────────────────────────────────── */
const style = document.createElement('style');
style.textContent = `
  /* ── Layout ─────────────────────────────── */
  .wk {
    display: block;
    max-width: var(--container-xl, 1280px);
    width: 100%;
    margin: 0 auto;
    padding: var(--space-6, 1.5rem) var(--space-4, 1rem);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    box-sizing: border-box;
    overflow-x: hidden;
  }

  /* ── Toolbar ────────────────────────────── */
  .wk-toolbar {
    display: flex;
    align-items: center;
    gap: 0.625rem;
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
  }
  .wk-title {
    font-size: 1.125rem;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
    flex-shrink: 0;
  }
  .wk-search-wrap {
    flex: 1;
    min-width: 160px;
    position: relative;
  }
  .wk-search-icon {
    position: absolute;
    left: 10px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--text-muted);
    pointer-events: none;
  }
  .wk-search-input {
    width: 100%;
    padding: 0.4375rem 0.625rem 0.4375rem 2rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.8125rem;
    outline: none;
    transition: border-color 0.15s;
    box-sizing: border-box;
  }
  .wk-search-input:focus {
    border-color: var(--text-primary);
    box-shadow: 0 0 0 2px rgba(0,0,0,0.06);
  }

  /* Selects & Comboboxes */
  .wk-imp-select,
  .wk-sort-select {
    padding: 0.4375rem 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.75rem;
    cursor: pointer;
    outline: none;
  }
  .wk-proj-combo,
  .wk-tag-combo {
    flex-shrink: 0;
    width: 140px;
  }
  .wk-proj-combo .combobox-input,
  .wk-tag-combo .combobox-input {
    padding: 0.4375rem 1.75rem 0.4375rem 0.5rem;
    font-size: 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-primary);
  }
  .wk-proj-combo .combobox-input:focus,
  .wk-tag-combo .combobox-input:focus {
    border-color: var(--text-primary);
    box-shadow: 0 0 0 2px rgba(0,0,0,0.06);
  }
  .wk-proj-combo .combobox-dropdown,
  .wk-tag-combo .combobox-dropdown {
    border-radius: var(--border-radius-sm, 6px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.12);
  }

  .wk-sort-dir-btn {
    padding: 0.4375rem 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-primary);
    cursor: pointer;
    font-size: 0.8125rem;
    line-height: 1;
  }
  .wk-sort-dir-btn:hover { border-color: var(--border-hover); }

  /* View toggle */
  .wk-view-toggle {
    display: flex;
    gap: 2px;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    overflow: hidden;
  }
  .wk-view-btn {
    padding: 0.375rem 0.5rem;
    border: none;
    background: var(--bg-primary);
    color: var(--text-muted);
    cursor: pointer;
    display: flex;
    align-items: center;
    transition: all 0.15s;
  }
  .wk-view-btn:hover { background: var(--bg-secondary); }
  .wk-view-btn.active {
    background: var(--text-primary);
    color: var(--bg-primary);
  }

  /* New pin button */
  .wk-new-btn {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.4375rem 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--text-primary);
    color: var(--bg-primary);
    font-size: 0.8125rem;
    font-weight: 500;
    cursor: pointer;
    transition: opacity 0.15s;
    flex-shrink: 0;
  }
  .wk-new-btn:hover { opacity: 0.85; }

  /* ── Session banner ─────────────────────── */
  .wk-session-inner {
    display: flex;
    align-items: center;
    gap: 0.625rem;
    padding: 0.5rem 0.75rem;
    margin-bottom: 0.5rem;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    font-size: 0.8125rem;
    color: var(--text-primary);
  }
  .wk-session-text { flex: 1; }
  .wk-session-end-btn {
    padding: 0.25rem 0.625rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.75rem;
    cursor: pointer;
  }
  .wk-session-end-btn:hover { border-color: var(--text-primary); color: var(--text-primary); }

  /* ── Batch bar ──────────────────────────── */
  .wk-batch-bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    margin-bottom: 0.5rem;
    background: var(--bg-tertiary, var(--bg-secondary));
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    font-size: 0.8125rem;
    color: var(--text-primary);
  }
  .wk-batch-count { flex: 1; font-weight: 500; }
  .wk-batch-bar button {
    padding: 0.25rem 0.625rem;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.75rem;
    cursor: pointer;
  }
  .wk-batch-bar button:hover { background: var(--bg-secondary); }
  .wk-batch-delete-btn { color: var(--text-muted) !important; }

  /* ── Chips ──────────────────────────────── */
  .wk-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
    margin-bottom: 0.5rem;
  }
  .wk-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.1875rem 0.5rem;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 99px;
    font-size: 0.6875rem;
    color: var(--text-secondary);
  }
  .wk-chip-remove {
    border: none;
    background: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 0.875rem;
    line-height: 1;
    padding: 0;
  }
  .wk-chip-remove:hover { color: var(--text-primary); }
  .wk-clear-all-btn {
    border: none;
    background: none;
    color: var(--text-primary);
    font-size: 0.6875rem;
    cursor: pointer;
    padding: 0.1875rem 0.375rem;
  }
  .wk-clear-all-btn:hover { text-decoration: underline; }

  /* ── Stats bar ──────────────────────────── */
  .wk-stats-bar {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.375rem 0;
    margin-bottom: 0.5rem;
    font-size: 0.75rem;
    color: var(--text-secondary);
  }
  .wk-stat {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
  }
  .wk-stat-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  /* ── Content area (list + peek) ─────────── */
  .wk-content-area {
    display: flex;
    gap: 0;
    transition: gap 0.2s;
  }
  .wk-content-area.wk-peek-open {
    gap: 1rem;
  }
  .wk-list {
    flex: 1;
    min-width: 0;
  }

  /* ── Row ─────────────────────────────────── */
  .wk-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    height: 40px;
    padding: 0 0.625rem;
    border-bottom: 1px solid var(--border-color);
    cursor: pointer;
    transition: background 0.1s;
    position: relative;
  }
  .wk-row:hover { background: var(--bg-secondary); }
  .wk-row.wk-kbd-selected { background: var(--bg-secondary); box-shadow: inset 2px 0 0 var(--text-primary); }
  .wk-row.wk-selected { background: rgba(0,0,0,0.03); }

  .wk-checkbox-wrap {
    display: flex;
    align-items: center;
    flex-shrink: 0;
  }
  .wk-checkbox {
    width: 14px;
    height: 14px;
    cursor: pointer;
    accent-color: var(--text-primary);
  }

  .wk-imp-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 4px;
    font-size: 0.6875rem;
    font-weight: 600;
    color: #fff;
    flex-shrink: 0;
  }

  .wk-row-content {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.8125rem;
    color: var(--text-primary);
  }
  .wk-row-content mark {
    background: rgba(250, 204, 21, 0.3);
    color: inherit;
    border-radius: 2px;
    padding: 0 1px;
  }

  .wk-row-project {
    flex-shrink: 0;
    font-size: 0.6875rem;
    color: var(--text-muted);
    background: var(--bg-secondary);
    padding: 0.125rem 0.375rem;
    border-radius: 3px;
    max-width: 100px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .wk-row-tags {
    display: flex;
    gap: 0.25rem;
    flex-shrink: 0;
  }
  .wk-tag {
    font-size: 0.625rem;
    color: var(--text-muted);
    background: var(--bg-tertiary, var(--bg-secondary));
    padding: 0 4px;
    border-radius: 3px;
    white-space: nowrap;
  }

  .wk-status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .wk-row-time {
    font-size: 0.6875rem;
    color: var(--text-muted);
    flex-shrink: 0;
    min-width: 48px;
    text-align: right;
  }

  .wk-row-actions {
    display: flex;
    gap: 0.125rem;
    opacity: 0;
    transition: opacity 0.1s;
    position: absolute;
    right: 0.625rem;
    background: var(--bg-secondary);
    padding: 0 0.25rem;
  }
  .wk-row:hover .wk-row-actions { opacity: 1; }

  .wk-action-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    background: var(--bg-primary);
    color: var(--text-muted);
    cursor: pointer;
    transition: all 0.1s;
  }
  .wk-action-btn:hover {
    border-color: var(--border-hover);
    color: var(--text-primary);
    background: var(--bg-secondary);
  }

  /* ── Skeleton ────────────────────────────── */
  .wk-row.wk-skeleton {
    pointer-events: none;
    cursor: default;
  }
  .wk-sk-line {
    height: 12px;
    border-radius: 4px;
    background: linear-gradient(90deg, var(--bg-secondary) 25%, var(--bg-tertiary, var(--bg-secondary)) 50%, var(--bg-secondary) 75%);
    background-size: 200% 100%;
    animation: sk-shimmer 1.5s infinite;
  }
  @keyframes sk-shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }

  /* ── Empty state ─────────────────────────── */
  .wk-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
    padding: 3rem 1rem;
    color: var(--text-muted);
    text-align: center;
  }
  .wk-empty p { margin: 0; font-size: 0.875rem; }
  .wk-empty kbd {
    display: inline-block;
    padding: 0.125rem 0.375rem;
    border: 1px solid var(--border-color);
    border-radius: 3px;
    background: var(--bg-secondary);
    font-size: 0.75rem;
  }

  /* ── Kanban ──────────────────────────────── */
  .wk-kanban {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.75rem;
    min-height: 300px;
  }
  .wk-kanban-col {
    background: var(--bg-secondary);
    border-radius: var(--border-radius-sm, 6px);
    padding: 0.75rem;
    transition: all 0.15s;
  }
  .wk-kanban-col.wk-drag-over {
    outline: 2px dashed var(--text-primary);
    outline-offset: -2px;
    background: rgba(0,0,0,0.02);
  }
  .wk-kanban-col-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.625rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border-color);
  }
  .wk-kanban-col-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .wk-kanban-col-title { font-size: 0.8125rem; font-weight: 600; color: var(--text-primary); }
  .wk-kanban-col-count { font-size: 0.6875rem; color: var(--text-muted); }
  .wk-kanban-col-content { display: flex; flex-direction: column; gap: 0.375rem; min-height: 100px; }

  .wk-kanban-card {
    padding: 0.5rem;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    cursor: grab;
    transition: all 0.15s;
  }
  .wk-kanban-card:hover { border-color: var(--border-hover); box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
  .wk-kanban-card.wk-dragging { opacity: 0.4; transform: rotate(1deg); }
  .wk-kanban-card-top {
    display: flex;
    align-items: flex-start;
    gap: 0.375rem;
    margin-bottom: 0.25rem;
  }
  .wk-kanban-card-content {
    font-size: 0.75rem;
    color: var(--text-primary);
    line-height: 1.4;
    word-break: break-word;
  }
  .wk-kanban-card-bottom {
    display: flex;
    justify-content: space-between;
    font-size: 0.625rem;
    color: var(--text-muted);
  }
  .wk-kanban-empty {
    font-size: 0.75rem;
    color: var(--text-muted);
    text-align: center;
    padding: 1.5rem 0;
  }

  /* ── Peek panel ─────────────────────────── */
  .wk-peek-panel {
    width: 360px;
    flex-shrink: 0;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    padding: 1rem;
    max-height: 70vh;
    overflow-y: auto;
    position: sticky;
    top: 1rem;
  }
  .wk-peek-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }
  .wk-peek-status {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    font-size: 0.75rem;
    color: var(--text-secondary);
    flex: 1;
  }
  .wk-peek-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 0.625rem;
    font-size: 0.6875rem;
    color: var(--text-muted);
  }
  .wk-peek-project {
    background: var(--bg-secondary);
    padding: 0.125rem 0.375rem;
    border-radius: 3px;
  }
  .wk-peek-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    margin-bottom: 0.625rem;
  }
  .wk-peek-body {
    font-size: 0.8125rem;
    color: var(--text-primary);
    line-height: 1.6;
    word-break: break-word;
    margin-bottom: 0.75rem;
  }
  .wk-peek-body h3 { font-size: 0.9375rem; margin: 0.75rem 0 0.25rem; }
  .wk-peek-body h4 { font-size: 0.875rem; margin: 0.5rem 0 0.25rem; }
  .wk-peek-body code {
    background: var(--bg-secondary);
    padding: 0.125rem 0.25rem;
    border-radius: 3px;
    font-size: 0.75rem;
  }
  .wk-peek-body ul { margin: 0.25rem 0; padding-left: 1.25rem; }
  .wk-peek-body li { margin-bottom: 0.125rem; }
  .wk-peek-actions {
    display: flex;
    gap: 0.375rem;
    margin-bottom: 0.5rem;
    flex-wrap: wrap;
  }
  .wk-peek-action-btn {
    padding: 0.3125rem 0.625rem;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.75rem;
    cursor: pointer;
    transition: all 0.1s;
  }
  .wk-peek-action-btn:hover { border-color: var(--border-hover); background: var(--bg-secondary); }
  .wk-peek-footer {
    font-size: 0.625rem;
    color: var(--text-muted);
  }

  /* ── Session history ────────────────────── */
  .wk-session-history {
    margin-top: 0.75rem;
    margin-bottom: 0.5rem;
  }
  .wk-session-history-toggle {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-secondary);
    font-size: 0.8125rem;
    cursor: pointer;
    transition: all 0.15s;
  }
  .wk-session-history-toggle:hover { background: var(--bg-secondary); }
  .wk-chevron { margin-left: auto; }
  .wk-session-list {
    border: 1px solid var(--border-color);
    border-top: none;
    border-radius: 0 0 6px 6px;
    overflow: hidden;
  }
  .wk-session-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border-color);
    font-size: 0.75rem;
    color: var(--text-primary);
  }
  .wk-session-item:last-child { border-bottom: none; }
  .wk-session-item-meta { color: var(--text-muted); flex: 1; }
  .wk-session-item-summary {
    color: var(--text-secondary);
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .wk-session-pins-btn {
    padding: 0.1875rem 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    background: var(--bg-primary);
    color: var(--text-muted);
    font-size: 0.6875rem;
    cursor: pointer;
  }
  .wk-session-pins-btn:hover { border-color: var(--border-hover); }
  .wk-session-pins-list {
    padding: 0.375rem 0.75rem 0.375rem 1.5rem;
    border-bottom: 1px solid var(--border-color);
  }
  .wk-session-pin-item {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.25rem 0;
    font-size: 0.75rem;
    color: var(--text-secondary);
  }
  .wk-session-pins-empty {
    font-size: 0.75rem;
    color: var(--text-muted);
    padding: 0.25rem 0;
  }

  /* ── Footer ─────────────────────────────── */
  .wk-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 0;
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  .wk-count { flex: 1; }
  .wk-shortcuts-hint {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    border: none;
    background: none;
    color: var(--text-muted);
    font-size: 0.6875rem;
    cursor: pointer;
  }
  .wk-shortcuts-hint:hover { color: var(--text-primary); }
  .wk-shortcuts-hint kbd {
    display: inline-block;
    padding: 0.0625rem 0.3125rem;
    border: 1px solid var(--border-color);
    border-radius: 3px;
    background: var(--bg-secondary);
    font-size: 0.625rem;
  }

  /* ── Modal overlay ──────────────────────── */
  .wk-modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10000;
    backdrop-filter: blur(2px);
  }
  .wk-modal {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1.25rem;
    width: 100%;
    max-width: 480px;
    max-height: 85vh;
    overflow-y: auto;
    box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  }
  .wk-modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
  }
  .wk-modal-header h3 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
  }
  .wk-modal-close {
    border: none;
    background: none;
    font-size: 1.25rem;
    color: var(--text-muted);
    cursor: pointer;
    padding: 0.25rem;
  }
  .wk-modal-close:hover { color: var(--text-primary); }
  .wk-form-group {
    margin-bottom: 0.75rem;
  }
  .wk-form-group label {
    display: block;
    margin-bottom: 0.25rem;
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--text-secondary);
  }
  .wk-form-group input,
  .wk-form-group textarea,
  .wk-form-group select {
    width: 100%;
    padding: 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.8125rem;
    outline: none;
    box-sizing: border-box;
    font-family: inherit;
  }
  .wk-form-group input:focus,
  .wk-form-group textarea:focus,
  .wk-form-group select:focus {
    border-color: var(--text-primary);
    box-shadow: 0 0 0 2px rgba(0,0,0,0.06);
  }
  .wk-form-group textarea { resize: vertical; min-height: 60px; }
  .wk-form-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
  }
  .wk-form-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    margin-top: 1rem;
  }
  .wk-modal-cancel {
    padding: 0.5rem 1rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: transparent;
    color: var(--text-primary);
    font-size: 0.8125rem;
    cursor: pointer;
  }
  .wk-modal-cancel:hover { background: var(--bg-secondary); }
  .wk-modal-submit {
    padding: 0.5rem 1rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--text-primary);
    color: var(--bg-primary);
    font-size: 0.8125rem;
    font-weight: 500;
    cursor: pointer;
  }
  .wk-modal-submit:hover { opacity: 0.85; }

  /* ── Shortcuts overlay ──────────────────── */
  .wk-shortcuts-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10001;
  }
  .wk-shortcuts-panel {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1.25rem;
    width: 340px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  }
  .wk-shortcuts-panel h3 {
    margin: 0 0 1rem;
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
  }
  .wk-shortcuts-grid {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.375rem 0.75rem;
    font-size: 0.8125rem;
    color: var(--text-secondary);
  }
  .wk-shortcuts-grid kbd {
    display: inline-block;
    padding: 0.125rem 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    background: var(--bg-secondary);
    font-size: 0.6875rem;
    font-family: inherit;
    text-align: center;
    min-width: 1.5rem;
    color: var(--text-primary);
  }
  .wk-shortcuts-close {
    display: block;
    width: 100%;
    margin-top: 1rem;
    padding: 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: transparent;
    color: var(--text-primary);
    font-size: 0.8125rem;
    cursor: pointer;
  }
  .wk-shortcuts-close:hover { background: var(--bg-secondary); }

  /* ── Responsive ─────────────────────────── */
  @media (max-width: 640px) {
    .wk { padding: 1rem 0.75rem; }
    .wk-toolbar { gap: 0.375rem; }
    .wk-search-wrap { min-width: 120px; order: 10; flex-basis: 100%; }
    .wk-proj-combo, .wk-tag-combo { width: 120px; }
    .wk-kanban { grid-template-columns: 1fr; }
    .wk-peek-panel { display: none !important; }
    .wk-form-row { grid-template-columns: 1fr; }
    .wk-row-project, .wk-row-tags { display: none; }
  }

  /* ── Dark mode adjustments ──────────────── */
  [data-theme="dark"] .wk-modal { box-shadow: 0 20px 60px rgba(0,0,0,0.4); }
  [data-theme="dark"] .wk-shortcuts-panel { box-shadow: 0 20px 60px rgba(0,0,0,0.4); }
  [data-theme="dark"] .wk-kanban-card:hover { box-shadow: 0 1px 4px rgba(0,0,0,0.2); }
  [data-theme="dark"] .wk-session-inner { border-color: var(--border-color); }
`;
document.head.appendChild(style);
