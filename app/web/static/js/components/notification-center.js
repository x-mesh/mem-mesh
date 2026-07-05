/**
 * Global realtime notification center.
 *
 * Mounted ONCE on document.body (main.js), so memory/pin/relay events reach
 * the user on EVERY page — previously only the memories/dashboard pages
 * listened, so popups appeared page-dependently even though the WebSocket
 * was fine. Two surfaces:
 *
 *  - a toast per event (existing global toast util), and
 *  - a bell button + history panel (last 100 events with timestamps), which
 *    doubles as a debugging view: if an event reached this tab it is in the
 *    list, whether or not anyone saw the toast.
 *
 * Page components keep their own listeners for LIST updates (prepending rows
 * etc.) but should not also toast — this component owns user-facing popups.
 */
import { wsClient } from '../services/websocket-client.js';
import { showToast } from '../utils/toast-notifications.js';

const MAX_HISTORY = 100;

const EVENT_META = {
  memory_created: { icon: '🧠', label: 'Memory created', toast: 'success' },
  memory_updated: { icon: '✏️', label: 'Memory updated', toast: 'info' },
  memory_deleted: { icon: '🗑', label: 'Memory deleted', toast: 'warning' },
  pin_created: { icon: '📌', label: 'Pin created', toast: 'info' },
  pin_completed: { icon: '✅', label: 'Pin completed', toast: 'info' },
  pin_promoted: { icon: '⬆️', label: 'Pin promoted', toast: 'info' },
  relay_ingested: { icon: '📡', label: 'Relay received', toast: 'info' },
  relay_materialized: { icon: '📥', label: 'Relay memory added', toast: 'info' },
  overview_generated: { icon: '📋', label: 'Project overview updated', toast: 'info' },
  memory_enriched: { icon: '✨', label: 'Memory enriched', toast: 'info' },
};

export class NotificationCenter extends HTMLElement {
  connectedCallback() {
    this.items = [];
    this.unread = 0;
    this.open = false;
    this._handlers = {};
    this.innerHTML = this._template();
    this._wireEvents();
    this._subscribe();
    this._updateStatusDot(!!wsClient.isConnected);
  }

  disconnectedCallback() {
    Object.entries(this._handlers).forEach(([event, fn]) => wsClient.off(event, fn));
  }

  // ── WebSocket wiring ──────────────────────────────────────────────────────

  _subscribe() {
    Object.keys(EVENT_META).forEach((event) => {
      const fn = (data) => this._onEvent(event, data);
      this._handlers[event] = fn;
      wsClient.on(event, fn);
    });
    const onUp = () => this._updateStatusDot(true);
    const onDown = () => this._updateStatusDot(false);
    this._handlers.connection_established = onUp;
    this._handlers.reconnected = onUp;
    this._handlers.disconnected = onDown;
    wsClient.on('connection_established', onUp);
    wsClient.on('reconnected', onUp);
    wsClient.on('disconnected', onDown);
  }

  _onEvent(event, data) {
    const meta = EVENT_META[event];
    const detail = this._describe(event, data);
    const item = {
      event,
      icon: meta.icon,
      label: meta.label,
      detail: detail.text,
      href: detail.href,
      at: new Date(),
    };
    this.items.unshift(item);
    if (this.items.length > MAX_HISTORY) this.items.length = MAX_HISTORY;
    if (!this.open) {
      this.unread += 1;
      this._renderBadge();
    }
    if (this.open) this._renderList();
    showToast(`${meta.icon} ${meta.label}${detail.text ? ` — ${detail.text}` : ''}`, meta.toast, {
      duration: 4000,
    });
  }

