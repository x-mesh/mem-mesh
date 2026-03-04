/**
 * Dashboard Page — Linear-style Memory-First
 * 1-line compact memory list as primary content
 */

import { wsClient } from '../services/websocket-client.js';

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

const CLIENT_COLORS = {
  claude_code: '#d97706',
  cursor: '#7c3aed',
  kiro: '#059669',
  web: '#2563eb',
  unknown: '#6b7280',
};

const VIZ_MODES = ['pulse', 'orbit', 'ticker', 'heatmap', 'stats', 'timeline', 'flow', 'calendar', 'leaderboard'];
const VIZ_LABELS = { pulse: 'Pulse', orbit: 'Orbit', ticker: 'Ticker', heatmap: 'Heatmap', stats: 'Stats', timeline: 'Timeline', flow: 'Flow', calendar: 'Calendar', leaderboard: 'Board' };

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
    this.filterDays = 30;
    this.page = 0;
    this.pageSize = 30;
    this.hasMore = true;
    // Peek state
    this._peekId = null;
    this._peekData = null;
    // Pins
    this.activePins = [];
    // Client viz state
    this._vizMode = localStorage.getItem('mem-mesh-client-viz') || 'orbit';
    this._vizEvents = []; // recent events for pulse/ticker
    this._orbitAnim = null; // orbit animation frame id
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
    if (this._orbitAnim) { cancelAnimationFrame(this._orbitAnim); this._orbitAnim = null; }
    if (this.refreshInterval) clearInterval(this.refreshInterval);
    if (this._bh) {
      wsClient.off('memory_created', this._bh.c);
      wsClient.off('memory_updated', this._bh.u);
      wsClient.off('memory_deleted', this._bh.d);
      wsClient.off('reconnected', this._bh.r);
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
      r: () => { this.page = 0; this.memories = []; this.loadData(); },
    };
    wsClient.on('memory_created', this._bh.c);
    wsClient.on('memory_updated', this._bh.u);
    wsClient.on('memory_deleted', this._bh.d);
    wsClient.on('reconnected', this._bh.r);
    // P5: connect()는 main.js에서 전역으로 호출됨
  }

  onMemoryCreated({ memory }) {
    if (!memory) return;
    if (this.memories.some(m => m.id === memory.id)) return;
    this.memories.unshift(memory);
    this.renderMemoryList();
    this.refreshStats();
    // Push viz event
    this._pushVizEvent(memory);
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
      if (e.target.closest('.viz-mode-btn')) {
        const mode = e.target.closest('.viz-mode-btn').dataset.mode;
        if (mode && VIZ_MODES.includes(mode)) {
          this._vizMode = mode;
          localStorage.setItem('mem-mesh-client-viz', mode);
          this.renderClientViz();
        }
        return;
      }
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

      // Server-side date filtering
      const from = new Date(Date.now() - this.filterDays * 86400000);
      searchParams.date_from = from.toISOString().split('T')[0];
      searchParams.temporal_mode = 'filter';

      const [statsR, memR, sessR, pinsR] = await Promise.allSettled([
        api.getStats(),
        api.searchMemories(' ', searchParams),
        api.get('/work/sessions?limit=3'),
        api.get('/work/pins', { limit: 50 }),
      ]);

      this.stats = statsR.status === 'fulfilled' ? statsR.value : null;
      const results = memR.status === 'fulfilled' ? (memR.value.results || []) : [];
      if (this.page === 0) this.memories = results;
      else this.memories = [...this.memories, ...results];
      this.hasMore = results.length >= this.pageSize;
      this.sessions = sessR.status === 'fulfilled' ? (sessR.value.sessions || []) : [];
      this.activePins = pinsR.status === 'fulfilled'
        ? (pinsR.value.pins || []).filter(p => p.status !== 'completed')
        : [];
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
      <div class="dash-pins" id="dash-pins"></div>
      <div class="dash-insights" id="dash-insights"></div>
      <div class="client-viz-section" id="client-viz">
        <div class="client-viz-header">
          <span class="client-viz-title">Client Activity</span>
          <div class="client-viz-switcher" id="viz-switcher"></div>
        </div>
        <div class="client-viz-body" id="client-viz-body"></div>
      </div>
      <div class="dash-projects" id="dash-projects"></div>
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
            <option value="30" selected>30d</option>
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
    this.renderPins();
    this.renderInsights();
    this.renderClientViz();
    this.renderProjects();
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

  renderPins() {
    const el = this.querySelector('#dash-pins');
    if (!el) return;

    const allPins = this.activePins || [];
    if (allPins.length === 0) { el.innerHTML = ''; return; }

    // Sort: importance DESC, then newest first. Show top 5.
    const sorted = [...allPins].sort((a, b) => (b.importance || 3) - (a.importance || 3) || new Date(b.created_at) - new Date(a.created_at));
    const pins = sorted.slice(0, 5);
    const hasMore = allPins.length > 5;

    const statusColors = { open: 'var(--text-muted)', in_progress: '#d97706' };

    const pinRows = pins.map(pin => {
      const proj = pin.project_id || '—';
      const importance = pin.importance || 3;
      const statusColor = statusColors[pin.status] || 'var(--text-muted)';
      const preview = (pin.content || '').length > 40 ? pin.content.substring(0, 40) + '…' : pin.content;

      return `<div class="pin-row">
        <span class="pin-status-dot" style="background:${statusColor}"></span>
        <span class="pin-imp pin-imp-${importance}">P${importance}</span>
        <span class="pin-project">${this.esc(proj)}</span>
        <span class="pin-content">${this.esc(preview)}</span>
      </div>`;
    }).join('');

    el.innerHTML = `
      <div class="pins-section">
        <div class="pins-header">
          <span class="pins-title">Active Pins</span>
          <span class="pins-count">${allPins.length}</span>
          ${hasMore ? '<a class="pins-more" href="#/work">View all</a>' : ''}
        </div>
        <div class="pins-list">${pinRows}</div>
      </div>
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

  renderProjects() {
    const el = this.querySelector('#dash-projects');
    if (!el || !this.stats) return;

    const breakdown = this.stats.projects_breakdown || {};
    const entries = Object.entries(breakdown).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) { el.innerHTML = ''; return; }

    const total = entries.reduce((s, [, c]) => s + c, 0) || 1;
    const topN = entries.slice(0, 6);
    const rest = entries.length - topN.length;

    const bars = topN.map(([name, count]) => {
      const pct = Math.round((count / total) * 100);
      const w = Math.max(pct, 3);
      return `<div class="proj-row" data-route="/project/${encodeURIComponent(name)}">
        <span class="proj-name" title="${this.esc(name)}">${this.esc(name)}</span>
        <div class="proj-bar-track"><div class="proj-bar-fill" style="width:${w}%"></div></div>
        <span class="proj-count">${count}</span>
      </div>`;
    }).join('');

    const restLabel = rest > 0 ? `<span class="proj-rest">+${rest} more projects</span>` : '';

    el.innerHTML = `
      <div class="proj-section">
        <div class="proj-header">
          <span class="proj-title">Projects</span>
          <span class="proj-total">${entries.length} projects · ${total.toLocaleString()} memories</span>
        </div>
        <div class="proj-list">${bars}</div>
        ${restLabel}
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

    const rows = this.memories.map(m => this.buildRow(m)).join('');
    const more = this.hasMore ? '<button class="load-more-btn">Load more</button>' : '';
    el.innerHTML = rows + more;
  }

  buildRow(m) {
    const icon = CAT_ICONS[m.category] || DEFAULT_ICON;
    const preview = (m.content || '').replace(/#{1,6}\s+/g, '').replace(/\*\*(.*?)\*\*/g, '$1').replace(/\n/g, ' ').trim();
    const truncated = preview.length > 120 ? preview.substring(0, 120) + '...' : preview;
    const time = this.relTime(m.created_at);
    const source = m.source && m.source !== 'unknown' ? m.source : '';
    const client = m.client || '';
    return `<div class="recent-item" data-id="${m.id}" role="button" tabindex="0">
      <span class="recent-item-icon cat-${m.category}">${icon}</span>
      <span class="recent-item-badge">${m.category}</span>
      ${m.project_id ? `<span class="recent-item-project">${this.esc(m.project_id)}</span>` : ''}
      ${client ? `<span class="recent-item-client client-${client}">${client}</span>` : ''}
      <span class="recent-item-content">${this.esc(truncated)}</span>
      <span class="recent-item-time">${time}${source ? ' \u00b7 ' + source : ''}</span>
    </div>`;
  }

  renderFooter() {
    const el = this.querySelector('#dash-footer');
    if (!el) return;
    const s = this.stats;
    const total = s?.total_memories?.toLocaleString() || '—';
    const projects = s?.unique_projects || '—';
    el.innerHTML = `
      <span>${total} memories</span>
      <span class="footer-sep">&middot;</span>
      <span>${projects} projects</span>
    `;
  }

  // ── Client Visualization ──

  _pushVizEvent(memory) {
    this._vizEvents.unshift({
      client: memory.client || 'unknown',
      category: memory.category || 'task',
      content: (memory.content || '').substring(0, 60),
      time: Date.now(),
    });
    if (this._vizEvents.length > 40) this._vizEvents.length = 40;
    // Live-update current viz
    if (this._vizMode === 'pulse') this._appendPulseDot(this._vizEvents[0]);
    if (this._vizMode === 'ticker') this._appendTickerItem(this._vizEvents[0]);
  }

  renderClientViz() {
    const section = this.querySelector('#client-viz');
    if (!section) return;

    const clients = this.stats?.clients_breakdown || {};
    const hasClients = Object.keys(clients).length > 0;
    if (!hasClients && this.memories.length === 0) {
      section.style.display = 'none';
      return;
    }
    section.style.display = '';

    // Render switcher
    const switcher = this.querySelector('#viz-switcher');
    if (switcher) {
      switcher.innerHTML = VIZ_MODES.map(m =>
        `<button class="viz-mode-btn${this._vizMode === m ? ' active' : ''}" data-mode="${m}">${VIZ_LABELS[m]}</button>`
      ).join('');
    }

    // Seed viz events from memories if empty
    if (this._vizEvents.length === 0 && this.memories.length > 0) {
      this._vizEvents = this.memories.slice(0, 30).map(m => ({
        client: m.client || 'unknown',
        category: m.category || 'task',
        content: (m.content || '').substring(0, 60),
        time: new Date(m.created_at).getTime(),
      }));
    }

    // Stop orbit if switching away
    if (this._vizMode !== 'orbit' && this._orbitAnim) {
      cancelAnimationFrame(this._orbitAnim);
      this._orbitAnim = null;
    }

    const body = this.querySelector('#client-viz-body');
    if (!body) return;

    if (this._vizMode === 'pulse') this._renderPulseStrip(body);
    else if (this._vizMode === 'orbit') this._renderOrbitRing(body);
    else if (this._vizMode === 'ticker') this._renderStreamTicker(body);
    else if (this._vizMode === 'heatmap') this._renderHeatmap(body);
    else if (this._vizMode === 'stats') this._renderStatsCards(body);
    else if (this._vizMode === 'timeline') this._renderTimeline(body);
    else if (this._vizMode === 'flow') this._renderFlow(body);
    else if (this._vizMode === 'calendar') this._renderCalendar(body);
    else if (this._vizMode === 'leaderboard') this._renderLeaderboard(body);
  }

  // ── 1. Pulse Strip ──

  _renderPulseStrip(container) {
    const clients = this.stats?.clients_breakdown || {};
    const entries = Object.entries(clients).sort(([,a],[,b]) => b - a);

    // Client legend + dot timeline
    const legend = entries.map(([name, count]) => {
      const color = CLIENT_COLORS[name] || CLIENT_COLORS.unknown;
      return `<span class="pulse-client" style="--c:${color}">
        <span class="pulse-client-dot"></span>
        <span class="pulse-client-name">${this.esc(name)}</span>
        <span class="pulse-client-count">${count}</span>
      </span>`;
    }).join('');

    // Build dot timeline from events
    const dots = this._vizEvents.slice(0, 30).map((ev, i) => {
      const color = CLIENT_COLORS[ev.client] || CLIENT_COLORS.unknown;
      const age = (Date.now() - ev.time) / 3600000; // hours
      const opacity = Math.max(0.25, 1 - age / 168); // fade over 7 days
      const catIcon = CAT_ICONS[ev.category] ? 'has-icon' : '';
      return `<span class="pulse-dot ${catIcon}" style="--c:${color};opacity:${opacity.toFixed(2)}" title="${this.esc(ev.client)}: ${this.esc(ev.content)}" data-idx="${i}"></span>`;
    }).join('');

    container.innerHTML = `
      <div class="pulse-legend">${legend}</div>
      <div class="pulse-timeline" id="pulse-timeline">${dots}</div>
    `;
  }

  _appendPulseDot(ev) {
    const timeline = this.querySelector('#pulse-timeline');
    if (!timeline || this._vizMode !== 'pulse') return;
    const color = CLIENT_COLORS[ev.client] || CLIENT_COLORS.unknown;
    const dot = document.createElement('span');
    dot.className = 'pulse-dot pulse-dot-enter';
    dot.style.setProperty('--c', color);
    dot.title = `${ev.client}: ${ev.content}`;
    timeline.prepend(dot);
    // Remove excess
    while (timeline.children.length > 30) timeline.lastElementChild.remove();
    // Trigger animation
    requestAnimationFrame(() => dot.classList.remove('pulse-dot-enter'));
  }

  // ── 2. Orbit Ring ──

  _renderOrbitRing(container) {
    const clients = this.stats?.clients_breakdown || {};
    const entries = Object.entries(clients).sort(([,a],[,b]) => b - a);
    const total = Object.values(clients).reduce((a, b) => a + b, 0) || 1;

    container.innerHTML = `<canvas id="orbit-canvas" width="600" height="180"></canvas>`;
    const canvas = container.querySelector('#orbit-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    // Build orbit nodes — size circle to fit label text
    const fontSize = 9;
    ctx.font = `600 ${fontSize}px system-ui, sans-serif`;
    const nodes = entries.map(([name, count], i) => {
      const textW = ctx.measureText(name).width;
      const minR = (textW / 2) + 6; // text half-width + padding
      const countR = Math.max(12, (count / total) * 50);
      return {
        name,
        count,
        color: CLIENT_COLORS[name] || CLIENT_COLORS.unknown,
        radius: Math.max(minR, countR),
        angle: (i / entries.length) * Math.PI * 2,
        speed: 0.003 + (i * 0.002),
        pulsePhase: Math.random() * Math.PI * 2,
        fontSize,
      };
    });

    // Particles for recent events
    const particles = [];
    this._vizEvents.slice(0, 15).forEach((ev, i) => {
      particles.push({
        color: CLIENT_COLORS[ev.client] || CLIENT_COLORS.unknown,
        angle: Math.random() * Math.PI * 2,
        dist: 30 + Math.random() * 40,
        speed: 0.01 + Math.random() * 0.015,
        size: 2 + Math.random() * 2,
        alpha: 0.3 + Math.random() * 0.5,
      });
    });

    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.offsetWidth * dpr;
    canvas.height = 180 * dpr;
    canvas.style.width = canvas.offsetWidth + 'px';
    canvas.style.height = '180px';
    ctx.scale(dpr, dpr);
    const W = canvas.offsetWidth;
    const H = 180;
    const cx = W / 2;
    const cy = H / 2;
    const orbitRx = Math.min(W * 0.35, 120);
    const orbitRy = orbitRx * 0.45;

    const draw = (t) => {
      ctx.clearRect(0, 0, W, H);

      // Draw orbit path
      ctx.beginPath();
      ctx.ellipse(cx, cy, orbitRx, orbitRy, 0, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(128,128,128,0.15)';
      ctx.lineWidth = 1;
      ctx.stroke();

      // Draw center label
      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim() || '#888';
      ctx.font = '600 11px system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('mem-mesh', cx, cy);

      // Draw particles
      particles.forEach(p => {
        p.angle += p.speed;
        const px = cx + Math.cos(p.angle) * (orbitRx * p.dist / 70);
        const py = cy + Math.sin(p.angle) * (orbitRy * p.dist / 70);
        ctx.beginPath();
        ctx.arc(px, py, p.size, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.globalAlpha = p.alpha * (0.5 + 0.5 * Math.sin(t * 0.002 + p.angle));
        ctx.fill();
        ctx.globalAlpha = 1;
      });

      // Draw client nodes
      nodes.forEach(node => {
        node.angle += node.speed;
        const nx = cx + Math.cos(node.angle) * orbitRx;
        const ny = cy + Math.sin(node.angle) * orbitRy;
        const pulse = 1 + 0.12 * Math.sin(t * 0.003 + node.pulsePhase);
        const r = node.radius * pulse;

        // Glow
        ctx.beginPath();
        ctx.arc(nx, ny, r + 4, 0, Math.PI * 2);
        ctx.fillStyle = node.color;
        ctx.globalAlpha = 0.12;
        ctx.fill();
        ctx.globalAlpha = 1;

        // Circle
        ctx.beginPath();
        ctx.arc(nx, ny, r, 0, Math.PI * 2);
        ctx.fillStyle = node.color;
        ctx.fill();

        // Label
        ctx.fillStyle = '#fff';
        ctx.font = `600 ${node.fontSize}px system-ui, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(node.name, nx, ny);
      });

      this._orbitAnim = requestAnimationFrame(draw);
    };

    this._orbitAnim = requestAnimationFrame(draw);
  }

  // ── 3. Stream Ticker ──

  _renderStreamTicker(container) {
    const items = this._vizEvents.slice(0, 20).map(ev => {
      const color = CLIENT_COLORS[ev.client] || CLIENT_COLORS.unknown;
      const catIcon = CAT_ICONS[ev.category] || DEFAULT_ICON;
      const preview = ev.content.length > 40 ? ev.content.substring(0, 40) + '...' : ev.content;
      const ago = this.relTime(new Date(ev.time).toISOString());
      return `<span class="ticker-item">
        <span class="ticker-client" style="background:${color}">${this.esc(ev.client)}</span>
        <span class="ticker-cat">${catIcon}</span>
        <span class="ticker-text">${this.esc(preview)}</span>
        <span class="ticker-time">${ago}</span>
      </span>`;
    }).join('');

    container.innerHTML = `
      <div class="ticker-track" id="ticker-track">
        <div class="ticker-scroll">${items}${items}</div>
      </div>
    `;
  }

  _appendTickerItem(ev) {
    const scroll = this.querySelector('.ticker-scroll');
    if (!scroll || this._vizMode !== 'ticker') return;
    const color = CLIENT_COLORS[ev.client] || CLIENT_COLORS.unknown;
    const catIcon = CAT_ICONS[ev.category] || DEFAULT_ICON;
    const preview = ev.content.length > 40 ? ev.content.substring(0, 40) + '...' : ev.content;
    const html = `<span class="ticker-item ticker-item-enter">
      <span class="ticker-client" style="background:${color}">${this.esc(ev.client)}</span>
      <span class="ticker-cat">${catIcon}</span>
      <span class="ticker-text">${this.esc(preview)}</span>
      <span class="ticker-time">now</span>
    </span>`;
    scroll.insertAdjacentHTML('afterbegin', html);
    requestAnimationFrame(() => {
      const el = scroll.firstElementChild;
      if (el) el.classList.remove('ticker-item-enter');
    });
  }

  // ── Heatmap ──

  _renderHeatmap(container) {
    const hours = Array.from({ length: 24 }, (_, i) => i);
    const clients = Object.keys(this.stats?.clients_breakdown || {});
    if (!clients.length) {
      container.innerHTML = '<div style="text-align:center;color:var(--text-muted);font-size:var(--text-xs);padding:var(--space-4)">No client data</div>';
      return;
    }

    // Build hour×client matrix from memories
    const matrix = {};
    clients.forEach(c => { matrix[c] = new Array(24).fill(0); });
    (this.memories || []).forEach(m => {
      const client = m.client || 'unknown';
      if (!matrix[client]) matrix[client] = new Array(24).fill(0);
      const h = new Date(m.created_at).getHours();
      matrix[client][h]++;
    });

    // Find max for opacity scaling
    let max = 0;
    clients.forEach(c => hours.forEach(h => { if (matrix[c]?.[h] > max) max = matrix[c][h]; }));
    if (max === 0) max = 1;

    // Hour labels (show every 3h)
    const hourLabels = hours.map(h =>
      h % 3 === 0 ? `<span class="heatmap-hour-label">${String(h).padStart(2, '0')}</span>` : '<span class="heatmap-hour-label"></span>'
    ).join('');

    // Rows
    const rows = clients.map(client => {
      const color = CLIENT_COLORS[client] || CLIENT_COLORS.unknown;
      const cells = hours.map(h => {
        const count = matrix[client]?.[h] || 0;
        const opacity = count === 0 ? 0.08 : 0.2 + (count / max) * 0.8;
        const title = `${client} · ${String(h).padStart(2, '0')}:00 — ${count} memor${count === 1 ? 'y' : 'ies'}`;
        return `<span class="heatmap-cell" style="background:${color};opacity:${opacity}" title="${title}"></span>`;
      }).join('');
      return `<div class="heatmap-row">
        <span class="heatmap-client" style="color:${color}">${this.esc(client)}</span>
        <div class="heatmap-cells">${cells}</div>
      </div>`;
    }).join('');

    container.innerHTML = `
      <div class="heatmap-grid">
        <div class="heatmap-row heatmap-header-row">
          <span class="heatmap-client"></span>
          <div class="heatmap-cells heatmap-hours">${hourLabels}</div>
        </div>
        ${rows}
      </div>
    `;
  }

  // ── Stats Cards ──

  _renderStatsCards(container) {
    const breakdown = this.stats?.clients_breakdown || {};
    const clients = Object.entries(breakdown).sort((a, b) => b[1] - a[1]);
    const total = clients.reduce((s, [, c]) => s + c, 0) || 1;

    if (!clients.length) {
      container.innerHTML = '<div style="text-align:center;color:var(--text-muted);font-size:var(--text-xs);padding:var(--space-4)">No client data</div>';
      return;
    }

    // Per-client category breakdown from memories
    const clientCats = {};
    (this.memories || []).forEach(m => {
      const c = m.client || 'unknown';
      if (!clientCats[c]) clientCats[c] = {};
      const cat = m.category || 'other';
      clientCats[c][cat] = (clientCats[c][cat] || 0) + 1;
    });

    // Recent activity (last 24h)
    const now = Date.now();
    const recentCounts = {};
    (this.memories || []).forEach(m => {
      const c = m.client || 'unknown';
      if (now - new Date(m.created_at).getTime() < 86400000) {
        recentCounts[c] = (recentCounts[c] || 0) + 1;
      }
    });

    const cards = clients.map(([client, count]) => {
      const color = CLIENT_COLORS[client] || CLIENT_COLORS.unknown;
      const pct = ((count / total) * 100).toFixed(0);
      const recent = recentCounts[client] || 0;
      const cats = clientCats[client] || {};
      const topCats = Object.entries(cats).sort((a, b) => b[1] - a[1]).slice(0, 3);
      const catTags = topCats.map(([cat, n]) =>
        `<span class="stats-cat-tag">${this.esc(cat)} <em>${n}</em></span>`
      ).join('');

      return `<div class="stats-card">
        <div class="stats-card-header">
          <span class="stats-card-dot" style="background:${color}"></span>
          <span class="stats-card-name">${this.esc(client)}</span>
          <span class="stats-card-count">${count}</span>
        </div>
        <div class="stats-card-bar-track">
          <div class="stats-card-bar-fill" style="width:${pct}%;background:${color}"></div>
        </div>
        <div class="stats-card-meta">
          <span class="stats-card-pct">${pct}%</span>
          <span class="stats-card-recent">${recent > 0 ? `${recent} today` : 'idle'}</span>
        </div>
        ${catTags ? `<div class="stats-card-cats">${catTags}</div>` : ''}
      </div>`;
    }).join('');

    container.innerHTML = `<div class="stats-grid">${cards}</div>`;
  }

  // ── Timeline ──

  _renderTimeline(container) {
    const events = (this._vizEvents || []).slice(0, 20);
    if (!events.length) {
      container.innerHTML = '<div style="text-align:center;color:var(--text-muted);font-size:var(--text-xs);padding:var(--space-4)">No recent events</div>';
      return;
    }

    const items = events.map((ev, i) => {
      const color = CLIENT_COLORS[ev.client] || CLIENT_COLORS.unknown;
      const catIcon = CAT_ICONS[ev.category] || DEFAULT_ICON;
      const preview = ev.content.length > 60 ? ev.content.substring(0, 60) + '...' : ev.content;
      const timeStr = this.relTime(ev.time);
      return `<div class="tl-item" style="--delay:${i * 40}ms">
        <div class="tl-line"><span class="tl-dot" style="background:${color}"></span></div>
        <div class="tl-body">
          <div class="tl-head">
            <span class="tl-client" style="background:${color}">${this.esc(ev.client)}</span>
            <span class="tl-cat">${catIcon}</span>
            <span class="tl-time">${timeStr}</span>
          </div>
          <div class="tl-text">${this.esc(preview)}</div>
        </div>
      </div>`;
    }).join('');

    container.innerHTML = `<div class="tl-container">${items}</div>`;
  }

  // ── Flow (Sankey) ──

  _renderFlow(container) {
    const breakdown = this.stats?.clients_breakdown || {};
    const clients = Object.keys(breakdown);
    if (!clients.length) {
      container.innerHTML = '<div style="text-align:center;color:var(--text-muted);font-size:var(--text-xs);padding:var(--space-4)">No client data</div>';
      return;
    }

    // Build client→category flow from memories
    const flows = {};
    const catTotals = {};
    (this.memories || []).forEach(m => {
      const c = m.client || 'unknown';
      const cat = m.category || 'other';
      const key = `${c}→${cat}`;
      flows[key] = (flows[key] || 0) + 1;
      catTotals[cat] = (catTotals[cat] || 0) + 1;
    });

    const total = Object.values(flows).reduce((s, v) => s + v, 0) || 1;
    const categories = Object.entries(catTotals).sort((a, b) => b[1] - a[1]);

    // SVG-based sankey
    const svgW = 400;
    const svgH = Math.max(120, clients.length * 28, categories.length * 28);
    const leftX = 90;
    const rightX = svgW - 90;

    // Position nodes
    const clientNodes = clients.map((c, i) => ({
      name: c, y: (i + 0.5) * (svgH / clients.length), count: breakdown[c] || 0,
      color: CLIENT_COLORS[c] || CLIENT_COLORS.unknown
    }));
    const catNodes = categories.map(([cat, count], i) => ({
      name: cat, y: (i + 0.5) * (svgH / categories.length), count
    }));

    // Draw paths
    const paths = Object.entries(flows).map(([key, count]) => {
      const [cName, catName] = key.split('→');
      const cNode = clientNodes.find(n => n.name === cName);
      const catNode = catNodes.find(n => n.name === catName);
      if (!cNode || !catNode) return '';
      const thickness = Math.max(1, (count / total) * 40);
      const color = cNode.color;
      const midX = (leftX + rightX) / 2;
      return `<path d="M${leftX + 4},${cNode.y} C${midX},${cNode.y} ${midX},${catNode.y} ${rightX - 4},${catNode.y}"
        fill="none" stroke="${color}" stroke-width="${thickness}" opacity="0.25"/>`;
    }).join('');

    // Client labels
    const cLabels = clientNodes.map(n =>
      `<text x="${leftX - 6}" y="${n.y + 3}" text-anchor="end" fill="${n.color}" class="flow-label">${this.esc(n.name)}</text>`
    ).join('');

    // Category labels
    const catLabels = catNodes.map(n =>
      `<text x="${rightX + 6}" y="${n.y + 3}" text-anchor="start" fill="var(--text-secondary)" class="flow-label">${this.esc(n.name)} <tspan fill="var(--text-muted)" font-size="9">${n.count}</tspan></text>`
    ).join('');

    // Client dots
    const cDots = clientNodes.map(n =>
      `<circle cx="${leftX}" cy="${n.y}" r="4" fill="${n.color}"/>`
    ).join('');

    // Category dots
    const catDots = catNodes.map(n =>
      `<circle cx="${rightX}" cy="${n.y}" r="4" fill="var(--text-muted)"/>`
    ).join('');

    container.innerHTML = `
      <svg class="flow-svg" viewBox="0 0 ${svgW} ${svgH}" preserveAspectRatio="xMidYMid meet">
        ${paths}${cDots}${catDots}${cLabels}${catLabels}
      </svg>`;
  }

  // ── Calendar ──

  _renderCalendar(container) {
    // Build 30-day calendar from memories
    const now = new Date();
    const days = [];
    for (let i = 29; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      const key = d.toISOString().slice(0, 10);
      days.push({ date: d, key, count: 0 });
    }

    const dayMap = {};
    days.forEach(d => { dayMap[d.key] = d; });

    (this.memories || []).forEach(m => {
      const key = (m.created_at || '').slice(0, 10);
      if (dayMap[key]) dayMap[key].count++;
    });

    const max = Math.max(1, ...days.map(d => d.count));

    const cells = days.map(d => {
      const opacity = d.count === 0 ? 0.08 : 0.2 + (d.count / max) * 0.8;
      const dayNum = d.date.getDate();
      const weekday = ['S', 'M', 'T', 'W', 'T', 'F', 'S'][d.date.getDay()];
      const isToday = d.key === now.toISOString().slice(0, 10);
      return `<div class="cal-cell${isToday ? ' cal-today' : ''}" title="${d.key}: ${d.count} memories">
        <span class="cal-day-label">${dayNum === 1 || d === days[0] ? d.date.toLocaleDateString('en', { month: 'short' }) : ''}</span>
        <span class="cal-block" style="opacity:${opacity}"></span>
        <span class="cal-weekday">${weekday}</span>
      </div>`;
    }).join('');

    container.innerHTML = `
      <div class="cal-strip">
        ${cells}
      </div>
      <div class="cal-legend">
        <span class="cal-legend-label">Less</span>
        ${[0.08, 0.3, 0.55, 0.8, 1].map(o => `<span class="cal-legend-block" style="opacity:${o}"></span>`).join('')}
        <span class="cal-legend-label">More</span>
      </div>
    `;
  }

  // ── Leaderboard ──

  _renderLeaderboard(container) {
    const breakdown = this.stats?.clients_breakdown || {};
    const clients = Object.entries(breakdown).sort((a, b) => b[1] - a[1]);
    const total = clients.reduce((s, [, c]) => s + c, 0) || 1;

    if (!clients.length) {
      container.innerHTML = '<div style="text-align:center;color:var(--text-muted);font-size:var(--text-xs);padding:var(--space-4)">No client data</div>';
      return;
    }

    const rows = clients.map(([client, count], i) => {
      const color = CLIENT_COLORS[client] || CLIENT_COLORS.unknown;
      const pct = ((count / total) * 100).toFixed(1);
      const rank = i + 1;
      const medal = rank === 1 ? '●' : rank === 2 ? '◐' : rank === 3 ? '○' : '';
      return `<div class="lb-row" style="--delay:${i * 60}ms">
        <span class="lb-rank">${medal || rank}</span>
        <span class="lb-dot" style="background:${color}"></span>
        <span class="lb-name">${this.esc(client)}</span>
        <div class="lb-bar-track">
          <div class="lb-bar-fill" style="width:${pct}%;background:${color}"></div>
        </div>
        <span class="lb-count">${count}</span>
        <span class="lb-pct">${pct}%</span>
      </div>`;
    }).join('');

    container.innerHTML = `<div class="lb-container">${rows}</div>`;
  }

  // ── Helpers ──

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
        ${m.client ? `<span class="dash-peek-client client-${m.client}">${this.esc(m.client)}</span>` : ''}
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
