/**
 * Settings Page — Linear-style redesign
 * Embedding management, rules, OAuth, info
 */

import { showToast } from '../utils/toast-notifications.js';

export class SettingsPage extends HTMLElement {
    constructor() {
        super();
        this.statusData = null;
        this.migrationInterval = null;
        this.rulesIndex = null;
        this.rulesMeta = null;
        this.rulesCache = new Map();
        this.progressErrorCount = 0;
    }

    connectedCallback() {
        this.render();
        this.bindEvents();
        this.loadSystemInfo();
        this.loadAccessStatus();
        this.loadStatus();
        this.loadRulesIndex();
        this.loadChatSettings();
        this.loadLlmRouting();
        this.loadWorkerConfig();
    }

    disconnectedCallback() {
        if (this.migrationInterval) {
            clearInterval(this.migrationInterval);
            this.migrationInterval = null;
        }
    }

    // ── Render ──

    render() {
        this.className = 'settings';

        this.innerHTML = `
      <div class="settings-toolbar">
        <span class="settings-title">Settings</span>
      </div>

      <!-- System Info -->
      <div class="settings-section">
        <div class="section-header">
          <span class="section-label">System</span>
        </div>
        <div class="section-body" id="system-info">
          <div class="settings-loading">
            <div class="settings-spinner"></div>
            <span>Loading system info...</span>
          </div>
        </div>
      </div>

      <!-- Client Setup & Security -->
      <div class="settings-section" id="settings-access">
        <div class="section-header">
          <span class="section-label">Client Setup &amp; Security</span>
        </div>
        <div class="section-body">
          <p class="section-desc">Connect AI clients, manage tokens, and control dashboard or MCP authentication.</p>
          <div class="data-actions settings-access-actions">
            <div class="data-action-row">
              <div class="data-action-info">
                <span class="data-action-title">Connect Clients</span>
                <span class="data-action-desc">Generate MCP and hook config for Codex, Claude Code, Cursor, and other MCP clients</span>
              </div>
              <a href="/connect" class="settings-btn-primary" data-route="/connect">Open Connect</a>
            </div>
            <div class="data-action-row">
              <div class="data-action-info">
                <span class="data-action-title">Security &amp; Tokens</span>
                <span class="data-action-desc">Reveal or rotate the hook token, enable web auth, and manage MCP OAuth clients</span>
              </div>
              <a href="/security" class="settings-btn" data-route="/security">Open Security</a>
            </div>
          </div>
          <div class="oauth-env settings-access-env">
            <div class="env-head">
              <span class="env-title">Server Environment Variables</span>
              <button class="section-action" id="refresh-access-btn" title="Refresh">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"/></svg>
              </button>
            </div>
            <div class="env-list" id="access-env-list">
              <div class="settings-loading"><div class="settings-spinner"></div><span>Loading status...</span></div>
            </div>
            <p class="env-foot"><span class="env-src env-src-env">env</span> set via <code>.env</code> (read-only here) &middot; <span class="env-src env-src-db">db</span> set from dashboard &middot; <span class="env-src env-src-default">default</span> unset. These reflect this <strong>server's</strong> configuration, not a client setting — clients no longer read these env vars: the hook token is baked into each tool's config and lives in <code>~/.mem-mesh/hook_token</code>. Toggle <strong>On/Off</strong> below to change auth (env-pinned rows are read-only); passwords &amp; OAuth clients are managed on the <a href="/security" data-route="/security">Security</a> page.</p>
          </div>
        </div>
      </div>

      <!-- Chat Assistant -->
      <div class="settings-section" id="settings-chat">
        <div class="section-header">
          <span class="section-label">Chat Assistant</span>
          <label class="chat-enable-toggle" title="Show the floating chat widget (requires a configured provider)">
            <input type="checkbox" id="chat-enabled">
            <span>Enabled</span>
          </label>
        </div>
        <div class="section-body">
          <p class="section-desc">Configure an OpenAI/Anthropic-compatible API for the dashboard chat assistant. The key is stored on the server and never returned to the browser. The floating widget appears only when a provider is configured and this is enabled.</p>
          <div class="chat-settings-grid">
            <label class="chat-field">
              <span>Provider</span>
              <select id="chat-provider">
                <option value="anthropic">anthropic</option>
                <option value="openai">openai</option>
              </select>
            </label>
            <label class="chat-field">
              <span>Model</span>
              <input id="chat-model" type="text" placeholder="provider default">
            </label>
            <label class="chat-field">
              <span>Output Language</span>
              <select id="chat-language">
                <option value="auto">Auto</option>
                <option value="korean">한국어</option>
                <option value="english">English</option>
              </select>
            </label>
            <label class="chat-field chat-field-wide">
              <span>API Key</span>
              <div class="chat-key-row">
                <input id="chat-api-key" type="password" autocomplete="new-password" placeholder="enter key to set">
                <button type="button" class="settings-btn" id="chat-key-toggle">Show</button>
              </div>
            </label>
            <label class="chat-field chat-field-wide">
              <span>Base URL</span>
              <input id="chat-base-url" type="url" placeholder="empty = provider default (e.g. https://api.groq.com/openai/v1)">
            </label>
          </div>
          <div class="chat-actions">
            <button class="settings-btn-primary" id="chat-save-btn">Save</button>
            <button class="settings-btn" id="chat-test-btn">Test</button>
            <span id="chat-settings-meta" class="env-foot"></span>
          </div>
        </div>
      </div>

      <!-- LLM Routing -->
      <div class="settings-section" id="settings-llm-routing">
        <div class="section-header">
          <span class="section-label">LLM Routing</span>
        </div>
        <div class="section-body">
          <p class="section-desc">relay and reconcile use the shared Chat LLM above by default. Switch to a per-service dedicated LLM when needed.</p>
          <p class="env-foot" id="llm-routing-chat-status"></p>
          ${this.renderLlmServiceBlock('relay', 'Relay')}
          ${this.renderLlmServiceBlock('reconcile', 'Reconcile')}
          <div class="chat-actions">
            <button class="settings-btn-primary" id="llm-routing-save-btn">Save LLM Routing</button>
            <span id="llm-routing-meta" class="env-foot"></span>
          </div>
        </div>
      </div>

      <!-- Worker -->
      <div class="settings-section" id="settings-worker">
        <div class="section-header">
          <span class="section-label">Worker</span>
        </div>
        <div class="section-body">
          <p class="section-desc">Which background tasks the relay worker runs. A task with missing config just waits until it's configured — the worker stays up.</p>
          <div class="chat-field worker-tasks-field">
            <span>Worker tasks</span>
            <div class="worker-task-list">
              <label class="worker-task"><input type="checkbox" id="worker-task-outbox"><span class="worker-task-name">outbox</span><span class="worker-task-desc">Sync memories to the team hub (needs a hub token — set on the Relay page)</span></label>
              <label class="worker-task"><input type="checkbox" id="worker-task-item"><span class="worker-task-name">item</span><span class="worker-task-desc">AI-enrich each memory (title, abstract, tags) — needs an LLM</span></label>
              <label class="worker-task"><input type="checkbox" id="worker-task-aggregate"><span class="worker-task-name">aggregate</span><span class="worker-task-desc">Generate per-project digests — needs an LLM</span></label>
              <label class="worker-task"><input type="checkbox" id="worker-task-reconcile"><span class="worker-task-name">reconcile</span><span class="worker-task-desc">Detect conflicting/duplicate memories for curation (also turns on write-time detection) — needs an LLM</span></label>
            </div>
          </div>
          <p class="env-foot" id="worker-hub-note"></p>
          <div class="chat-actions">
            <button class="settings-btn-primary" id="worker-save-btn">Save Worker Settings</button>
            <span id="worker-meta" class="env-foot"></span>
          </div>
        </div>
      </div>

      <!-- Embedding Status -->
      <div class="settings-section">
        <div class="section-header">
          <span class="section-label">Embedding Status</span>
          <div class="section-actions">
            <button class="section-action" id="change-model-btn" title="Change Embedding Model">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
              <span>Change Model</span>
            </button>
            <button class="section-action" id="refresh-status-btn" title="Refresh">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"/></svg>
            </button>
          </div>
        </div>
        <div class="section-body" id="embedding-status">
          <div class="settings-loading">
            <div class="settings-spinner"></div>
            <span>Loading status...</span>
          </div>
        </div>
      </div>

      <!-- Migration -->
      <div class="settings-section">
        <div class="section-header">
          <span class="section-label">Embedding Migration</span>
        </div>
        <div class="section-body">
          <p class="section-desc">Re-generate vector embeddings when the model changes or vectors need rebuilding.</p>
          <div class="migration-row">
            <label class="check-label">
              <input type="checkbox" id="force-migration">
              <span>Force (re-embed even if model matches)</span>
            </label>
            <div class="batch-group">
              <label for="batch-size">Batch</label>
              <input type="number" id="batch-size" class="settings-input" value="100" min="10" max="500">
            </div>
            <button id="start-migration-btn" class="settings-btn-primary">Start Migration</button>
          </div>
          <div id="migration-progress" class="mig-progress hidden">
            <div class="mig-bar-track"><div class="mig-bar-fill" id="progress-bar"></div></div>
            <div class="mig-stats" id="progress-stats"></div>
          </div>
        </div>
      </div>

      <!-- Data Management -->
      <div class="settings-section">
        <div class="section-header">
          <span class="section-label">Data Management</span>
        </div>
        <div class="section-body">
          <p class="section-desc">Export memories for backup or analysis.</p>
          <div class="data-actions">
            <div class="data-action-row">
              <div class="data-action-info">
                <span class="data-action-title">Export All Memories</span>
                <span class="data-action-desc">Download all memories as JSON</span>
              </div>
              <button id="export-json-btn" class="settings-btn">Export JSON</button>
            </div>
            <div class="data-action-row">
              <div class="data-action-info">
                <span class="data-action-title">Export as CSV</span>
                <span class="data-action-desc">Spreadsheet-compatible format</span>
              </div>
              <button id="export-csv-btn" class="settings-btn">Export CSV</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Rules Manager -->
      <div class="settings-section">
        <div class="section-header">
          <span class="section-label">Rules Manager</span>
          <button class="section-action" id="refresh-rules-btn" title="Refresh">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"/></svg>
          </button>
        </div>
        <div class="section-body">
          <p class="section-desc">Generate copy-ready hook rules from the same renderer used by <code>mem-mesh hooks rules</code>, or merge packaged rule modules.</p>
          <div class="rules-toolbar">
            <div class="rules-field">
              <label for="rules-project-id">Project ID</label>
              <input id="rules-project-id" class="settings-input" value="mem-mesh" autocomplete="off" spellcheck="false">
            </div>
            <div class="rules-field">
              <label for="rules-format-select">Output</label>
              <select id="rules-format-select" class="settings-select">
                <option value="plain">Plain hook rules</option>
                <option value="claude">CLAUDE.md managed block</option>
              </select>
            </div>
            <button id="generate-hook-rules-btn" class="settings-btn-primary">Generate Hook Rules</button>
            <button id="copy-rules-command-btn" class="settings-btn">Copy CLI Command</button>
          </div>
          <div class="rules-meta" id="rules-meta">Prompt version and output details will appear after rules load.</div>
          <div class="rules-grid">
            <div class="rules-col">
              <div class="rules-pane-head">
                <span class="rules-pane-title">Module Library</span>
                <span class="rules-pane-desc">Select modules for a manual bundle.</span>
              </div>
              <div class="rules-list" id="rules-list">
                <div class="settings-loading">
                  <div class="settings-spinner"></div>
                  <span>Loading rules...</span>
                </div>
              </div>
              <div class="rules-btns">
                <button id="merge-rules-btn" class="settings-btn">Merge Selected Modules</button>
                <button id="copy-rules-btn" class="settings-btn">Copy</button>
                <button id="download-rules-btn" class="settings-btn">Download</button>
              </div>
              <div class="rules-save-row">
                <select id="rules-target-select" class="settings-select"></select>
                <button id="save-rules-btn" class="settings-btn">Save to Module</button>
              </div>
            </div>
            <div class="rules-col">
              <div class="rules-pane-head">
                <span class="rules-pane-title">Output</span>
                <span class="rules-pane-desc" id="rules-output-stats">0 chars</span>
              </div>
              <textarea id="rules-output" class="rules-textarea" rows="14" placeholder="Generated hook rules or merged module output will appear here..."></textarea>
            </div>
          </div>
        </div>
      </div>

      <!-- Info (Accordion) -->
      <div class="settings-section">
        <div class="section-header">
          <span class="section-label">Information</span>
        </div>
        <div class="section-body settings-info">
          <details class="info-accordion">
            <summary class="info-summary">Embedding Models</summary>
            <div class="info-details">
              <p>Uses <code>sentence-transformers</code> for text-to-vector conversion.</p>
              <ul>
                <li><strong>all-MiniLM-L6-v2</strong> — Fast, lightweight English (384d)</li>
                <li><strong>intfloat/multilingual-e5-small</strong> — Multilingual (384d)</li>
              </ul>
            </div>
          </details>
          <details class="info-accordion">
            <summary class="info-summary">Migration</summary>
            <div class="info-details">
              <p>When the model changes, existing memories need re-embedding. Runs in batches with live progress.</p>
            </div>
          </details>
          <details class="info-accordion">
            <summary class="info-summary">Configuration</summary>
            <div class="info-details">
              <p>Set model via <code>MEM_MESH_EMBEDDING_MODEL</code> in <code>.env</code>.</p>
            </div>
          </details>
          <details class="info-accordion">
            <summary class="info-summary">API Documentation</summary>
            <div class="info-details">
              <p>Full API reference available at <a href="/docs" target="_blank" class="info-link">/docs</a> (OpenAPI/Swagger).</p>
            </div>
          </details>
        </div>
      </div>

      <!-- Danger Zone -->
      <div class="settings-section settings-danger">
        <div class="section-header">
          <span class="section-label">Danger Zone</span>
        </div>
        <div class="section-body">
          <div class="data-actions">
            <div class="data-action-row">
              <div class="data-action-info">
                <span class="data-action-title">Delete All Memories</span>
                <span class="data-action-desc">Permanently remove all memories. This cannot be undone.</span>
              </div>
              <button id="delete-all-btn" class="settings-btn-danger">Delete All</button>
            </div>
          </div>
        </div>
      </div>
    `;
    }