  /** One-line human description + optional detail link for an event payload. */
  _describe(event, data) {
    const memory = data?.memory || {};
    const pin = data?.pin || {};
    const head = (s, n = 48) => {
      const line = String(s || '').split('\n').find((l) => l.trim()) || '';
      return line.length > n ? `${line.slice(0, n)}…` : line;
    };
    if (event.startsWith('memory_')) {
      const id = memory.id || data?.memory_id || '';
      const projId = memory.project_id || data?.project_id;
      const proj = projId ? ` (${projId})` : '';
      // memory_enriched sends a flat {memory_id, project_id, title} payload.
      const text = `${head(memory.title || data?.title || memory.content) || String(id).slice(0, 8)}${proj}`;
      return {
        text,
        href: event !== 'memory_deleted' && id ? `/memory/${encodeURIComponent(id)}` : null,
      };
    }
    if (event.startsWith('pin_')) {
      return { text: head(pin.content), href: null };
    }
    if (event.startsWith('relay_')) {
      const id = data?.memory_id || data?.current_memory_id || '';
      return {
        text: head(data?.title || data?.content) || String(id).slice(0, 8),
        href: event === 'relay_materialized' && id ? `/memory/${encodeURIComponent(id)}` : null,
      };
    }
    if (event === 'overview_generated') {
      const proj = data?.project_id || '';
      const n = data?.item_count;
      return {
        text: `${proj}${n != null ? ` · ${n} memories` : ''}`,
        href: proj
          ? `/memories?view=project&project_id=${encodeURIComponent(proj)}`
          : null,
      };
    }
    return { text: '', href: null };
  }

  // ── UI ────────────────────────────────────────────────────────────────────

  _template() {
    // Feather-style inline SVG (matches connection-status.js), not an emoji —
    // emoji render inconsistently across platforms and can't inherit color.
    return `
      <button class="nc-bell" title="Realtime notifications" aria-label="Notifications">
        <svg class="nc-bell-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
          <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
        </svg>
        <span class="nc-dot"></span><span class="nc-badge" hidden></span>
      </button>
      <div class="nc-panel" hidden>
        <div class="nc-head">
          <span>Notifications</span>
          <span class="nc-conn"></span>
          <button class="nc-clear" title="Clear history">Clear</button>
          <button class="nc-close" aria-label="Close">&times;</button>
        </div>
        <div class="nc-list"><div class="nc-empty">No events yet this session.</div></div>
      </div>`;
  }

  _wireEvents() {
    this.querySelector('.nc-bell').addEventListener('click', () => this._toggle());
    this.querySelector('.nc-close').addEventListener('click', () => this._toggle(false));
    this.querySelector('.nc-clear').addEventListener('click', () => {
      this.items = [];
      this._renderList();
    });
    this.querySelector('.nc-list').addEventListener('click', (e) => {
      const row = e.target.closest('.nc-item[data-href]');
      if (!row) return;
      const href = row.getAttribute('data-href');
      this._toggle(false);
      if (window.app?.router) window.app.router.navigate(href);
      else window.location.href = href;
    });
  }

  _toggle(force) {
    this.open = force !== undefined ? force : !this.open;
    this.querySelector('.nc-panel').hidden = !this.open;
    if (this.open) {
      this.unread = 0;
      this._renderBadge();
      this._renderList();
    }
  }

  _renderBadge() {
    const badge = this.querySelector('.nc-badge');
    badge.hidden = this.unread === 0;
    badge.textContent = this.unread > 99 ? '99+' : String(this.unread);
  }

  _updateStatusDot(connected) {
    this.querySelector('.nc-dot')?.classList.toggle('nc-dot-on', !!connected);
    const conn = this.querySelector('.nc-conn');
    if (conn) conn.textContent = connected ? '● live' : '○ offline';
    if (conn) conn.classList.toggle('nc-conn-on', !!connected);
  }

