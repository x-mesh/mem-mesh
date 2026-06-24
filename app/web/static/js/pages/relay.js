import { showToast } from '../utils/toast-notifications.js';

export class RelayPage extends HTMLElement {
  constructor() {
    super();
    this.overview = null;
    this.settings = null;
    this.activeTab = 'operations';
    this.limit = 10;
    this.loading = false;
  }

  connectedCallback() {
    this.render();
    this.loadOverview();
    this.loadSettings();
  }

  get api() {
    return window.app?.apiClient;
  }

  render() {
    this.className = 'relay-page page-container';
    this.innerHTML = `
      <header class="page-header">
        <div class="page-header-main">
          <h1 class="page-title">Relay</h1>
          <p class="page-subtitle">Team memory relay operations</p>
        </div>
        <div class="page-header-actions">
          <select id="relay-limit" class="secondary-button relay-select" aria-label="Recent row limit">
            <option value="10" selected>10 rows</option>
            <option value="25">25 rows</option>
            <option value="50">50 rows</option>
          </select>
          <button id="relay-refresh" class="secondary-button">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"/></svg>
            Refresh
          </button>
        </div>
      </header>

      <nav class="relay-tabs" aria-label="Relay sections">
        <button class="relay-tab active" data-tab="operations" type="button">Operations</button>
        <button class="relay-tab" data-tab="settings" type="button">Settings</button>
      </nav>

      <div class="relay-tab-panel" data-panel="operations">
        <section class="relay-summary" aria-label="Relay summary">
          ${this.renderSummarySkeleton()}
        </section>

        <section class="relay-grid">
          <form class="relay-panel relay-share-panel" id="relay-share-form">
          <div class="relay-panel-header">
            <h2>Share Memory</h2>
            <span class="relay-panel-meta">outbox</span>
          </div>
          <div class="relay-form-grid">
            <label class="relay-field">
              <span>Memory ID</span>
              <input id="share-memory-id" name="memory_id" type="text" autocomplete="off" required>
            </label>
            <label class="relay-field">
              <span>Source Node</span>
              <input id="share-source-node" name="source_node_id" type="text" autocomplete="off" required>
            </label>
            <label class="relay-field">
              <span>Version</span>
              <input id="share-source-version" name="source_version" type="number" min="0" value="1" required>
            </label>
            <label class="relay-field">
              <span>Event</span>
              <select id="share-event-type" name="event_type">
                <option value="update" selected>update</option>
                <option value="create">create</option>
                <option value="retract">retract</option>
              </select>
            </label>
            <label class="relay-field relay-field-wide">
              <span>Target Hub</span>
              <input id="share-target-hub" name="target_hub" type="url" autocomplete="off" required>
            </label>
          </div>
          <div class="relay-actions">
            <button class="primary-button" id="relay-share-submit" type="submit">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13"/><path d="M22 2L15 22L11 13L2 9L22 2Z"/></svg>
              Queue Share
            </button>
            <span id="relay-share-result" class="relay-inline-status" aria-live="polite"></span>
          </div>
          </form>

          <section class="relay-panel">
          <div class="relay-panel-header">
            <h2>Queue Status</h2>
            <span id="relay-generated-at" class="relay-panel-meta">-</span>
          </div>
          <div id="relay-queue-status" class="relay-status-stack">
            ${this.renderStatusSkeleton()}
          </div>
          </section>
        </section>

        <section class="relay-table-grid">
          <section class="relay-panel">
          <div class="relay-panel-header">
            <h2>Outbox</h2>
            <span class="relay-panel-meta">recent</span>
          </div>
          <div id="relay-outbox-table" class="relay-table-wrap">${this.renderTableSkeleton()}</div>
          </section>

          <section class="relay-panel">
          <div class="relay-panel-header">
            <h2>Workers</h2>
            <span class="relay-panel-meta">recent</span>
          </div>
          <div id="relay-queue-table" class="relay-table-wrap">${this.renderTableSkeleton()}</div>
          </section>
        </section>

        <section class="relay-panel">
          <div class="relay-panel-header">
            <h2>Digests</h2>
            <span class="relay-panel-meta">latest</span>
          </div>
          <div id="relay-digest-list" class="relay-digest-list">${this.renderTableSkeleton()}</div>
        </section>
      </div>

      <section class="relay-tab-panel hidden" data-panel="settings">
        ${this.renderSettingsSkeleton()}
      </section>
    `;

    this.setupEventListeners();
  }