    bindEvents() {
        this.querySelector('#refresh-access-btn')?.addEventListener('click', () => this.loadAccessStatus());
        this.querySelector('#chat-save-btn')?.addEventListener('click', () => this.saveChatSettings());
        this.querySelector('#chat-test-btn')?.addEventListener('click', () => this.testChatConnection());
        this.querySelector('#chat-key-toggle')?.addEventListener('click', () => this.toggleChatKeyVisibility());
        this.querySelector('#chat-enabled')?.addEventListener('change', () => this.saveChatEnabled());
        this.querySelector('#llm-routing-save-btn')?.addEventListener('click', () => this.saveLlmRouting());
        this.querySelector('#relay-use-own')?.addEventListener('change', () => this.toggleLlmFields('relay'));
        this.querySelector('#reconcile-use-own')?.addEventListener('change', () => this.toggleLlmFields('reconcile'));
        this.querySelector('#worker-save-btn')?.addEventListener('click', () => this.saveWorkerConfig());
        this.querySelector('#refresh-status-btn')?.addEventListener('click', () => this.loadStatus());
        this.querySelector('#change-model-btn')?.addEventListener('click', () => {
            window.history.pushState({}, '', '/onboarding');
            window.dispatchEvent(new PopStateEvent('popstate'));
        });
        this.querySelector('#start-migration-btn')?.addEventListener('click', () => this.startMigration());
        this.querySelector('#refresh-rules-btn')?.addEventListener('click', () => this.loadRulesIndex({ refresh: true }));
        this.querySelector('#generate-hook-rules-btn')?.addEventListener('click', () => this.generateHookRules());
        this.querySelector('#copy-rules-command-btn')?.addEventListener('click', () => this.copyRulesCommand());
        this.querySelector('#rules-format-select')?.addEventListener('change', () => this.renderRulesCommandMeta());
        this.querySelector('#rules-project-id')?.addEventListener('input', () => this.renderRulesCommandMeta());
        this.querySelector('#rules-project-id')?.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') this.generateHookRules();
        });
        this.querySelector('#rules-output')?.addEventListener('input', () => this.updateRulesOutputStats());
        this.querySelector('#merge-rules-btn')?.addEventListener('click', () => this.mergeSelectedRules());
        this.querySelector('#copy-rules-btn')?.addEventListener('click', () => this.copyMergedRules());
        this.querySelector('#download-rules-btn')?.addEventListener('click', () => this.downloadMergedRules());
        this.querySelector('#save-rules-btn')?.addEventListener('click', () => this.saveMergedRules());
        this.querySelector('#export-json-btn')?.addEventListener('click', () => this.exportMemories('json'));
        this.querySelector('#export-csv-btn')?.addEventListener('click', () => this.exportMemories('csv'));
        this.querySelector('#delete-all-btn')?.addEventListener('click', () => this.deleteAllMemories());
    }

    // ── System Info ──

    async loadSystemInfo() {
        const el = this.querySelector('#system-info');
        if (!el) return;
        try {
            const info = await window.app.apiClient.get('/system/info');
            this.renderSystemInfo(el, info);
        } catch (error) {
            el.innerHTML = `<div class="settings-error">Failed to load system info</div>`;
        }
    }

    renderSystemInfo(container, info) {
        const formatBytes = (bytes) => {
            if (!bytes || bytes === 0) return '0 B';
            const units = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(1024));
            return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
        };

        container.innerHTML = `
      <div class="sysinfo-grid">
        <div class="sysinfo-item">
          <span class="sysinfo-label">Version</span>
          <span class="sysinfo-value sysinfo-version">${info.version}</span>
        </div>
        <div class="sysinfo-item">
          <span class="sysinfo-label">MCP Protocol</span>
          <span class="sysinfo-value">${info.mcp_protocol}</span>
        </div>
        <div class="sysinfo-item">
          <span class="sysinfo-label">Python</span>
          <span class="sysinfo-value">${info.python_version}</span>
        </div>
        <div class="sysinfo-item">
          <span class="sysinfo-label">SQLite</span>
          <span class="sysinfo-value">${info.sqlite_version}</span>
        </div>
        <div class="sysinfo-item">
          <span class="sysinfo-label">Platform</span>
          <span class="sysinfo-value">${info.platform} ${info.platform_version}</span>
        </div>
        <div class="sysinfo-item">
          <span class="sysinfo-label">DB Size</span>
          <span class="sysinfo-value">${formatBytes(info.db_size_bytes)}</span>
        </div>
        <div class="sysinfo-item">
          <span class="sysinfo-label">DB Path</span>
          <span class="sysinfo-value sysinfo-path">${info.db_path}</span>
        </div>
        <div class="sysinfo-item">
          <span class="sysinfo-label">PID</span>
          <span class="sysinfo-value">${info.pid}</span>
        </div>
      </div>
    `;
    }

    // ── Access & Security Status ──

    async fetchSecurityJSON(path) {
        // Direct fetch (not the cached APIClient): the security/connect endpoints
        // send Cache-Control: no-store and report live source/env-pin state.
        const res = await fetch(path, { headers: { Accept: 'application/json' } });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.message || data.detail || `HTTP ${res.status}`);
        return data;
    }

    // ── Chat Assistant settings ──

    async loadChatSettings() {
        const meta = this.querySelector('#chat-settings-meta');
        try {
            const data = await this.fetchSecurityJSON('/api/chat/v1/settings');
            this.applyChatSettings(data);
        } catch (error) {
            if (meta) meta.textContent = `Failed to load: ${error.message}`;
        }
    }

    applyChatSettings(data) {
        if (!data) return;
        const provider = this.querySelector('#chat-provider');
        if (provider) provider.value = (data.llm_provider && data.llm_provider.value) || 'anthropic';
        const model = this.querySelector('#chat-model');
        if (model) model.value = (data.llm_model && data.llm_model.value) || '';
        const baseUrl = this.querySelector('#chat-base-url');
        if (baseUrl) baseUrl.value = (data.llm_base_url && data.llm_base_url.value) || '';
        const language = this.querySelector('#chat-language');
        if (language) language.value = (data.output_language && data.output_language.value) || 'auto';
        const key = this.querySelector('#chat-api-key');
        const configured = data.llm_api_key && data.llm_api_key.configured;
        if (key) {
            key.value = '';
            key.placeholder = configured ? 'configured — enter new key to replace' : 'enter key to set';
        }
        const enabled = this.querySelector('#chat-enabled');
        if (enabled) enabled.checked = data.enabled !== false;
        const meta = this.querySelector('#chat-settings-meta');
        if (meta) {
            const src = (data.llm_provider && data.llm_provider.source) || 'default';
            const avail = data.available
                ? '<span class="env-src env-src-db">active</span>'
                : !configured
                  ? 'inactive (no key)'
                  : 'inactive (disabled)';
            meta.innerHTML = `provider <span class="env-src env-src-${src}">${src}</span> &middot; key ${configured ? 'configured' : 'not set'} &middot; widget ${avail}`;
        }
    }

    async saveChatEnabled() {
        const enabled = this.querySelector('#chat-enabled')?.checked ?? true;
        try {
            const res = await fetch('/api/chat/v1/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || data.message || `HTTP ${res.status}`);
            this.applyChatSettings(data);
            window.dispatchEvent(new CustomEvent('memmesh:chat-settings-changed'));
            showToast(enabled ? 'Chat assistant enabled.' : 'Chat assistant disabled.', 'success');
        } catch (error) {
            showToast(`Failed: ${error.message}`, 'error');
        }
    }

    async saveChatSettings() {
        const payload = {
            llm_provider: this.querySelector('#chat-provider')?.value || 'anthropic',
            llm_model: this.querySelector('#chat-model')?.value.trim() || '',
            llm_base_url: this.querySelector('#chat-base-url')?.value.trim() || '',
            output_language: this.querySelector('#chat-language')?.value || 'auto',
        };
        const key = this.querySelector('#chat-api-key')?.value.trim();
        if (key) payload.llm_api_key = key;
        const btn = this.querySelector('#chat-save-btn');
        if (btn) btn.disabled = true;
        try {
            const res = await fetch('/api/chat/v1/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || data.message || `HTTP ${res.status}`);
            this.applyChatSettings(data);
            window.dispatchEvent(new CustomEvent('memmesh:chat-settings-changed'));
            showToast('Chat settings saved.', 'success');
        } catch (error) {
            showToast(`Save failed: ${error.message}`, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    toggleChatKeyVisibility() {
        const input = this.querySelector('#chat-api-key');
        const btn = this.querySelector('#chat-key-toggle');
        if (!input) return;
        const reveal = input.type === 'password';
        input.type = reveal ? 'text' : 'password';
        if (btn) btn.textContent = reveal ? 'Hide' : 'Show';
    }

    async testChatConnection() {
        const btn = this.querySelector('#chat-test-btn');
        const meta = this.querySelector('#chat-settings-meta');
        if (btn) btn.disabled = true;
        if (meta) meta.textContent = 'Testing…';
        // Verify the values currently in the form (incl. a freshly typed key)
        // without saving; blanks fall back to the stored config server-side.
        const body = {
            provider: this.querySelector('#chat-provider')?.value || undefined,
            model: this.querySelector('#chat-model')?.value.trim() || undefined,
            base_url: this.querySelector('#chat-base-url')?.value.trim() || undefined,
        };
        const key = this.querySelector('#chat-api-key')?.value.trim();
        if (key) body.api_key = key;
        try {
            const res = await fetch('/api/chat/v1/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || data.message || `HTTP ${res.status}`);
            const sample = (data.sample || '').slice(0, 60);
            if (meta) meta.textContent = `OK — ${data.provider}/${data.model}${sample ? `: "${sample}"` : ''}`;
            showToast('Chat connection OK.', 'success');
        } catch (error) {
            if (meta) meta.textContent = `Test failed: ${error.message}`;
            showToast(`Chat test failed: ${error.message}`, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    // ── LLM Routing settings ──

    renderLlmServiceBlock(svc, label) {
        return `
      <div class="llm-svc" data-svc="${svc}">
        <div class="llm-svc-head">
          <span class="llm-svc-title">${label}</span>
          <label class="chat-enable-toggle" title="Use a dedicated LLM for ${label} (otherwise the shared Chat LLM)">
            <input type="checkbox" id="${svc}-use-own">
            <span>Use dedicated LLM</span>
          </label>
        </div>
        <div class="llm-svc-off" id="${svc}-llm-off">Using shared Chat LLM</div>
        <div class="chat-settings-grid llm-svc-fields" id="${svc}-llm-fields" hidden>
          <label class="chat-field">
            <span>Provider</span>
            <select id="${svc}-llm-provider">
              <option value="anthropic">anthropic</option>
              <option value="openai">openai</option>
            </select>
          </label>
          <label class="chat-field">
            <span>Model</span>
            <input id="${svc}-llm-model" type="text" placeholder="provider default">
          </label>
          <label class="chat-field chat-field-wide">
            <span>API Key</span>
            <input id="${svc}-llm-api-key" type="password" autocomplete="new-password" placeholder="enter key to set">
          </label>
          <label class="chat-field chat-field-wide">
            <span>Base URL</span>
            <input id="${svc}-llm-base-url" type="url" placeholder="empty = provider default">
          </label>
        </div>
      </div>`;
    }

    async loadLlmRouting() {
        const meta = this.querySelector('#llm-routing-meta');
        try {
            const data = await window.app.apiClient.get('/settings/llm-routing');
            this.applyLlmRouting(data);
        } catch (error) {
            if (meta) meta.textContent = `Failed to load: ${error.message}`;
        }
    }

    applyLlmRouting(data) {
        if (!data) return;
        const status = this.querySelector('#llm-routing-chat-status');
        if (status) {
            status.innerHTML = data.chat_configured
                ? '<span class="env-src env-src-db">Shared Chat LLM configured</span> Services without a dedicated LLM use the Chat settings above.'
                : '<span class="env-state off">Shared Chat LLM not configured</span> Set a key in Chat Assistant above, or configure a per-service dedicated LLM.';
        }
        ['relay', 'reconcile'].forEach((svc) => {
            const s = data[svc] || {};
            const toggle = this.querySelector(`#${svc}-use-own`);
            if (toggle) toggle.checked = s.use_own === true;
            const provider = this.querySelector(`#${svc}-llm-provider`);
            if (provider) provider.value = s.provider || 'anthropic';
            const model = this.querySelector(`#${svc}-llm-model`);
            if (model) model.value = s.model || '';
            const baseUrl = this.querySelector(`#${svc}-llm-base-url`);
            if (baseUrl) baseUrl.value = s.base_url || '';
            const key = this.querySelector(`#${svc}-llm-api-key`);
            if (key) {
                key.value = '';
                key.placeholder = s.api_key_configured ? 'configured — enter a new key to replace' : 'enter key to set';
            }
            this.toggleLlmFields(svc);
        });
    }

    toggleLlmFields(svc) {
        const on = this.querySelector(`#${svc}-use-own`)?.checked ?? false;
        const fields = this.querySelector(`#${svc}-llm-fields`);
        const off = this.querySelector(`#${svc}-llm-off`);
        if (fields) fields.hidden = !on;
        if (off) off.hidden = on;
    }

    async saveLlmRouting() {
        const payload = {};
        ['relay', 'reconcile'].forEach((svc) => {
            const block = { use_own: this.querySelector(`#${svc}-use-own`)?.checked ?? false };
            const provider = this.querySelector(`#${svc}-llm-provider`)?.value || '';
            if (provider) block.provider = provider;
            block.model = this.querySelector(`#${svc}-llm-model`)?.value.trim() || '';
            block.base_url = this.querySelector(`#${svc}-llm-base-url`)?.value.trim() || '';
            const key = this.querySelector(`#${svc}-llm-api-key`)?.value.trim();
            if (key) block.api_key = key;
            payload[svc] = block;
        });
        const btn = this.querySelector('#llm-routing-save-btn');
        if (btn) btn.disabled = true;
        try {
            await window.app.apiClient.put('/settings/llm-routing', payload);
            showToast('LLM routing saved.', 'success');
            await this.loadLlmRouting();
        } catch (error) {
            showToast(`Save failed: ${error.message}`, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    // ── Worker settings ──

    get workerTasks() {
        return ['outbox', 'item', 'aggregate', 'reconcile'];
    }

    async loadWorkerConfig() {
        const meta = this.querySelector('#worker-meta');
        try {
            const data = await window.app.apiClient.get('/settings/worker');
            this.applyWorkerConfig(data);
        } catch (error) {
            if (meta) meta.textContent = `Failed to load: ${error.message}`;
        }
    }

    applyWorkerConfig(data) {
        if (!data) return;
        const tasks = Array.isArray(data.worker_tasks) ? data.worker_tasks : [];
        this.workerTasks.forEach((task) => {
            const cb = this.querySelector(`#worker-task-${task}`);
            if (cb) cb.checked = tasks.includes(task);
        });
        // hub token lives on the Relay page — just surface its status here.
        const note = this.querySelector('#worker-hub-note');
        if (note) {
            note.innerHTML = data.hub_token_configured
                ? '<span class="env-src env-src-db">Hub token configured</span> outbox is ready. Manage it on the <a href="/relay" data-route="/relay">Relay page</a>.'
                : '<span class="env-state off">No hub token</span> outbox waits until you set one on the <a href="/relay" data-route="/relay">Relay page</a>.';
        }
    }

    async saveWorkerConfig() {
        const payload = {
            worker_tasks: this.workerTasks.filter(
                (task) => this.querySelector(`#worker-task-${task}`)?.checked,
            ),
        };
        const btn = this.querySelector('#worker-save-btn');
        if (btn) btn.disabled = true;
        try {
            await window.app.apiClient.put('/settings/worker', payload);
            showToast('Worker settings saved.', 'success');
            await this.loadWorkerConfig();
        } catch (error) {
            showToast(`Save failed: ${error.message}`, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async loadAccessStatus() {
        const el = this.querySelector('#access-env-list');
        if (!el) return;
        try {
            const [config, overview, connectCfg] = await Promise.all([
                this.fetchSecurityJSON('/api/security/config'),
                this.fetchSecurityJSON('/api/security/overview'),
                this.fetchSecurityJSON('/api/connect/config').catch(() => null),
            ]);
            this.renderAccessStatus(el, config, overview, connectCfg);
        } catch (error) {
            console.error('Failed to load security status:', error);
            el.innerHTML = `<div class="settings-error">Failed to load security status: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    renderAccessStatus(el, config, overview, connectCfg) {
        const auth = (config && config.auth) || {};
        const hook = (overview && overview.hook) || {};
        const bind = (overview && overview.bind) || {};
        const a = (k) => auth[k] || {};

        const srcBadge = (source, pinned) => {
            const s = source || 'default';
            const cls = s === 'env' ? 'env-src-env' : s === 'db' ? 'env-src-db' : 'env-src-default';
            return `<span class="env-src ${cls}" title="active source">${s}${pinned ? ' &#128274;' : ''}</span>`;
        };
        const onOff = (v) => v
            ? '<span class="env-state on">On</span>'
            : '<span class="env-state off">Off</span>';
        const setUnset = (v) => v
            ? '<span class="env-state on">Set</span>'
            : '<span class="env-state off">Not set</span>';
        const textVal = (v) => `<span class="env-state val">${this.escapeHtml(v || '(unset)')}</span>`;

        // hook source is env | data_file | legacy_file | none → collapse to a badge.
        const hookSrc = hook.source === 'env' ? 'env' : (hook.configured ? 'db' : 'default');

        const rows = [
            { name: 'MEM_MESH_HOOK_TOKEN', state: setUnset(hook.configured),
              src: srcBadge(hookSrc, hook.env_pinned), desc: 'Server bearer token (baked into client configs)' },
            { name: 'MEM_MESH_PUBLIC_URL',
              state: connectCfg && connectCfg.public_url ? textVal(connectCfg.public_url) : setUnset(false),
              src: srcBadge(connectCfg && connectCfg.source, connectCfg && connectCfg.env_pinned),
              desc: 'Shared URL used by Connect config' },
            { name: 'MEM_MESH_WEB_BASIC_AUTH_ENABLED', key: 'web_basic_auth_enabled', toggle: true,
              tval: !!a('web_basic_auth_enabled').value, pinned: !!a('web_basic_auth_enabled').env_pinned,
              src: srcBadge(a('web_basic_auth_enabled').source, a('web_basic_auth_enabled').env_pinned),
              desc: 'Dashboard login (Basic Auth)' },
            { name: 'MEM_MESH_ADMIN_USERNAME', state: textVal(a('admin_username').value),
              src: srcBadge(a('admin_username').source, a('admin_username').env_pinned),
              desc: 'Dashboard admin username' },
            { name: 'MEM_MESH_ADMIN_PASSWORD', state: setUnset(a('admin_password').value),
              src: srcBadge(a('admin_password').source, a('admin_password').env_pinned),
              desc: 'Dashboard admin password' },
            { name: 'MEM_MESH_AUTH_ENABLED', key: 'auth_enabled', toggle: true,
              tval: !!a('auth_enabled').value, pinned: !!a('auth_enabled').env_pinned,
              src: srcBadge(a('auth_enabled').source, a('auth_enabled').env_pinned),
              desc: 'Global OAuth (api + mcp)' },
            { name: 'MEM_MESH_MCP_AUTH_ENABLED', key: 'mcp_auth_enabled', toggle: true,
              tval: !!a('mcp_auth_enabled').value, pinned: !!a('mcp_auth_enabled').env_pinned,
              src: srcBadge(a('mcp_auth_enabled').source, a('mcp_auth_enabled').env_pinned),
              desc: 'MCP SSE OAuth' },
            { name: 'MEM_MESH_WEB_AUTH_ENABLED', key: 'web_auth_enabled', toggle: true,
              tval: !!a('web_auth_enabled').value, pinned: !!a('web_auth_enabled').env_pinned,
              src: srcBadge(a('web_auth_enabled').source, a('web_auth_enabled').env_pinned),
              desc: 'Web API OAuth' },
        ];

        const exposed = bind && bind.effective_host && !bind.is_loopback;
        const unguarded = !a('web_basic_auth_enabled').value && !a('web_auth_enabled').value;
        const warn = exposed && unguarded
            ? `<div class="env-warn">Dashboard is reachable on <code>${this.escapeHtml(bind.effective_host)}</code> without login. Enable Basic Auth on the <a href="/security" data-route="/security">Security</a> page, or restrict access with a firewall.</div>`
            : '';

        el.innerHTML = warn + rows.map((r) => {
            const stateHtml = r.toggle
                ? `<button class="env-toggle ${r.tval ? 'on' : 'off'}" data-key="${r.key}" data-next="${r.tval ? '0' : '1'}"${r.pinned ? ' disabled title="env-pinned — set via the environment, read-only here"' : ''}>${r.tval ? 'On' : 'Off'}</button>`
                : (r.state || '');
            return `
            <div class="env-item">
              <code>${r.name}</code>
              ${stateHtml}
              ${r.src}
              <span class="env-desc">${r.desc}</span>
            </div>`;
        }).join('');

        el.querySelectorAll('.env-toggle:not([disabled])').forEach((btn) => {
            btn.addEventListener('click', () =>
                this.toggleAuth(btn.dataset.key, btn.dataset.next === '1'));
        });
    }

    async toggleAuth(key, nextVal) {
        // Same backend as the Security page (PUT /api/security/auth); the server
        // enforces env-pinned skips and lockout guards (Basic Auth password,
        // OAuth-without-Basic-Auth). On rejection we surface the detail so the
        // user knows to set a password / enable Basic Auth on the Security page.
        try {
            const res = await fetch('/api/security/auth', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [key]: nextVal }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                window.alert(data.detail || `Failed to update ${key} (HTTP ${res.status})`);
                return;
            }
            const notices = data.notices || [];
            if (notices.length) window.alert(notices.join('\n\n'));
            this.loadAccessStatus();
        } catch (e) {
            window.alert('Request failed: ' + (e && e.message ? e.message : e));
        }
    }

    escapeHtml(text) {
        return (text == null ? '' : String(text))
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // ── Status ──

    async loadStatus() {
        const el = this.querySelector('#embedding-status');
        if (!el) return;

        el.innerHTML = `<div class="settings-loading"><div class="settings-spinner"></div><span>Loading status...</span></div>`;

        try {
            this.statusData = await window.app.apiClient.get('/embeddings/status');
            this.renderStatus(el);

            if (this.statusData.migration_in_progress) {
                this.startProgressPolling();
            }
        } catch (error) {
            console.error('Failed to load embedding status:', error);
            el.innerHTML = `<div class="settings-error">Failed to load status: ${error.message}</div>`;
        }
    }

    renderStatus(container) {
        const d = this.statusData;
        const ok = !d.needs_migration;
        const modelMatch = d.stored_model === d.current_model;
        const dimMatch = d.stored_dimension === d.current_dimension;
        const coverage = d.total_memories > 0 ? Math.round((d.vector_count / d.total_memories) * 100) : 100;
        const coverageOk = coverage >= 95;

        const indicator = (match) => match
            ? '<span class="status-indicator status-ok" title="Match">&#10003;</span>'
            : '<span class="status-indicator status-mismatch" title="Mismatch">&#9888;</span>';

        container.innerHTML = `
      <div class="status-overview">
        <div class="status-badge ${ok ? 'badge-ok' : 'badge-warn'}">
          ${ok ? 'Healthy' : 'Migration Needed'}
        </div>
      </div>
      <div class="status-grid">
        <div class="status-cell">
          <span class="status-label">DB Model ${indicator(modelMatch)}</span>
          <span class="status-value">${d.stored_model || '(not set)'}</span>
        </div>
        <div class="status-cell">
          <span class="status-label">Current Model</span>
          <span class="status-value status-highlight">${d.current_model}</span>
        </div>
        <div class="status-cell">
          <span class="status-label">Dimension ${indicator(dimMatch)}</span>
          <span class="status-value">${d.stored_dimension || '?'} / ${d.current_dimension}</span>
        </div>
        <div class="status-cell">
          <span class="status-label">Last Migration</span>
          <span class="status-value">${d.last_migration ? new Date(d.last_migration).toLocaleString() : '(never)'}</span>
        </div>
      </div>
      <div class="status-coverage">
        <div class="coverage-header">
          <span class="coverage-title">Vector Coverage</span>
          <span class="coverage-stats">${d.vector_count.toLocaleString()} / ${d.total_memories.toLocaleString()} memories</span>
          <span class="coverage-pct ${coverageOk ? '' : 'status-warn'}">${coverage}%</span>
        </div>
        <div class="coverage-bar-track">
          <div class="coverage-bar-fill ${coverageOk ? '' : 'coverage-warn'}" style="width:${coverage}%"></div>
        </div>
      </div>
    `;
    }

    // ── Migration ──

    async startMigration() {
        const force = this.querySelector('#force-migration')?.checked || false;
        const batchSize = parseInt(this.querySelector('#batch-size')?.value) || 100;
        const btn = this.querySelector('#start-migration-btn');
        const progressSection = this.querySelector('#migration-progress');

        if (!confirm('Start embedding migration? This may take some time.')) return;

        btn.disabled = true;
        btn.textContent = 'Starting...';
        progressSection.classList.remove('hidden');

        try {
            const result = await window.app.apiClient.post('/embeddings/migrate', null, { force, batch_size: batchSize });

            if (result.skipped) {
                showToast(result.message, 'info');
                btn.disabled = false;
                btn.textContent = 'Start Migration';
                progressSection.classList.add('hidden');
                return;
            }

            if (result.success || result.progress) {
                btn.textContent = 'Migrating...';
                this.startProgressPolling();
                showToast('Migration started.', 'info');
            } else if (result.error) {
                throw new Error(result.error);
            }
        } catch (error) {
            console.error('Migration error:', error);
            showToast(`Migration failed: ${error.message}`, 'error');
            btn.disabled = false;
            btn.textContent = 'Start Migration';
            progressSection.classList.add('hidden');
        }
    }

    startProgressPolling() {
        if (this.migrationInterval) clearInterval(this.migrationInterval);
        this.migrationInterval = setInterval(async () => { await this.updateProgress(); }, 1000);
    }

    async updateProgress() {
        try {
            const progress = await window.app.apiClient.get('/embeddings/migration/progress');
            this.renderProgress(progress);

            if (!progress.in_progress) {
                clearInterval(this.migrationInterval);
                this.migrationInterval = null;

                const btn = this.querySelector('#start-migration-btn');
                const progressSection = this.querySelector('#migration-progress');

                if (btn) { btn.disabled = false; btn.textContent = 'Start Migration'; }

                if (progress.status === 'completed') {
                    showToast('Migration completed.', 'success');
                    await this.loadStatus();
                    setTimeout(() => { if (progressSection) progressSection.classList.add('hidden'); }, 3000);
                } else if (progress.status === 'failed') {
                    showToast(`Migration failed: ${progress.message}`, 'error');
                    if (progressSection) progressSection.classList.add('hidden');
                }
            }
        } catch (error) {
            console.error('Progress update error:', error);
            this.progressErrorCount++;
            if (this.progressErrorCount >= 3) {
                clearInterval(this.migrationInterval);
                this.migrationInterval = null;
                this.progressErrorCount = 0;
                const btn = this.querySelector('#start-migration-btn');
                if (btn) { btn.disabled = false; btn.textContent = 'Start Migration'; }
                this.querySelector('#migration-progress')?.classList.add('hidden');
                showToast('Progress monitoring failed.', 'error');
            }
        }
    }

    renderProgress(progress) {
        const bar = this.querySelector('#progress-bar');
        const stats = this.querySelector('#progress-stats');
        const pct = progress.percent || 0;
        const processed = progress.processed || 0;
        const total = progress.total || 0;
        const failed = progress.failed || 0;
        const msg = progress.message || 'Initializing...';

        if (bar) bar.style.width = `${pct}%`;
        if (stats) {
            stats.innerHTML = `
        <span class="mig-stat"><span class="mig-stat-label">Progress</span><span>${pct}%</span></span>
        <span class="mig-stat"><span class="mig-stat-label">Processed</span><span>${processed.toLocaleString()} / ${total.toLocaleString()}</span></span>
        <span class="mig-stat"><span class="mig-stat-label">Failed</span><span class="${failed > 0 ? 'mig-stat-err' : ''}">${failed}</span></span>
        <span class="mig-stat"><span class="mig-stat-label">Status</span><span>${msg}</span></span>
      `;
        }
    }

    // ── Rules ──

    async loadRulesIndex({ refresh = false } = {}) {
        const el = this.querySelector('#rules-list');
        if (!el) return;

        el.innerHTML = `<div class="settings-loading"><div class="settings-spinner"></div><span>Loading rules...</span></div>`;

        try {
            if (refresh) {
                window.app.apiClient.invalidateCache('/rules');
                this.rulesCache.clear();
            }
            const data = await window.app.apiClient.get('/rules');
            this.rulesMeta = data.hook_rules || null;
            this.rulesIndex = data.rules || [];
            this.renderRulesCommandMeta();
            this.renderRulesList();
            this.renderRulesTargets();
            const out = this.querySelector('#rules-output');
            if (out && !out.value.trim()) {
                await this.generateHookRules({ silent: true });
            }
        } catch (error) {
            console.error('Failed to load rules index:', error);
            el.innerHTML = `<div class="settings-error">Failed to load rules: ${error.message}</div>`;
        }
    }

    renderRulesList() {
        const el = this.querySelector('#rules-list');
        if (!el) return;

        const modules = this.getRuleModules();
        if (modules.length === 0) {
            el.innerHTML = '<span class="section-desc">No rules available.</span>';
            return;
        }

        el.innerHTML = '';
        modules.forEach((rule) => {
            const item = document.createElement('label');
            item.className = 'rule-row';
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = rule.id;
            if (rule.id === 'core') { cb.checked = true; cb.disabled = true; }
            const name = document.createElement('span');
            name.className = 'rule-name';
            name.textContent = rule.title;
            const id = document.createElement('span');
            id.className = 'rule-id';
            id.textContent = rule.id;
            const kind = document.createElement('span');
            kind.className = 'rule-kind';
            kind.textContent = rule.kind || '';
            item.append(cb, name, id, kind);
            el.appendChild(item);
        });
    }

    renderRulesTargets() {
        const select = this.querySelector('#rules-target-select');
        if (!select) return;
        select.innerHTML = '';
        this.getRuleModules().forEach((rule) => {
            const opt = document.createElement('option');
            opt.value = rule.id;
            opt.textContent = `${rule.title} (${rule.id})`;
            select.appendChild(opt);
        });
    }

    getRuleModules() {
        return (this.rulesIndex || []).filter((rule) => rule.kind === 'module');
    }

    getSelectedRuleIds() {
        const boxes = this.querySelectorAll('#rules-list input[type="checkbox"]');
        const selected = Array.from(boxes).filter(c => c.checked).map(c => c.value);
        if (!selected.includes('core')) selected.unshift('core');
        return selected;
    }

    getRulesProjectId() {
        const input = this.querySelector('#rules-project-id');
        return (input?.value || 'mem-mesh').trim() || 'mem-mesh';
    }

    getRulesFormat() {
        return this.querySelector('#rules-format-select')?.value || 'plain';
    }

    shellArg(value) {
        const text = String(value || '');
        if (/^[A-Za-z0-9._/-]+$/.test(text)) return text;
        return "'" + text.replace(/'/g, "'\\''") + "'";
    }

    buildRulesCommand() {
        const projectId = this.getRulesProjectId();
        const format = this.getRulesFormat();
        return `mem-mesh hooks rules --project-id ${this.shellArg(projectId)} --format ${this.shellArg(format)}`;
    }

    renderRulesCommandMeta(extra = '') {
        const el = this.querySelector('#rules-meta');
        if (!el) return;
        const version = this.rulesMeta?.prompt_version ? `v${this.rulesMeta.prompt_version}` : 'version unknown';
        const command = this.buildRulesCommand();
        el.innerHTML = `
          <span class="rules-meta-pill">${this.escapeHtml(version)}</span>
          <code>${this.escapeHtml(command)}</code>
          ${extra ? `<span>${this.escapeHtml(extra)}</span>` : ''}
        `;
    }

    updateRulesOutputStats(payload = null) {
        const stats = this.querySelector('#rules-output-stats');
        const out = this.querySelector('#rules-output');
        if (!stats || !out) return;
        const content = out.value || '';
        const lines = content ? content.split('\n').length : 0;
        const suffix = payload
            ? `${payload.format} · ${payload.project_id} · prompt v${payload.prompt_version}`
            : `${content.length.toLocaleString()} chars · ${lines.toLocaleString()} lines`;
        stats.textContent = suffix;
    }

    async generateHookRules({ silent = false } = {}) {
        const out = this.querySelector('#rules-output');
        const btn = this.querySelector('#generate-hook-rules-btn');
        if (!out) return;

        const projectId = this.getRulesProjectId();
        const format = this.getRulesFormat();
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Generating...';
        }

        try {
            const payload = await window.app.apiClient.get('/rules/render', {
                project_id: projectId,
                format,
            });
            const projectInput = this.querySelector('#rules-project-id');
            if (projectInput && payload.project_id) projectInput.value = payload.project_id;
            out.value = `${payload.content || ''}\n`;
            this.renderRulesCommandMeta('Generated');
            this.updateRulesOutputStats(payload);
            if (!silent) showToast('Hook rules generated.', 'success');
        } catch (error) {
            console.error('Failed to generate hook rules:', error);
            if (!silent) showToast(`Generate failed: ${error.message}`, 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Generate Hook Rules';
            }
        }
    }

    async copyRulesCommand() {
        try {
            await navigator.clipboard.writeText(this.buildRulesCommand());
            showToast('CLI command copied.', 'success');
        } catch (error) {
            console.error('Command copy failed:', error);
            showToast('Command copy failed.', 'error');
        }
    }

    async fetchRuleContent(ruleId) {
        if (this.rulesCache.has(ruleId)) return this.rulesCache.get(ruleId);
        const data = await window.app.apiClient.get(`/rules/${encodeURIComponent(ruleId)}`);
        const content = data.content || '';
        this.rulesCache.set(ruleId, content);
        return content;
    }

    async mergeSelectedRules() {
        const ids = this.getSelectedRuleIds();
        if (ids.length === 0) { showToast('Select at least one rule.', 'warning'); return; }

        try {
            const parts = [];
            for (const id of ids) { parts.push((await this.fetchRuleContent(id)).trim()); }
            const merged = `${parts.join('\n\n---\n\n')}\n`;
            const out = this.querySelector('#rules-output');
            if (out) out.value = merged;
            this.renderRulesCommandMeta('Merged modules');
            this.updateRulesOutputStats();
            showToast('Rules merged.', 'success');
        } catch (error) {
            console.error('Failed to merge rules:', error);
            showToast(`Merge failed: ${error.message}`, 'error');
        }
    }

    async copyMergedRules() {
        const out = this.querySelector('#rules-output');
        if (!out || !out.value.trim()) { showToast('Nothing to copy.', 'warning'); return; }
        try {
            await navigator.clipboard.writeText(out.value);
            showToast('Copied to clipboard.', 'success');
        } catch (error) {
            console.error('Copy failed:', error);
            showToast('Copy failed.', 'error');
        }
    }

    downloadMergedRules() {
        const out = this.querySelector('#rules-output');
        if (!out || !out.value.trim()) { showToast('Nothing to download.', 'warning'); return; }
        const blob = new Blob([out.value], { type: 'text/markdown' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = 'rules-bundle.md';
        link.click();
        URL.revokeObjectURL(link.href);
    }

    async saveMergedRules() {
        const out = this.querySelector('#rules-output');
        const sel = this.querySelector('#rules-target-select');
        if (!out || !sel) return;
        const content = out.value.trim();
        if (!content) { showToast('Nothing to save.', 'warning'); return; }
        const ruleId = sel.value;
        try {
            await window.app.apiClient.put(`/rules/${encodeURIComponent(ruleId)}`, { content });
            showToast('Rules saved.', 'success');
            this.rulesCache.set(ruleId, content);
        } catch (error) {
            console.error('Save failed:', error);
            showToast(`Save failed: ${error.message}`, 'error');
        }
    }

    // ── Data Management ──

    async exportMemories(format) {
        const btn = this.querySelector(format === 'csv' ? '#export-csv-btn' : '#export-json-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Exporting...'; }

        try {
            const api = window.app.apiClient;
            // Fetch all memories via search with large limit
            const result = await api.get('/memories/search', { query: ' ', limit: 10000, recency_weight: 1.0 });
            const memories = result.results || [];

            if (memories.length === 0) {
                showToast('No memories to export.', 'warning');
                return;
            }

            let blob, filename;
            if (format === 'csv') {
                const headers = ['id', 'content', 'category', 'project_id', 'client', 'source', 'tags', 'created_at'];
                const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
                const rows = memories.map(m =>
                    headers.map(h => h === 'tags' ? escape((m.tags || []).join('; ')) : escape(m[h])).join(',')
                );
                const csv = [headers.join(','), ...rows].join('\n');
                blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
                filename = `mem-mesh-export-${new Date().toISOString().slice(0, 10)}.csv`;
            } else {
                const json = JSON.stringify(memories, null, 2);
                blob = new Blob([json], { type: 'application/json' });
                filename = `mem-mesh-export-${new Date().toISOString().slice(0, 10)}.json`;
            }

            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = filename;
            link.click();
            URL.revokeObjectURL(link.href);
            showToast(`Exported ${memories.length} memories.`, 'success');
        } catch (error) {
            console.error('Export failed:', error);
            showToast(`Export failed: ${error.message}`, 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = format === 'csv' ? 'Export CSV' : 'Export JSON'; }
        }
    }

    // ── Danger Zone ──

    async deleteAllMemories() {
        const count = this.statusData?.total_memories || '?';
        if (!confirm(`Delete ALL ${count} memories? This cannot be undone.`)) return;
        if (!confirm('Are you absolutely sure? Type the button again to confirm.')) return;

        const btn = this.querySelector('#delete-all-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Deleting...'; }

        try {
            const api = window.app.apiClient;
            // Fetch all memory IDs
            const result = await api.get('/memories/search', { query: ' ', limit: 10000, recency_weight: 1.0 });
            const memories = result.results || [];

            let deleted = 0;
            for (const m of memories) {
                try {
                    await api.delete(`/memories/${m.id}`);
                    deleted++;
                } catch (_) {}
            }

            showToast(`Deleted ${deleted} memories.`, 'success');
            await this.loadStatus();
        } catch (error) {
            console.error('Delete failed:', error);
            showToast(`Delete failed: ${error.message}`, 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = 'Delete All'; }
        }
    }
}

customElements.define('settings-page', SettingsPage);

// ── Scoped styles ──

const style = document.createElement('style');
style.textContent = `
/* ── Settings — Linear-style ── */

.settings {
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 60px);
  max-width: var(--container-xl, 1280px);
  margin: 0 auto;
  padding: 0 var(--space-4);
}

/* Toolbar */

.settings-toolbar {
  display: flex;
  align-items: center;
  padding: var(--space-4) 0 var(--space-2);
}

.settings-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

/* Sections */

.settings-section {
  margin-bottom: var(--space-3);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border-color);
}

.section-label {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-muted);
}

.section-action {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 80ms ease;
}

.section-action:hover {
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}

.section-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.section-action span {
  font-size: var(--text-xs);
  margin-left: 4px;
}

.section-action:has(span) {
  width: auto;
  padding: 0 8px;
}

.section-body {
  padding: var(--space-3);
}

.section-desc {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0 0 var(--space-3);
  line-height: 1.5;
}

/* System Info */

.sysinfo-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-2);
}

.sysinfo-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2);
  background: var(--bg-primary);
  border-radius: var(--radius-sm);
}

.sysinfo-label {
  font-size: 10px;
  font-weight: var(--font-medium);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.sysinfo-value {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  word-break: break-all;
}

.sysinfo-version {
  font-weight: var(--font-bold, 700);
  font-size: var(--text-base, 16px);
}

.sysinfo-path {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
}

/* Status grid */

.status-overview {
  margin-bottom: var(--space-3);
}

.status-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
}

.badge-ok {
  background: var(--bg-primary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
}

.badge-warn {
  background: var(--bg-primary);
  color: var(--text-muted);
  border: 1px solid var(--text-muted);
  font-style: italic;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.status-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2);
  background: var(--bg-primary);
  border-radius: var(--radius-sm);
}

.status-label {
  font-size: 10px;
  font-weight: var(--font-medium);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  display: flex;
  align-items: center;
  gap: 4px;
}

.status-value {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  word-break: break-all;
}

.status-highlight {
  font-weight: var(--font-bold, 700);
}

.status-warn {
  color: var(--text-muted);
  font-style: italic;
}

.status-indicator {
  font-size: 11px;
}

.status-ok {
  color: var(--text-primary);
}

.status-mismatch {
  color: var(--text-muted);
}

/* Coverage bar */

.status-coverage {
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-color);
}

.coverage-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: 6px;
}

.coverage-title {
  font-size: 10px;
  font-weight: var(--font-semibold);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.coverage-stats {
  flex: 1;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.coverage-pct {
  font-size: var(--text-sm);
  font-weight: var(--font-bold, 700);
  color: var(--text-primary);
}

.coverage-bar-track {
  height: 6px;
  background: var(--bg-tertiary);
  border-radius: 3px;
  overflow: hidden;
}

.coverage-bar-fill {
  height: 100%;
  background: var(--text-primary);
  border-radius: 3px;
  transition: width 400ms ease;
}

.coverage-warn {
  background: var(--text-muted);
}

/* Migration */

.migration-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.check-label {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  cursor: pointer;
}

.check-label input[type="checkbox"] {
  accent-color: var(--text-primary);
}

.batch-group {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.settings-input {
  width: 72px;
  padding: 3px var(--space-2);
  font-size: var(--text-xs);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
  color: var(--text-primary);
  outline: none;
}

.settings-input:focus {
  border-color: var(--text-muted);
}

/* Buttons */

.settings-btn-primary,
.settings-btn {
  padding: 4px var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 80ms ease;
  border: 1px solid transparent;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}

.settings-btn-primary {
  background: var(--text-primary);
  color: var(--bg-primary);
  border-color: var(--text-primary);
}

.settings-btn-primary:hover {
  opacity: 0.85;
}

.settings-btn-primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.settings-btn {
  background: transparent;
  color: var(--text-secondary);
  border-color: var(--border-color);
}

.settings-btn:hover {
  background: var(--bg-tertiary);
}

/* Chat assistant settings */

.chat-settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.chat-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.chat-field-wide {
  grid-column: 1 / -1;
}

.chat-field > span {
  font-size: 12px;
  color: var(--text-secondary);
}

.chat-field select,
.chat-field input {
  padding: 6px 8px;
  background: var(--bg-primary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font: inherit;
}

.chat-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.chat-actions .settings-btn-primary {
  width: auto;
  flex: 0 0 auto;
  padding: 6px 16px;
}

.chat-actions .env-foot {
  margin: 0;
}

.chat-key-row {
  display: flex;
  gap: var(--space-2);
  align-items: stretch;
}

.chat-key-row input {
  flex: 1 1 auto;
  min-width: 0;
}

.chat-key-row .settings-btn {
  flex: 0 0 auto;
  padding: 6px 12px;
}

.chat-enable-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
}

.chat-enable-toggle input {
  width: 14px;
  height: 14px;
}

@media (max-width: 640px) {
  .chat-settings-grid {
    grid-template-columns: 1fr;
  }
}

/* LLM routing */

.llm-svc {
  padding: var(--space-3) 0;
  border-top: 1px solid var(--border-color);
}

.llm-svc:first-of-type {
  border-top: none;
  padding-top: var(--space-2);
}

.llm-svc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

.llm-svc-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.llm-svc-off {
  font-size: 12px;
  color: var(--text-muted);
  padding: 4px 0;
}

.llm-svc-fields {
  margin-bottom: 0;
}

.llm-svc-fields[hidden] {
  display: none;
}

.llm-svc-fields select,
.llm-svc-fields input {
  background: var(--bg-primary);
  color: var(--text-primary);
}

/* Worker */

.worker-tasks-field {
  margin-bottom: var(--space-3);
}

.worker-tasks-field .migration-row {
  gap: var(--space-3);
}

/* Migration progress */

.mig-progress {
  margin-top: var(--space-3);
}

.mig-progress.hidden {
  display: none;
}

.mig-bar-track {
  height: 6px;
  background: var(--bg-tertiary);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: var(--space-2);
}

.mig-bar-fill {
  height: 100%;
  background: var(--text-secondary);
  border-radius: 3px;
  transition: width 300ms ease;
  width: 0%;
}

.mig-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-2);
}

.mig-stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
  font-size: var(--text-xs);
  color: var(--text-primary);
}

.mig-stat-label {
  font-size: 10px;
  color: var(--text-muted);
}

.mig-stat-err {
  font-weight: var(--font-semibold);
}

/* Rules */

.rules-toolbar {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr) auto auto;
  align-items: end;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.rules-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.rules-field label {
  font-size: 10px;
  font-weight: var(--font-semibold);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0;
}

.rules-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 26px;
  padding: 5px var(--space-2);
  margin-bottom: var(--space-2);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-secondary);
  color: var(--text-muted);
  font-size: var(--text-xs);
  overflow-x: auto;
}

.rules-meta code {
  color: var(--text-primary);
  white-space: nowrap;
}

.rules-meta-pill {
  flex-shrink: 0;
  padding: 1px 6px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: var(--font-semibold);
}

.rules-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.rules-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.rules-pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  min-height: 20px;
}

.rules-pane-title {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-secondary);
}

.rules-pane-desc {
  font-size: 10px;
  color: var(--text-muted);
}

.rules-list {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: var(--space-2);
  max-height: 280px;
  overflow-y: auto;
  background: var(--bg-primary);
}

.rule-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 3px var(--space-1);
  font-size: var(--text-xs);
  cursor: pointer;
  border-radius: 2px;
  transition: background 60ms ease;
}

.rule-row:hover {
  background: var(--bg-secondary);
}

.rule-row input[type="checkbox"] {
  accent-color: var(--text-primary);
  flex-shrink: 0;
}

.rule-name {
  color: var(--text-primary);
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rule-id {
  color: var(--text-muted);
  font-size: 10px;
  flex-shrink: 0;
}

.rule-kind {
  color: var(--text-muted);
  font-size: 10px;
  background: var(--bg-tertiary);
  padding: 0 4px;
  border-radius: 2px;
  flex-shrink: 0;
}

.rule-kind:empty {
  display: none;
}

.rules-btns {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}

.rules-save-row {
  display: flex;
  gap: var(--space-1);
}

.settings-select {
  flex: 1;
  padding: 3px var(--space-2);
  font-size: var(--text-xs);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
  color: var(--text-secondary);
  outline: none;
}

.rules-textarea {
  width: 100%;
  min-height: 240px;
  padding: var(--space-2);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: var(--text-xs);
  line-height: 1.5;
  resize: vertical;
}

.rules-textarea:focus {
  border-color: var(--text-muted);
  outline: none;
}

/* OAuth */

.oauth-row {
  margin-bottom: var(--space-3);
}

.oauth-env {
  border-top: 1px solid var(--border-color);
  padding-top: var(--space-2);
}

.settings-access-env {
  margin-top: var(--space-3);
}

.env-title {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-muted);
  display: block;
  margin-bottom: var(--space-1);
}

.env-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.env-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
}

.env-item code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  background: var(--bg-tertiary);
  padding: 1px 5px;
  border-radius: 2px;
  color: var(--text-primary);
  min-width: 250px;
  flex-shrink: 0;
}

.env-item span {
  color: var(--text-muted);
}

.env-item .env-toggle {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: var(--font-semibold);
  padding: 1px 8px;
  border-radius: 3px;
  border: 1px solid var(--border-color);
  cursor: pointer;
  font-family: inherit;
  background: transparent;
  color: var(--text-muted);
}

.env-item .env-toggle.on {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border-color: var(--text-secondary);
}

.env-item .env-toggle:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.env-item .env-toggle:not(:disabled):hover {
  border-color: var(--text-secondary);
}

/* Access status — head / footer */

.env-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-1);
}

