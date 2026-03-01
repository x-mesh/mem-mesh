/**
 * Memories Page — Linear-style compact list redesign
 * Replaces legacy card-based UI with 1-line rows, filter chips,
 * Cmd+K command palette, and load-more pagination.
 */

import { wsClient } from '../services/websocket-client.js';
import '../components/connection-status.js';
import '../components/searchable-combobox.js';

/* ── helpers (same as dashboard.js) ─────────────────────────── */

const CAT_ICONS = {
  task: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>',
  bug: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
  decision: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
  code_snippet: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
  incident: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  idea: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 00-4 12.7V17h8v-2.3A7 7 0 0012 2z"/></svg>',
  'git-history': '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><line x1="1.05" y1="12" x2="7" y2="12"/><line x1="17.01" y1="12" x2="22.96" y2="12"/></svg>'
};
const DEFAULT_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';

function esc(text) {
  if (text == null) return '';
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function relTime(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return '방금';
  if (m < 60) return `${m}분 전`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}시간 전`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}일 전`;
  if (d < 30) return `${Math.floor(d / 7)}주 전`;
  return `${Math.floor(d / 30)}개월 전`;
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

/* ── Component ──────────────────────────────────────────────── */

class MemoriesPage extends HTMLElement {
  constructor() {
    super();
    this.memories = [];
    this.isLoading = false;
    this.page = 0;
    this.pageSize = 50;
    this.totalMemories = 0;
    this.hasMore = true;
    this.sortBy = 'created_at';
    this.sortDirection = 'desc';
    this.searchQuery = '';
    this.searchMode = 'hybrid';
    this.recencyWeight = 0;
    this.timeRange = null; // today, this_week, this_month
    this._prevSortBy = 'created_at'; // remember sort before search auto-switch
    this.viewParams = {};
    this._searchTimer = null;
    this._paletteEl = null;
    this._paletteSearchTimer = null;
    this._paletteIdx = -1;
    this._isInitialized = false;
    // P1: batch selection
    this._selected = new Set();
    // P1: stats
    this._stats = null;
    // P1: active pins
    this._activePins = [];
    // P2: favorites (localStorage)
    this._favorites = new Set(JSON.parse(localStorage.getItem('mem-favorites') || '[]'));
    this._showFavoritesOnly = false;
    // P2: peek panel
    this._peekId = null;
    this._peekData = null;
    // P2: sources list (from stats)
    this._sources = [];
  }

  connectedCallback() {
    if (this._isInitialized) return;
    this._isInitialized = true;

    this.parseURLParameters();
    this.render();
    this.setupEventListeners();
    this.setupWebSocketListeners();
    this.connectWebSocket();
    this.loadMemories();
    this.loadProjectsForFilter();
    this.loadStats();
    this.loadActivePins();
  }

  disconnectedCallback() {
    if (this._boundHandlers) {
      wsClient.off('memory_created', this._boundHandlers.memoryCreated);
      wsClient.off('memory_updated', this._boundHandlers.memoryUpdated);
      wsClient.off('memory_deleted', this._boundHandlers.memoryDeleted);
    }
    if (this._boundKeydown) {
      document.removeEventListener('keydown', this._boundKeydown);
      this._boundKeydown = null;
    }
    this.destroyPalette();
  }

  /* ── URL state ──────────────────────────────────────────── */

  parseURLParameters() {
    const p = new URLSearchParams(window.location.search);
    this.viewParams = {
      category: p.get('category') || null,
      project_id: p.get('project_id') || null,
      tag: p.get('tag') || null,
      source: p.get('source') || null
    };
    this.searchQuery = p.get('query') || '';
    this.sortBy = p.get('sort_by') || 'created_at';
    this.timeRange = p.get('time_range') || null;
    this.searchMode = p.get('search_mode') || 'hybrid';
  }

  updateURL() {
    const p = new URLSearchParams();
    if (this.viewParams.category) p.set('category', this.viewParams.category);
    if (this.viewParams.project_id) p.set('project_id', this.viewParams.project_id);
    if (this.viewParams.tag) p.set('tag', this.viewParams.tag);
    if (this.viewParams.source) p.set('source', this.viewParams.source);
    if (this.searchQuery) p.set('query', this.searchQuery);
    if (this.sortBy !== 'created_at') p.set('sort_by', this.sortBy);
    if (this.timeRange) p.set('time_range', this.timeRange);
    if (this.searchMode !== 'hybrid') p.set('search_mode', this.searchMode);
    const qs = p.toString();
    window.history.replaceState({}, '', qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  }

  /* ── Render skeleton ────────────────────────────────────── */

  render() {
    this.className = 'mem page-container';
    this.innerHTML = `
      <div class="mem-toolbar">
        <h1 class="mem-title">Memories</h1>
        <div class="mem-search-wrap">
          <svg class="mem-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
          <input class="mem-search-input" type="text" placeholder="Search memories... (${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl+'}K)" value="${esc(this.searchQuery)}" />
        </div>
        <select class="mem-mode-select" title="Search mode">
          <option value="hybrid">Hybrid</option>
          <option value="exact">Exact</option>
          <option value="semantic">Semantic</option>
          <option value="fuzzy">Fuzzy</option>
        </select>
        <searchable-combobox class="mem-cat-combo" placeholder="All Categories">
          <option value="">All Categories</option>
          <option value="task" data-icon="📋">Task</option>
          <option value="bug" data-icon="🐛">Bug</option>
          <option value="idea" data-icon="💡">Idea</option>
          <option value="decision" data-icon="💎">Decision</option>
          <option value="incident" data-icon="⚠️">Incident</option>
          <option value="code_snippet" data-icon="💻">Code Snippet</option>
          <option value="git-history" data-icon="📚">Git History</option>
        </searchable-combobox>
        <searchable-combobox class="mem-proj-combo" placeholder="All Projects">
          <option value="">All Projects</option>
        </searchable-combobox>
        <select class="mem-sort-select">
          <option value="created_at">Newest</option>
          <option value="updated_at">Updated</option>
          <option value="category">Category</option>
          <option value="recency">Recency</option>
        </select>
        <div class="mem-time-range">
          <button class="mem-time-btn${this.timeRange === null ? ' active' : ''}" data-range="">All</button>
          <button class="mem-time-btn${this.timeRange === 'today' ? ' active' : ''}" data-range="today">Today</button>
          <button class="mem-time-btn${this.timeRange === 'this_week' ? ' active' : ''}" data-range="this_week">Week</button>
          <button class="mem-time-btn${this.timeRange === 'this_month' ? ' active' : ''}" data-range="this_month">Month</button>
        </div>
        <select class="mem-source-select">
          <option value="">All Sources</option>
        </select>
        <button class="mem-fav-toggle${this._showFavoritesOnly ? ' active' : ''}" title="Favorites only">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="${this._showFavoritesOnly ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
        </button>
        <button class="mem-export-btn" title="Export memories">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        </button>
        <connection-status></connection-status>
      </div>
      <div class="mem-stats-bar"></div>
      <div class="mem-batch-bar" style="display:none"></div>
      <div class="mem-chips"></div>
      <div class="mem-suggestions"></div>
      <div class="mem-content-area">
        <div class="mem-list"></div>
        <div class="mem-peek-panel" style="display:none"></div>
      </div>
      <div class="mem-footer"></div>
    `;

    // restore select/combobox values from URL
    const sortSel = this.querySelector('.mem-sort-select');
    if (sortSel) sortSel.value = this.sortBy;
    const modeSel = this.querySelector('.mem-mode-select');
    if (modeSel) modeSel.value = this.searchMode;
    const srcSel = this.querySelector('.mem-source-select');
    if (srcSel && this.viewParams.source) srcSel.value = this.viewParams.source;

    // Initialize combobox options explicitly (child <option> may not be parsed yet)
    setTimeout(() => {
      const catCombo = this.querySelector('.mem-cat-combo');
      if (catCombo) {
        catCombo.setOptions([
          { value: '', text: 'All Categories' },
          { value: 'task', text: 'Task', icon: '📋' },
          { value: 'bug', text: 'Bug', icon: '🐛' },
          { value: 'idea', text: 'Idea', icon: '💡' },
          { value: 'decision', text: 'Decision', icon: '💎' },
          { value: 'incident', text: 'Incident', icon: '⚠️' },
          { value: 'code_snippet', text: 'Code Snippet', icon: '💻' },
          { value: 'git-history', text: 'Git History', icon: '📚' }
        ]);
        if (this.viewParams.category) catCombo.setValue(this.viewParams.category);
      }
      const projCombo = this.querySelector('.mem-proj-combo');
      if (projCombo && this.viewParams.project_id) {
        projCombo.setValue(this.viewParams.project_id);
      }
    }, 0);

    this.renderChips();
  }

  /* ── Build single row (dashboard pattern) ───────────────── */

  buildRow(mem) {
    const icon = CAT_ICONS[mem.category] || DEFAULT_ICON;
    const content = truncate(mem.content);
    const time = relTime(mem.created_at);
    const source = mem.source && mem.source !== 'unknown' ? mem.source : '';
    const tags = (mem.tags || []).slice(0, 3);
    const score = mem.similarity_score ? `<span class="mem-score">${(mem.similarity_score * 100).toFixed(0)}%</span>` : '';
    const contentHtml = this.searchQuery ? highlight(content, this.searchQuery) : esc(content);
    const isSelected = this._selected.has(mem.id);
    const isFav = this._favorites.has(mem.id);
    const srcBadge = source ? `<span class="mem-source-badge mem-clickable-filter" data-filter-type="source" data-filter-value="${esc(source)}">${esc(source)}</span>` : '';

    return `
      <div class="recent-item mem-row${isSelected ? ' mem-selected' : ''}" data-memory-id="${esc(mem.id)}" role="button" tabindex="0">
        <label class="mem-checkbox-wrap" onclick="event.stopPropagation()">
          <input type="checkbox" class="mem-checkbox" data-id="${esc(mem.id)}" ${isSelected ? 'checked' : ''} />
        </label>
        <button class="mem-star-btn${isFav ? ' active' : ''}" data-id="${esc(mem.id)}" title="${isFav ? 'Remove from favorites' : 'Add to favorites'}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="${isFav ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
        </button>
        <span class="recent-item-icon">${icon}</span>
        <span class="recent-item-badge mem-clickable-filter" data-filter-type="category" data-filter-value="${esc(mem.category)}">${esc(mem.category)}</span>
        ${mem.project_id ? `<span class="recent-item-project mem-clickable-filter" data-filter-type="project_id" data-filter-value="${esc(mem.project_id)}">${esc(mem.project_id)}</span>` : ''}
        <span class="recent-item-content">${contentHtml}</span>
        ${tags.length ? `<span class="mem-tags">${tags.map(t => `<span class="mem-tag mem-clickable-filter" data-filter-type="tag" data-filter-value="${esc(t)}">#${esc(t)}</span>`).join('')}</span>` : ''}
        ${srcBadge}
        ${score}
        <span class="recent-item-time">${time}</span>
        <span class="mem-row-actions">
          <button class="mem-action-btn mem-edit-btn" data-id="${esc(mem.id)}" title="Edit">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
          <button class="mem-action-btn mem-delete-btn" data-id="${esc(mem.id)}" title="Delete">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
          </button>
        </span>
      </div>`;
  }

  /* ── Render memory list ─────────────────────────────────── */

  renderMemoryList() {
    const container = this.querySelector('.mem-list');
    if (!container) return;

    if (this.isLoading && this.page === 0) {
      container.innerHTML = Array.from({ length: 10 }, () =>
        '<div class="recent-item ml-skeleton"><div class="sk-line" style="width:' + (40 + Math.random() * 50) + '%"></div></div>'
      ).join('');
      return;
    }

    const displayMems = this._showFavoritesOnly
      ? this.memories.filter(m => this._favorites.has(m.id))
      : this.memories;

    if (displayMems.length === 0) {
      const hasFilters = this.searchQuery || Object.values(this.viewParams).some(v => v);
      container.innerHTML = `
        <div class="mem-empty">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          <p>${hasFilters ? `No results for "${esc(this.searchQuery || '')}"` : 'No memories yet'}</p>
          ${hasFilters ? '<button class="mem-clear-all-btn">Clear all filters</button>' : ''}
        </div>`;
      return;
    }

    if (this.page === 0 || this._showFavoritesOnly) {
      container.innerHTML = displayMems.map(m => this.buildRow(m)).join('');
    } else {
      // append new rows for load-more
      const frag = document.createRange().createContextualFragment(
        this.memories.slice((this.page) * this.pageSize).map(m => this.buildRow(m)).join('')
      );
      container.appendChild(frag);
    }
  }

  /* ── Footer (count + load more) ─────────────────────────── */

  renderFooter() {
    const footer = this.querySelector('.mem-footer');
    if (!footer) return;

    const count = this.memories.length;
    const total = this.totalMemories;

    if (count === 0 && !this.isLoading) {
      footer.innerHTML = '';
      return;
    }

    footer.innerHTML = `
      <span class="mem-count">${count} / ${total} memories</span>
      ${this.hasMore ? '<button class="mem-load-more-btn">Load more</button>' : ''}
    `;
  }

  /* ── Search suggestions ────────────────────────────────── */

  renderSuggestions() {
    const container = this.querySelector('.mem-suggestions');
    if (!container) return;

    const suggestions = this._suggestions || [];
    if (!suggestions.length || !this.searchQuery || this.memories.length > 5) {
      container.innerHTML = '';
      return;
    }

    container.innerHTML = `
      <span class="mem-suggest-label">Did you mean:</span>
      ${suggestions.map(s => `<button class="mem-suggest-item" data-query="${esc(s)}">${esc(s)}</button>`).join('')}
    `;
  }

  /* ── Filter chips ───────────────────────────────────────── */

  renderChips() {
    const container = this.querySelector('.mem-chips');
    if (!container) return;

    const chips = [];
    if (this.viewParams.category) chips.push({ key: 'category', label: this.viewParams.category });
    if (this.viewParams.project_id) chips.push({ key: 'project_id', label: `project:${this.viewParams.project_id}` });
    if (this.viewParams.tag) chips.push({ key: 'tag', label: `#${this.viewParams.tag}` });
    if (this.viewParams.source) chips.push({ key: 'source', label: `source:${this.viewParams.source}` });
    if (this.timeRange) chips.push({ key: 'timeRange', label: this.timeRange === 'today' ? 'Today' : this.timeRange === 'this_week' ? 'This week' : 'This month' });
    if (this.searchQuery) chips.push({ key: 'query', label: `"${this.searchQuery}"` });

    if (chips.length === 0) {
      container.innerHTML = '';
      return;
    }

    container.innerHTML = chips.map(c =>
      `<span class="mem-chip" data-filter="${c.key}">${esc(c.label)} <button class="mem-chip-remove" data-filter="${c.key}">&times;</button></span>`
    ).join('') + '<button class="mem-clear-all-btn">Clear all</button>';
  }

  removeFilter(key) {
    if (key === 'query') {
      this.searchQuery = '';
      const input = this.querySelector('.mem-search-input');
      if (input) input.value = '';
      // Restore sort when search cleared
      this.sortBy = this._prevSortBy || 'created_at';
      const sortSel = this.querySelector('.mem-sort-select');
      if (sortSel) sortSel.value = this.sortBy;
    } else if (key === 'timeRange') {
      this.timeRange = null;
      this.querySelectorAll('.mem-time-btn').forEach(b => b.classList.toggle('active', b.dataset.range === ''));
    } else {
      this.viewParams[key] = null;
      if (key === 'category') {
        const combo = this.querySelector('.mem-cat-combo');
        if (combo) combo.setValue('', 'All Categories');
      }
      if (key === 'project_id') {
        const combo = this.querySelector('.mem-proj-combo');
        if (combo) combo.setValue('', 'All Projects');
      }
    }
    this.resetAndLoad();
  }

  clearAllFilters() {
    this.searchQuery = '';
    this.viewParams = { category: null, project_id: null, tag: null, source: null };
    this.timeRange = null;
    this.sortBy = this._prevSortBy || 'created_at';
    const input = this.querySelector('.mem-search-input');
    if (input) input.value = '';
    const catCombo = this.querySelector('.mem-cat-combo');
    if (catCombo) catCombo.setValue('', 'All Categories');
    const projCombo = this.querySelector('.mem-proj-combo');
    if (projCombo) projCombo.setValue('', 'All Projects');
    const sortSel = this.querySelector('.mem-sort-select');
    if (sortSel) sortSel.value = this.sortBy;
    this.querySelectorAll('.mem-time-btn').forEach(b => b.classList.toggle('active', b.dataset.range === ''));
    this.resetAndLoad();
  }

  /* ── Data loading ───────────────────────────────────────── */

  resetAndLoad() {
    this.page = 0;
    this.memories = [];
    this.hasMore = true;
    this.updateURL();
    this.renderChips();
    this.loadMemories();
  }

  async loadMemories() {
    try {
      this.isLoading = true;
      if (this.page === 0) this.renderMemoryList(); // show skeleton

      const sortBy = this.sortBy === 'recency' ? 'created_at' : this.sortBy;
      const params = {
        limit: this.pageSize,
        offset: this.page * this.pageSize,
        sort_by: sortBy,
        sort_direction: this.sortDirection,
        search_mode: this.searchMode
      };
      if (this.sortBy === 'recency') {
        params.recency_weight = 0.7;
      } else if (this.recencyWeight > 0) {
        params.recency_weight = this.recencyWeight;
      }
      if (this.timeRange) {
        params.time_range = this.timeRange;
        params.temporal_mode = 'filter';
      }
      if (this.viewParams.category) params.category = this.viewParams.category;
      if (this.viewParams.project_id) params.project_id = this.viewParams.project_id;
      if (this.viewParams.source) params.source = this.viewParams.source;
      if (this.viewParams.tag) params.tag = this.viewParams.tag;

      const query = this.searchQuery || '';
      const api = window.app?.apiClient;
      if (!api) return;

      const result = await api.searchMemories(query, params);
      if (result && result.results) {
        if (this.page === 0) {
          this.memories = result.results;
        } else {
          this.memories = this.memories.concat(result.results);
        }
        this.totalMemories = result.total || result.results.length;
        this.hasMore = this.memories.length < this.totalMemories;
        this._suggestions = result.suggestions || [];
      } else {
        if (this.page === 0) this.memories = [];
        this.totalMemories = 0;
        this.hasMore = false;
        this._suggestions = [];
      }

      this.isLoading = false;
      this.renderMemoryList();
      this.renderFooter();
      this.renderSuggestions();
    } catch (error) {
      console.error('Failed to load memories:', error);
      this.showToast('Failed to load memories', 'error');
      this.isLoading = false;
    }
  }

  async loadProjectsForFilter() {
    try {
      const api = window.app?.apiClient;
      if (!api) return;

      let projectsData;
      try { projectsData = await api.get('/projects'); } catch { /* ignore */ }

      if (!projectsData) {
        try {
          const sr = await api.searchMemories('', { limit: 100 });
          if (sr?.results) {
            const ids = new Set(sr.results.map(m => m.project_id).filter(Boolean));
            projectsData = { projects: Array.from(ids).map(id => ({ id, name: id })) };
          }
        } catch { /* ignore */ }
      }

      if (projectsData?.projects) {
        const projCombo = this.querySelector('.mem-proj-combo');
        if (projCombo) {
          const opts = [{ value: '', text: 'All Projects' }];
          projectsData.projects.forEach(p => {
            opts.push({ value: p.id, text: p.name || p.id });
          });
          projCombo.setOptions(opts);
          if (this.viewParams.project_id) projCombo.setValue(this.viewParams.project_id);
        }
      }
    } catch { /* ignore */ }
  }

  /* ── Event delegation ───────────────────────────────────── */

  setupEventListeners() {
    // Click delegation
    this.addEventListener('click', (e) => {
      const target = e.target;

      // Star/favorite toggle
      const starBtn = target.closest('.mem-star-btn');
      if (starBtn) {
        e.stopPropagation();
        this.toggleFavorite(starBtn.dataset.id);
        return;
      }

      // Favorites filter toggle
      if (target.closest('.mem-fav-toggle')) {
        this.toggleFavoritesFilter();
        return;
      }

      // Export button (left click = JSON, will show dropdown)
      const exportBtn = target.closest('.mem-export-btn');
      if (exportBtn) {
        this._showExportMenu(exportBtn);
        return;
      }
      // Export menu item
      const exportItem = target.closest('.mem-export-item');
      if (exportItem) {
        this.exportMemories(exportItem.dataset.format);
        this._closeExportMenu();
        return;
      }

      // Peek panel actions
      if (target.closest('.mem-peek-close')) {
        this.closePeek();
        return;
      }
      if (target.closest('.mem-peek-edit')) {
        const id = target.closest('.mem-peek-edit').dataset.id;
        if (id) { this.closePeek(); this.openEditModal(id); }
        return;
      }
      if (target.closest('.mem-peek-fav')) {
        const id = target.closest('.mem-peek-fav').dataset.id;
        if (id) { this.toggleFavorite(id); this.renderPeekPanel(); }
        return;
      }
      if (target.closest('.mem-peek-open-btn')) {
        const id = target.closest('.mem-peek-open-btn').dataset.id;
        if (id && window.app?.router) { this.closePeek(); window.app.router.navigate(`/memory/${id}`); }
        return;
      }

      // Inline click filter (badge, tag, project, source)
      const filterEl = target.closest('.mem-clickable-filter');
      if (filterEl) {
        e.stopPropagation();
        const type = filterEl.dataset.filterType;
        const value = filterEl.dataset.filterValue;
        if (type && value) {
          this.viewParams[type] = value;
          if (type === 'category') {
            const catCombo = this.querySelector('.mem-cat-combo');
            if (catCombo) catCombo.setValue(value);
          }
          if (type === 'project_id') {
            const projCombo = this.querySelector('.mem-proj-combo');
            if (projCombo) projCombo.setValue(value);
          }
          this.resetAndLoad();
        }
        return;
      }

      // Row click → if peek is open, switch peek; otherwise navigate
      const row = target.closest('.mem-row');
      if (row && !target.closest('.mem-action-btn') && !target.closest('.mem-checkbox-wrap')) {
        const id = row.dataset.memoryId;
        if (!id) return;
        if (this._peekId) {
          this.openPeek(id);
        } else if (window.app?.router) {
          window.app.router.navigate(`/memory/${id}`);
        }
        return;
      }

      // Edit button → open inline modal
      const editBtn = target.closest('.mem-edit-btn');
      if (editBtn) {
        e.stopPropagation();
        const id = editBtn.dataset.id;
        if (id) this.openEditModal(id);
        return;
      }

      // Suggestion click
      const suggestBtn = target.closest('.mem-suggest-item');
      if (suggestBtn) {
        const q = suggestBtn.dataset.query;
        if (q) {
          this.searchQuery = q;
          const input = this.querySelector('.mem-search-input');
          if (input) input.value = q;
          this.resetAndLoad();
        }
        return;
      }

      // Delete button
      const delBtn = target.closest('.mem-delete-btn');
      if (delBtn) {
        e.stopPropagation();
        const id = delBtn.dataset.id;
        if (id && confirm('Delete this memory?')) this.deleteMemory(id);
        return;
      }

      // Load more
      if (target.closest('.mem-load-more-btn')) {
        this.page++;
        this.loadMemories();
        return;
      }

      // Chip remove
      const chipRemove = target.closest('.mem-chip-remove');
      if (chipRemove) {
        this.removeFilter(chipRemove.dataset.filter);
        return;
      }

      // Clear all (chip bar or empty state)
      if (target.closest('.mem-clear-all-btn')) {
        this.clearAllFilters();
        return;
      }

      // Batch: delete
      if (target.closest('.mem-batch-delete-btn')) {
        this.batchDelete();
        return;
      }
      // Batch: deselect
      if (target.closest('.mem-batch-clear-btn')) {
        this.toggleSelectAll(false);
        return;
      }
      // Pins badge click → filter by first pin's project
      if (target.closest('.mem-stat-pins')) {
        const pin = this._activePins[0];
        if (pin?.project_id) {
          this.viewParams.project_id = pin.project_id;
          const projCombo = this.querySelector('.mem-proj-combo');
          if (projCombo) projCombo.setValue(pin.project_id);
          this.resetAndLoad();
        }
        return;
      }

      // Time range button
      const timeBtn = target.closest('.mem-time-btn');
      if (timeBtn) {
        const range = timeBtn.dataset.range || null;
        this.timeRange = range;
        this.querySelectorAll('.mem-time-btn').forEach(b => b.classList.toggle('active', b.dataset.range === (range || '')));
        this.resetAndLoad();
        return;
      }
    });

    // Change delegation
    this.addEventListener('change', (e) => {
      const target = e.target;
      // Checkbox for batch selection
      if (target.matches('.mem-checkbox')) {
        this.toggleSelect(target.dataset.id, target.checked);
        return;
      }
      // Batch category change
      if (target.matches('.mem-batch-cat')) {
        this.batchChangeCategory(target.value);
        return;
      }
      // Searchable combobox change events (CustomEvent with detail)
      if (target.matches('.mem-cat-combo')) {
        this.viewParams.category = e.detail?.value || null;
        this.resetAndLoad();
        return;
      }
      if (target.matches('.mem-proj-combo')) {
        this.viewParams.project_id = e.detail?.value || null;
        this.resetAndLoad();
        return;
      }
      if (target.matches('.mem-sort-select')) {
        this.sortBy = target.value;
        this._prevSortBy = target.value;
        this.resetAndLoad();
      }
      if (target.matches('.mem-mode-select')) {
        this.searchMode = target.value;
        this.resetAndLoad();
      }
      if (target.matches('.mem-source-select')) {
        this.viewParams.source = target.value || null;
        this.resetAndLoad();
      }
    });

    // Search input with debounce
    const searchInput = this.querySelector('.mem-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', () => {
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => {
          const val = searchInput.value.trim();
          const wasEmpty = !this.searchQuery;
          const nowEmpty = !val;
          this.searchQuery = val;

          // Auto-switch sort to recency when searching, restore when cleared
          if (wasEmpty && !nowEmpty) {
            this._prevSortBy = this.sortBy;
            this.sortBy = 'recency';
            const sortSel = this.querySelector('.mem-sort-select');
            if (sortSel) sortSel.value = 'recency';
          } else if (!wasEmpty && nowEmpty) {
            this.sortBy = this._prevSortBy || 'created_at';
            const sortSel = this.querySelector('.mem-sort-select');
            if (sortSel) sortSel.value = this.sortBy;
          }

          this.resetAndLoad();
        }, 300);
      });
      searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          clearTimeout(this._searchTimer);
          this.searchQuery = searchInput.value.trim();
          this.resetAndLoad();
        }
      });
    }

    // Keyboard: j/k navigation, Space peek, Cmd+K palette — bound on document
    this._boundKeydown = (e) => {
      // Only handle when this page is connected and visible
      if (!this.isConnected) return;

      // Cmd+K palette (always active)
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        this.openPalette();
        return;
      }

      // Skip when focus is in an input/select/textarea (except Escape)
      if (e.target.matches('input, select, textarea, .combobox-input') && e.key !== 'Escape') return;

      // Skip when a modal overlay is open (edit modal, palette, export menu)
      if (document.querySelector('.cmd-palette-overlay, .mem-edit-overlay')) return;

      const rows = Array.from(this.querySelectorAll('.mem-row'));
      if (!rows.length && e.key !== 'Escape') return;
      const curIdx = rows.findIndex(r => r.classList.contains('keyboard-selected'));

      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault();
        const next = curIdx < rows.length - 1 ? curIdx + 1 : 0;
        rows.forEach(r => r.classList.remove('keyboard-selected'));
        rows[next].classList.add('keyboard-selected');
        rows[next].scrollIntoView({ block: 'nearest' });
      }
      if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault();
        const prev = curIdx > 0 ? curIdx - 1 : rows.length - 1;
        rows.forEach(r => r.classList.remove('keyboard-selected'));
        rows[prev].classList.add('keyboard-selected');
        rows[prev].scrollIntoView({ block: 'nearest' });
      }
      if (e.key === 'Enter') {
        const sel = this.querySelector('.mem-row.keyboard-selected');
        if (sel) sel.click();
      }
      // x = toggle selection on keyboard-selected row
      if (e.key === 'x') {
        const sel = this.querySelector('.mem-row.keyboard-selected');
        if (sel) {
          const id = sel.dataset.memoryId;
          const isSelected = this._selected.has(id);
          this.toggleSelect(id, !isSelected);
          const cb = sel.querySelector('.mem-checkbox');
          if (cb) cb.checked = !isSelected;
        }
      }
      // Space = toggle peek on keyboard-selected row
      if (e.key === ' ') {
        e.preventDefault();
        const sel = this.querySelector('.mem-row.keyboard-selected');
        if (sel) {
          const id = sel.dataset.memoryId;
          if (id) {
            if (this._peekId === id) this.closePeek();
            else this.openPeek(id);
          }
        }
      }
      // Escape = close peek, or deselect all
      if (e.key === 'Escape') {
        if (this._peekId) {
          this.closePeek();
        } else if (this._selected.size > 0) {
          this.toggleSelectAll(false);
        }
      }
      // e = export JSON, E (shift) = export CSV
      if (e.key === 'e' && !e.metaKey && !e.ctrlKey) {
        this.exportMemories(e.shiftKey ? 'csv' : 'json');
      }
    };
    document.addEventListener('keydown', this._boundKeydown);
  }

  /* ── WebSocket ──────────────────────────────────────────── */

  setupWebSocketListeners() {
    this._boundHandlers = {
      memoryCreated: this.handleMemoryCreated.bind(this),
      memoryUpdated: this.handleMemoryUpdated.bind(this),
      memoryDeleted: this.handleMemoryDeleted.bind(this)
    };
    wsClient.on('memory_created', this._boundHandlers.memoryCreated);
    wsClient.on('memory_updated', this._boundHandlers.memoryUpdated);
    wsClient.on('memory_deleted', this._boundHandlers.memoryDeleted);
  }

  async connectWebSocket() {
    try {
      await wsClient.connect();
      if (this.viewParams.project_id) wsClient.subscribeToProject(this.viewParams.project_id);
    } catch { /* ignore */ }
  }

  handleMemoryCreated(data) {
    const { memory } = data;
    if (!memory || this.memories.some(m => m.id === memory.id)) return;
    if (!this.shouldIncludeMemory(memory)) return;

    this.memories.unshift(memory);
    this.totalMemories++;

    // prepend row into DOM
    const container = this.querySelector('.mem-list');
    if (container) {
      const frag = document.createRange().createContextualFragment(this.buildRow(memory));
      const newEl = frag.firstElementChild;
      newEl.style.background = 'rgba(34,197,94,0.08)';
      container.prepend(frag);
      setTimeout(() => { if (newEl) newEl.style.background = ''; }, 3000);
    }
    this.renderFooter();
    this.showToast('New memory created', 'success');
  }

  handleMemoryUpdated(data) {
    const { memory_id, memory } = data;
    const idx = this.memories.findIndex(m => m.id === memory_id);
    if (idx !== -1) {
      if (this.shouldIncludeMemory(memory)) {
        this.memories[idx] = memory;
      } else {
        this.memories.splice(idx, 1);
      }
    } else if (this.shouldIncludeMemory(memory)) {
      this.memories.unshift(memory);
      this.totalMemories++;
    }
    this.renderMemoryList();
    this.renderFooter();
  }

  handleMemoryDeleted(data) {
    const { memory_id } = data;
    const idx = this.memories.findIndex(m => m.id === memory_id);
    if (idx !== -1) {
      this.memories.splice(idx, 1);
      this.totalMemories--;
      const row = this.querySelector(`.mem-row[data-memory-id="${memory_id}"]`);
      if (row) {
        row.style.opacity = '0';
        row.style.transform = 'translateX(20px)';
        setTimeout(() => row.remove(), 200);
      }
      this.renderFooter();
    }
  }

  shouldIncludeMemory(memory) {
    if (this.viewParams.project_id && memory.project_id !== this.viewParams.project_id) return false;
    if (this.viewParams.category && memory.category !== this.viewParams.category) return false;
    if (this.viewParams.source && memory.source !== this.viewParams.source) return false;
    if (this.viewParams.tag && !(memory.tags || []).includes(this.viewParams.tag)) return false;
    if (this.searchQuery) {
      const q = this.searchQuery.toLowerCase();
      const c = (memory.content || '').toLowerCase();
      const p = (memory.project_id || '').toLowerCase();
      const t = (memory.tags || []).join(' ').toLowerCase();
      if (!c.includes(q) && !p.includes(q) && !t.includes(q)) return false;
    }
    return true;
  }

  /* ── Delete ─────────────────────────────────────────────── */

  async deleteMemory(memoryId) {
    try {
      const api = window.app?.apiClient;
      if (!api) throw new Error('API not available');
      await api.deleteMemory(memoryId);
      this.memories = this.memories.filter(m => m.id !== memoryId);
      this.totalMemories--;
      const row = this.querySelector(`.mem-row[data-memory-id="${memoryId}"]`);
      if (row) row.remove();
      this.renderFooter();
      this.showToast('Memory deleted', 'success');
    } catch (error) {
      console.error('Failed to delete memory:', error);
      this.showToast('Failed to delete memory', 'error');
    }
  }

  /* ── Inline Edit Modal ───────────────────────────────────── */

  async openEditModal(memoryId) {
    this.closeEditModal();
    const api = window.app?.apiClient;
    if (!api) return;

    let mem = this.memories.find(m => m.id === memoryId);
    if (!mem) {
      try { mem = await api.getMemory(memoryId); } catch { return; }
    }
    if (!mem) return;

    const overlay = document.createElement('div');
    overlay.className = 'mem-edit-overlay';
    overlay.innerHTML = `
      <div class="mem-edit-modal">
        <div class="mem-edit-header">
          <h3>Edit Memory</h3>
          <button class="mem-edit-close">&times;</button>
        </div>
        <div class="mem-edit-body">
          <label class="mem-edit-label">Category</label>
          <select class="mem-edit-category">
            ${['task','bug','idea','decision','incident','code_snippet','git-history'].map(c =>
              `<option value="${c}"${c === mem.category ? ' selected' : ''}>${c}</option>`
            ).join('')}
          </select>
          <label class="mem-edit-label">Tags <span class="mem-edit-hint">(comma-separated)</span></label>
          <input class="mem-edit-tags" type="text" value="${esc((mem.tags || []).join(', '))}" placeholder="tag1, tag2" />
          <label class="mem-edit-label">Content</label>
          <textarea class="mem-edit-content" rows="10">${esc(mem.content || '')}</textarea>
        </div>
        <div class="mem-edit-footer">
          <span class="mem-edit-id">${memoryId.substring(0, 8)}...</span>
          <div class="mem-edit-actions">
            <button class="mem-edit-cancel">Cancel</button>
            <button class="mem-edit-save">Save</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    this._editOverlay = overlay;
    this._editMemoryId = memoryId;

    // Focus content
    const textarea = overlay.querySelector('.mem-edit-content');
    if (textarea) { textarea.focus(); textarea.setSelectionRange(0, 0); }

    // Event listeners
    overlay.querySelector('.mem-edit-close').addEventListener('click', () => this.closeEditModal());
    overlay.querySelector('.mem-edit-cancel').addEventListener('click', () => this.closeEditModal());
    overlay.querySelector('.mem-edit-save').addEventListener('click', () => this.saveEdit());
    overlay.addEventListener('click', (e) => { if (e.target === overlay) this.closeEditModal(); });
    overlay.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this.closeEditModal();
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') this.saveEdit();
    });
  }

  closeEditModal() {
    if (this._editOverlay) {
      this._editOverlay.remove();
      this._editOverlay = null;
      this._editMemoryId = null;
    }
  }

  async saveEdit() {
    if (!this._editOverlay || !this._editMemoryId) return;
    const overlay = this._editOverlay;
    const memoryId = this._editMemoryId;

    const content = overlay.querySelector('.mem-edit-content')?.value?.trim();
    const category = overlay.querySelector('.mem-edit-category')?.value;
    const tagsStr = overlay.querySelector('.mem-edit-tags')?.value || '';
    const tags = tagsStr.split(',').map(t => t.trim()).filter(Boolean);

    if (!content || content.length < 10) {
      this.showToast('Content must be at least 10 characters', 'warning');
      return;
    }

    const saveBtn = overlay.querySelector('.mem-edit-save');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving...'; }

    try {
      const api = window.app?.apiClient;
      if (!api) throw new Error('API not available');
      await api.updateMemory(memoryId, { content, category, tags });

      // Update local state
      const idx = this.memories.findIndex(m => m.id === memoryId);
      if (idx !== -1) {
        this.memories[idx] = { ...this.memories[idx], content, category, tags };
      }

      this.closeEditModal();
      this.renderMemoryList();
      this.showToast('Memory updated', 'success');
    } catch (error) {
      console.error('Failed to update memory:', error);
      this.showToast('Failed to update: ' + (error.message || 'Unknown error'), 'error');
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save'; }
    }
  }

  /* ── Cmd+K Command Palette ──────────────────────────────── */

  openPalette() {
    if (this._paletteEl) { this.closePalette(); return; }

    const overlay = document.createElement('div');
    overlay.className = 'cmd-palette-overlay';
    overlay.innerHTML = `
      <div class="cmd-palette">
        <div class="cmd-palette-header">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
          <input class="cmd-palette-input" type="text" placeholder="Search memories..." autofocus />
        </div>
        <div class="cmd-palette-body">
          <div class="cmd-palette-section">RECENT</div>
          <div class="cmd-palette-results"></div>
        </div>
        <div class="cmd-palette-footer">
          <span>↑↓ Navigate</span><span>↵ Open</span><span>Esc Close</span>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    this._paletteEl = overlay;
    this._paletteIdx = -1;

    const input = overlay.querySelector('.cmd-palette-input');
    const results = overlay.querySelector('.cmd-palette-results');

    // Show recent from localStorage
    this._showRecentPalette(results);

    // Search on input
    input.addEventListener('input', () => {
      clearTimeout(this._paletteSearchTimer);
      this._paletteSearchTimer = setTimeout(() => this._paletteSearch(input.value, results), 300);
    });

    // Keyboard
    overlay.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { this.closePalette(); return; }
      const items = results.querySelectorAll('.cmd-palette-item');
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        this._paletteIdx = Math.min(this._paletteIdx + 1, items.length - 1);
        this._highlightPaletteItem(items);
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        this._paletteIdx = Math.max(this._paletteIdx - 1, 0);
        this._highlightPaletteItem(items);
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        if (this._paletteIdx >= 0 && items[this._paletteIdx]) {
          const id = items[this._paletteIdx].dataset.memoryId;
          if (id) {
            this._savePaletteRecent(id, input.value);
            this.closePalette();
            if (window.app?.router) window.app.router.navigate(`/memory/${id}`);
          }
        }
      }
    });

    // Click overlay to close
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) this.closePalette();
    });

    // Click item
    results.addEventListener('click', (e) => {
      const item = e.target.closest('.cmd-palette-item');
      if (item) {
        const id = item.dataset.memoryId;
        if (id) {
          this._savePaletteRecent(id, input.value);
          this.closePalette();
          if (window.app?.router) window.app.router.navigate(`/memory/${id}`);
        }
      }
    });

    input.focus();
  }

  closePalette() {
    if (this._paletteEl) {
      this._paletteEl.remove();
      this._paletteEl = null;
      this._paletteIdx = -1;
    }
  }

  destroyPalette() {
    this.closePalette();
  }

  _showRecentPalette(container) {
    const recent = JSON.parse(localStorage.getItem('mem-palette-recent') || '[]');
    if (recent.length === 0) {
      // Show some recent memories from current data
      const items = this.memories.slice(0, 5);
      container.innerHTML = items.map(m => this._buildPaletteItem(m)).join('') || '<div class="cmd-palette-empty">Type to search...</div>';
    } else {
      container.innerHTML = '<div class="cmd-palette-section">RECENT SEARCHES</div>' +
        recent.map(r => `<div class="cmd-palette-item cmd-palette-recent-item" data-query="${esc(r)}">${esc(r)}</div>`).join('');
    }
  }

  async _paletteSearch(query, container) {
    if (!query.trim()) {
      this._showRecentPalette(container);
      this._paletteIdx = -1;
      return;
    }
    try {
      const api = window.app?.apiClient;
      if (!api) return;
      const result = await api.searchMemories(query, { limit: 8, search_mode: 'hybrid' });
      if (result?.results?.length) {
        // group by category
        const grouped = {};
        result.results.forEach(m => {
          const cat = m.category || 'other';
          if (!grouped[cat]) grouped[cat] = [];
          grouped[cat].push(m);
        });
        let html = '';
        for (const [cat, mems] of Object.entries(grouped)) {
          html += `<div class="cmd-palette-section">${cat.toUpperCase()}</div>`;
          html += mems.map(m => this._buildPaletteItem(m)).join('');
        }
        container.innerHTML = html;
      } else {
        container.innerHTML = '<div class="cmd-palette-empty">No results found</div>';
      }
      this._paletteIdx = -1;
    } catch {
      container.innerHTML = '<div class="cmd-palette-empty">Search failed</div>';
    }
  }

  _buildPaletteItem(mem) {
    const icon = CAT_ICONS[mem.category] || DEFAULT_ICON;
    const content = truncate(mem.content, 60);
    const time = relTime(mem.created_at);
    return `
      <div class="cmd-palette-item" data-memory-id="${esc(mem.id)}">
        <span class="cmd-palette-item-icon">${icon}</span>
        <span class="cmd-palette-item-badge">${esc(mem.category)}</span>
        <span class="cmd-palette-item-content">${esc(content)}</span>
        <span class="cmd-palette-item-time">${time}</span>
      </div>`;
  }

  _highlightPaletteItem(items) {
    items.forEach((el, i) => el.classList.toggle('active', i === this._paletteIdx));
    if (items[this._paletteIdx]) items[this._paletteIdx].scrollIntoView({ block: 'nearest' });
  }

  _savePaletteRecent(id, query) {
    if (!query?.trim()) return;
    let recent = JSON.parse(localStorage.getItem('mem-palette-recent') || '[]');
    recent = recent.filter(r => r !== query.trim());
    recent.unshift(query.trim());
    recent = recent.slice(0, 5);
    localStorage.setItem('mem-palette-recent', JSON.stringify(recent));
  }

  /* ── Stats bar ─────────────────────────────────────────── */

  async loadStats() {
    try {
      const api = window.app?.apiClient;
      if (!api) return;
      const [stats, daily] = await Promise.all([
        api.getStats(),
        api.get('/memories/daily-counts', { days: 7 })
      ]);
      this._stats = { ...stats, daily: daily?.daily_counts || [] };
      // Populate source filter select
      const sources = stats.sources_breakdown || {};
      this._sources = Object.keys(sources);
      const srcSel = this.querySelector('.mem-source-select');
      if (srcSel && this._sources.length) {
        this._sources.forEach(s => {
          if (!srcSel.querySelector(`option[value="${s}"]`)) {
            const opt = document.createElement('option');
            opt.value = s;
            opt.textContent = `${s} (${sources[s]})`;
            srcSel.appendChild(opt);
          }
        });
        if (this.viewParams.source) srcSel.value = this.viewParams.source;
      }
      this.renderStatsBar();
    } catch { /* ignore — stats are optional */ }
  }

  renderStatsBar() {
    const bar = this.querySelector('.mem-stats-bar');
    if (!bar || !this._stats) return;

    const s = this._stats;
    const total = s.total_memories || 0;
    const cats = s.categories_breakdown || {};
    const daily = s.daily || [];

    // Mini sparkline (7 days)
    const maxCount = Math.max(...daily.map(d => d.count), 1);
    const sparkBars = daily.map(d => {
      const h = Math.max(2, Math.round((d.count / maxCount) * 20));
      return `<span class="mem-spark-bar" style="height:${h}px" title="${d.date}: ${d.count}"></span>`;
    }).join('');

    // Category pills (top 4)
    const topCats = Object.entries(cats).sort((a, b) => b[1] - a[1]).slice(0, 4);
    const catPills = topCats.map(([c, n]) =>
      `<span class="mem-stat-cat mem-clickable-filter" data-filter-type="category" data-filter-value="${esc(c)}">${esc(c)} <strong>${n}</strong></span>`
    ).join('');

    // Week total
    const weekTotal = daily.reduce((sum, d) => sum + d.count, 0);

    // Active pins
    const pinsHtml = this._activePins.length
      ? `<span class="mem-stat-pins" title="Active pins">${this._activePins.length} pins</span>`
      : '';

    bar.innerHTML = `
      <span class="mem-stat-total">${total} memories</span>
      <span class="mem-stat-sep">·</span>
      <span class="mem-stat-week">+${weekTotal} this week</span>
      <span class="mem-sparkline">${sparkBars}</span>
      ${catPills}
      ${pinsHtml}
    `;
  }

  /* ── Active Pins ──────────────────────────────────────── */

  async loadActivePins() {
    try {
      const api = window.app?.apiClient;
      if (!api) return;
      const result = await api.get('/work/pins', { status: 'open', limit: 10 });
      this._activePins = result?.pins || [];
      this.renderStatsBar();
    } catch { /* ignore */ }
  }

  /* ── Batch operations ─────────────────────────────────── */

  toggleSelect(memoryId, checked) {
    if (checked) {
      this._selected.add(memoryId);
    } else {
      this._selected.delete(memoryId);
    }
    const row = this.querySelector(`.mem-row[data-memory-id="${memoryId}"]`);
    if (row) row.classList.toggle('mem-selected', checked);
    this.renderBatchBar();
  }

  toggleSelectAll(checked) {
    this._selected.clear();
    if (checked) {
      this.memories.forEach(m => this._selected.add(m.id));
    }
    this.querySelectorAll('.mem-checkbox').forEach(cb => { cb.checked = checked; });
    this.querySelectorAll('.mem-row').forEach(r => r.classList.toggle('mem-selected', checked));
    this.renderBatchBar();
  }

  renderBatchBar() {
    const bar = this.querySelector('.mem-batch-bar');
    if (!bar) return;
    const count = this._selected.size;
    if (count === 0) {
      bar.style.display = 'none';
      return;
    }
    bar.style.display = 'flex';
    bar.innerHTML = `
      <span class="mem-batch-count">${count} selected</span>
      <select class="mem-batch-cat" title="Change category">
        <option value="">Category...</option>
        <option value="task">Task</option>
        <option value="bug">Bug</option>
        <option value="idea">Idea</option>
        <option value="decision">Decision</option>
        <option value="incident">Incident</option>
        <option value="code_snippet">Code Snippet</option>
      </select>
      <button class="mem-batch-delete-btn">Delete</button>
      <button class="mem-batch-clear-btn">Deselect</button>
    `;
  }

  async batchDelete() {
    const ids = [...this._selected];
    if (!ids.length) return;
    if (!confirm(`Delete ${ids.length} memories?`)) return;

    const api = window.app?.apiClient;
    if (!api) return;

    let deleted = 0;
    for (const id of ids) {
      try {
        await api.deleteMemory(id);
        this.memories = this.memories.filter(m => m.id !== id);
        this.totalMemories--;
        const row = this.querySelector(`.mem-row[data-memory-id="${id}"]`);
        if (row) row.remove();
        deleted++;
      } catch { /* continue */ }
    }
    this._selected.clear();
    this.renderBatchBar();
    this.renderFooter();
    this.showToast(`${deleted} memories deleted`, 'success');
  }

  async batchChangeCategory(category) {
    if (!category) return;
    const ids = [...this._selected];
    if (!ids.length) return;

    const api = window.app?.apiClient;
    if (!api) return;

    let updated = 0;
    for (const id of ids) {
      try {
        await api.updateMemory(id, { category });
        const idx = this.memories.findIndex(m => m.id === id);
        if (idx !== -1) this.memories[idx].category = category;
        updated++;
      } catch { /* continue */ }
    }
    this._selected.clear();
    this.renderBatchBar();
    this.renderMemoryList();
    this.showToast(`${updated} memories updated to ${category}`, 'success');
  }

  /* ── P2: Favorites ─────────────────────────────────────── */

  toggleFavorite(memoryId) {
    if (this._favorites.has(memoryId)) {
      this._favorites.delete(memoryId);
    } else {
      this._favorites.add(memoryId);
    }
    localStorage.setItem('mem-favorites', JSON.stringify([...this._favorites]));

    // Update star icon in DOM
    const starBtn = this.querySelector(`.mem-star-btn[data-id="${memoryId}"]`);
    if (starBtn) {
      const isFav = this._favorites.has(memoryId);
      starBtn.classList.toggle('active', isFav);
      starBtn.title = isFav ? 'Remove from favorites' : 'Add to favorites';
      const svg = starBtn.querySelector('svg');
      if (svg) svg.setAttribute('fill', isFav ? 'currentColor' : 'none');
    }

    // Re-filter if showing favorites only
    if (this._showFavoritesOnly) this.renderMemoryList();
  }

  toggleFavoritesFilter() {
    this._showFavoritesOnly = !this._showFavoritesOnly;
    const btn = this.querySelector('.mem-fav-toggle');
    if (btn) {
      btn.classList.toggle('active', this._showFavoritesOnly);
      const svg = btn.querySelector('svg');
      if (svg) svg.setAttribute('fill', this._showFavoritesOnly ? 'currentColor' : 'none');
    }
    this.renderMemoryList();
    this.renderFooter();
  }

  /* ── P2: Peek Preview Panel ──────────────────────────── */

  async openPeek(memoryId) {
    if (this._peekId === memoryId) { this.closePeek(); return; }
    this._peekId = memoryId;

    const panel = this.querySelector('.mem-peek-panel');
    if (!panel) return;

    panel.style.display = 'block';
    panel.innerHTML = '<div class="mem-peek-loading">Loading...</div>';
    this.querySelector('.mem-content-area')?.classList.add('peek-open');

    try {
      const api = window.app?.apiClient;
      if (!api) return;
      const mem = await api.getMemory(memoryId);
      if (!mem || this._peekId !== memoryId) return;
      this._peekData = mem;
      this.renderPeekPanel();
    } catch {
      panel.innerHTML = '<div class="mem-peek-loading">Failed to load</div>';
    }
  }

  closePeek() {
    this._peekId = null;
    this._peekData = null;
    const panel = this.querySelector('.mem-peek-panel');
    if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }
    this.querySelector('.mem-content-area')?.classList.remove('peek-open');
  }

  renderPeekPanel() {
    const panel = this.querySelector('.mem-peek-panel');
    if (!panel || !this._peekData) return;

    const m = this._peekData;
    // Normalize tags (API may return JSON string)
    if (typeof m.tags === 'string') {
      try { m.tags = JSON.parse(m.tags); } catch { m.tags = []; }
    }
    const icon = CAT_ICONS[m.category] || DEFAULT_ICON;
    const isFav = this._favorites.has(m.id);

    panel.innerHTML = `
      <div class="mem-peek-header">
        <span class="mem-peek-cat">${icon} ${esc(m.category)}</span>
        <div class="mem-peek-actions">
          <button class="mem-action-btn mem-peek-fav" data-id="${esc(m.id)}" title="Favorite">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="${isFav ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
          </button>
          <button class="mem-action-btn mem-peek-edit" data-id="${esc(m.id)}" title="Edit">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
          <button class="mem-action-btn mem-peek-close" title="Close">&times;</button>
        </div>
      </div>
      <div class="mem-peek-meta">
        ${m.project_id ? `<span class="mem-peek-project">${esc(m.project_id)}</span>` : ''}
        ${m.source ? `<span class="mem-peek-source">${esc(m.source)}</span>` : ''}
        <span class="mem-peek-time">${relTime(m.created_at)}</span>
        ${m.updated_at && m.updated_at !== m.created_at ? `<span class="mem-peek-updated">updated ${relTime(m.updated_at)}</span>` : ''}
      </div>
      ${(m.tags || []).length ? `<div class="mem-peek-tags">${m.tags.map(t => `<span class="mem-tag">#${esc(t)}</span>`).join('')}</div>` : ''}
      <div class="mem-peek-body">${this._renderMarkdown(m.content || '')}</div>
      <div class="mem-peek-footer">
        <span class="mem-peek-id">${m.id.substring(0, 8)}...</span>
        <button class="mem-peek-open-btn" data-id="${esc(m.id)}">Open full →</button>
      </div>
    `;
  }

  _renderMarkdown(text) {
    // Simple markdown → HTML: headers, bold, code blocks, lists
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

  /* ── P2: Export Menu ──────────────────────────────────── */

  _showExportMenu(anchorEl) {
    this._closeExportMenu();
    const menu = document.createElement('div');
    menu.className = 'mem-export-menu';
    const count = this._selected.size > 0 ? `${this._selected.size} selected` : `${this.memories.length} memories`;
    menu.innerHTML = `
      <div class="mem-export-menu-label">Export ${count}</div>
      <button class="mem-export-item" data-format="json">JSON</button>
      <button class="mem-export-item" data-format="csv">CSV</button>
    `;
    const rect = anchorEl.getBoundingClientRect();
    Object.assign(menu.style, {
      position: 'fixed',
      top: `${rect.bottom + 4}px`,
      right: `${window.innerWidth - rect.right}px`,
      zIndex: '9999'
    });
    document.body.appendChild(menu);
    this._exportMenu = menu;
    // Close on outside click
    this._exportMenuClose = (e) => {
      if (!menu.contains(e.target) && !anchorEl.contains(e.target)) this._closeExportMenu();
    };
    setTimeout(() => document.addEventListener('click', this._exportMenuClose), 0);
  }

  _closeExportMenu() {
    if (this._exportMenu) {
      this._exportMenu.remove();
      this._exportMenu = null;
    }
    if (this._exportMenuClose) {
      document.removeEventListener('click', this._exportMenuClose);
      this._exportMenuClose = null;
    }
  }

  /* ── P2: Export ───────────────────────────────────────── */

  exportMemories(format) {
    const data = this._selected.size > 0
      ? this.memories.filter(m => this._selected.has(m.id))
      : this.memories;

    if (!data.length) {
      this.showToast('No memories to export', 'warning');
      return;
    }

    let content, filename, mime;

    if (format === 'json') {
      const exported = data.map(m => ({
        id: m.id,
        content: m.content,
        category: m.category,
        tags: m.tags,
        project_id: m.project_id,
        source: m.source,
        created_at: m.created_at,
        updated_at: m.updated_at
      }));
      content = JSON.stringify(exported, null, 2);
      filename = `memories-${new Date().toISOString().slice(0, 10)}.json`;
      mime = 'application/json';
    } else {
      // CSV
      const headers = ['id', 'category', 'project_id', 'source', 'tags', 'content', 'created_at'];
      const csvEsc = (v) => `"${String(v || '').replace(/"/g, '""')}"`;
      const rows = data.map(m =>
        [m.id, m.category, m.project_id || '', m.source || '', (m.tags || []).join(';'), m.content || '', m.created_at || ''].map(csvEsc).join(',')
      );
      content = headers.join(',') + '\n' + rows.join('\n');
      filename = `memories-${new Date().toISOString().slice(0, 10)}.csv`;
      mime = 'text/csv';
    }

    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
    this.showToast(`Exported ${data.length} memories as ${format.toUpperCase()}`, 'success');
  }

  /* ── Toast ──────────────────────────────────────────────── */

  showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    Object.assign(toast.style, {
      position: 'fixed', top: '20px', right: '20px',
      padding: '10px 18px', borderRadius: '6px', color: 'white',
      fontSize: '13px', fontWeight: '500', zIndex: '10001',
      opacity: '0', transform: 'translateY(-16px)', transition: 'all 0.25s ease'
    });
    const colors = { success: '#10b981', info: '#3b82f6', warning: '#f59e0b', error: '#ef4444' };
    toast.style.backgroundColor = colors[type] || colors.info;
    document.body.appendChild(toast);
    requestAnimationFrame(() => { toast.style.opacity = '1'; toast.style.transform = 'translateY(0)'; });
    setTimeout(() => {
      toast.style.opacity = '0'; toast.style.transform = 'translateY(-16px)';
      setTimeout(() => toast.remove(), 250);
    }, 3000);
  }
}

