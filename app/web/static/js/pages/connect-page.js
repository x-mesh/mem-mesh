import { showToast } from '../utils/toast-notifications.js';

/**
 * Connect page — generates copy-paste client config (hooks + MCP) with this
 * server's real URL and hook token filled in, so operators never hand-edit
 * URLs/tokens (the token-mismatch/wrong-URL class of errors that `doctor`
 * reports). Backed by GET /api/connect/{hooks,mcp}.
 */
export class ConnectPage extends HTMLElement {
  connectedCallback() {
    this.render();
    this.load();
  }

  async fetchJSON(path, opts = {}) {
    const res = await fetch(path, {
      headers: { Accept: 'application/json', ...(opts.headers || {}) },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.message || data.detail || `HTTP ${res.status}`);
    return data;
  }

  render() {
    this.innerHTML = `
      <div class="connect-page page-container">
        <header class="page-header">
          <div class="page-header-main">
            <h1 class="page-title">Connect a client</h1>
            <p class="page-subtitle">Copy-paste hook &amp; MCP config — this server's URL and token are filled in for you.</p>
          </div>
        </header>

        <div class="card">
          <div class="card-body">
            <div class="cn-controls">
              <label class="cn-url-label">Server URL <span class="hint">(domain/proxy — saved, applied to all snippets)</span>
                <input type="text" id="cn-url" placeholder="https://your-host">
              </label>
              <label>Client
                <select id="cn-client">
                  <option value="claude">Claude Code (hooks + MCP)</option>
                  <option value="cursor">Cursor (hooks + MCP)</option>
                  <option value="claude-desktop">Claude Desktop (MCP only)</option>
                  <option value="generic">Generic MCP client</option>
                </select>
              </label>
              <label>Hook mode
                <select id="cn-hookmode">
                  <option value="http">HTTP (native)</option>
                  <option value="api">API (curl)</option>
                </select>
              </label>
              <label>MCP transport
                <select id="cn-mcpmode">
                  <option value="http">HTTP (remote)</option>
                  <option value="uvx">uvx (local)</option>
                  <option value="stdio">stdio (local)</option>
                </select>
              </label>
            </div>
          </div>
        </div>

        <div id="cn-output"></div>
      </div>
      ${this.styles()}
    `;
    this.querySelector('#cn-client').addEventListener('change', () => this.load());
    this.querySelector('#cn-hookmode').addEventListener('change', () => this.load());
    this.querySelector('#cn-mcpmode').addEventListener('change', () => this.load());

    // Server URL persists across visits (same server == same public URL).
    const urlInput = this.querySelector('#cn-url');
    urlInput.value = this.savedUrl();
    urlInput.addEventListener('change', () => {
      const v = urlInput.value.trim();
      try {
        if (v) localStorage.setItem(ConnectPage.URL_KEY, v);
        else localStorage.removeItem(ConnectPage.URL_KEY);
      } catch (e) {}
      this.load();
    });
  }

  savedUrl() {
    try {
      return localStorage.getItem(ConnectPage.URL_KEY) || window.location.origin;
    } catch (e) {
      return window.location.origin;
    }
  }

  async load() {
    const out = this.querySelector('#cn-output');
    if (!out) return;
    out.innerHTML = '<div class="loading-state"><div class="spinner"></div><p>Generating…</p></div>';
    const client = this.querySelector('#cn-client').value;
    const hookMode = this.querySelector('#cn-hookmode').value;
    const mcpMode = this.querySelector('#cn-mcpmode').value;
    const serverUrl = (this.querySelector('#cn-url')?.value || '').trim();
    const q = serverUrl ? `&server_url=${encodeURIComponent(serverUrl)}` : '';
    const hasHooks = client === 'claude' || client === 'cursor';

    try {
      const cards = [];
      if (hasHooks) {
        const h = await this.fetchJSON(`/api/connect/hooks?client=${client}&mode=${hookMode}${q}`);
        this._hookData = h;
        cards.push(this.hookCard(h));
      } else {
        this._hookData = null;
      }
      const mcpClient = client === 'claude' ? 'claude-code' : client;
      const m = await this.fetchJSON(`/api/connect/mcp?client=${mcpClient}&mode=${mcpMode}${q}`);
      cards.push(this.mcpCard(m));
      out.innerHTML = cards.join('');
      this.bindCopies(out);
    } catch (e) {
      out.innerHTML = `<div class="error-message">Failed to generate: ${this.esc(e.message)}</div>`;
    }
  }

  hookCard(h) {
    const json = JSON.stringify(h.settings, null, 2);
    const tokenRow = h.hook_token
      ? `<div class="cn-token">Set <code>${this.esc(h.hook_token_env)}</code> = <code id="cn-tok">${this.esc(h.hook_token)}</code>
           <button class="btn btn-sm copy-token">Copy token</button></div>`
      : `<div class="cn-token">Hook token: <code>${this.esc(h.hook_token_masked)}</code>
           <span class="hint">(reveal requires dashboard login or local access)</span></div>`;
    const cliNote = h.paste_complete
      ? ''
      : `<p class="hint warn">Paste covers HTTP hooks only — command hooks also need shell scripts. For the full set: <code>mem-mesh-hooks install</code>.</p>`;
    return `
      <div class="card">
        <div class="card-header">
          <h2>Hooks → <code>${this.esc(h.settings_path)}</code></h2>
          <div class="cn-actions">
            <button class="btn btn-sm btn-secondary cn-test-hook">Test auth</button>
            <button class="btn btn-sm btn-primary copy-block">Copy JSON</button>
          </div>
        </div>
        <div class="card-body">
          <p class="hint">${this.esc(h.note)}</p>
          ${cliNote}
          ${tokenRow}
          <div class="cn-test-result"></div>
          <pre class="snippet"><code>${this.esc(json)}</code></pre>
        </div>
      </div>`;
  }

  mcpCard(m) {
    const json = JSON.stringify(m.config, null, 2);
    const oauthBlock = m.oauth_required
      ? `<div class="cn-oauth">
           <p class="hint warn">MCP OAuth is enabled — this client authenticates via OAuth. Register a client, then complete the flow on first connect.</p>
           <div class="cn-actions">
             <button class="btn btn-sm btn-secondary cn-create-oauth">Register OAuth client</button>
             <a href="/security" class="btn btn-sm btn-secondary" data-route="/security">Manage in Security →</a>
           </div>
           <div class="cn-oauth-result"></div>
         </div>`
      : `<div class="cn-oauth">
           <p class="hint">MCP OAuth is off — clients connect without auth. <a href="/security" data-route="/security">Enable it in Security →</a> if this server is network-exposed.</p>
         </div>`;
    return `
      <div class="card">
        <div class="card-header">
          <h2>MCP → <code>${this.esc(m.config_path)}</code></h2>
          <button class="btn btn-sm btn-primary copy-block">Copy JSON</button>
        </div>
        <div class="card-body">
          <pre class="snippet"><code>${this.esc(json)}</code></pre>
          ${oauthBlock}
        </div>
      </div>`;
  }

  bindCopies(root) {
    root.querySelectorAll('.copy-block').forEach((b) =>
      b.addEventListener('click', () => {
        const code = b.closest('.card')?.querySelector('pre code');
        if (code) this.copy(code.textContent);
      })
    );
    root.querySelectorAll('.copy-token').forEach((b) =>
      b.addEventListener('click', () => {
        const el = this.querySelector('#cn-tok');
        if (el) this.copy(el.textContent);
      })
    );
    root.querySelectorAll('.cn-create-oauth').forEach((b) =>
      b.addEventListener('click', () => this.createOAuthClient(b))
    );
    root.querySelectorAll('.cn-test-hook').forEach((b) =>
      b.addEventListener('click', () => this.testHookAuth(b))
    );
  }

  async testHookAuth(btn) {
    const result = btn.closest('.card')?.querySelector('.cn-test-result');
    const h = this._hookData;
    if (!h) return;
    const ep = `${h.server_url}/api/hooks/claude/session-start`;
    const ct = { 'Content-Type': 'application/json' };
    btn.disabled = true;
    if (result) result.innerHTML = '<span class="hint">Testing…</span>';
    try {
      const r1 = await fetch(ep, { method: 'POST', headers: ct, body: '{}' });
      let html = `<div class="cn-test-row">no-token → <strong>${r1.status}</strong> ${
        r1.status === 401 ? '✓ rejected' : '⚠ accepted (unauthenticated!)'
      }</div>`;
      if (h.hook_token) {
        const r2 = await fetch(ep, {
          method: 'POST',
          headers: { ...ct, Authorization: `Bearer ${h.hook_token}` },
          body: '{}',
        });
        html += `<div class="cn-test-row">with-token → <strong>${r2.status}</strong> ${
          r2.status !== 401 ? '✓ accepted' : '✗ rejected (token mismatch)'
        }</div>`;
      } else {
        html += `<div class="cn-test-row hint">with-token skipped — token not revealed</div>`;
      }
      if (result) result.innerHTML = html;
    } catch (e) {
      if (result) result.innerHTML = `<span class="error-message">Test failed: ${this.esc(e.message)}</span>`;
    } finally {
      btn.disabled = false;
    }
  }

  async createOAuthClient(btn) {
    const result = btn.closest('.cn-oauth')?.querySelector('.cn-oauth-result');
    btn.disabled = true;
    try {
      const r = await this.fetchJSON('/api/oauth/clients', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_name: 'MCP client (connect)',
          redirect_uris: [],
          scopes: ['read', 'write'],
          grant_types: ['authorization_code', 'refresh_token'],
        }),
      });
      if (result) {
        result.innerHTML = `
          <div class="cn-token">client_id: <code>${this.esc(r.client_id)}</code></div>
          <div class="cn-token">client_secret: <code>${this.esc(r.client_secret || '(public client)')}</code>
            <span class="hint">shown once — store it now</span></div>`;
      }
      showToast('OAuth client registered.', 'success');
    } catch (e) {
      btn.disabled = false;
      showToast('Failed to register: ' + e.message, 'error');
    }
  }

  async copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      showToast('Copied to clipboard.', 'success');
    } catch {
      showToast('Copy failed.', 'error');
    }
  }

  esc(t) {
    return (t == null ? '' : String(t))
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  styles() {
    return `
      <style>
        .connect-page { width: 100%; }
        .connect-page .page-header { margin-bottom: 1.25rem; }
        .connect-page .card { background: var(--card-bg, #fff); border: 1px solid var(--border-color, #e5e5e5); border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); overflow: hidden; margin-bottom: 1.25rem; }
        .connect-page .card-header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 0.9rem 1.25rem; background: var(--card-header-bg, #f8f9fa); border-bottom: 1px solid var(--border-color, #e5e5e5); }
        .connect-page .card-header h2 { font-size: 1rem; margin: 0; font-weight: 600; }
        .connect-page .card-header code { background: var(--code-bg, #f1f3f5); padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.82em; }
        .connect-page .card-body { padding: 1.25rem; }
        .cn-controls { display: flex; flex-wrap: wrap; gap: 1.25rem; }
        .cn-controls label { display: flex; flex-direction: column; gap: 0.35rem; font-size: 0.82rem; color: var(--text-secondary, #525252); font-weight: 500; }
        .cn-controls select, .cn-controls input { padding: 0.5rem 0.7rem; border: 1px solid var(--border-color, #e5e5e5); border-radius: 8px; background: var(--bg-primary, #fff); color: var(--text-primary, #171717); font-size: 0.9rem; min-width: 220px; }
        .cn-url-label { flex: 1 1 280px; }
        .cn-url-label input { width: 100%; box-sizing: border-box; }
        .cn-token { margin: 0.5rem 0 1rem; font-size: 0.88rem; display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
        .cn-token code { background: var(--code-bg, #f1f3f5); padding: 0.15rem 0.45rem; border-radius: 4px; word-break: break-all; }
        .snippet { background: var(--code-bg, #1e1e2e); color: var(--code-fg, #e0e0e0); padding: 1rem; border-radius: 8px; overflow-x: auto; font-size: 0.82rem; margin: 0; }
        .snippet code { font-family: 'SF Mono', Monaco, monospace; white-space: pre; }
        .hint { color: var(--text-secondary, #888); font-size: 0.82rem; margin: 0 0 0.5rem; }
        .connect-page .btn { padding: 0.4rem 0.85rem; border: none; border-radius: 7px; cursor: pointer; font-size: 0.85rem; }
        .connect-page .btn-primary { background: var(--text-primary, #171717); color: var(--bg-primary, #fff); }
        .connect-page .btn-primary:hover { opacity: 0.9; }
        .connect-page .btn-sm { font-size: 0.82rem; }
        .loading-state { display: flex; flex-direction: column; align-items: center; padding: 2rem; color: var(--text-secondary, #666); }
        .spinner { width: 36px; height: 36px; border: 3px solid var(--border-color, #e0e0e0); border-top-color: var(--accent-color, #4f46e5); border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 0.75rem; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .error-message { background: #f8d7da; color: #721c24; padding: 1rem; border-radius: 8px; }
        .cn-oauth { margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border-color, #e5e5e5); }
        .cn-oauth-result { margin-top: 0.6rem; }
        .connect-page .hint.warn { color: #856404; background: #fff3cd; padding: 0.5rem 0.7rem; border-radius: 6px; }
        .connect-page .btn-secondary { background: var(--secondary-bg, #e9ecef); color: var(--text-primary, #333); }
        .cn-actions { display: flex; gap: 0.5rem; }
        .cn-test-result { margin: 0.5rem 0; }
        .cn-test-row { font-size: 0.85rem; padding: 0.15rem 0; }
      </style>
    `;
  }
}

ConnectPage.URL_KEY = 'mem-mesh-connect-url';
customElements.define('connect-page', ConnectPage);