  setupEventListeners() {
    this.querySelector('#relay-refresh')?.addEventListener('click', () => {
      this.loadOverview();
    });
    this.querySelector('#relay-limit')?.addEventListener('change', (event) => {
      this.limit = Number(event.target.value || 10);
      this.loadOverview();
    });
    this.querySelector('#relay-share-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      this.shareMemory();
    });
    this.querySelectorAll('.relay-tab').forEach((button) => {
      button.addEventListener('click', () => this.switchTab(button.dataset.tab));
    });
  }

  bindSettingsEvents() {
    this.querySelector('#relay-settings-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      this.saveSettings();
    });
    this.querySelector('#relay-identity-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      this.createIdentity();
    });
  }

  switchTab(tab) {
    if (!tab) return;
    this.activeTab = tab;
    this.querySelectorAll('.relay-tab').forEach((button) => {
      button.classList.toggle('active', button.dataset.tab === tab);
    });
    this.querySelectorAll('.relay-tab-panel').forEach((panel) => {
      panel.classList.toggle('hidden', panel.dataset.panel !== tab);
    });
    if (tab === 'settings' && !this.settings) {
      this.loadSettings();
    }
  }

  async loadOverview() {
    if (!this.api || this.loading) return;
    this.loading = true;
    this.setRefreshState(true);
    try {
      this.overview = await this.api.getRelayOverview(this.limit);
      this.renderOverview();
    } catch (error) {
      this.renderLoadError(error);
    } finally {
      this.loading = false;
      this.setRefreshState(false);
    }
  }

  async loadSettings() {
    if (!this.api) return;
    try {
      this.settings = await this.api.getRelaySettings();
      this.renderSettings();
      this.applyShareDefaults();
    } catch (error) {
      const panel = this.querySelector('[data-panel="settings"]');
      if (panel) {
        panel.innerHTML = `<div class="relay-error" role="alert">${this.escapeHtml(this.errorMessage(error))}</div>`;
      }
    }
  }

  async saveSettings() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-settings-submit');
    const hubUrlInput = this.querySelector('#relay-setting-hub-url');
    const sourceNodeInput = this.querySelector('#relay-setting-source-node');
    const payload = {
      default_source_version: Number(
        this.querySelector('#relay-setting-source-version')?.value || 1
      ),
    };
    if (hubUrlInput && !hubUrlInput.disabled) {
      payload.hub_url = hubUrlInput.value.trim();
    }
    if (sourceNodeInput && !sourceNodeInput.disabled) {
      payload.source_node_id = sourceNodeInput.value.trim();
    }
    submit.disabled = true;
    try {
      this.settings = await this.api.updateRelaySettings(payload);
      this.renderSettings();
      this.applyShareDefaults();
      showToast('Relay settings saved.', 'success');
    } catch (error) {
      showToast(`Relay settings failed: ${this.errorMessage(error)}`, 'error');
    } finally {
      submit.disabled = false;
    }
  }

  async createIdentity() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-identity-submit');
    const tokenMode = this.querySelector('#identity-token-mode')?.value || 'generate';
    const payload = {
      user_id: this.querySelector('#identity-user-id')?.value.trim(),
      source_node_id: this.querySelector('#identity-source-node')?.value.trim(),
      display_name: this.querySelector('#identity-display-name')?.value.trim(),
      home_domain: this.querySelector('#identity-home-domain')?.value.trim() || null,
      scopes: Array.from(this.querySelectorAll('[name="identity_scope"]:checked')).map(
        (item) => item.value
      ),
    };
    const manualToken = this.querySelector('#identity-token')?.value.trim();
    if (tokenMode === 'manual' && manualToken) {
      payload.token = manualToken;
    }
    if (!payload.user_id || !payload.source_node_id || !payload.display_name) {
      showToast('Identity fields are missing.', 'warning');
      return;
    }
    submit.disabled = true;
    try {
      const result = await this.api.createRelayIdentity(payload);
      await this.loadSettings();
      if (result.token) {
        this.showIssuedToken(result.token);
      }
      showToast('Relay identity registered.', 'success');
    } catch (error) {
      showToast(`Identity registration failed: ${this.errorMessage(error)}`, 'error');
    } finally {
      submit.disabled = false;
    }
  }

  async shareMemory() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-share-submit');
    const status = this.querySelector('#relay-share-result');
    const memoryId = this.querySelector('#share-memory-id')?.value.trim();
    const sourceNodeId = this.querySelector('#share-source-node')?.value.trim();
    const sourceVersion = Number(this.querySelector('#share-source-version')?.value || 0);
    const targetHub = this.querySelector('#share-target-hub')?.value.trim();
    const eventType = this.querySelector('#share-event-type')?.value || 'update';

    if (!memoryId || !sourceNodeId || !targetHub) {
      showToast('Required relay fields are missing.', 'warning');
      return;
    }

    submit.disabled = true;
    status.textContent = 'Queueing...';
    try {
      const result = await this.api.shareRelayMemory(memoryId, {
        source_node_id: sourceNodeId,
        source_version: sourceVersion,
        target_hub: targetHub,
        event_type: eventType,
      });
      status.textContent = `Queued ${result.outbox_id}`;
      showToast('Memory queued for relay.', 'success');
      await this.loadOverview();
    } catch (error) {
      const message = this.errorMessage(error);
      status.textContent = message;
      showToast(`Relay share failed: ${message}`, 'error');
    } finally {
      submit.disabled = false;
    }
  }

  renderOverview() {
    const data = this.overview;
    if (!data) return;

    this.querySelector('.relay-summary').innerHTML = `
      ${this.renderMetric('Outbox Pending', this.countFor(data.outbox_counts, 'pending'))}
      ${this.renderMetric('Item Queue', this.countFor(data.item_queue_counts, 'pending'))}
      ${this.renderMetric('Aggregate Queue', this.countFor(data.aggregate_queue_counts, 'pending'))}
      ${this.renderMetric('Visible Memories', data.visible_memories)}
      ${this.renderMetric('Enriched Items', data.enriched_items)}
      ${this.renderMetric('Projects', data.projects)}
    `;
    this.querySelector('#relay-generated-at').textContent = this.formatDate(data.generated_at);
    this.querySelector('#relay-queue-status').innerHTML = `
      ${this.renderStatusRow('Outbox', data.outbox_counts)}
      ${this.renderStatusRow('Item worker', data.item_queue_counts)}
      ${this.renderStatusRow('Aggregate worker', data.aggregate_queue_counts)}
      <div class="relay-status-row">
        <span class="relay-status-label">Raw events</span>
        <span class="relay-status-value">${data.raw_events.toLocaleString()}</span>
      </div>
    `;
    this.renderOutboxTable(data.recent_outbox);
    this.renderQueueTable(data.recent_queue);
    this.renderDigests(data.recent_digests);
  }

  renderSettings() {
    const data = this.settings;
    const panel = this.querySelector('[data-panel="settings"]');
    if (!data || !panel) return;

    panel.innerHTML = `
      <section class="relay-settings-grid">
        <form class="relay-panel" id="relay-settings-form">
          <div class="relay-panel-header">
            <h2>Personal Node Defaults</h2>
            <span class="relay-panel-meta">${this.formatDate(data.generated_at)}</span>
          </div>
          <div class="relay-form-grid">
            <label class="relay-field relay-field-wide">
              <span>Team Hub URL</span>
              <input
                id="relay-setting-hub-url"
                type="url"
                value="${this.escapeHtml(data.hub_url.value || '')}"
                ${data.hub_url.env_pinned ? 'disabled' : ''}
                placeholder="https://team-hub.example.com"
              >
              ${this.renderSettingHint(data.hub_url)}
            </label>
            <label class="relay-field">
              <span>Source Node ID</span>
              <input
                id="relay-setting-source-node"
                type="text"
                value="${this.escapeHtml(data.source_node_id.value || '')}"
                ${data.source_node_id.env_pinned ? 'disabled' : ''}
                placeholder="jinwoo-laptop"
              >
              ${this.renderSettingHint(data.source_node_id)}
            </label>
            <label class="relay-field">
              <span>Default Version</span>
              <input
                id="relay-setting-source-version"
                type="number"
                min="0"
                value="${Number(data.default_source_version || 1)}"
              >
            </label>
          </div>
          <div class="relay-actions">
            <button class="primary-button" id="relay-settings-submit" type="submit">Save Defaults</button>
            <span class="relay-inline-status">Used to prefill Share Memory.</span>
          </div>
        </form>

        <section class="relay-panel">
          <div class="relay-panel-header">
            <h2>Worker Environment</h2>
            <span class="relay-panel-meta">read-only</span>
          </div>
          <div class="relay-setting-list">
            ${this.renderSettingRow(data.hub_token)}
            ${this.renderSettingRow(data.sonnet_api_key)}
            ${this.renderSettingRow(data.sonnet_model)}
            ${this.renderSettingRow(data.sonnet_base_url)}
            ${this.renderSettingRow(data.prompt_version)}
          </div>
        </section>
      </section>

      <section class="relay-settings-grid">
        <form class="relay-panel" id="relay-identity-form">
          <div class="relay-panel-header">
            <h2>Hub Identity</h2>
            <span class="relay-panel-meta">team hub</span>
          </div>
          <div class="relay-form-grid">
            <label class="relay-field">
              <span>User ID</span>
              <input id="identity-user-id" type="text" autocomplete="off" required>
            </label>
            <label class="relay-field">
              <span>Source Node ID</span>
              <input id="identity-source-node" type="text" autocomplete="off" value="${this.escapeHtml(data.source_node_id.value || '')}" required>
            </label>
            <label class="relay-field">
              <span>Display Name</span>
              <input id="identity-display-name" type="text" autocomplete="off" required>
            </label>
            <label class="relay-field">
              <span>Home Domain</span>
              <input id="identity-home-domain" type="text" autocomplete="off" placeholder="local">
            </label>
            <label class="relay-field">
              <span>Token</span>
              <select id="identity-token-mode">
                <option value="generate" selected>generate</option>
                <option value="manual">manual</option>
              </select>
            </label>
            <label class="relay-field">
              <span>Manual Token</span>
              <input id="identity-token" type="password" autocomplete="new-password" placeholder="optional">
            </label>
            <div class="relay-scope-row relay-field-wide">
              <label><input type="checkbox" name="identity_scope" value="read" checked> read</label>
              <label><input type="checkbox" name="identity_scope" value="write" checked> write</label>
            </div>
          </div>
          <div class="relay-actions">
            <button class="primary-button" id="relay-identity-submit" type="submit">Register Identity</button>
            <span class="relay-inline-status">Generated token is shown once.</span>
          </div>
          <div id="relay-issued-token" class="relay-issued-token hidden"></div>
        </form>

        <section class="relay-panel">
          <div class="relay-panel-header">
            <h2>Registered Nodes</h2>
            <span class="relay-panel-meta">${data.identities.length} identities</span>
          </div>
          <div class="relay-table-wrap">
            ${this.renderIdentityTable(data.identities)}
          </div>
        </section>
      </section>
    `;

    this.bindSettingsEvents();
  }

  renderSettingRow(item) {
    const value = item.secret
      ? (item.configured ? 'configured' : 'missing')
      : (item.value || 'not set');
    return `
      <div class="relay-setting-row">
        <div>
          <span class="relay-setting-label">${this.escapeHtml(item.label)}</span>
          <code>${this.escapeHtml(item.env_var)}</code>
        </div>
        <div class="relay-setting-value">
          <span class="relay-status-chip ${item.configured ? 'status-completed' : 'status-pending'}">${this.escapeHtml(value)}</span>
          <span class="relay-panel-meta">${this.escapeHtml(item.source)}</span>
        </div>
      </div>
    `;
  }

  renderSettingHint(item) {
    return `
      <small class="relay-field-hint">
        ${this.escapeHtml(item.env_var)}
        ${item.env_pinned ? ' is set and overrides dashboard changes.' : ` source: ${item.source}`}
      </small>
    `;
  }

  renderIdentityTable(rows) {
    if (!rows?.length) {
      return this.renderEmpty('No relay identities');
    }
    return `
      <table class="relay-table">
        <thead>
          <tr>
            <th>Node</th>
            <th>User</th>
            <th>Scopes</th>
            <th>Token Hash</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              <td class="relay-ellipsis">${this.escapeHtml(row.source_node_id)}</td>
              <td>${this.escapeHtml(row.display_name)}<br><span class="relay-muted">${this.escapeHtml(row.user_id)}</span></td>
              <td>${row.scopes.map((scope) => `<span class="relay-status-chip">${this.escapeHtml(scope)}</span>`).join(' ')}</td>
              <td><code>${this.escapeHtml(row.token_hash_prefix)}</code></td>
              <td>${this.formatDate(row.updated_at)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }

  applyShareDefaults() {
    if (!this.settings) return;
    const sourceInput = this.querySelector('#share-source-node');
    const versionInput = this.querySelector('#share-source-version');
    const hubInput = this.querySelector('#share-target-hub');
    if (sourceInput && !sourceInput.value) {
      sourceInput.value = this.settings.source_node_id.value || '';
    }
    if (versionInput && (!versionInput.value || versionInput.value === '1')) {
      versionInput.value = this.settings.default_source_version || 1;
    }
    if (hubInput && !hubInput.value) {
      hubInput.value = this.settings.hub_url.value || '';
    }
  }

  showIssuedToken(token) {
    const target = this.querySelector('#relay-issued-token');
    if (!target) return;
    target.classList.remove('hidden');
    target.innerHTML = `
      <span>New token</span>
      <code>${this.escapeHtml(token)}</code>
      <button class="secondary-button" type="button" id="relay-copy-issued-token">Copy</button>
    `;
    target.querySelector('#relay-copy-issued-token')?.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(token);
        showToast('Relay token copied.', 'success');
      } catch {
        showToast('Copy failed.', 'error');
      }
    });
  }

  renderMetric(label, value) {
    return `
      <div class="relay-metric">
        <span class="relay-metric-label">${this.escapeHtml(label)}</span>
        <span class="relay-metric-value">${Number(value || 0).toLocaleString()}</span>
      </div>
    `;
  }

  renderStatusRow(label, counts) {
    const total = (counts || []).reduce((sum, item) => sum + item.count, 0);
    const chips = (counts || []).map((item) => `
      <span class="relay-status-chip ${this.statusClass(item.status)}">
        ${this.escapeHtml(item.status)}
        <strong>${item.count.toLocaleString()}</strong>
      </span>
    `).join('');
    return `
      <div class="relay-status-row">
        <span class="relay-status-label">${this.escapeHtml(label)}</span>
        <span class="relay-status-value">${total.toLocaleString()}</span>
        <span class="relay-status-chips">${chips || '<span class="relay-muted">empty</span>'}</span>
      </div>
    `;
  }

  renderOutboxTable(rows) {
    const target = this.querySelector('#relay-outbox-table');
    if (!target) return;
    if (!rows?.length) {
      target.innerHTML = this.renderEmpty('No outbox rows');
      return;
    }
    target.innerHTML = `
      <table class="relay-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Target</th>
            <th>Attempts</th>
            <th>Idempotency Key</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              <td><span class="relay-status-chip ${this.statusClass(row.status)}">${this.escapeHtml(row.status)}</span></td>
              <td class="relay-ellipsis">${this.escapeHtml(row.target_hub)}</td>
              <td>${row.attempts}</td>
              <td class="relay-ellipsis"><code>${this.escapeHtml(row.idempotency_key)}</code></td>
              <td>${this.formatDate(row.updated_at)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }

  renderQueueTable(rows) {
    const target = this.querySelector('#relay-queue-table');
    if (!target) return;
    if (!rows?.length) {
      target.innerHTML = this.renderEmpty('No worker queue rows');
      return;
    }
    target.innerHTML = `
      <table class="relay-table">
        <thead>
          <tr>
            <th>Queue</th>
            <th>Status</th>
            <th>Attempts</th>
            <th>Reference</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              <td>${this.escapeHtml(row.queue)}</td>
              <td><span class="relay-status-chip ${this.statusClass(row.status)}">${this.escapeHtml(row.status)}</span></td>
              <td>${row.attempts}</td>
              <td class="relay-ellipsis"><code>${this.escapeHtml(row.ref_id)}</code></td>
              <td>${this.formatDate(row.updated_at)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }

  renderDigests(rows) {
    const target = this.querySelector('#relay-digest-list');
    if (!target) return;
    if (!rows?.length) {
      target.innerHTML = this.renderEmpty('No project digests');
      return;
    }
    target.innerHTML = rows.map((row) => `
      <article class="relay-digest-row">
        <div class="relay-digest-main">
          <h3>${this.escapeHtml(row.team_project_id)}</h3>
          <p>${this.escapeHtml(row.narrative || 'No narrative')}</p>
        </div>
        <div class="relay-digest-meta">
          <span>${row.source_memory_count.toLocaleString()} sources</span>
          <span>${this.escapeHtml(row.model_version)}</span>
          <span>${this.formatDate(row.generated_at)}</span>
          ${row.stale ? '<span class="relay-status-chip warning">stale</span>' : ''}
        </div>
      </article>
    `).join('');
  }

  renderLoadError(error) {
    const message = this.errorMessage(error);
    this.querySelector('.relay-summary').innerHTML = `
      <div class="relay-error" role="alert">${this.escapeHtml(message)}</div>
    `;
    this.querySelector('#relay-queue-status').innerHTML = this.renderEmpty('Status unavailable');
    this.querySelector('#relay-outbox-table').innerHTML = this.renderEmpty('Outbox unavailable');
    this.querySelector('#relay-queue-table').innerHTML = this.renderEmpty('Worker queue unavailable');
    this.querySelector('#relay-digest-list').innerHTML = this.renderEmpty('Digests unavailable');
  }

  renderSummarySkeleton() {
    return Array.from({ length: 6 }, () => `
      <div class="relay-metric loading">
        <span class="relay-skeleton short"></span>
        <span class="relay-skeleton value"></span>
      </div>
    `).join('');
  }

  renderStatusSkeleton() {
    return Array.from({ length: 4 }, () => `
      <div class="relay-status-row">
        <span class="relay-skeleton short"></span>
        <span class="relay-skeleton value"></span>
      </div>
    `).join('');
  }

  renderTableSkeleton() {
    return `
      <div class="relay-skeleton-table">
        <span class="relay-skeleton"></span>
        <span class="relay-skeleton"></span>
        <span class="relay-skeleton"></span>
      </div>
    `;
  }

  renderSettingsSkeleton() {
    return `
      <section class="relay-settings-grid">
        <div class="relay-panel">${this.renderTableSkeleton()}</div>
        <div class="relay-panel">${this.renderTableSkeleton()}</div>
      </section>
    `;
  }

  renderEmpty(message) {
    return `<div class="relay-empty">${this.escapeHtml(message)}</div>`;
  }

  setRefreshState(isLoading) {
    const refresh = this.querySelector('#relay-refresh');
    if (refresh) refresh.disabled = isLoading;
  }

  countFor(counts, status) {
    return (counts || []).find((item) => item.status === status)?.count || 0;
  }

  statusClass(status) {
    return `status-${String(status || 'unknown').toLowerCase().replace(/[^a-z0-9_-]/g, '-')}`;
  }

  formatDate(value) {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }

  errorMessage(error) {
    return error?.data?.detail || error?.data?.message || error?.message || 'Request failed';
  }

  escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
}

customElements.define('relay-page', RelayPage);
