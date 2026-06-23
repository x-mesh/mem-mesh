import { showToast } from '../utils/toast-notifications.js';
// MCP tab reuses the existing OAuth client manager (registers <oauth-page>).
import './oauth.js';

/**
 * Unified Security & Tokens page.
 *
 * Three tabs over the three independent auth mechanisms:
 *  - Hook Token  — /api/security/* (reveal/rotate the auto-generated secret)
 *  - Web Auth    — read-only status of Basic Auth / OAuth web auth
 *  - MCP OAuth   — embeds the existing <oauth-page> client manager
 *
 * Token reads go through direct fetch (not the cached APIClient) so a plaintext
 * secret is never retained in the GET cache.
 */
export class SecurityPage extends HTMLElement {
  constructor() {
    super();
    this.overview = null;
    this.revealedToken = null;
    this.activeTab = 'hook';
  }

  connectedCallback() {
    this.render();
    this.loadOverview();
  }

  async fetchJSON(path, opts = {}) {
    const res = await fetch(path, {
      headers: { Accept: 'application/json', ...(opts.headers || {}) },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      // The global HTTPException handler wraps errors as {error, message,
      // details}; raw FastAPI errors use {detail}. Prefer message, fall back.
      const err = new Error(data.message || data.detail || `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  render() {
    this.innerHTML = `
      <div class="security-page page-container">
        <header class="page-header">
          <div class="page-header-main">
            <h1 class="page-title">Security &amp; Tokens</h1>
            <p class="page-subtitle">Hook token, web dashboard auth, and MCP OAuth clients</p>
          </div>
        </header>

        <div class="sec-tabs">
          <button class="sec-tab active" data-tab="hook">API Token</button>
          <button class="sec-tab" data-tab="web">Web Dashboard Auth</button>
          <button class="sec-tab" data-tab="mcp">MCP OAuth</button>
        </div>

        <div class="sec-panel" data-panel="hook" id="panel-hook">
          <div class="loading-state"><div class="spinner"></div><p>Loading…</p></div>
        </div>
        <div class="sec-panel hidden" data-panel="web" id="panel-web"></div>
        <div class="sec-panel hidden" data-panel="mcp" id="panel-mcp"></div>
      </div>
      ${this.styles()}
    `;
    this.querySelectorAll('.sec-tab').forEach((btn) =>
      btn.addEventListener('click', () => this.switchTab(btn.dataset.tab))
    );
  }

  switchTab(tab) {
    this.activeTab = tab;
    this.querySelectorAll('.sec-tab').forEach((b) =>
      b.classList.toggle('active', b.dataset.tab === tab)
    );
    this.querySelectorAll('.sec-panel').forEach((p) =>
      p.classList.toggle('hidden', p.dataset.panel !== tab)
    );
    if (tab === 'mcp') this.mountMcp();
  }

  mountMcp() {
    const panel = this.querySelector('#panel-mcp');
    if (panel && !panel.querySelector('oauth-page')) {
      panel.appendChild(document.createElement('oauth-page'));
    }
  }

  async loadOverview() {
    try {
      const [overview, config, connectCfg] = await Promise.all([
        this.fetchJSON('/api/security/overview'),
        this.fetchJSON('/api/security/config'),
        // The URL the operator actually reaches (public_url > request origin),
        // NOT the server's bind address — mirrors the Connect page.
        this.fetchJSON('/api/connect/config').catch(() => null),
      ]);
      this.overview = overview;
      this.config = config;
      this.serverUrl =
        (connectCfg && (connectCfg.public_url || connectCfg.origin)) ||
        window.location.origin;
      // Reveal the plaintext token up front (for an authorized operator: loopback
      // / logged-in / OAuth) BEFORE the first render, so the token field and the
      // install snippet show the real value with no masked flash. It's
      // server-stored, so this never needs a regenerate. Mirrors Connect.
      if (overview.hook && overview.hook.can_reveal && !this.revealedToken) {
        try {
          const data = await this.fetchJSON('/api/security/hook/reveal');
          this.revealedToken = data.token;
        } catch {
          /* not allowed for this request — fall back to masked display */
        }
      }
      this.renderHookPanel();
      this.renderWebPanel();
    } catch (error) {
      const msg = `<div class="error-message">Failed to load security status: ${this.escapeHtml(error.message)}</div>`;
      const hp = this.querySelector('#panel-hook');
      const wp = this.querySelector('#panel-web');
      if (hp) hp.innerHTML = msg;
      if (wp) wp.innerHTML = msg;
    }
  }

  srcBadge(item) {
    if (!item) return '';
    const s = item.source || 'default';
    const cls = s === 'env' ? 'src-env' : s === 'db' ? 'src-db' : 'src-default';
    const lock = item.env_pinned ? ' &#128274;' : '';
    return `<span class="src-badge ${cls}" title="active source">${s}${lock}</span>`;
  }

  // ----- Hook token tab -------------------------------------------------

  renderHookPanel() {
    const panel = this.querySelector('#panel-hook');
    if (!panel || !this.overview) return;
    const hook = this.overview.hook;
    const tokenDisplay = this.revealedToken || hook.masked || '(none)';
    const sourceLabel = {
      env: 'Environment (.env)',
      data_file: 'Auto-generated (data dir)',
      legacy_file: 'Legacy file (~/.mem-mesh)',
      none: 'Not configured',
    }[hook.source] || hook.source;

    const serverUrl = this.serverUrl || window.location.origin;
    const snippetToken = this.revealedToken || '<HOOK_TOKEN>';

    panel.innerHTML = `
      <div class="card">
        <div class="card-header">
          <h2>API Token</h2>
          <span class="status-badge ${hook.configured ? 'active' : 'inactive'}">${hook.configured ? 'Configured' : 'Missing'}</span>
        </div>
        <div class="card-body">
          <p class="muted">Single static Bearer token for <strong>all programmatic access</strong> — hooks (<code>/api/hooks/claude/*</code>), MCP (<code>/mcp</code>), and the REST API (<code>/api</code>). One token, set as <code>MEM_MESH_HOOK_TOKEN</code> where clients run.</p>
          <p class="hint">Web dashboard login (password) and OAuth are separate — see the other tabs.</p>
          <p class="hint">Stored on the server — if you lose it, just reveal it here again. No need to regenerate (which would break every existing client).</p>

          <div class="kv"><span class="k">Source</span><span class="v">${this.escapeHtml(sourceLabel)}${hook.env_pinned ? ' <span class="pill">env-pinned</span>' : ''}</span></div>

          <div class="form-group">
            <label>Token</label>
            <div class="copy-field">
              <code id="hook-token-value">${this.escapeHtml(tokenDisplay)}</code>
              <button class="btn btn-sm btn-secondary" id="hook-reveal-btn" ${hook.can_reveal ? '' : 'disabled'}>${this.revealedToken ? 'Hide' : 'Reveal'}</button>
              <button class="btn btn-sm copy-btn" id="hook-copy-btn" ${this.revealedToken ? '' : 'disabled'}>Copy</button>
            </div>
            ${hook.can_reveal ? '' : '<p class="hint">Revealing requires an authenticated dashboard (Basic Auth / OAuth web auth) or a local request.</p>'}
          </div>

          <div class="actions">
            <button class="btn btn-danger" id="hook-regen-btn" ${hook.env_pinned ? 'disabled' : ''}>Regenerate</button>
            ${hook.env_pinned ? '<span class="hint">Pinned via MEM_MESH_HOOK_TOKEN; edit .env and restart to change.</span>' : '<span class="hint">Rotating invalidates all existing hook clients — reinstall them afterwards.</span>'}
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><h2>Install Snippet</h2></div>
        <div class="card-body info-content">
          <p class="muted">Claude Code HTTP hooks authenticate with this token:</p>
          <pre class="snippet"><code>curl -H "Authorization: Bearer ${this.escapeHtml(snippetToken)}" \\
  -X POST ${this.escapeHtml(serverUrl)}/api/hooks/claude/stop</code></pre>
          <p class="hint">The installer (<code>install_hooks</code>) wires this automatically via the <code>MEM_MESH_HOOK_TOKEN</code> env var; the secret is never written into settings.json.</p>
        </div>
      </div>
    `;

    panel.querySelector('#hook-reveal-btn')?.addEventListener('click', () => this.toggleReveal());
    panel.querySelector('#hook-copy-btn')?.addEventListener('click', () => this.copyToken());
    panel.querySelector('#hook-regen-btn')?.addEventListener('click', () => this.regenerate());
  }

  async toggleReveal() {
    if (this.revealedToken) {
      this.revealedToken = null;
      this.renderHookPanel();
      return;
    }
    try {
      const data = await this.fetchJSON('/api/security/hook/reveal');
      this.revealedToken = data.token;
      this.renderHookPanel();
    } catch (error) {
      showToast(`Cannot reveal token: ${error.message}`, 'error');
    }
  }

  async copyToken() {
    if (!this.revealedToken) return;
    try {
      await navigator.clipboard.writeText(this.revealedToken);
      showToast('Token copied to clipboard.', 'success');
    } catch {
      showToast('Failed to copy.', 'error');
    }
  }

  async regenerate() {
    if (!confirm('Regenerate the hook token?\nAll existing hook clients must be reinstalled with the new token.')) {
      return;
    }
    try {
      const data = await this.fetchJSON('/api/security/hook/regenerate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      this.revealedToken = data.token || null; // present only when reveal is allowed
      showToast('Hook token rotated. Reinstall hook clients.', 'success');
      await this.loadOverview();
      if (this.revealedToken) this.renderHookPanel();
    } catch (error) {
      showToast(`Failed to rotate: ${error.message}`, 'error');
    }
  }

  // ----- Web dashboard auth tab ----------------------------------------

  renderWebPanel() {
    const panel = this.querySelector('#panel-web');
    if (!panel || !this.config) return;
    const a = this.config.auth;
    const basic = a.web_basic_auth_enabled;
    const uname = a.admin_username;
    const pw = a.admin_password;
    const bind = this.overview ? this.overview.bind : { is_loopback: true };

    const basicPinned = basic.env_pinned;
    const editable = !basicPinned; // env-pinned => whole Basic Auth block read-only
    const dis = editable ? '' : 'disabled';

    const lockoutWarn =
      basic.value && !pw.value
        ? '<p class="hint warn">Basic Auth is on but no admin password is set — login will fail. Set one below (or MEM_MESH_ADMIN_PASSWORD).</p>'
        : '';
    const exposureWarn =
      !bind.is_loopback && !basic.value
        ? '<p class="hint warn">Dashboard is reachable on a non-loopback host without Basic Auth. Enable it here, or restrict access with a firewall.</p>'
        : '';
    const pinnedNote = basicPinned
      ? '<p class="hint">Pinned via environment variables — read-only here. Unset the <code>MEM_MESH_*</code> vars to edit from the dashboard.</p>'
      : '';

    const oa = a.auth_enabled;
    const oaMcp = a.mcp_auth_enabled;
    const oaWeb = a.web_auth_enabled;
    const oauthWarn =
      !basic.value && (oa.value || oaWeb.value)
        ? '<p class="hint warn">Basic Auth is off — turning OAuth on cuts the browser dashboard off from <code>/api</code>. Enable Basic Auth above first (in the same save).</p>'
        : '';
    const oauthPinnedNote =
      oa.env_pinned || oaMcp.env_pinned || oaWeb.env_pinned
        ? '<p class="hint">Some toggles are pinned via environment variables — read-only.</p>'
        : '';

    panel.innerHTML = `
      <div class="card">
        <div class="card-header">
          <h2>Web Dashboard Login (Basic Auth)</h2>
          ${this.srcBadge(basic)}
        </div>
        <div class="card-body">
          ${exposureWarn}${lockoutWarn}
          <div class="form-row">
            <label class="switch-row">
              <input type="checkbox" id="ba-enabled" ${basic.value ? 'checked' : ''} ${dis}>
              <span>Require login for the dashboard</span>
            </label>
          </div>
          <div class="form-group">
            <label>Admin username ${this.srcBadge(uname)}</label>
            <input type="text" id="ba-username" class="form-input" value="${this.escapeHtml(uname.value || 'admin')}" ${dis}>
          </div>
          <div class="form-group">
            <label>Admin password ${this.srcBadge(pw)}</label>
            <input type="password" id="ba-password" class="form-input" placeholder="${pw.value ? '•••••••• (set — type to change)' : 'set a password'}" ${dis}>
          </div>
          <div class="actions">
            <button class="btn btn-primary" id="ba-save" ${dis}>Save</button>
            <span class="hint">Enabling login takes effect immediately — the next page load will prompt for credentials.</span>
          </div>
          <p class="hint">Guards dashboard <strong>pages</strong> only. <code>/api</code>, <code>/mcp</code> and hooks keep their own auth (OAuth / hook token) and are never blocked by this login — enable OAuth web auth to protect the API itself.</p>
          ${pinnedNote}
        </div>
      </div>

      <details class="card oauth-advanced">
        <summary class="oauth-summary">
          <span class="oauth-summary-title">OAuth (MCP / Web API) — Advanced</span>
          <span class="hint">Optional — the API token already covers api &amp; mcp. Expand only for standard OAuth clients (dynamic registration, /mcp Authenticate).</span>
        </summary>
        <div class="card-body">
          <p class="muted">Protects <code>/api</code> and <code>/mcp</code> with OAuth bearer tokens (one shared scheme — manage clients in the <strong>MCP OAuth</strong> tab). The browser dashboard keeps access through its Basic Auth session.</p>
          ${oauthWarn}
          <div class="form-row"><label class="switch-row">
            <input type="checkbox" id="oa-enabled" ${oa.value ? 'checked' : ''} ${oa.env_pinned ? 'disabled' : ''}>
            <span>Global OAuth — <code>auth_enabled</code> (api + mcp)</span>
            ${this.srcBadge(oa)}
          </label></div>
          <div class="form-row"><label class="switch-row">
            <input type="checkbox" id="oa-mcp" ${oaMcp.value ? 'checked' : ''} ${oaMcp.env_pinned ? 'disabled' : ''}>
            <span>MCP SSE auth — <code>mcp_auth_enabled</code></span>
            ${this.srcBadge(oaMcp)}
          </label></div>
          <div class="form-row"><label class="switch-row">
            <input type="checkbox" id="oa-web" ${oaWeb.value ? 'checked' : ''} ${oaWeb.env_pinned ? 'disabled' : ''}>
            <span>Web API auth — <code>web_auth_enabled</code></span>
            ${this.srcBadge(oaWeb)}
          </label></div>
          <div class="actions">
            <button class="btn btn-primary" id="oa-save">Save</button>
            <span class="hint">Enabling OAuth requires Basic Auth on — the dashboard reaches <code>/api</code> via its login session.</span>
          </div>
          <div class="kv"><span class="k">Bind host</span><span class="v"><code>${this.escapeHtml(bind.effective_host || '')}</code> ${bind.is_loopback ? '<span class="pill">loopback</span>' : '<span class="pill warn-pill">exposed</span>'}</span></div>
          ${oauthPinnedNote}
        </div>
      </details>
    `;

    if (editable) {
      panel.querySelector('#ba-save')?.addEventListener('click', () => this.saveBasicAuth());
    }
    panel.querySelector('#oa-save')?.addEventListener('click', () => this.saveOAuth());
  }

  async saveOAuth() {
    const a = this.config.auth;
    const payload = {};
    // Only send keys that are not env-pinned (the server would skip them anyway).
    if (!a.auth_enabled.env_pinned) payload.auth_enabled = this.querySelector('#oa-enabled')?.checked;
    if (!a.mcp_auth_enabled.env_pinned) payload.mcp_auth_enabled = this.querySelector('#oa-mcp')?.checked;
    if (!a.web_auth_enabled.env_pinned) payload.web_auth_enabled = this.querySelector('#oa-web')?.checked;
    if (!Object.keys(payload).length) {
      showToast('All OAuth toggles are env-pinned (read-only).', 'warning');
      return;
    }
    try {
      const r = await this.fetchJSON('/api/security/auth', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const skipped = r.skipped && Object.keys(r.skipped).length ? r.skipped : null;
      if (skipped) showToast('Some keys skipped: ' + JSON.stringify(skipped), 'warning');
      showToast('OAuth settings saved.', 'success');
      await this.loadOverview();
    } catch (error) {
      // The server's lockout guard returns 400 with a clear message.
      showToast('Failed to save: ' + error.message, 'error');
    }
  }

  async saveBasicAuth() {
    const enabled = this.querySelector('#ba-enabled')?.checked;
    const username = (this.querySelector('#ba-username')?.value || '').trim();
    const password = this.querySelector('#ba-password')?.value || '';
    const payload = { web_basic_auth_enabled: enabled };
    if (username) payload.admin_username = username;
    if (password) payload.admin_password = password;
    try {
      const r = await this.fetchJSON('/api/security/auth', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const skipped = r.skipped && Object.keys(r.skipped).length ? r.skipped : null;
      if (skipped) showToast('Some keys skipped: ' + JSON.stringify(skipped), 'warning');
      if (enabled) {
        // Basic Auth is now active; this page itself needs a session. Go to the
        // login page instead of a doomed loadOverview() (which would 302 -> fail).
        showToast('Saved. Login required — redirecting…', 'success');
        setTimeout(() => {
          window.location.href = '/login?next=/security';
        }, 900);
        return;
      }
      showToast('Saved.', 'success');
      await this.loadOverview();
    } catch (error) {
      showToast('Failed to save: ' + error.message, 'error');
    }
  }

  badge(on, label) {
    const text = label || (on ? 'Enabled' : 'Disabled');
    return `<span class="status-badge ${on ? 'active' : 'inactive'}">${text}</span>`;
  }

  escapeHtml(text) {
    // Escapes both element- and attribute-context special chars (textContent
    // alone does not escape quotes, which would let admin_username break out of
    // a value="..." attribute).
    return (text == null ? '' : String(text))
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  styles() {
    return `
      <style>
        .security-page { width: 100%; }
        .security-page .page-header { margin-bottom: 1.25rem; }
        .sec-tabs { display: flex; gap: 0.25rem; border-bottom: 1px solid var(--border-color, #e0e0e0); margin-bottom: 1.5rem; }
        .sec-tab {
          background: none; border: none; padding: 0.65rem 1.1rem; cursor: pointer;
          font-size: 0.95rem; color: var(--text-secondary, #666);
          border-bottom: 2px solid transparent; transition: all 0.15s;
        }
        .sec-tab:hover { color: var(--text-primary, #171717); }
        .sec-tab.active { color: var(--text-primary, #171717); border-bottom-color: var(--accent-color, #4f46e5); font-weight: 600; }
        .sec-panel { display: flex; flex-direction: column; gap: 1.5rem; }
        .sec-panel.hidden { display: none; }

        .security-page .card { background: var(--card-bg, #fff); border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); overflow: hidden; }
        .security-page .card-header { display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.5rem; background: var(--card-header-bg, #f8f9fa); border-bottom: 1px solid var(--border-color, #e0e0e0); }
        .security-page .card-header h2 { font-size: 1.15rem; margin: 0; }
        .security-page .card-body { padding: 1.5rem; }
        .security-page .muted { color: var(--text-secondary, #666); margin-bottom: 1rem; }

        .kv { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0; border-bottom: 1px solid var(--border-color, #eee); }
        .kv:last-of-type { border-bottom: none; }
        .kv .k { color: var(--text-secondary, #666); font-size: 0.9rem; }
        .kv .v { font-size: 0.9rem; }

        .status-badge { display: inline-block; padding: 0.25rem 0.6rem; border-radius: 6px; font-size: 0.8rem; font-weight: 500; }
        .status-badge.active { background: #d4edda; color: #155724; }
        .status-badge.inactive { background: #f8d7da; color: #721c24; }
        .pill { display: inline-block; padding: 0.1rem 0.45rem; border-radius: 5px; font-size: 0.72rem; background: var(--secondary-bg, #e9ecef); color: var(--text-secondary, #555); }
        .warn-pill { background: #fff3cd; color: #856404; }

        .form-group { margin: 1.25rem 0; }
        .form-group label { display: block; margin-bottom: 0.5rem; font-weight: 500; }
        .copy-field { display: flex; align-items: center; gap: 0.5rem; background: var(--code-bg, #f1f3f5); padding: 0.5rem; border-radius: 6px; }
        .copy-field code { flex: 1; word-break: break-all; font-family: monospace; }

        .actions { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
        .hint { color: var(--text-secondary, #888); font-size: 0.82rem; margin: 0; }
        .hint.warn { color: #856404; background: #fff3cd; padding: 0.6rem 0.8rem; border-radius: 6px; margin-bottom: 1rem; }

        .snippet { background: var(--code-bg, #1e1e2e); color: var(--code-fg, #e0e0e0); padding: 1rem; border-radius: 8px; overflow-x: auto; font-size: 0.82rem; }
        .snippet code { font-family: monospace; white-space: pre; }
        .info-content code { background: var(--code-bg, #f1f3f5); padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.88em; }

        .btn { padding: 0.5rem 1rem; border: none; border-radius: 6px; cursor: pointer; font-size: 0.9rem; transition: all 0.2s; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-secondary { background: var(--secondary-bg, #e9ecef); color: var(--text-primary, #333); }
        .btn-secondary:hover:not(:disabled) { background: var(--secondary-hover, #dee2e6); }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover:not(:disabled) { background: #c82333; }
        .copy-btn { background: var(--secondary-bg, #e9ecef); color: var(--text-primary, #333); }
        .btn-sm { padding: 0.35rem 0.75rem; font-size: 0.85rem; }

        .loading-state { display: flex; flex-direction: column; align-items: center; padding: 2rem; color: var(--text-secondary, #666); }
        .spinner { width: 40px; height: 40px; border: 3px solid var(--border-color, #e0e0e0); border-top-color: var(--accent-color, #4f46e5); border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 1rem; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .error-message { background: #f8d7da; color: #721c24; padding: 1rem; border-radius: 8px; }

        .src-badge { display: inline-block; padding: 0.1rem 0.45rem; border-radius: 5px; font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.02em; }
        .src-env { background: #dbeafe; color: #1e40af; }
        .src-db { background: #dcfce7; color: #166534; }
        .src-default { background: var(--secondary-bg, #e9ecef); color: var(--text-secondary, #555); }
        .form-row { margin: 1rem 0; }
        .switch-row { display: flex; align-items: center; gap: 0.6rem; cursor: pointer; }
        .switch-row input { width: 18px; height: 18px; }
        .security-page input:disabled { opacity: 0.6; cursor: not-allowed; }
        .oauth-advanced { padding: 0; }
        .oauth-summary { cursor: pointer; padding: 0.9rem 1.25rem; display: flex; flex-direction: column; gap: 0.25rem; background: var(--card-header-bg, #f8f9fa); list-style: none; }
        .oauth-summary::-webkit-details-marker { display: none; }
        .oauth-summary::marker { content: ''; }
        .oauth-summary-title { font-size: 1.1rem; font-weight: 600; color: var(--text-primary, #171717); }
        .oauth-advanced[open] .oauth-summary { border-bottom: 1px solid var(--border-color, #e0e0e0); }
      </style>
    `;
  }
}

customElements.define('security-page', SecurityPage);
