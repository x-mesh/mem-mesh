import { showToast } from '../utils/toast-notifications.js';

export class RelayPage extends HTMLElement {
  constructor() {
    super();
    this.overview = null;
    this.settings = null;
    this.activeTab = 'operations';
    this.limit = 10;
    this.loading = false;
    this.shareCandidates = [];
    this.selectedMemoryId = '';
    this.memorySearchTimer = null;
  }

  connectedCallback() {
    this.render();
    this.loadOverview();
    this.loadSettings();
    this.loadShareCandidates();
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
        <button class="relay-tab" data-tab="personal" type="button">Personal Node</button>
        <button class="relay-tab" data-tab="hub" type="button">Team Hub</button>
      </nav>

      <div class="relay-tab-panel" data-panel="operations">
        <section class="relay-summary" aria-label="Relay summary">
          ${this.renderSummarySkeleton()}
        </section>

        <section class="relay-grid">
          <form class="relay-panel relay-share-panel" id="relay-share-form">
          <div class="relay-panel-header">
            <h2>Share Memory</h2>
            <span id="relay-share-target-meta" class="relay-panel-meta">outbox</span>
          </div>
          <div id="relay-share-connection" class="relay-connection-summary">
            ${this.renderEmpty('Load settings to show the target hub')}
          </div>
          <div class="relay-form-grid">
            <label class="relay-field relay-field-wide">
              <span>Find Memory</span>
              <input id="relay-memory-search" type="search" autocomplete="off" placeholder="Search recent memories">
            </label>
            <input id="share-memory-id" name="memory_id" type="hidden">
            <div id="relay-memory-options" class="relay-memory-options relay-field-wide">
              ${this.renderTableSkeleton()}
            </div>
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
              <span>Project</span>
              <input id="share-project-id" type="text" autocomplete="off" placeholder="Select a memory or enter a project id">
            </label>
          </div>
          <div class="relay-actions">
            <button class="primary-button" id="relay-share-submit" type="submit">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13"/><path d="M22 2L15 22L11 13L2 9L22 2Z"/></svg>
              Queue Memory
            </button>
            <button class="secondary-button" id="relay-project-share-submit" type="button">
              Queue Project
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

      <section class="relay-tab-panel hidden" data-panel="personal">
        ${this.renderSettingsSkeleton()}
      </section>

      <section class="relay-tab-panel hidden" data-panel="hub">
        ${this.renderSettingsSkeleton()}
      </section>
    `;

    this.setupEventListeners();
  }

  setupEventListeners() {
    this.querySelector('#relay-refresh')?.addEventListener('click', () => {
      this.loadOverview();
      this.loadShareCandidates();
    });
    this.querySelector('#relay-limit')?.addEventListener('change', (event) => {
      this.limit = Number(event.target.value || 10);
      this.loadOverview();
    });
    this.querySelector('#relay-share-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      this.shareMemory();
    });
    this.querySelector('#relay-project-share-submit')?.addEventListener('click', () => {
      this.shareProject();
    });
    this.querySelector('#relay-memory-search')?.addEventListener('input', (event) => {
      window.clearTimeout(this.memorySearchTimer);
      this.memorySearchTimer = window.setTimeout(() => {
        this.loadShareCandidates(event.target.value.trim());
      }, 180);
    });
    this.querySelector('#relay-memory-options')?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-memory-id]');
      if (button) {
        this.selectMemory(button.dataset.memoryId);
      }
    });
    this.querySelectorAll('.relay-tab').forEach((button) => {
      button.addEventListener('click', () => this.switchTab(button.dataset.tab));
    });
  }

  bindSettingsEvents() {
    this.querySelector('#relay-personal-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      this.savePersonalSettings();
    });
    this.querySelector('#relay-hub-check')?.addEventListener('click', () => {
      this.checkHubConnection();
    });
    this.querySelector('#relay-worker-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      this.saveWorkerSettings();
    });
    this.querySelector('#relay-identity-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      this.createIdentity();
    });
    this.querySelectorAll('[data-identity-save]').forEach((button) => {
      button.addEventListener('click', () => this.saveIdentity(button.dataset.identitySave));
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
    if ((tab === 'personal' || tab === 'hub') && !this.settings) {
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
      const errorHtml = `<div class="relay-error" role="alert">${this.escapeHtml(this.errorMessage(error))}</div>`;
      const personalPanel = this.querySelector('[data-panel="personal"]');
      const hubPanel = this.querySelector('[data-panel="hub"]');
      if (personalPanel) personalPanel.innerHTML = errorHtml;
      if (hubPanel) hubPanel.innerHTML = errorHtml;
    }
  }

  async loadShareCandidates(query = '') {
    if (!this.api) return;
    const target = this.querySelector('#relay-memory-options');
    if (target) {
      target.innerHTML = this.renderTableSkeleton();
    }
    try {
      const response = await this.api.searchMemories(query, {
        limit: 8,
        recency_weight: query ? 0 : 1.0,
        search_mode: query ? 'hybrid' : 'exact',
      });
      this.shareCandidates = response?.results || [];
      this.renderMemoryOptions();
    } catch (error) {
      if (target) {
        target.innerHTML = `<div class="relay-error" role="alert">${this.escapeHtml(this.errorMessage(error))}</div>`;
      }
    }
  }

  async savePersonalSettings() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-personal-submit');
    const hubUrlInput = this.querySelector('#relay-setting-hub-url');
    const sourceNodeInput = this.querySelector('#relay-setting-source-node');
    const hubTokenInput = this.querySelector('#relay-setting-hub-token');
    const payload = {
      hub_url: hubUrlInput?.value.trim() || '',
      source_node_id: sourceNodeInput?.value.trim() || '',
      default_source_version: Number(
        this.querySelector('#relay-setting-source-version')?.value || 1
      ),
    };
    if (hubTokenInput?.value.trim()) {
      payload.hub_token = hubTokenInput.value.trim();
    }
    submit.disabled = true;
    try {
      this.settings = await this.api.updateRelaySettings(payload);
      this.renderSettings();
      this.applyShareDefaults();
      showToast('Personal relay settings saved.', 'success');
    } catch (error) {
      showToast(`Relay settings failed: ${this.errorMessage(error)}`, 'error');
    } finally {
      submit.disabled = false;
    }
  }

  async saveWorkerSettings() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-worker-submit');
    const payload = {
      sonnet_model: this.querySelector('#relay-setting-sonnet-model')?.value.trim() || '',
      sonnet_base_url: this.querySelector('#relay-setting-sonnet-base-url')?.value.trim() || '',
      prompt_version: this.querySelector('#relay-setting-prompt-version')?.value.trim() || '',
    };
    const sonnetKey = this.querySelector('#relay-setting-sonnet-api-key')?.value.trim();
    if (sonnetKey) {
      payload.sonnet_api_key = sonnetKey;
    }
    submit.disabled = true;
    try {
      this.settings = await this.api.updateRelaySettings(payload);
      this.renderSettings();
      showToast('Team hub worker settings saved.', 'success');
    } catch (error) {
      showToast(`Worker settings failed: ${this.errorMessage(error)}`, 'error');
    } finally {
      submit.disabled = false;
    }
  }

  async checkHubConnection() {
    if (!this.api) return;
    const button = this.querySelector('#relay-hub-check');
    const status = this.querySelector('#relay-hub-check-result');
    const hubUrl = this.querySelector('#relay-setting-hub-url')?.value.trim()
      || this.settings?.hub_url?.value
      || '';
    if (!hubUrl) {
      showToast('Team hub URL is missing.', 'warning');
      return;
    }
    button.disabled = true;
    status.textContent = 'Checking...';
    try {
      const result = await this.api.checkRelayHub({ hub_url: hubUrl });
      status.textContent = result.ok
        ? `Reachable: ${result.health_url}`
        : `Failed: ${result.message}`;
      showToast(result.ok ? 'Hub is reachable.' : 'Hub check failed.', result.ok ? 'success' : 'error');
    } catch (error) {
      status.textContent = this.errorMessage(error);
      showToast(`Hub check failed: ${this.errorMessage(error)}`, 'error');
    } finally {
      button.disabled = false;
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

  async saveIdentity(tokenHashPrefix) {
    if (!this.api || !tokenHashPrefix) return;
    const row = Array.from(this.querySelectorAll('[data-identity-row]')).find(
      (item) => item.dataset.identityRow === tokenHashPrefix
    );
    if (!row) return;
    const payload = {
      user_id: row.querySelector('[data-field="user_id"]')?.value.trim(),
      source_node_id: row.querySelector('[data-field="source_node_id"]')?.value.trim(),
      display_name: row.querySelector('[data-field="display_name"]')?.value.trim(),
      home_domain: row.querySelector('[data-field="home_domain"]')?.value.trim() || null,
      scopes: Array.from(row.querySelectorAll('[data-field="scope"]:checked')).map(
        (item) => item.value
      ),
      revoked: Boolean(row.querySelector('[data-field="revoked"]')?.checked),
    };
    try {
      await this.api.updateRelayIdentity(tokenHashPrefix, payload);
      await this.loadSettings();
      showToast('Relay identity updated.', 'success');
    } catch (error) {
      showToast(`Identity update failed: ${this.errorMessage(error)}`, 'error');
    }
  }

  async shareMemory() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-share-submit');
    const status = this.querySelector('#relay-share-result');
    const memoryId = this.querySelector('#share-memory-id')?.value.trim();
    const sourceVersion = Number(this.querySelector('#share-source-version')?.value || 0);
    const eventType = this.querySelector('#share-event-type')?.value || 'update';

    if (!memoryId) {
      showToast('Select a memory to share.', 'warning');
      return;
    }

    submit.disabled = true;
    status.textContent = 'Queueing...';
    try {
      const result = await this.api.shareRelayMemory(memoryId, {
        source_version: sourceVersion,
        event_type: eventType,
      });
      status.textContent = `Queued ${result.outbox_id} to ${result.target_hub}`;
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

  async shareProject() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-project-share-submit');
    const status = this.querySelector('#relay-share-result');
    const projectId = this.querySelector('#share-project-id')?.value.trim();
    const sourceVersion = Number(this.querySelector('#share-source-version')?.value || 0);
    const eventType = this.querySelector('#share-event-type')?.value || 'update';

    if (!projectId) {
      showToast('Project id is missing.', 'warning');
      return;
    }

    submit.disabled = true;
    status.textContent = 'Queueing project...';
    try {
      const result = await this.api.shareRelayProject(projectId, {
        source_version: sourceVersion,
        event_type: eventType,
      });
      status.textContent = `Queued ${result.queued_count} memories to ${result.target_hub}`;
      showToast('Project queued for relay.', 'success');
      await this.loadOverview();
    } catch (error) {
      const message = this.errorMessage(error);
      status.textContent = message;
      showToast(`Relay project share failed: ${message}`, 'error');
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

  selectMemory(memoryId) {
    this.selectedMemoryId = memoryId || '';
    const input = this.querySelector('#share-memory-id');
    if (input) input.value = this.selectedMemoryId;
    const projectInput = this.querySelector('#share-project-id');
    const selected = this.shareCandidates.find((memory) => memory.id === this.selectedMemoryId);
    if (projectInput && selected?.project_id) {
      projectInput.value = selected.project_id;
    }
    this.renderMemoryOptions();
  }

  renderMemoryOptions() {
    const target = this.querySelector('#relay-memory-options');
    if (!target) return;
    if (!this.shareCandidates?.length) {
      target.innerHTML = this.renderEmpty('No shareable memory candidates');
      return;
    }
    target.innerHTML = this.shareCandidates.map((memory) => {
      const selected = memory.id === this.selectedMemoryId;
      const content = this.truncate(memory.content || '', 120);
      return `
        <button
          class="relay-memory-option ${selected ? 'selected' : ''}"
          type="button"
          data-memory-id="${this.escapeHtml(memory.id)}"
        >
          <span class="relay-memory-option-main">
            <strong>${this.escapeHtml(memory.category || 'memory')}</strong>
            <span>${this.escapeHtml(content)}</span>
          </span>
          <span class="relay-memory-option-meta">
            ${this.escapeHtml(memory.project_id || 'default')}
          </span>
        </button>
      `;
    }).join('');
  }

  renderShareConnection() {
    const target = this.querySelector('#relay-share-connection');
    const meta = this.querySelector('#relay-share-target-meta');
    if (!target || !this.settings) return;
    const hub = this.settings.hub_url?.value || '';
    const node = this.settings.source_node_id?.value || '';
    const tokenConfigured = Boolean(this.settings.hub_token?.configured);
    if (meta) {
      meta.textContent = hub || 'hub not set';
    }
    target.innerHTML = `
      <div class="relay-connection-item">
        <span>Hub</span>
        <code>${this.escapeHtml(hub || 'not set')}</code>
      </div>
      <div class="relay-connection-item">
        <span>Node</span>
        <code>${this.escapeHtml(node || 'not set')}</code>
      </div>
      <div class="relay-connection-item">
        <span>Token</span>
        <span class="relay-status-chip ${tokenConfigured ? 'status-completed' : 'status-pending'}">
          ${tokenConfigured ? 'configured' : 'missing'}
        </span>
      </div>
    `;
  }

  renderSettings() {
    const data = this.settings;
    const personalPanel = this.querySelector('[data-panel="personal"]');
    const hubPanel = this.querySelector('[data-panel="hub"]');
    if (!data || !personalPanel || !hubPanel) return;

    personalPanel.innerHTML = `
      <section class="relay-settings-grid">
        <form class="relay-panel" id="relay-personal-form">
          <div class="relay-panel-header">
            <h2>Connection</h2>
            <span class="relay-panel-meta">${this.formatDate(data.generated_at)}</span>
          </div>
          <div class="relay-form-grid">
            <label class="relay-field relay-field-wide">
              <span>Team Hub URL</span>
              <input
                id="relay-setting-hub-url"
                type="url"
                value="${this.escapeHtml(data.hub_url.value || '')}"
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
            <label class="relay-field relay-field-wide">
              <span>Hub Token</span>
              <input
                id="relay-setting-hub-token"
                type="password"
                autocomplete="new-password"
                placeholder="${data.hub_token.configured ? 'configured, enter new token to replace' : 'paste hub-issued token'}"
              >
              ${this.renderSettingHint(data.hub_token)}
            </label>
          </div>
          <div class="relay-actions">
            <button class="primary-button" id="relay-personal-submit" type="submit">Save Personal Node</button>
            <button class="secondary-button" id="relay-hub-check" type="button">Check Hub</button>
            <span id="relay-hub-check-result" class="relay-inline-status" aria-live="polite"></span>
          </div>
        </form>

        <section class="relay-panel">
          <div class="relay-panel-header">
            <h2>Connection State</h2>
            <span class="relay-panel-meta">local db first</span>
          </div>
          <div class="relay-setting-list">
            ${this.renderSettingRow(data.hub_url)}
            ${this.renderSettingRow(data.source_node_id)}
            ${this.renderSettingRow(data.hub_token)}
          </div>
        </section>
      </section>
    `;

    hubPanel.innerHTML = `
      <section class="relay-settings-grid">
        <form class="relay-panel" id="relay-worker-form">
          <div class="relay-panel-header">
            <h2>Worker LLM</h2>
            <span class="relay-panel-meta">team hub</span>
          </div>
          <div class="relay-form-grid">
            <label class="relay-field relay-field-wide">
              <span>Sonnet API Key</span>
              <input
                id="relay-setting-sonnet-api-key"
                type="password"
                autocomplete="new-password"
                placeholder="${data.sonnet_api_key.configured ? 'configured, enter new key to replace' : 'required for item/aggregate workers'}"
              >
              ${this.renderSettingHint(data.sonnet_api_key)}
            </label>
            <label class="relay-field">
              <span>Sonnet Model</span>
              <input id="relay-setting-sonnet-model" type="text" value="${this.escapeHtml(data.sonnet_model.value || '')}">
              ${this.renderSettingHint(data.sonnet_model)}
            </label>
            <label class="relay-field">
              <span>Prompt Version</span>
              <input id="relay-setting-prompt-version" type="text" value="${this.escapeHtml(data.prompt_version.value || '')}">
              ${this.renderSettingHint(data.prompt_version)}
            </label>
            <label class="relay-field relay-field-wide">
              <span>Sonnet Endpoint</span>
              <input id="relay-setting-sonnet-base-url" type="url" value="${this.escapeHtml(data.sonnet_base_url.value || '')}">
              ${this.renderSettingHint(data.sonnet_base_url)}
            </label>
          </div>
          <div class="relay-actions">
            <button class="primary-button" id="relay-worker-submit" type="submit">Save Worker</button>
            <span class="relay-inline-status">Used by item and aggregate workers.</span>
          </div>
        </form>

        <section class="relay-panel">
          <div class="relay-panel-header">
            <h2>Worker State</h2>
            <span class="relay-panel-meta">local db first</span>
          </div>
          <div class="relay-setting-list">
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
    this.renderShareConnection();
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
        ${item.env_pinned && item.source !== 'db' ? ' fallback from env' : ` source: ${item.source}`}
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
            <th>User</th>
            <th>Node</th>
            <th>Home</th>
            <th>Scopes</th>
            <th>State</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr data-identity-row="${this.escapeHtml(row.token_hash_prefix)}">
              <td>
                <input class="relay-table-input" data-field="display_name" value="${this.escapeHtml(row.display_name)}">
                <input class="relay-table-input muted" data-field="user_id" value="${this.escapeHtml(row.user_id)}">
              </td>
              <td>
                <input class="relay-table-input" data-field="source_node_id" value="${this.escapeHtml(row.source_node_id)}">
                <code>${this.escapeHtml(row.token_hash_prefix)}</code>
              </td>
              <td>
                <input class="relay-table-input" data-field="home_domain" value="${this.escapeHtml(row.home_domain || '')}">
              </td>
              <td>
                <label class="relay-inline-check"><input data-field="scope" type="checkbox" value="read" ${row.scopes.includes('read') ? 'checked' : ''}> read</label>
                <label class="relay-inline-check"><input data-field="scope" type="checkbox" value="write" ${row.scopes.includes('write') ? 'checked' : ''}> write</label>
              </td>
              <td>
                <label class="relay-inline-check"><input data-field="revoked" type="checkbox" ${row.revoked ? 'checked' : ''}> revoked</label>
                <span class="relay-muted">${this.formatDate(row.updated_at)}</span>
              </td>
              <td>
                <button class="secondary-button relay-table-action" type="button" data-identity-save="${this.escapeHtml(row.token_hash_prefix)}">Save</button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }

  applyShareDefaults() {
    if (!this.settings) return;
    const versionInput = this.querySelector('#share-source-version');
    if (versionInput && (!versionInput.value || versionInput.value === '1')) {
      versionInput.value = this.settings.default_source_version || 1;
    }
    this.renderShareConnection();
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

  truncate(value, maxLength) {
    const text = String(value ?? '').replace(/\s+/g, ' ').trim();
    if (text.length <= maxLength) return text;
    return `${text.slice(0, Math.max(0, maxLength - 3))}...`;
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
