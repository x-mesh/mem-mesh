/**
 * Dashboard Page — Linear-style Memory-First
 * 1-line compact memory list as primary content
 */

import { wsClient } from '../services/websocket-client.js';
import '../components/connection-status.js';

const CAT_ICONS = {
  decision: '\u2605', bug: '\u25CF', code_snippet: '\u25C6',
  idea: '\u25CB', incident: '\u25B2', task: '\u25A0', 'git-history': '\u25C7',
};

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
      const row = e.target.closest('.ml-row');
      if (row) {
        const id = row.dataset.id;
        if (id && window.app?.router) window.app.router.navigate(`/memory/${id}`);
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
      <div class="dash-list" id="dash-list"></div>
      <div class="dash-footer" id="dash-footer"></div>
    `;
  }

  renderContent() {
    this.renderSession();
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

  renderMemoryList() {
    const el = this.querySelector('#dash-list');
    if (!el) return;

    if (this.isLoading && this.memories.length === 0) {
      el.innerHTML = Array.from({ length: 8 }, () =>
        '<div class="ml-row ml-skeleton"><span class="sk-line"></span></div>'
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
    const icon = CAT_ICONS[m.category] || '\u25CF';
    const cat = (m.category || '').replace('_', ' ');
    const title = this.extractTitle(m.content);
    const proj = m.project_id || '';
    const time = this.relTime(m.created_at);
    return `<div class="ml-row" data-id="${m.id}" role="button" tabindex="0">
      <span class="ml-icon cat-${m.category}">${icon}</span>
      <span class="ml-cat">${cat}</span>
      <span class="ml-title">${this.esc(title)}</span>
      <span class="ml-proj">${this.esc(proj)}</span>
      <span class="ml-time">${time}</span>
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

  extractTitle(content) {
    if (!content) return '(empty)';
    const line = content.replace(/^#{1,6}\s+/, '').replace(/\*\*(.*?)\*\*/g, '$1').split('\n')[0].trim();
    return line.length > 60 ? line.slice(0, 60) + '\u2026' : line;
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
}

customElements.define('dashboard-page', DashboardPage);
export { DashboardPage };