customElements.define('memories-page', MemoriesPage);
export { MemoriesPage };

/* ── Styles (injected once) ──────────────────────────────────── */
const style = document.createElement('style');
style.textContent = `
  /* ── Layout ─────────────────────────────── */
  .mem {
    display: block;
    max-width: 960px;
    width: 100%;
    margin: 0 auto;
    padding: var(--space-6, 1.5rem) var(--space-4, 1rem);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    box-sizing: border-box;
    overflow-x: hidden;
  }

  /* ── Toolbar ────────────────────────────── */
  .mem-toolbar {
    display: flex;
    align-items: center;
    gap: 0.625rem;
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
  }
  .mem-title {
    font-size: 1.125rem;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
    flex-shrink: 0;
  }
  .mem-search-wrap {
    flex: 1;
    min-width: 180px;
    position: relative;
  }
  .mem-search-icon {
    position: absolute;
    left: 10px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--text-muted);
    pointer-events: none;
  }
  .mem-search-input {
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
  .mem-search-input:focus {
    border-color: var(--primary-color, #6366f1);
    box-shadow: 0 0 0 2px rgba(99,102,241,0.12);
  }
  .mem-sort-select {
    padding: 0.4375rem 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.75rem;
    cursor: pointer;
    outline: none;
  }

  /* ── Searchable Combobox in toolbar ──── */
  .mem-cat-combo,
  .mem-proj-combo {
    flex-shrink: 0;
    width: 150px;
  }
  .mem-cat-combo .combobox-input,
  .mem-proj-combo .combobox-input {
    padding: 0.4375rem 1.75rem 0.4375rem 0.5rem;
    font-size: 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-primary);
  }
  .mem-cat-combo .combobox-input:focus,
  .mem-proj-combo .combobox-input:focus {
    border-color: var(--primary-color, #6366f1);
    box-shadow: 0 0 0 2px rgba(99,102,241,0.12);
  }
  .mem-cat-combo .combobox-dropdown,
  .mem-proj-combo .combobox-dropdown {
    border-radius: var(--border-radius-sm, 6px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.12);
    max-height: 240px;
  }
  .mem-cat-combo .combobox-option,
  .mem-proj-combo .combobox-option {
    padding: 0.375rem 0.5rem;
    font-size: 0.75rem;
    gap: 0.375rem;
  }

  /* ── Search Mode Select ───────────────────── */
  .mem-mode-select {
    padding: 0.4375rem 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-secondary);
    font-size: 0.6875rem;
    cursor: pointer;
    outline: none;
    flex-shrink: 0;
  }

  /* ── Search Suggestions ──────────────────── */
  .mem-suggestions {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0;
    flex-wrap: wrap;
  }
  .mem-suggestions:empty { display: none; }
  .mem-suggest-label {
    font-size: 0.6875rem;
    color: var(--text-muted);
    white-space: nowrap;
  }
  .mem-suggest-item {
    padding: 2px 8px;
    border: 1px solid var(--border-color);
    border-radius: 9999px;
    background: var(--bg-primary);
    color: var(--primary-color, #6366f1);
    font-size: 0.6875rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
  }
  .mem-suggest-item:hover {
    background: rgba(99,102,241,0.08);
    border-color: var(--primary-color, #6366f1);
  }

  /* ── Time Range Buttons ──────────────────── */
  .mem-time-range {
    display: flex;
    gap: 1px;
    background: var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    overflow: hidden;
    flex-shrink: 0;
  }
  .mem-time-btn {
    padding: 0.375rem 0.625rem;
    border: none;
    background: var(--bg-primary);
    color: var(--text-muted);
    font-size: 0.6875rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
  }
  .mem-time-btn:hover { color: var(--text-primary); background: var(--bg-secondary); }
  .mem-time-btn.active { color: var(--text-primary); background: var(--bg-secondary); font-weight: 600; }

  /* Clickable filter elements */
  .mem-clickable-filter { cursor: pointer; transition: all 0.15s; }
  .mem-clickable-filter:hover { opacity: 0.8; text-decoration: underline; }

  /* ── Filter Chips ───────────────────────── */
  .mem-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
    margin-bottom: 0.5rem;
    align-items: center;
  }
  .mem-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 2px 8px;
    border-radius: 9999px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    font-size: 0.6875rem;
    color: var(--text-secondary);
    font-weight: 500;
  }
  .mem-chip-remove {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 0.875rem;
    line-height: 1;
    padding: 0 2px;
  }
  .mem-chip-remove:hover {
    color: var(--error-color, #ef4444);
  }
  .mem-clear-all-btn {
    background: none;
    border: none;
    font-size: 0.6875rem;
    color: var(--text-muted);
    cursor: pointer;
    padding: 2px 6px;
    text-decoration: underline;
  }
  .mem-clear-all-btn:hover {
    color: var(--text-primary);
  }

  /* ── Compact list (reuse dashboard's .recent-item) ──────── */
  .mem-list {
    background: var(--card-bg, var(--bg-primary));
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius, 8px);
    overflow: hidden;
    min-height: 200px;
    min-width: 0;
  }

  .mem-list .recent-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border-color);
    cursor: pointer;
    transition: background 0.15s;
    font-size: 0.8125rem;
    line-height: 1.4;
    position: relative;
  }
  .mem-list .recent-item:last-child { border-bottom: none; }
  .mem-list .recent-item:hover { background: var(--bg-secondary); }
  .mem-list .recent-item.keyboard-selected { background: var(--bg-secondary); outline: 2px solid var(--primary-color, #6366f1); outline-offset: -2px; }

  .mem-list .recent-item-icon { flex-shrink: 0; display: flex; align-items: center; color: var(--text-muted); }
  .mem-list .recent-item-icon svg { display: block; }
  .mem-list .recent-item-badge { flex-shrink: 0; font-size: 0.6875rem; padding: 1px 6px; border-radius: var(--border-radius-sm, 4px); background: var(--bg-secondary); color: var(--text-secondary); font-weight: 500; }
  .mem-list .recent-item-project { flex-shrink: 0; font-size: 0.6875rem; padding: 1px 6px; border-radius: var(--border-radius-sm, 4px); background: var(--bg-tertiary, var(--bg-secondary)); color: var(--text-primary); font-weight: 500; border: 1px solid var(--border-color); }
  .mem-list .recent-item-content { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); }
  .mem-list .recent-item-time { flex-shrink: 0; font-size: 0.6875rem; color: var(--text-muted); white-space: nowrap; }

  /* Tags inline */
  .mem-tags { display: flex; gap: 0.25rem; flex-shrink: 0; }
  .mem-tag { font-size: 0.625rem; padding: 0 4px; border-radius: 3px; background: var(--bg-tertiary, var(--bg-secondary)); color: var(--text-muted); white-space: nowrap; }

  /* Score badge */
  .mem-score { flex-shrink: 0; font-size: 0.625rem; padding: 1px 5px; border-radius: 3px; background: rgba(99,102,241,0.1); color: var(--primary-color, #6366f1); font-weight: 600; }

  /* Hover actions */
  .mem-row-actions {
    display: none;
    gap: 0.25rem;
    flex-shrink: 0;
  }
  .mem-row:hover .mem-row-actions { display: flex; }
  .mem-row:hover .recent-item-time { display: none; }
  .mem-action-btn {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: var(--text-muted);
    transition: all 0.15s;
    padding: 0;
  }
  .mem-action-btn:hover {
    background: var(--bg-tertiary, var(--bg-secondary));
    color: var(--text-primary);
    border-color: var(--border-hover, var(--border-color));
  }
  .mem-delete-btn:hover { color: var(--error-color, #ef4444); }

  /* ── Skeleton loading ───────────────────── */
  .ml-skeleton {
    padding: 0.625rem 0.75rem !important;
    cursor: default !important;
  }
  .sk-line {
    height: 12px;
    border-radius: 3px;
    background: var(--bg-secondary);
    animation: sk-pulse 1.2s ease-in-out infinite;
  }
  @keyframes sk-pulse {
    0%, 100% { opacity: 0.4; }
    50% { opacity: 1; }
  }

  /* ── Empty state ────────────────────────── */
  .mem-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 3rem 1rem;
    color: var(--text-muted);
    gap: 0.75rem;
  }
  .mem-empty p { margin: 0; font-size: 0.875rem; }
  .mem-empty .mem-clear-all-btn {
    padding: 0.375rem 1rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    text-decoration: none;
    font-size: 0.8125rem;
  }

  /* ── Footer ─────────────────────────────── */
  .mem-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.75rem 0;
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  .mem-count { font-weight: 500; }
  .mem-load-more-btn {
    padding: 0.375rem 1rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
  }
  .mem-load-more-btn:hover {
    background: var(--bg-secondary);
    border-color: var(--border-hover, var(--border-color));
  }

  /* ── Cmd+K Command Palette ──────────────── */
  .cmd-palette-overlay {
    position: fixed;
    inset: 0;
    z-index: 10000;
    background: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 15vh;
    animation: cp-fade-in 0.12s ease;
  }
  @keyframes cp-fade-in { from { opacity: 0; } to { opacity: 1; } }

  .cmd-palette {
    width: 560px;
    max-width: 92vw;
    max-height: 420px;
    background: var(--card-bg, var(--bg-primary));
    border: 1px solid var(--border-color);
    border-radius: 12px;
    box-shadow: 0 16px 48px rgba(0, 0, 0, 0.25);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    animation: cp-slide-in 0.15s ease;
  }
  @keyframes cp-slide-in { from { transform: translateY(-8px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }

  .cmd-palette-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border-color);
    color: var(--text-muted);
  }
  .cmd-palette-input {
    flex: 1;
    border: none;
    background: transparent;
    color: var(--text-primary);
    font-size: 0.9375rem;
    outline: none;
  }
  .cmd-palette-input::placeholder { color: var(--text-muted); }

  .cmd-palette-body {
    flex: 1;
    overflow-y: auto;
    padding: 0.375rem 0;
  }
  .cmd-palette-section {
    padding: 0.375rem 1rem;
    font-size: 0.625rem;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .cmd-palette-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.4375rem 1rem;
    cursor: pointer;
    transition: background 0.1s;
    font-size: 0.8125rem;
  }
  .cmd-palette-item:hover,
  .cmd-palette-item.active {
    background: var(--bg-secondary);
  }
  .cmd-palette-item-icon { flex-shrink: 0; display: flex; align-items: center; color: var(--text-muted); }
  .cmd-palette-item-badge { flex-shrink: 0; font-size: 0.625rem; padding: 1px 5px; border-radius: 3px; background: var(--bg-secondary); color: var(--text-secondary); font-weight: 500; }
  .cmd-palette-item-content { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); }
  .cmd-palette-item-time { flex-shrink: 0; font-size: 0.625rem; color: var(--text-muted); }
  .cmd-palette-empty { padding: 2rem 1rem; text-align: center; color: var(--text-muted); font-size: 0.8125rem; }

  .cmd-palette-footer {
    display: flex;
    gap: 1.25rem;
    padding: 0.5rem 1rem;
    border-top: 1px solid var(--border-color);
    font-size: 0.6875rem;
    color: var(--text-muted);
  }

  /* ── Inline Edit Modal ────────────────────── */
  .mem-edit-overlay {
    position: fixed;
    inset: 0;
    z-index: 10000;
    background: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 12vh;
    animation: cp-fade-in 0.12s ease;
  }
  .mem-edit-modal {
    width: 580px;
    max-width: 92vw;
    max-height: 75vh;
    background: var(--card-bg, var(--bg-primary));
    border: 1px solid var(--border-color);
    border-radius: 12px;
    box-shadow: 0 16px 48px rgba(0, 0, 0, 0.25);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    animation: cp-slide-in 0.15s ease;
  }
  .mem-edit-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border-color);
  }
  .mem-edit-header h3 {
    margin: 0;
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--text-primary);
  }
  .mem-edit-close {
    background: none;
    border: none;
    font-size: 1.25rem;
    color: var(--text-muted);
    cursor: pointer;
    line-height: 1;
    padding: 0 4px;
  }
  .mem-edit-close:hover { color: var(--text-primary); }
  .mem-edit-body {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .mem-edit-label {
    font-size: 0.6875rem;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .mem-edit-hint {
    font-weight: 400;
    text-transform: none;
    letter-spacing: normal;
    color: var(--text-muted);
  }
  .mem-edit-category,
  .mem-edit-tags {
    padding: 0.4375rem 0.625rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.8125rem;
    outline: none;
  }
  .mem-edit-category:focus,
  .mem-edit-tags:focus {
    border-color: var(--primary-color, #6366f1);
    box-shadow: 0 0 0 2px rgba(99,102,241,0.12);
  }
  .mem-edit-content {
    padding: 0.625rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.8125rem;
    font-family: 'SF Mono', 'Fira Code', monospace;
    line-height: 1.5;
    resize: vertical;
    min-height: 160px;
    outline: none;
  }
  .mem-edit-content:focus {
    border-color: var(--primary-color, #6366f1);
    box-shadow: 0 0 0 2px rgba(99,102,241,0.12);
  }
  .mem-edit-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.625rem 1rem;
    border-top: 1px solid var(--border-color);
  }
  .mem-edit-id {
    font-size: 0.625rem;
    color: var(--text-muted);
    font-family: monospace;
  }
  .mem-edit-actions { display: flex; gap: 0.5rem; }
  .mem-edit-cancel {
    padding: 0.375rem 0.875rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-secondary);
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
  }
  .mem-edit-cancel:hover { background: var(--bg-secondary); }
  .mem-edit-save {
    padding: 0.375rem 0.875rem;
    border: none;
    border-radius: var(--border-radius-sm, 6px);
    background: var(--primary-color, #6366f1);
    color: white;
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .mem-edit-save:hover { opacity: 0.9; }
  .mem-edit-save:disabled { opacity: 0.5; cursor: not-allowed; }

  /* ── Search Highlighting ───────────────── */
  mark {
    background: rgba(250, 204, 21, 0.25);
    color: inherit;
    padding: 0 1px;
    border-radius: 2px;
  }
  [data-theme="dark"] mark,
  .dark mark {
    background: rgba(250, 204, 21, 0.15);
  }

  /* ── Stats Bar ────────────────────────── */
  .mem-stats-bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.375rem 0;
    font-size: 0.6875rem;
    color: var(--text-muted);
    flex-wrap: wrap;
    min-height: 1.5rem;
  }
  .mem-stats-bar:empty { display: none; }
  .mem-stat-total { font-weight: 600; color: var(--text-secondary); }
  .mem-stat-sep { opacity: 0.4; }
  .mem-stat-week { color: var(--success-color, #10b981); }
  .mem-sparkline {
    display: inline-flex;
    align-items: flex-end;
    gap: 2px;
    height: 20px;
    margin: 0 0.25rem;
  }
  .mem-spark-bar {
    width: 4px;
    background: var(--primary-color, #6366f1);
    border-radius: 1px;
    opacity: 0.6;
    transition: opacity 0.15s;
  }
  .mem-spark-bar:hover { opacity: 1; }
  .mem-stat-cat {
    padding: 1px 6px;
    border-radius: 3px;
    background: var(--bg-secondary);
    cursor: pointer;
    transition: background 0.15s;
  }
  .mem-stat-cat:hover { background: var(--border-color); }
  .mem-stat-cat strong { font-weight: 600; color: var(--text-primary); margin-left: 2px; }
  .mem-stat-pins {
    padding: 1px 6px;
    border-radius: 3px;
    background: rgba(99, 102, 241, 0.1);
    color: var(--primary-color, #6366f1);
    font-weight: 500;
    cursor: pointer;
  }
  .mem-stat-pins:hover { background: rgba(99, 102, 241, 0.2); }

  /* ── Batch Toolbar ────────────────────── */
  .mem-batch-bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.375rem 0.75rem;
    background: var(--primary-color, #6366f1);
    color: white;
    border-radius: var(--border-radius-sm, 6px);
    font-size: 0.75rem;
    font-weight: 500;
    margin-bottom: 0.5rem;
  }
  .mem-batch-count { flex: 1; }
  .mem-batch-cat {
    padding: 0.25rem 0.5rem;
    border: 1px solid rgba(255,255,255,0.3);
    border-radius: 4px;
    background: rgba(255,255,255,0.1);
    color: white;
    font-size: 0.6875rem;
    cursor: pointer;
  }
  .mem-batch-cat option { color: var(--text-primary); background: var(--bg-primary); }
  .mem-batch-delete-btn {
    padding: 0.25rem 0.625rem;
    border: 1px solid rgba(255,255,255,0.3);
    border-radius: 4px;
    background: rgba(239,68,68,0.8);
    color: white;
    font-size: 0.6875rem;
    font-weight: 500;
    cursor: pointer;
  }
  .mem-batch-delete-btn:hover { background: #ef4444; }
  .mem-batch-clear-btn {
    padding: 0.25rem 0.625rem;
    border: 1px solid rgba(255,255,255,0.3);
    border-radius: 4px;
    background: transparent;
    color: white;
    font-size: 0.6875rem;
    cursor: pointer;
  }
  .mem-batch-clear-btn:hover { background: rgba(255,255,255,0.15); }

  /* ── Checkbox in rows ─────────────────── */
  .mem-checkbox-wrap {
    display: flex;
    align-items: center;
    width: 0;
    overflow: hidden;
    opacity: 0;
    transition: width 0.15s, opacity 0.15s, margin 0.15s;
    margin-right: 0;
    flex-shrink: 0;
  }
  .mem-row:hover .mem-checkbox-wrap,
  .mem-row.mem-selected .mem-checkbox-wrap,
  .mem-row.keyboard-selected .mem-checkbox-wrap {
    width: 18px;
    opacity: 1;
    margin-right: 4px;
  }
  .mem-checkbox {
    width: 14px;
    height: 14px;
    cursor: pointer;
    accent-color: var(--primary-color, #6366f1);
  }
  .mem-row.mem-selected {
    background: rgba(99, 102, 241, 0.06);
  }

  /* ── P2: Favorites star ─────────────────── */
  .mem-star-btn {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    padding: 2px;
    display: flex;
    align-items: center;
    flex-shrink: 0;
    opacity: 0;
    width: 0;
    overflow: hidden;
    transition: opacity 0.15s, width 0.15s, color 0.15s;
  }
  .mem-row:hover .mem-star-btn,
  .mem-row.keyboard-selected .mem-star-btn,
  .mem-star-btn.active {
    opacity: 1;
    width: 18px;
  }
  .mem-star-btn.active { color: #f59e0b; }
  .mem-star-btn:hover { color: #f59e0b; }

  /* ── P2: Favorites toggle btn ─────────── */
  .mem-fav-toggle {
    background: none;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    color: var(--text-muted);
    cursor: pointer;
    padding: 0.375rem;
    display: flex;
    align-items: center;
    transition: all 0.15s;
    flex-shrink: 0;
  }
  .mem-fav-toggle:hover { color: #f59e0b; border-color: #f59e0b; }
  .mem-fav-toggle.active { color: #f59e0b; border-color: #f59e0b; background: rgba(245, 158, 11, 0.08); }

  /* ── P2: Export btn ───────────────────── */
  .mem-export-btn {
    background: none;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    color: var(--text-muted);
    cursor: pointer;
    padding: 0.375rem;
    display: flex;
    align-items: center;
    transition: all 0.15s;
    flex-shrink: 0;
  }
  .mem-export-btn:hover { color: var(--text-primary); border-color: var(--border-hover, var(--border-color)); }

  /* ── P2: Export Menu ──────────────────── */
  .mem-export-menu {
    background: var(--card-bg, var(--bg-primary));
    border: 1px solid var(--border-color);
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.15);
    padding: 0.375rem;
    min-width: 140px;
    animation: cp-slide-in 0.1s ease;
  }
  .mem-export-menu-label {
    padding: 0.25rem 0.625rem;
    font-size: 0.625rem;
    color: var(--text-muted);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .mem-export-item {
    display: block;
    width: 100%;
    padding: 0.375rem 0.625rem;
    border: none;
    background: none;
    color: var(--text-primary);
    font-size: 0.8125rem;
    text-align: left;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.1s;
  }
  .mem-export-item:hover { background: var(--bg-secondary); }

  /* ── P2: Source badge ─────────────────── */
  .mem-source-badge {
    flex-shrink: 0;
    font-size: 0.5625rem;
    padding: 0 4px;
    border-radius: 3px;
    background: var(--bg-tertiary, var(--bg-secondary));
    color: var(--text-muted);
    white-space: nowrap;
    font-weight: 500;
    letter-spacing: 0.02em;
    text-transform: uppercase;
  }

  /* ── P2: Source select ────────────────── */
  .mem-source-select {
    padding: 0.4375rem 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm, 6px);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.75rem;
    cursor: pointer;
    outline: none;
  }

  /* ── P2: Content area (list + peek) ─── */
  .mem-content-area {
    display: flex;
    gap: 0;
    transition: gap 0.2s;
  }
  .mem-content-area .mem-list {
    flex: 1;
    min-width: 0;
    transition: flex 0.2s;
  }
  .mem-content-area.peek-open {
    gap: 0.75rem;
  }
  .mem-content-area.peek-open .mem-list {
    flex: 1;
  }

  /* ── P2: Peek Panel ───────────────────── */
  .mem-peek-panel {
    width: 380px;
    max-height: calc(100vh - 220px);
    overflow-y: auto;
    background: var(--card-bg, var(--bg-primary));
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius, 8px);
    animation: peek-in 0.15s ease;
    flex-shrink: 0;
  }
  @keyframes peek-in { from { opacity: 0; transform: translateX(12px); } to { opacity: 1; transform: translateX(0); } }

  .mem-peek-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.625rem 0.75rem;
    border-bottom: 1px solid var(--border-color);
  }
  .mem-peek-cat {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: capitalize;
  }
  .mem-peek-actions { display: flex; gap: 0.25rem; }
  .mem-peek-close {
    background: none;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: var(--text-muted);
    font-size: 1rem;
    line-height: 1;
  }
  .mem-peek-close:hover { color: var(--text-primary); }

  .mem-peek-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
    padding: 0.5rem 0.75rem;
    font-size: 0.6875rem;
    color: var(--text-muted);
    border-bottom: 1px solid var(--border-color);
  }
  .mem-peek-project {
    padding: 1px 6px;
    border-radius: 3px;
    background: var(--bg-secondary);
    font-weight: 500;
    color: var(--text-secondary);
  }
  .mem-peek-source {
    padding: 1px 6px;
    border-radius: 3px;
    background: var(--bg-tertiary, var(--bg-secondary));
    text-transform: uppercase;
    font-weight: 500;
    font-size: 0.5625rem;
    letter-spacing: 0.02em;
  }
  .mem-peek-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    padding: 0.375rem 0.75rem;
    border-bottom: 1px solid var(--border-color);
  }
  .mem-peek-body {
    padding: 0.75rem;
    font-size: 0.8125rem;
    line-height: 1.6;
    color: var(--text-primary);
    word-break: break-word;
  }
  .mem-peek-body h3 { font-size: 0.875rem; font-weight: 600; margin: 0.75rem 0 0.375rem; color: var(--text-primary); }
  .mem-peek-body h4 { font-size: 0.8125rem; font-weight: 600; margin: 0.5rem 0 0.25rem; color: var(--text-secondary); }
  .mem-peek-body code { padding: 1px 4px; border-radius: 3px; background: var(--bg-secondary); font-size: 0.75rem; font-family: 'SF Mono', 'Fira Code', monospace; }
  .mem-peek-body strong { font-weight: 600; }
  .mem-peek-body ul { margin: 0.25rem 0; padding-left: 1.25rem; }
  .mem-peek-body li { margin-bottom: 0.125rem; }

  .mem-peek-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 0.75rem;
    border-top: 1px solid var(--border-color);
    font-size: 0.625rem;
    color: var(--text-muted);
  }
  .mem-peek-id { font-family: monospace; }
  .mem-peek-open-btn {
    background: none;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 0.25rem 0.625rem;
    font-size: 0.6875rem;
    color: var(--text-secondary);
    cursor: pointer;
    font-weight: 500;
  }
  .mem-peek-open-btn:hover { color: var(--text-primary); background: var(--bg-secondary); }
  .mem-peek-loading { padding: 2rem 1rem; text-align: center; color: var(--text-muted); font-size: 0.8125rem; }

  /* ── Responsive ─────────────────────────── */
  @media (max-width: 640px) {
    .mem-toolbar {
      flex-direction: column;
      align-items: stretch;
      gap: 0.5rem;
    }
    .mem-toolbar .mem-title { font-size: 1rem; }
    .mem-search-wrap { min-width: 100%; }
    .mem-cat-combo, .mem-proj-combo { width: auto; flex: 1; min-width: 0; }
    .mem-sort-select, .mem-mode-select { flex: 1; min-width: 0; }
    .mem-time-range { width: 100%; }
    .mem-toolbar { flex-direction: row; flex-wrap: wrap; }
    .mem-tags { display: none; }
    .mem-list .recent-item-badge { display: none; }
    .mem-list .recent-item-project { display: none; }
    .mem-score { display: none; }
    .mem-source-badge { display: none; }
    .mem-peek-panel { display: none !important; }
    .mem-content-area.peek-open { gap: 0; }
    .cmd-palette { max-height: 70vh; }
  }
`;
document.head.appendChild(style);
