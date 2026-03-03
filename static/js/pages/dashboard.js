/**
 * Dashboard Page — Linear-style Memory-First
 * 1-line compact memory list as primary content
 */

import { wsClient } from '../services/websocket-client.js';
import '../components/connection-status.js';

const CAT_ICONS = {
  task: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>',
  bug: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
  decision: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
  code_snippet: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
  incident: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  idea: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 00-4 12.7V17h8v-2.3A7 7 0 0012 2z"/></svg>',
  'git-history': '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><line x1="1.05" y1="12" x2="7" y2="12"/><line x1="17.01" y1="12" x2="22.96" y2="12"/></svg>',
};
const DEFAULT_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';

class DashboardPage extends HTMLElement {
  constructor() {
    super();
    this.stats = null;
    this.memories = [];
    this.sessions = [];
    this.isLoading = true;
    this.isInitialized = false;
    this.refreshInterval = null;
    this.filterCategory = 'all';
    this.filterDays = 7;
    this.page = 0;
    this.pageSize = 30;
    this.hasMore = true;
    // Peek state
    this._peekId = null;
    this._peekData = null;
  }

  connectedCallback() {
    if (this.isInitialized) return;
    this.isInitialized = true;
    this.render();
    this.setupEventListeners();
    this.waitForAppAndLoadData();
    this.connectWebSocket();
    this.refreshInterval = setInterval(() => { if (!this.isLoading) this.loadData(); }, 5 * 60 * 1000);
  }

  disconnectedCallback() {
    if (this.refreshInterval) clearInterval(this.refreshInterval);
    if (this._bh) {
      wsClient.off('memory_created', this._bh.c);
      wsClient.off('memory_updated', this._bh.u);
      wsClient.off('memory_deleted', this._bh.d);
    }
    if (this._boundKeydown) {
      document.removeEventListener('keydown', this._boundKeydown);
      this._boundKeydown = null;
    }
  }

  // ── WebSocket ──

  connectWebSocket() {
    this._bh = {
      c: this.onMemoryCreated.bind(this),
      u: this.onMemoryUpdated.bind(this),
      d: this.onMemoryDeleted.bind(this),
    };
    wsClient.on('memory_created', this._bh.c);
    wsClient.on('memory_updated', this._bh.u);
    wsClient.on('memory_deleted', this._bh.d);
    if (!wsClient.getConnectionStatus().isConnected) wsClient.connect().catch(() => {});
  }

  onMemoryCreated({ memory }) {
    if (!memory) return;
    if (this.memories.some(m => m.id === memory.id)) return;
    this.memories.unshift(memory);
    this.renderMemoryList();
    this.refreshStats();
  }

  onMemoryUpdated({ memory_id, memory }) {
    const idx = this.memories.findIndex(m => m.id === memory_id);
    if (idx !== -1) { this.memories[idx] = memory; this.renderMemoryList(); }
  }

  onMemoryDeleted({ memory_id }) {
    this.memories = this.memories.filter(m => m.id !== memory_id);
    this.renderMemoryList();
    this.refreshStats();
  }

  // ── Events ──

  setupEventListeners() {
    this.addEventListener('click', (e) => {
      // Peek panel actions
      if (e.target.closest('.dash-peek-close')) { this.closePeek(); return; }
      if (e.target.closest('.dash-peek-open')) {
        const id = e.target.closest('.dash-peek-open').dataset.id;
        if (id && window.app?.router) { this.closePeek(); window.app.router.navigate(`/memory/${id}`); }
        return;
      }

      const row = e.target.closest('.recent-item');
      if (row) {
        const id = row.dataset.id;
        if (!id) return;
        // If peek is open, switch peek target; otherwise navigate
        if (this._peekId) {
          this.openPeek(id);
        } else if (window.app?.router) {
          window.app.router.navigate(`/memory/${id}`);
        }
        return;
      }
      if (e.target.closest('.load-more-btn')) { this.loadMore(); return; }
      if (e.target.closest('.session-end-btn')) { this.endSession(); return; }
      if (e.target.closest('.session-link')) {
        if (window.app?.router) window.app.router.navigate('/work');
        return;
      }
    });
    this.addEventListener('change', (e) => {
      if (e.target.matches('.filter-cat')) {
        this.filterCategory = e.target.value;
        this.page = 0; this.memories = []; this.loadData();
      }
      if (e.target.matches('.filter-days')) {
        this.filterDays = parseInt(e.target.value, 10);
        this.page = 0; this.memories = []; this.loadData();
      }
    });

    // Keyboard: Space = peek on hovered row, Escape = close peek
    this._boundKeydown = (e) => {
      if (!this.isConnected) return;
      if (e.target.matches('input, select, textarea') && e.key !== 'Escape') return;

      if (e.key === ' ') {
        e.preventDefault();
        const row = this.querySelector('.recent-item:hover');
        if (row) {
          const id = row.dataset.id;
          if (id) {
            if (this._peekId === id) this.closePeek();
            else this.openPeek(id);
          }
        }
      }
      if (e.key === 'Escape' && this._peekId) {
        this.closePeek();
      }
    };
    document.addEventListener('keydown', this._boundKeydown);
  }