  _esc(s) {
    // Quotes included: _esc output lands in attribute values (data-href).
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  _renderList() {
    const list = this.querySelector('.nc-list');
    if (!this.items.length) {
      list.innerHTML = '<div class="nc-empty">No events yet this session.</div>';
      return;
    }
    list.innerHTML = this.items
      .map(
        (it) => `
        <div class="nc-item${it.href ? '' : ' nc-item-static'}"${it.href ? ` data-href="${this._esc(it.href)}"` : ''}>
          <span class="nc-item-icon">${it.icon}</span>
          <span class="nc-item-main">
            <span class="nc-item-label">${this._esc(it.label)}</span>
            ${it.detail ? `<span class="nc-item-detail">${this._esc(it.detail)}</span>` : ''}
          </span>
          <span class="nc-item-time">${it.at.toLocaleTimeString()}</span>
        </div>`
      )
      .join('');
  }
}

customElements.define('notification-center', NotificationCenter);

const style = document.createElement('style');
style.textContent = `
  notification-center {
    position: fixed;
    left: 18px;
    bottom: 18px;
    z-index: 2147483000;
  }
  notification-center .nc-bell {
    position: relative;
    display: flex; align-items: center; justify-content: center;
    width: 44px; height: 44px;
    border-radius: 50%;
    border: 1px solid var(--border-color);
    background: var(--bg-primary);
    color: var(--text-secondary, var(--text-muted));
    box-shadow: 0 2px 10px rgba(0,0,0,0.15);
    cursor: pointer;
    transition: color 0.15s ease, border-color 0.15s ease;
  }
  notification-center .nc-bell:hover { color: var(--text-primary); border-color: var(--text-muted); }
  notification-center .nc-bell-icon { width: 20px; height: 20px; }
  notification-center .nc-dot {
    position: absolute; right: 2px; top: 2px;
    width: 9px; height: 9px; border-radius: 50%;
    background: var(--text-muted);
  }
  notification-center .nc-dot-on { background: var(--success-color, #16a34a); }
  notification-center .nc-badge {
    position: absolute; left: -4px; top: -4px;
    min-width: 18px; height: 18px; padding: 0 4px;
    border-radius: 999px;
    background: var(--error-color, #ef4444);
    color: #fff; font-size: 0.68rem; line-height: 18px;
  }
  notification-center .nc-panel {
    position: absolute; left: 0; bottom: 54px;
    width: 340px; max-height: 60vh;
    display: flex; flex-direction: column;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    box-shadow: 0 8px 30px rgba(0,0,0,0.25);
    overflow: hidden;
  }
  /* The class selector above out-specifies the [hidden] UA rule (display:none),
     so toggling the hidden attribute did nothing — the X never closed the
     panel. This restores hidden's effect with matching specificity. */
  notification-center .nc-panel[hidden] { display: none; }
  notification-center .nc-head {
    display: flex; align-items: center; gap: 8px;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-color);
    font-weight: 600; font-size: 0.9rem;
    color: var(--text-primary);
  }
  notification-center .nc-conn { font-size: 0.72rem; color: var(--text-muted); }
  notification-center .nc-conn-on { color: var(--success-color, #16a34a); }
  notification-center .nc-clear {
    margin-left: auto;
    border: 1px solid var(--border-color); background: transparent;
    color: var(--text-muted); border-radius: 6px;
    font-size: 0.72rem; padding: 2px 8px; cursor: pointer;
  }
  notification-center .nc-close {
    border: none; background: transparent; cursor: pointer;
    color: var(--text-muted); font-size: 1.1rem; line-height: 1;
  }
  notification-center .nc-list { overflow-y: auto; }
  notification-center .nc-empty {
    padding: 18px 12px; color: var(--text-muted); font-size: 0.85rem;
  }
  notification-center .nc-item {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-color);
    cursor: pointer; font-size: 0.82rem;
  }
  notification-center .nc-item-static { cursor: default; }
  notification-center .nc-item:hover { background: var(--bg-tertiary); }
  notification-center .nc-item-main { display: flex; flex-direction: column; min-width: 0; flex: 1; }
  notification-center .nc-item-label { color: var(--text-primary); font-weight: 600; }
  notification-center .nc-item-detail {
    color: var(--text-muted);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  notification-center .nc-item-time { color: var(--text-muted); font-size: 0.72rem; white-space: nowrap; }
`;
document.head.appendChild(style);