.env-head .env-title {
  margin-bottom: 0;
}

.env-head .section-action {
  width: 24px;
  height: 24px;
}

.env-foot {
  margin-top: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-color);
  font-size: 10px;
  color: var(--text-muted);
  line-height: 1.7;
}

.env-foot code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
  background: var(--bg-tertiary);
  padding: 0 3px;
  border-radius: 2px;
}

.env-foot a {
  color: var(--text-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}

/* Access status — value & source badges */

.env-state {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: var(--font-semibold);
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid var(--border-color);
}

.env-item .env-state.on {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.env-item .env-state.off {
  background: transparent;
  color: var(--text-muted);
}

.env-item .env-state.val {
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-weight: var(--font-medium);
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.env-src {
  flex-shrink: 0;
  font-size: 9px;
  font-weight: var(--font-semibold);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 1px 5px;
  border-radius: 3px;
}

.env-src-env {
  background: #dbeafe;
  color: #1e40af;
}

.env-src-db {
  background: #dcfce7;
  color: #166534;
}

.env-src-default {
  background: var(--bg-tertiary);
  color: var(--text-muted);
}

.env-item .env-desc {
  margin-left: auto;
  text-align: right;
  color: var(--text-muted);
}

.env-warn {
  margin-bottom: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: #fff3cd;
  color: #856404;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  line-height: 1.5;
}

.env-warn code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  background: rgba(0, 0, 0, 0.06);
  padding: 0 3px;
  border-radius: 2px;
}

.env-warn a {
  color: #856404;
  font-weight: var(--font-semibold);
  text-decoration: underline;
}

/* Info */

.settings-info {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.info-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.info-heading {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.info-block p {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0;
  line-height: 1.5;
}

.info-block ul {
  margin: 0;
  padding-left: var(--space-4);
}

.info-block li {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-bottom: 2px;
}

.info-block code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  background: var(--bg-tertiary);
  padding: 1px 4px;
  border-radius: 2px;
}

/* Data Management */

.data-actions {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.data-action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2);
  background: var(--bg-primary);
  border-radius: var(--radius-sm);
  gap: var(--space-3);
}

.data-action-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.data-action-title {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.data-action-desc {
  font-size: 10px;
  color: var(--text-muted);
}

/* Info Accordion */

.info-accordion {
  border-bottom: 1px solid var(--border-color);
  padding-bottom: var(--space-2);
  margin-bottom: var(--space-2);
}

.info-accordion:last-child {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 0;
}

.info-summary {
  cursor: pointer;
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  padding: var(--space-1) 0;
  list-style: none;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.info-summary::-webkit-details-marker { display: none; }

.info-summary::before {
  content: '+';
  font-size: 14px;
  font-weight: 400;
  color: var(--text-muted);
  width: 16px;
  text-align: center;
  flex-shrink: 0;
}

details[open] .info-summary::before {
  content: '-';
}

.info-details {
  padding: var(--space-1) 0 0 calc(16px + var(--space-2));
}

.info-details p {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0 0 var(--space-1);
  line-height: 1.5;
}

.info-details ul {
  margin: 0;
  padding-left: var(--space-4);
}

.info-details li {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-bottom: 2px;
}

.info-details code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  background: var(--bg-tertiary);
  padding: 1px 4px;
  border-radius: 2px;
}

.info-link {
  color: var(--text-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.info-link:hover {
  color: var(--text-secondary);
}

/* Danger Zone */

.settings-danger {
  border-color: var(--text-muted);
}

.settings-danger .section-header {
  border-bottom-color: var(--text-muted);
}

.settings-danger .section-label {
  color: var(--text-muted);
}

.settings-btn-danger {
  padding: 4px var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 80ms ease;
  border: 1px solid var(--text-muted);
  background: transparent;
  color: var(--text-muted);
  flex-shrink: 0;
}

.settings-btn-danger:hover {
  background: var(--text-muted);
  color: var(--bg-primary);
}

.settings-btn-danger:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Loading & Error */

.settings-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-4);
  color: var(--text-muted);
  font-size: var(--text-xs);
}

.settings-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border-color);
  border-top-color: var(--text-secondary);
  border-radius: 50%;
  animation: settings-spin 0.8s linear infinite;
}

@keyframes settings-spin {
  to { transform: rotate(360deg); }
}

.settings-error {
  padding: var(--space-2) var(--space-3);
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
}

/* Responsive */

@media (max-width: 640px) {
  .settings {
    padding: 0 var(--space-3);
  }

  .sysinfo-grid {
    grid-template-columns: 1fr 1fr;
  }

  .status-grid {
    grid-template-columns: 1fr 1fr;
  }

  .mig-stats {
    grid-template-columns: 1fr 1fr;
  }

  .rules-toolbar {
    grid-template-columns: 1fr;
  }

  .rules-meta {
    align-items: flex-start;
    flex-direction: column;
  }

  .rules-grid {
    grid-template-columns: 1fr;
  }

  .migration-row {
    flex-direction: column;
    align-items: flex-start;
  }

  .data-action-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .env-item {
    flex-wrap: wrap;
  }

  .env-item code {
    min-width: 0;
  }

  .env-item .env-desc {
    margin-left: 0;
    width: 100%;
    text-align: left;
  }
}

@media (prefers-reduced-motion: reduce) {
  .settings-spinner {
    animation: none;
  }
}
`;

document.head.appendChild(style);