  // ── Data ──

  async waitForAppAndLoadData() {
    let n = 0;
    const check = () => {
      if (window.app?.apiClient) { this.loadData(); return; }
      if (++n >= 50) { this.loadData(); return; }
      setTimeout(check, 100);
    };
    check();
  }

  async loadData() {
    this.isLoading = true;
    try {
      const api = window.app?.apiClient;
      if (!api) return;

      const searchParams = { limit: this.pageSize, recency_weight: 1.0 };
      if (this.filterCategory !== 'all') searchParams.category = this.filterCategory;

      const [statsR, memR, sessR] = await Promise.allSettled([
        api.getStats(),
        api.searchMemories(' ', searchParams),
        api.get('/work/sessions?limit=3'),
      ]);

      this.stats = statsR.status === 'fulfilled' ? statsR.value : null;
      const results = memR.status === 'fulfilled' ? (memR.value.results || []) : [];
      if (this.page === 0) this.memories = results;
      else this.memories = [...this.memories, ...results];
      this.hasMore = results.length >= this.pageSize;
      this.sessions = sessR.status === 'fulfilled' ? (sessR.value.sessions || []) : [];
    } catch (_) {}
    this.isLoading = false;
    this.renderContent();
  }

  async loadMore() {
    this.page++;
    await this.loadData();
  }

  async refreshStats() {
    try {
      const api = window.app?.apiClient;
      if (!api) return;
      this.stats = await api.getStats();
      this.renderFooter();
    } catch (_) {}
  }

  async endSession() {
    const active = this.sessions.find(s => s.status === 'active');
    if (!active) return;
    try {
      const api = window.app?.apiClient;
      if (!api) return;
      await api.post(`/work/sessions/${active.session_id || active.id}/end`, {});
      this.loadData();
    } catch (_) {}
  }

  // ── Render ──

  render() {
    this.className = 'dash';
    this.innerHTML = `
      <div class="dash-session" id="dash-session"></div>
      <div class="dash-insights" id="dash-insights"></div>
      <div class="dash-toolbar">
        <span class="dash-title">Recent Memories</span>
        <div class="dash-filters">
          <select class="filter-cat">
            <option value="all">All</option>
            <option value="decision">decision</option>
            <option value="bug">bug</option>
            <option value="code_snippet">code</option>
            <option value="idea">idea</option>
            <option value="incident">incident</option>
          </select>
          <select class="filter-days">
            <option value="7">7d</option>
            <option value="30">30d</option>
            <option value="90">90d</option>
            <option value="365">1y</option>
          </select>
        </div>
      </div>
      <div class="dash-content-area" id="dash-content-area">
        <div class="dash-list" id="dash-list"></div>
        <div class="dash-peek-panel" id="dash-peek" style="display:none"></div>
      </div>
      <div class="dash-footer" id="dash-footer"></div>
    `;
  }

  renderContent() {
    this.renderSession();
    this.renderInsights();
    this.renderMemoryList();
    this.renderFooter();
  }

  renderSession() {
    const el = this.querySelector('#dash-session');
    if (!el) return;
    const active = this.sessions.find(s => s.status === 'active');
    if (!active) { el.innerHTML = ''; el.classList.remove('has-session'); return; }
    el.classList.add('has-session');
    const pins = active.open_pins ?? 0;
    const t = active.started_at ? this.relTime(active.started_at) : '';
    const proj = active.project_id || '—';
    el.innerHTML = `
      <span class="session-dot"></span>
      <span class="session-project">${this.esc(proj)}</span>
      <span class="session-meta">${pins} pins open</span>
      <span class="session-meta">${t}</span>
      <button class="session-link">View</button>
      <button class="session-end-btn">End</button>
    `;
  }

