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
    this.init();
  }

  async init() {
    // Server URL default comes from the shared server config (env > db), not a
    // per-browser value — set once, shared by all users.
    try {
      const cfg = await this.fetchJSON('/api/connect/config');
      const input = this.querySelector('#cn-url');
      input.value = cfg.public_url || cfg.origin || window.location.origin;
      if (cfg.env_pinned) {
        input.disabled = true;
        const save = this.querySelector('#cn-save-url');
        if (save) save.disabled = true;
        const hint = this.querySelector('.cn-url-pinned');
        if (hint) hint.textContent = ' (pinned via MEM_MESH_PUBLIC_URL)';
      }
    } catch (e) {
      const input = this.querySelector('#cn-url');
      if (input) input.value = window.location.origin;
    }
    this.syncClientControls();
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
            <p class="page-subtitle">Copy-paste MCP and hook config with this server's URL and token already filled in.</p>
          </div>
        </header>

        <div class="cn-steps">
          <div class="cn-step"><span>1</span><strong>Confirm URL</strong></div>
          <div class="cn-step"><span>2</span><strong>Select client</strong></div>
          <div class="cn-step"><span>3</span><strong>Copy config</strong></div>
        </div>

        <div class="card">
          <div class="card-body">
            <div class="cn-controls">
              <label class="cn-url-label">Server URL <span class="hint">(shared — domain/proxy for all users<span class="cn-url-pinned"></span>)</span>
                <div class="cn-url-row">
                  <input type="text" id="cn-url" placeholder="https://your-host">
                  <button type="button" class="btn btn-sm btn-secondary" id="cn-save-url">Save for all</button>
                </div>
              </label>
              <label>Client
                <select id="cn-client">
                  <option value="codex">Codex (MCP + installer hooks)</option>
                  <option value="claude">Claude Code (hooks + MCP)</option>
                  <option value="cursor">Cursor (hooks + MCP)</option>
                  <option value="claude-desktop">Claude Desktop (MCP only)</option>
                  <option value="generic">Generic MCP client</option>
                </select>
              </label>
              <label>Hook mode <span class="hint" id="cn-hook-hint"></span>
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
    this.querySelector('#cn-client').addEventListener('change', () => {
      this.syncClientControls();
      this.load();
    });
    this.querySelector('#cn-hookmode').addEventListener('change', () => this.load());
    this.querySelector('#cn-mcpmode').addEventListener('change', () => this.load());

    // Server URL is shared (server-stored): change = local preview, Save = persist.
    this.querySelector('#cn-url').addEventListener('change', () => this.load());
    this.querySelector('#cn-save-url').addEventListener('click', () => this.savePublicUrl());
  }

  async savePublicUrl() {
    const url = (this.querySelector('#cn-url')?.value || '').trim();
    try {
      // Persist via the runtime-config write API (public_url is dashboard-settable).
      await this.fetchJSON('/api/security/auth', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ public_url: url }),
      });
      showToast(url ? 'Server URL saved for all users.' : 'Server URL cleared.', 'success');
      this.load();
    } catch (e) {
      showToast('Failed to save: ' + e.message, 'error');
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
    const meta = this.clientMeta(client);
    const hasHooks = meta.hooks === 'paste';

    try {
      const cards = [];
      if (meta.installTarget) {
        cards.push(this.quickInstallCard(meta, serverUrl || window.location.origin));
      }
      if (hasHooks) {
        const h = await this.fetchJSON(`/api/connect/hooks?client=${client}&mode=${hookMode}${q}`);
        this._hookData = h;
        cards.push(this.hookCard(h));
      } else {
        this._hookData = null;
      }
      const mcpClient = meta.mcpClient;
      const m = await this.fetchJSON(`/api/connect/mcp?client=${mcpClient}&mode=${mcpMode}${q}`);
      cards.push(this.mcpCard(m));
      out.innerHTML = cards.join('');
      this.bindCopies(out);
    } catch (e) {
      out.innerHTML = `<div class="error-message">Failed to generate: ${this.esc(e.message)}</div>`;
    }
  }

  clientMeta(client) {
    const clients = {
      codex: {
        mcpClient: 'codex',
        hooks: 'installer',
        hookTarget: 'codex',
        hookPath: '~/.codex/hooks.json',
        installTarget: 'codex',
      },
      claude: {
        mcpClient: 'claude-code',
        hooks: 'paste',
        hookTarget: 'claude',
        hookPath: '~/.claude/settings.json',
        installTarget: 'claude',
      },
      cursor: {
        mcpClient: 'cursor',
        hooks: 'paste',
        hookTarget: 'cursor',
      },
      'claude-desktop': {
        mcpClient: 'claude-desktop',
        hooks: 'none',
      },
      generic: {
        mcpClient: 'generic',
        hooks: 'none',
      },
    };
    return clients[client] || clients.generic;
  }

  syncClientControls() {
    const client = this.querySelector('#cn-client')?.value || 'codex';
    const meta = this.clientMeta(client);
    const hookMode = this.querySelector('#cn-hookmode');
    const hint = this.querySelector('#cn-hook-hint');
    if (!hookMode) return;
    hookMode.disabled = meta.hooks !== 'paste';
    if (hint) {
      hint.textContent =
        meta.hooks === 'paste'
          ? '(paste-ready)'
          : meta.hooks === 'installer'
            ? '(installer managed)'
            : '(MCP only)';
    }
  }

  quickInstallCard(meta, serverUrl) {
    const target = meta.hookTarget || 'codex';
    const path = meta.hookPath || 'client hook settings';
    const base = serverUrl.replace(/\/$/, '');
    const shortCommand = `curl -fsSL ${base}/${target} | bash`;
    const apiCommand = `curl -fsSL ${base}/api/connect/install/${target}.sh | bash`;
    return `
      <div class="card">
        <div class="card-header">
          <h2>One-line install → <code>${this.esc(path)}</code></h2>
          <button class="btn btn-sm btn-primary copy-install-command">Copy command</button>
        </div>
        <div class="card-body">
          <p class="hint">Installs this client on the machine where you run it. No local mem-mesh checkout is required; hooks call this server over HTTP.</p>
          <pre class="snippet"><code>${this.esc(shortCommand)}</code></pre>
          <p class="hint">Stable API endpoint: <code>${this.esc(apiCommand)}</code></p>
        </div>
      </div>`;
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
    // SSRF guard: Claude Code HTTP hooks reject private/VPN/LAN hosts. When the
    // server URL is blocked, steer to Command (api) mode instead of an http
    // config that fails at runtime.
    const blocked = h.http_hook_blocked
      ? `<p class="hint warn" style="border-left:3px solid #e5484d;padding-left:.6em">
           ⚠ HTTP hooks can't reach <code>${this.esc(h.server_url)}</code>: ${this.esc(h.http_hook_blocked)}
           <br>Switch <b>Hook mode → Command (api)</b> for this server.</p>`
      : '';
    // HTTP hooks read $MEM_MESH_HOOK_TOKEN from the shell (no file fallback), so
    // remind the user to export it or it is sent empty (401).
    const tokenHint =
      h.mode === 'http'
        ? `<p class="hint">HTTP hooks read the token from your shell — run <code>mem-mesh-hooks setup-token</code> so <code>${this.esc(h.hook_token_env)}</code> isn't sent empty.</p>`
        : '';
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
          ${blocked}
          <p class="hint">${this.esc(h.note)}</p>
          ${cliNote}
          ${tokenRow}
          ${tokenHint}
          <div class="cn-test-result"></div>
          <pre class="snippet"><code>${this.esc(json)}</code></pre>
        </div>
      </div>`;
  }

  mcpCard(m) {
    const format = m.config_format === 'toml' ? 'TOML' : 'JSON';
    const configText = m.config_text || JSON.stringify(m.config, null, 2);
    const oauthBlock = m.oauth ? this.mcpOAuthBlock(m.oauth, m) : '';
    return `
      <div class="card">
        <div class="card-header">
          <h2>MCP → <code>${this.esc(m.config_path)}</code></h2>
          <button class="btn btn-sm btn-primary copy-block">Copy ${format}</button>
        </div>
        <div class="card-body">
          <pre class="snippet"><code>${this.esc(configText)}</code></pre>
          ${oauthBlock}
        </div>
      </div>`;
  }

  mcpOAuthBlock(o, m) {
    const clients = o.clients || [];
    const clientList = clients.length
      ? `<div class="cn-clients"><span class="hint">Registered OAuth clients:</span>
           <ul>${clients
             .map(
               (c) =>
                 `<li><code>${this.esc(c.client_id)}</code> <span class="hint">${this.esc(c.client_name || '')}${
                   c.is_active === false ? ' · inactive' : ''
                 }</span></li>`
             )
             .join('')}</ul></div>`
      : '';

    // MCP auth OFF: making a client does NOT enable OAuth; the config works as-is.
    if (!o.enabled) {
      const warn = clients.length
        ? `<p class="hint warn"><strong>${clients.length} OAuth client(s) registered, but MCP auth is OFF</strong> — not enforced, so this config <strong>works as-is without auth</strong>. Making a client doesn't enable OAuth. <a href="/security" data-route="/security">Open Settings → Security</a> to require it.</p>`
        : `<p class="hint">MCP OAuth is off — clients connect without auth, so this config <strong>works as-is</strong> (fine for localhost/loopback). <a href="/security" data-route="/security">Open Settings → Security</a> if network-exposed.</p>`;
      return `<div class="cn-oauth">${warn}${clientList}</div>`;
    }

    // MCP auth ON: Claude Code does NOT auto-OAuth from the URL — the user must
    // Authenticate (CLI) or paste a bearer header. Spell that out so the pasted
    // block is actually usable.
    const endpoints = `<details class="cn-endpoints"><summary>OAuth endpoints</summary>
         <div class="cn-token">metadata: <code>${this.esc(o.metadata_url || '')}</code></div>
         <div class="cn-token">authorize: <code>${this.esc(o.authorize_url || '')}</code></div>
         <div class="cn-token">token: <code>${this.esc(o.token_url || '')}</code></div>
       </details>`;
    const env = (m && m.mcp_token_env) || 'MEM_MESH_HOOK_TOKEN';
    const tokenRow = m && m.mcp_token
      ? `<div class="cn-token">Set <code>${this.esc(env)}</code> = <code id="cn-mcptok">${this.esc(m.mcp_token)}</code> <button class="btn btn-sm copy-mcptok">Copy token</button></div>`
      : `<div class="cn-token">Token: <code>${this.esc((m && m.mcp_token_masked) || '')}</code> <span class="hint">(reveal requires dashboard login or local access)</span></div>`;
    return `<div class="cn-oauth">
         <p class="hint warn">MCP auth is enabled — the block above already includes a <code>headers</code> Bearer token, so it works as-is once the env var is set:</p>
         ${tokenRow}
         <p class="hint">The header reads <code>\${${this.esc(env)}}</code> — export that env where the client runs (jina-style), or paste the token inline. Prefer interactive OAuth instead? Remove the header and use Claude Code <code>/mcp</code> → Authenticate (endpoints below).</p>
         ${clients.length ? clientList : ''}
         ${endpoints}
         <div class="cn-actions">
           <button class="btn btn-sm btn-secondary cn-create-oauth">Register OAuth client</button>
           <a href="/security" class="btn btn-sm btn-secondary" data-route="/security">Open Settings → Security</a>
         </div>
         <div class="cn-oauth-result"></div>
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
    root.querySelectorAll('.copy-mcptok').forEach((b) =>
      b.addEventListener('click', () => {
        const el = this.querySelector('#cn-mcptok');
        if (el) this.copy(el.textContent);
      })
    );
    root.querySelectorAll('.cn-create-oauth').forEach((b) =>
      b.addEventListener('click', () => this.createOAuthClient(b))
    );
    root.querySelectorAll('.cn-test-hook').forEach((b) =>
      b.addEventListener('click', () => this.testHookAuth(b))
    );
    root.querySelectorAll('.copy-install-command').forEach((b) =>
      b.addEventListener('click', () => {
        const code = b.closest('.card')?.querySelector('pre code');
        if (code) this.copy(code.textContent);
      })
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
        .connect-page .card { background: var(--card-bg, #fff); border: 1px solid var(--border-color, #e5e5e5); border-radius: 8px; overflow: hidden; margin-bottom: 1.25rem; }
        .connect-page .card-header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 0.9rem 1.25rem; background: var(--card-header-bg, #f8f9fa); border-bottom: 1px solid var(--border-color, #e5e5e5); }
        .connect-page .card-header h2 { font-size: 1rem; margin: 0; font-weight: 600; }
        .connect-page .card-header code { background: var(--code-bg, #f1f3f5); padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.82em; }
        .connect-page .card-body { padding: 1.25rem; }
        .cn-controls { display: flex; flex-wrap: wrap; gap: 1.25rem; }
        .cn-controls label { display: flex; flex-direction: column; gap: 0.35rem; font-size: 0.82rem; color: var(--text-secondary, #525252); font-weight: 500; }
        .cn-controls select, .cn-controls input { padding: 0.5rem 0.7rem; border: 1px solid var(--border-color, #e5e5e5); border-radius: 8px; background: var(--bg-primary, #fff); color: var(--text-primary, #171717); font-size: 0.9rem; min-width: 220px; }
        .cn-controls select:disabled { opacity: 0.55; cursor: not-allowed; }
        .cn-url-label { flex: 1 1 320px; }
        .cn-url-row { display: flex; gap: 0.5rem; }
        .cn-url-row input { flex: 1; min-width: 0; box-sizing: border-box; }
        .cn-steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.75rem; margin-bottom: 1rem; }
        .cn-step { display: flex; align-items: center; gap: 0.55rem; padding: 0.65rem 0.75rem; background: var(--bg-secondary, #f8f9fa); border: 1px solid var(--border-color, #e5e5e5); border-radius: 8px; min-width: 0; }
        .cn-step span { display: inline-flex; align-items: center; justify-content: center; width: 1.35rem; height: 1.35rem; border-radius: 999px; background: var(--text-primary, #171717); color: var(--bg-primary, #fff); font-size: 0.75rem; font-weight: 700; flex-shrink: 0; }
        .cn-step strong { font-size: 0.86rem; color: var(--text-primary, #171717); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
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
        .cn-clients ul { margin: 0.4rem 0 0.8rem; padding-left: 1.2rem; }
        .cn-clients li { margin: 0.2rem 0; word-break: break-all; }
        .cn-endpoints { margin: 0.6rem 0; }
        .cn-endpoints summary { cursor: pointer; font-size: 0.85rem; color: var(--text-secondary, #666); }
        .cn-howto { margin: 0.4rem 0 0.8rem; padding-left: 1.2rem; font-size: 0.85rem; }
        .cn-howto li { margin: 0.3rem 0; }
        .cn-howto code { background: var(--code-bg, #f1f3f5); padding: 0.1rem 0.35rem; border-radius: 4px; }
        .connect-page .hint.warn { color: #856404; background: #fff3cd; padding: 0.5rem 0.7rem; border-radius: 6px; }
        .connect-page .btn-secondary { background: var(--secondary-bg, #e9ecef); color: var(--text-primary, #333); }
        .cn-actions { display: flex; gap: 0.5rem; }
        .cn-test-result { margin: 0.5rem 0; }
        .cn-test-row { font-size: 0.85rem; padding: 0.15rem 0; }
        @media (max-width: 720px) {
          .cn-steps { grid-template-columns: 1fr; }
          .cn-url-row { flex-direction: column; }
          .connect-page .card-header { align-items: flex-start; flex-direction: column; }
        }
      </style>
    `;
  }
}

customElements.define('connect-page', ConnectPage);