  renderInsights() {
    const el = this.querySelector('#dash-insights');
    if (!el || !this.stats) return;

    const cats = this.stats.categories_breakdown || {};
    const total = Object.values(cats).reduce((a, b) => a + b, 0);
    if (total === 0) { el.innerHTML = ''; return; }

    // Category distribution — top categories as inline bars
    const sorted = Object.entries(cats).sort(([,a],[,b]) => b - a);
    const topCats = sorted.slice(0, 4);
    const catBars = topCats.map(([cat, count]) => {
      const pct = Math.round((count / total) * 100);
      const w = Math.max(pct, 4);
      return `<span class="insight-bar-item">
        <span class="insight-bar-track"><span class="insight-bar-fill cat-bg-${cat}" style="width:${w}%"></span></span>
        <span class="insight-bar-label">${cat.replace('_',' ')} ${pct}%</span>
      </span>`;
    }).join('');
    const moreCount = sorted.length - 4;
    const moreLabel = moreCount > 0 ? `<span class="insight-more">+${moreCount} more</span>` : '';

    // Weekly activity — count memories from last 7 days as mini bars
    const filtered = this.memories.filter(m => {
      const age = Date.now() - new Date(m.created_at).getTime();
      return age < 7 * 86400000;
    });
    const dayBuckets = new Array(7).fill(0);
    filtered.forEach(m => {
      const daysAgo = Math.floor((Date.now() - new Date(m.created_at).getTime()) / 86400000);
      if (daysAgo >= 0 && daysAgo < 7) dayBuckets[6 - daysAgo]++;
    });
    const maxDay = Math.max(...dayBuckets, 1);
    const dayLabels = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
    const today = new Date().getDay(); // 0=Sun
    const sparkBars = dayBuckets.map((c, i) => {
      const h = Math.max(Math.round((c / maxDay) * 24), 2);
      const dayIdx = (today - 6 + i + 7) % 7;
      return `<span class="spark-col" title="${dayLabels[dayIdx]}: ${c}"><span class="spark-bar" style="height:${h}px"></span></span>`;
    }).join('');
    const weekTotal = dayBuckets.reduce((a, b) => a + b, 0);

    const totalMemories = this.stats.total_memories ?? total;

    el.innerHTML = `
      <div class="insight-card insight-total">
        <span class="insight-count-lg">${totalMemories.toLocaleString()}</span>
        <span class="insight-title">memories</span>
      </div>
      <div class="insight-card">
        <span class="insight-title">Categories</span>
        <div class="insight-bars">${catBars}${moreLabel}</div>
      </div>
      <div class="insight-card">
        <span class="insight-title">This week</span>
        <div class="insight-spark">${sparkBars}</div>
        <span class="insight-count">${weekTotal}</span>
      </div>
    `;
  }

  renderMemoryList() {
    const el = this.querySelector('#dash-list');
    if (!el) return;

    if (this.isLoading && this.memories.length === 0) {
      el.innerHTML = Array.from({ length: 8 }, () =>
        '<div class="recent-item ml-skeleton"><span class="sk-line"></span></div>'
      ).join('');
      return;
    }

    if (this.memories.length === 0) {
      el.innerHTML = '<div class="ml-empty">No memories found</div>';
      return;
    }

    const filtered = this.filterByDays(this.memories);
    const rows = filtered.map(m => this.buildRow(m)).join('');
    const more = this.hasMore ? '<button class="load-more-btn">Load more</button>' : '';
    el.innerHTML = rows + more;
  }

  buildRow(m) {
    const icon = CAT_ICONS[m.category] || DEFAULT_ICON;
    const preview = (m.content || '').replace(/#{1,6}\s+/g, '').replace(/\*\*(.*?)\*\*/g, '$1').replace(/\n/g, ' ').trim();
    const truncated = preview.length > 120 ? preview.substring(0, 120) + '...' : preview;
    const time = this.relTime(m.created_at);
    const source = m.source && m.source !== 'unknown' ? m.source : '';
    return `<div class="recent-item" data-id="${m.id}" role="button" tabindex="0">
      <span class="recent-item-icon cat-${m.category}">${icon}</span>
      <span class="recent-item-badge">${m.category}</span>
      ${m.project_id ? `<span class="recent-item-project">${this.esc(m.project_id)}</span>` : ''}
      <span class="recent-item-content">${this.esc(truncated)}</span>
      <span class="recent-item-time">${time}${source ? ' \u00b7 ' + source : ''}</span>
    </div>`;
  }

  renderFooter() {
    const el = this.querySelector('#dash-footer');
    if (!el) return;
    const s = this.stats;
    const total = s?.total_memories?.toLocaleString() || '—';
    const today = s?.categories_breakdown ? Object.values(s.categories_breakdown).reduce((a, b) => a + b, 0) : '—';
    const projects = s?.unique_projects || '—';
    const ws = wsClient.getConnectionStatus().isConnected;
    el.innerHTML = `
      <span>${total} memories</span>
      <span class="footer-sep">&middot;</span>
      <span>${projects} projects</span>
      <span class="footer-sep">&middot;</span>
      <connection-status></connection-status>
    `;
  }

  // ── Helpers ──

  filterByDays(memories) {
    const cutoff = Date.now() - this.filterDays * 86400000;
    return memories.filter(m => new Date(m.created_at).getTime() >= cutoff);
  }

  relTime(d) {
    if (!d) return '';
    const ms = Date.now() - new Date(d).getTime();
    const m = Math.floor(ms / 60000);
    if (m < 1) return 'now';
    if (m < 60) return `${m}m`;
    const h = Math.floor(ms / 3600000);
    if (h < 24) return `${h}h`;
    const day = Math.floor(ms / 86400000);
    if (day < 30) return `${day}d`;
    return `${Math.floor(day / 30)}mo`;
  }

  esc(t) {
    if (t == null) return '';
    return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── Peek panel ──

  async openPeek(memoryId) {
    if (this._peekId === memoryId) { this.closePeek(); return; }
    this._peekId = memoryId;

    const panel = this.querySelector('#dash-peek');
    if (!panel) return;

    panel.style.display = 'block';
    panel.innerHTML = '<div class="dash-peek-loading">Loading...</div>';
    this.querySelector('#dash-content-area')?.classList.add('peek-open');

    try {
      const api = window.app?.apiClient;
      if (!api) return;
      const mem = await api.getMemory(memoryId);
      if (!mem || this._peekId !== memoryId) return;
      this._peekData = mem;
      this.renderPeekPanel();
    } catch {
      panel.innerHTML = '<div class="dash-peek-loading">Failed to load</div>';
    }
  }

  closePeek() {
    this._peekId = null;
    this._peekData = null;
    const panel = this.querySelector('#dash-peek');
    if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }
    this.querySelector('#dash-content-area')?.classList.remove('peek-open');
  }

  renderPeekPanel() {
    const panel = this.querySelector('#dash-peek');
    if (!panel || !this._peekData) return;

    const m = this._peekData;
    if (typeof m.tags === 'string') {
      try { m.tags = JSON.parse(m.tags); } catch { m.tags = []; }
    }
    const icon = CAT_ICONS[m.category] || DEFAULT_ICON;
    const time = this.relTime(m.created_at);

    panel.innerHTML = `
      <div class="dash-peek-header">
        <span class="dash-peek-cat">${icon} ${this.esc(m.category)}</span>
        <button class="dash-peek-close" title="Close (Esc)">&times;</button>
      </div>
      <div class="dash-peek-meta">
        ${m.project_id ? `<span class="dash-peek-project">${this.esc(m.project_id)}</span>` : ''}
        ${m.source && m.source !== 'unknown' ? `<span class="dash-peek-source">${this.esc(m.source)}</span>` : ''}
        <span class="dash-peek-time">${time}</span>
      </div>
      ${(m.tags || []).length ? `<div class="dash-peek-tags">${m.tags.map(t => `<span class="dash-peek-tag">#${this.esc(t)}</span>`).join('')}</div>` : ''}
      <div class="dash-peek-body">${this._renderMarkdown(m.content || '')}</div>
      <div class="dash-peek-footer">
        <span class="dash-peek-id">${m.id.substring(0, 8)}...</span>
        <button class="dash-peek-open" data-id="${this.esc(m.id)}">Open full →</button>
      </div>
    `;
  }

  _renderMarkdown(text) {
    return this.esc(text)
      .replace(/^### (.+)$/gm, '<h4>$1</h4>')
      .replace(/^## (.+)$/gm, '<h3>$1</h3>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/^- (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
      .replace(/\n\n/g, '<br><br>')
      .replace(/\n/g, '<br>');
  }
}

customElements.define('dashboard-page', DashboardPage);
export { DashboardPage };
