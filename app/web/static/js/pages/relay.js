import { showToast } from '../utils/toast-notifications.js';
import { wsClient } from '../services/websocket-client.js';

export class RelayPage extends HTMLElement {
  constructor() {
    super();
    this.overview = null;
    this.settings = null;
    this.invites = [];
    this.activeTab = 'operations';
    this.limit = 10;
    this.loading = false;
    this.shareCandidates = [];
    this.projectCandidates = [];
    this.filteredProjectCandidates = [];
    this.selectedMemoryId = '';
    this.selectedProjectId = '';
    this.memorySearchTimer = null;
    this.projectSearchTimer = null;
    this.realtimeRefreshTimer = null;
    this.overviewPollTimer = null;
    this.overviewPollIntervalMs = 3000;
    this.realtimeToastAt = 0;
    this.boundRealtimeHandlers = null;
    this.boundVisibilityHandler = null;
  }

  connectedCallback() {
    this.render();
    this.setupRealtimeListeners();
    this.loadOverview();
    this.loadSettings();
    this.loadProjects();
    this.loadShareCandidates();
    this.startOverviewPolling();
  }

  disconnectedCallback() {
    if (this.boundRealtimeHandlers) {
      wsClient.off('relay_ingested', this.boundRealtimeHandlers.relayIngested);
      wsClient.off('relay_materialized', this.boundRealtimeHandlers.relayMaterialized);
      wsClient.off('reconnected', this.boundRealtimeHandlers.reconnected);
      this.boundRealtimeHandlers = null;
    }
    if (this.realtimeRefreshTimer) {
      window.clearTimeout(this.realtimeRefreshTimer);
      this.realtimeRefreshTimer = null;
    }
    this.stopOverviewPolling();
    if (this.memorySearchTimer) {
      window.clearTimeout(this.memorySearchTimer);
      this.memorySearchTimer = null;
    }
    if (this.projectSearchTimer) {
      window.clearTimeout(this.projectSearchTimer);
      this.projectSearchTimer = null;
    }
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
          <span id="relay-live-status" class="relay-live-status" aria-live="polite">Live</span>
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
              <input id="share-source-version" name="source_version" type="number" min="0" placeholder="auto (from last edit)">
              <small class="relay-field-hint">Leave blank to auto-version from the memory's last edit — required for a re-share after a content change to not collide.</small>
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
            <div id="relay-project-options" class="relay-project-options relay-field-wide"></div>
            <label class="relay-force-row relay-field-wide">
              <input id="share-force" type="checkbox">
              <span>Requeue if already sent</span>
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
          <div id="relay-dead-letter-list" class="relay-dead-letter-list">
            ${this.renderEmpty('No dead letters')}
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
            <h2>Received Relay Memories</h2>
            <div class="relay-panel-actions">
              <span class="relay-panel-meta">relay view</span>
              <button class="secondary-button relay-panel-button" id="relay-materialize-submit" type="button">
                Sync to Memories
              </button>
              <button class="secondary-button relay-panel-button" id="relay-purge-current-submit" type="button">
                Clear Received
              </button>
            </div>
          </div>
          <div id="relay-memory-table" class="relay-table-wrap">${this.renderTableSkeleton()}</div>
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

  setupRealtimeListeners() {
    if (this.boundRealtimeHandlers) return;
    this.boundRealtimeHandlers = {
      relayIngested: this.handleRelayRealtime.bind(this),
      relayMaterialized: this.handleRelayRealtime.bind(this),
      reconnected: () => this.scheduleRealtimeRefresh('Reconnected'),
    };
    wsClient.on('relay_ingested', this.boundRealtimeHandlers.relayIngested);
    wsClient.on('relay_materialized', this.boundRealtimeHandlers.relayMaterialized);
    wsClient.on('reconnected', this.boundRealtimeHandlers.reconnected);
    wsClient.connect().catch((error) => {
      console.warn('Relay WebSocket connection failed:', error);
    });
  }

  startOverviewPolling() {
    this.stopOverviewPolling();
    this.boundVisibilityHandler = () => {
      if (document.visibilityState === 'visible') {
        this.pollOverviewNow();
      }
    };
    document.addEventListener('visibilitychange', this.boundVisibilityHandler);
    this.scheduleOverviewPoll();
  }

  stopOverviewPolling() {
    if (this.overviewPollTimer) {
      window.clearTimeout(this.overviewPollTimer);
      this.overviewPollTimer = null;
    }
    if (this.boundVisibilityHandler) {
      document.removeEventListener('visibilitychange', this.boundVisibilityHandler);
      this.boundVisibilityHandler = null;
    }
  }

  scheduleOverviewPoll(delay = this.overviewPollIntervalMs) {
    if (this.overviewPollTimer) {
      window.clearTimeout(this.overviewPollTimer);
    }
    this.overviewPollTimer = window.setTimeout(() => {
      this.pollOverview();
    }, delay);
  }

  async pollOverview() {
    this.overviewPollTimer = null;
    try {
      if (document.visibilityState !== 'hidden') {
        await this.loadOverview({ silent: true });
      }
    } finally {
      if (this.isConnected) {
        this.scheduleOverviewPoll();
      }
    }
  }

  async pollOverviewNow() {
    if (this.overviewPollTimer) {
      window.clearTimeout(this.overviewPollTimer);
      this.overviewPollTimer = null;
    }
    await this.loadOverview({ silent: true });
    if (this.isConnected) {
      this.scheduleOverviewPoll();
    }
  }

  setupEventListeners() {
    this.querySelector('#relay-refresh')?.addEventListener('click', () => {
      this.loadOverview();
      this.loadProjects();
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
    this.querySelector('#relay-materialize-submit')?.addEventListener('click', () => {
      this.materializeRelayMemories();
    });
    this.querySelector('#relay-purge-current-submit')?.addEventListener('click', () => {
      this.purgeRelayCurrentMemories();
    });
    this.querySelector('#relay-dead-letter-list')?.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (!target) return;
      const retryAll = target.closest('#relay-retry-dead-letters');
      if (retryAll) {
        this.retryRelayDeadLetters({ queue: 'all' });
        return;
      }
      const retryOne = target.closest('[data-retry-dead-letter]');
      if (retryOne) {
        this.retryRelayDeadLetters({
          queue: retryOne.dataset.queue,
          id: retryOne.dataset.jobId,
        });
      }
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
    this.querySelector('#share-project-id')?.addEventListener('input', (event) => {
      this.selectedProjectId = '';
      window.clearTimeout(this.projectSearchTimer);
      this.projectSearchTimer = window.setTimeout(() => {
        this.filterProjectCandidates(event.target.value.trim());
      }, 120);
    });
    this.querySelector('#share-project-id')?.addEventListener('focus', (event) => {
      this.filterProjectCandidates(event.target.value.trim());
    });
    this.querySelector('#relay-project-options')?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-project-id]');
      if (button) {
        this.selectProject(button.dataset.projectId);
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
    this.querySelector('#relay-sharing-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      this.saveSharingPolicy();
    });
    this.querySelector('#relay-worker-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      this.saveWorkerSettings();
    });
    this.querySelector('#relay-identity-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      this.createIdentity();
    });
    this.querySelector('#relay-pair-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      this.pairWithInvite();
    });
    this.querySelector('#relay-invite-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      this.createInvite();
    });
    this.querySelectorAll('[data-invite-delete]').forEach((button) => {
      button.addEventListener('click', () => this.deleteInvite(button.dataset.inviteDelete));
    });
    this.querySelectorAll('[data-identity-save]').forEach((button) => {
      button.addEventListener('click', () => this.saveIdentity(button.dataset.identitySave));
    });
    this.querySelectorAll('[data-identity-rotate]').forEach((button) => {
      button.addEventListener('click', () => this.rotateIdentity(button.dataset.identityRotate));
    });
    this.querySelectorAll('[data-identity-delete]').forEach((button) => {
      button.addEventListener('click', () => this.deleteIdentity(button.dataset.identityDelete));
    });
    this.bindIdentityAutofill();
  }

  bindIdentityAutofill() {
    // Typing a User ID prefills Display Name (and Source Node ID when empty)
    // until the user edits those fields themselves — reduces a 3-field form to
    // effectively one input for the common case.
    const userId = this.querySelector('#identity-user-id');
    const display = this.querySelector('#identity-display-name');
    const node = this.querySelector('#identity-source-node');
    if (!userId) return;
    [display, node].forEach((el) => {
      el?.addEventListener('input', () => { el.dataset.touched = '1'; });
    });
    userId.addEventListener('input', () => {
      const value = userId.value.trim();
      if (display && !display.dataset.touched) display.value = value;
      if (node && !node.dataset.touched && !node.value.trim()) node.value = value;
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

  async loadOverview({ silent = false } = {}) {
    if (!this.api || this.loading) return;
    this.loading = true;
    if (!silent) {
      this.setRefreshState(true);
    }
    try {
      this.overview = await this.api.getRelayOverview(this.limit);
      this.renderOverview();
      if (silent) {
        this.setLiveStatus(`Auto ${this.formatTime(new Date())}`);
      }
    } catch (error) {
      if (silent) {
        this.setLiveStatus('Auto refresh failed');
        console.warn('Relay overview polling failed:', error);
      } else {
        this.renderLoadError(error);
      }
    } finally {
      this.loading = false;
      if (!silent) {
        this.setRefreshState(false);
      }
    }
  }

  async loadSettings() {
    if (!this.api) return;
    try {
      this.settings = await this.api.getRelaySettings();
      // Invites are hub-side extras — a node without them (older server)
      // just renders an empty list.
      try {
        this.invites = (await this.api.getRelayInvites())?.invites || [];
      } catch {
        this.invites = [];
      }
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

  async loadProjects() {
    if (!this.api) return;
    try {
      const response = this.api.getProjects
        ? await this.api.getProjects()
        : await this.api.get('/projects');
      this.projectCandidates = response?.projects || [];
      this.filterProjectCandidates(this.querySelector('#share-project-id')?.value.trim() || '');
    } catch (error) {
      const target = this.querySelector('#relay-project-options');
      if (target) {
        target.innerHTML = `<div class="relay-error" role="alert">${this.escapeHtml(this.errorMessage(error))}</div>`;
      }
    }
  }

  filterProjectCandidates(query = '') {
    const needle = query.toLowerCase();
    const projects = this.projectCandidates || [];
    this.filteredProjectCandidates = projects
      .filter((project) => {
        if (!needle) return true;
        const haystack = [
          project.id,
          project.name,
          ...(project.categories || []),
          ...(project.tags || []),
        ].join(' ').toLowerCase();
        return haystack.includes(needle);
      })
      .slice(0, 8);
    this.renderProjectOptions();
  }

  async savePersonalSettings() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-personal-submit');
    const hubUrlInput = this.querySelector('#relay-setting-hub-url');
    const sourceNodeInput = this.querySelector('#relay-setting-source-node');
    const hubTokenInput = this.querySelector('#relay-setting-hub-token');
    // default_source_version is an internal relay detail (share fallback), not a
    // user knob — omitted here so the stored value is preserved.
    const payload = {
      hub_url: hubUrlInput?.value.trim() || '',
      source_node_id: sourceNodeInput?.value.trim() || '',
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

  async saveSharingPolicy() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-sharing-submit');
    // Every rendered checkbox is a category known to exist locally; unchecked
    // ones become the blocked set (checked = shared, the default).
    const boxes = Array.from(this.querySelectorAll('input[name="share_category"]'));
    const blockedCategories = boxes.filter((b) => !b.checked).map((b) => b.value);
    submit.disabled = true;
    try {
      this.settings = await this.api.updateRelaySettings({ blocked_categories: blockedCategories });
      this.renderSettings();
      showToast('Sharing policy saved.', 'success');
    } catch (error) {
      showToast(`Sharing policy failed: ${this.errorMessage(error)}`, 'error');
    } finally {
      submit.disabled = false;
    }
  }

  async saveWorkerSettings() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-worker-submit');
    // prompt_version is intentionally omitted — it's a code-prompt cache tag, not
    // a user setting. Leaving it out of the payload preserves the stored value.
    const payload = {
      llm_provider: this.querySelector('#relay-setting-llm-provider')?.value.trim() || '',
      llm_model: this.querySelector('#relay-setting-llm-model')?.value.trim() || '',
      llm_base_url: this.querySelector('#relay-setting-llm-base-url')?.value.trim() || '',
    };
    const llmKey = this.querySelector('#relay-setting-llm-api-key')?.value.trim();
    if (llmKey) {
      payload.llm_api_key = llmKey;
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
    // Send the token typed in the field; empty → the server falls back to the
    // stored hub token, so a saved token can be re-checked anytime after reload
    // (the password field is always blank on load).
    const hubToken = this.querySelector('#relay-setting-hub-token')?.value.trim() || '';
    const tokenConfigured = Boolean(this.settings?.hub_token?.configured);
    if (!hubToken && !tokenConfigured) {
      showToast('No hub token saved yet — paste one and Save, then Check Hub.', 'warning');
      return;
    }
    button.disabled = true;
    status.dataset.state = '';
    status.textContent = 'Checking...';
    try {
      const result = await this.api.checkRelayHub({ hub_url: hubUrl, token: hubToken });
      const lines = [result.ok ? `Reachable: ${result.health_url}` : `Failed: ${result.message}`];
      if (result.token_ok === true) {
        const scopes = (result.scopes && result.scopes.length) ? `, scopes: ${result.scopes.join('/')}` : '';
        lines.push(`Token: valid${result.node_id ? ` — ${result.node_id}` : ''}${scopes}`);
        // A valid Check Hub IS the commit: persist the just-verified token and
        // the hub-derived source node id, so a reload keeps them. (Check Hub OK
        // was being mistaken for Save, and the typed token was lost on reload.)
        await this._persistVerifiedHub(hubToken, result.node_id, lines);
      } else if (result.token_ok === false) {
        lines.push(`Token: INVALID — ${result.token_message}`);
      } else if (result.token_checked) {
        // Reachable but not verified (e.g. hub too old to expose /auth/check).
        lines.push(`Token: not verified — ${result.token_message}`);
      }

      status.textContent = lines.join('\n');

      const tokenBad = result.token_ok === false;
      const overallOk = result.ok && !tokenBad;
      status.dataset.state = (!result.ok || tokenBad) ? 'error' : (result.token_ok === true ? 'ok' : '');
      const toastMsg = !result.ok
        ? 'Hub check failed.'
        : tokenBad
          ? 'Hub reachable, but token is invalid.'
          : result.token_ok === true
            ? 'Hub reachable, token valid.'
            : 'Hub reachable, token not verified.';
      showToast(toastMsg, overallOk ? 'success' : 'error');
    } catch (error) {
      status.dataset.state = 'error';
      status.textContent = this.errorMessage(error);
      showToast(`Hub check failed: ${this.errorMessage(error)}`, 'error');
    } finally {
      button.disabled = false;
    }
  }

  _hubTokenBadgeHtml(configured) {
    return this._secretBadgeHtml(configured, 'Token saved', 'No token saved');
  }

  _secretBadgeHtml(configured, savedLabel, missingLabel) {
    return configured
      ? `<span class="relay-status-chip status-completed">${this.escapeHtml(savedLabel)}</span>`
      : `<span class="relay-status-chip status-pending">${this.escapeHtml(missingLabel)}</span>`;
  }

  // Persist what a successful Check Hub verified, so it survives a reload.
  // Saves a freshly-typed token (only after it validated) and the hub-derived
  // source node id. Re-checking an already-saved token with an unchanged node
  // writes nothing.
  async _persistVerifiedHub(hubToken, nodeId, lines) {
    const nodeInput = this.querySelector('#relay-setting-source-node');
    const currentNode = (this.settings?.source_node_id?.value || '').trim();
    if (nodeInput && nodeId) nodeInput.value = nodeId;
    const payload = {};
    if (hubToken) payload.hub_token = hubToken;
    if (nodeId && nodeId !== currentNode) payload.source_node_id = nodeId;
    if (!Object.keys(payload).length) return;
    try {
      this.settings = await this.api.updateRelaySettings(payload);
      lines.push(hubToken ? 'Saved — token verified and stored.' : `Source Node ID synced: ${nodeId}`);
      // Targeted update, not a full renderSettings() — a full re-render would
      // wipe the Checking.../result text and any in-progress form input.
      const badge = this.querySelector('#relay-hub-token-badge');
      if (badge) badge.innerHTML = this._hubTokenBadgeHtml(this.settings?.hub_token?.configured);
    } catch (error) {
      lines.push(`Verified, but auto-save failed: ${this.errorMessage(error)}`);
    }
  }

  _decodeInviteHubUrl(code) {
    // A pairing code may embed its hub URL as `<secret>.<b64url(hub_url)>`.
    // Return the decoded http(s) URL, or '' for a legacy bare code.
    const dot = code.indexOf('.');
    if (dot === -1) return '';
    const b64 = code.slice(dot + 1);
    try {
      const padded = b64.replace(/-/g, '+').replace(/_/g, '/')
        + '==='.slice((b64.length + 3) % 4);
      const url = decodeURIComponent(escape(atob(padded)));
      return /^https?:\/\//i.test(url) ? url.replace(/\/+$/, '') : '';
    } catch (error) {
      return '';
    }
  }

  async pairWithInvite() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-pair-submit');
    const status = this.querySelector('#relay-pair-result');
    const code = this.querySelector('#relay-pair-code')?.value.trim() || '';
    if (!code) {
      showToast('Paste the invite code.', 'warning');
      return;
    }
    // The code carries its hub URL — auto-fill it, falling back to the form/settings.
    const embeddedHubUrl = this._decodeInviteHubUrl(code);
    const hubField = this.querySelector('#relay-setting-hub-url');
    if (embeddedHubUrl && hubField) hubField.value = embeddedHubUrl;
    const hubUrl = embeddedHubUrl
      || hubField?.value.trim()
      || this.settings?.hub_url?.value
      || '';
    if (!hubUrl) {
      showToast('Enter the Team Hub URL first, or use an invite code that includes it.', 'warning');
      return;
    }
    // Offer this node's own id so codes that did not pin one still resolve.
    const nodeId = (this.settings?.source_node_id?.value || '').trim();
    submit.disabled = true;
    status.dataset.state = '';
    status.textContent = 'Pairing...';
    try {
      const payload = { hub_url: hubUrl, code };
      if (nodeId) payload.source_node_id = nodeId;
      const result = await this.api.pairRelayNode(payload);
      status.dataset.state = 'ok';
      const lines = [
        `Paired as ${result.source_node_id}${result.user_id ? ` (${result.user_id})` : ''}`,
        result.message || '',
      ];
      if (result.check) {
        lines.push(result.check.ok ? `Hub verified: ${result.check.health_url}` : `Hub check: ${result.check.message}`);
      }
      status.textContent = lines.filter(Boolean).join('\n');
      showToast('Paired with team hub.', 'success');
      await this.loadSettings();
    } catch (error) {
      status.dataset.state = 'error';
      status.textContent = this.errorMessage(error);
      showToast(`Pairing failed: ${this.errorMessage(error)}`, 'error');
    } finally {
      submit.disabled = false;
    }
  }

  async createInvite() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-invite-submit');
    const payload = {
      user_id: this.querySelector('#invite-user-id')?.value.trim(),
      display_name: this.querySelector('#invite-display-name')?.value.trim(),
      scopes: Array.from(this.querySelectorAll('[name="invite_scope"]:checked')).map(
        (item) => item.value
      ),
      expires_in_seconds: parseInt(this.querySelector('#invite-expiry')?.value || '86400', 10),
    };
    const nodeId = this.querySelector('#invite-source-node')?.value.trim();
    if (nodeId) {
      payload.source_node_id = nodeId;
    }
    const hubUrl = this.querySelector('#invite-hub-url')?.value.trim();
    if (hubUrl) {
      payload.hub_url = hubUrl;
    }
    if (!payload.user_id || !payload.display_name) {
      showToast('Invite fields are missing.', 'warning');
      return;
    }
    submit.disabled = true;
    try {
      const result = await this.api.createRelayInvite(payload);
      await this.loadSettings();
      if (result.code) {
        this.showIssuedInvite(result.code);
      }
      showToast('Pairing invite issued.', 'success');
    } catch (error) {
      showToast(`Invite failed: ${this.errorMessage(error)}`, 'error');
    } finally {
      submit.disabled = false;
    }
  }

  async deleteInvite(codePrefix) {
    if (!this.api || !codePrefix) return;
    try {
      await this.api.deleteRelayInvite(codePrefix);
      showToast('Invite revoked.', 'success');
      await this.loadSettings();
    } catch (error) {
      showToast(`Invite revoke failed: ${this.errorMessage(error)}`, 'error');
    }
  }

  showIssuedInvite(code) {
    const target = this.querySelector('#relay-issued-invite');
    if (!target) return;
    target.classList.remove('hidden');
    target.innerHTML = `
      <span>Invite code</span>
      <code>${this.escapeHtml(code)}</code>
      <button class="secondary-button" type="button" id="relay-copy-issued-invite">Copy</button>
    `;
    target.querySelector('#relay-copy-issued-invite')?.addEventListener('click', async () => {
      if (await this.copyText(code)) {
        showToast('Invite code copied.', 'success');
      } else {
        showToast('Copy failed.', 'error');
      }
    });
  }

  async createIdentity() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-identity-submit');
    const payload = {
      user_id: this.querySelector('#identity-user-id')?.value.trim(),
      source_node_id: this.querySelector('#identity-source-node')?.value.trim(),
      display_name: this.querySelector('#identity-display-name')?.value.trim(),
      scopes: Array.from(this.querySelectorAll('[name="identity_scope"]:checked')).map(
        (item) => item.value
      ),
    };
    // Blank custom token → the server auto-generates one (shown once); a filled
    // one is used verbatim.
    const manualToken = this.querySelector('#identity-token')?.value.trim();
    if (manualToken) {
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

  async deleteIdentity(tokenHashPrefix) {
    if (!this.api || !tokenHashPrefix) return;
    const row = Array.from(this.querySelectorAll('[data-identity-row]')).find(
      (item) => item.dataset.identityRow === tokenHashPrefix
    );
    const label = row?.querySelector('[data-field="display_name"]')?.value.trim() || tokenHashPrefix;
    if (!window.confirm(`Delete identity "${label}"? Its token stops working immediately. To disable it reversibly, use the revoked checkbox instead.`)) {
      return;
    }
    try {
      await this.api.deleteRelayIdentity(tokenHashPrefix);
      await this.loadSettings();
      showToast('Relay identity deleted.', 'success');
    } catch (error) {
      showToast(`Identity delete failed: ${this.errorMessage(error)}`, 'error');
    }
  }

  async rotateIdentity(tokenHashPrefix) {
    if (!this.api || !tokenHashPrefix) return;
    const row = Array.from(this.querySelectorAll('[data-identity-row]')).find(
      (item) => item.dataset.identityRow === tokenHashPrefix
    );
    const label = row?.querySelector('[data-field="display_name"]')?.value.trim() || tokenHashPrefix;
    if (!window.confirm(`Rotate the token for "${label}"? A new token is issued and the old one stops working immediately — update this node's Hub Token with the new value.`)) {
      return;
    }
    try {
      // Blank body → server generates a new token, returned once.
      const result = await this.api.rotateRelayIdentity(tokenHashPrefix);
      await this.loadSettings();
      if (result.token) {
        this.showIssuedToken(result.token);
      }
      showToast('Token rotated — copy the new token now.', 'success');
    } catch (error) {
      showToast(`Token rotation failed: ${this.errorMessage(error)}`, 'error');
    }
  }

  async shareMemory() {
    if (!this.api) return;
    const submit = this.querySelector('#relay-share-submit');
    const status = this.querySelector('#relay-share-result');
    const memoryId = this.querySelector('#share-memory-id')?.value.trim();
    // Blank → omit source_version so the server auto-derives it from the
    // memory's updated_at (same as auto-share); an explicit value pins it.
    const sourceVersionRaw = this.querySelector('#share-source-version')?.value.trim();
    const eventType = this.querySelector('#share-event-type')?.value || 'update';
    const force = Boolean(this.querySelector('#share-force')?.checked);

    if (!memoryId) {
      showToast('Select a memory to share.', 'warning');
      return;
    }

    submit.disabled = true;
    status.textContent = 'Queueing...';
    try {
      const payload = { event_type: eventType, force };
      if (sourceVersionRaw) payload.source_version = Number(sourceVersionRaw);
      const result = await this.api.shareRelayMemory(memoryId, payload);
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
    // Blank → each memory gets its own auto-derived version (see shareMemory).
    const sourceVersionRaw = this.querySelector('#share-source-version')?.value.trim();
    const eventType = this.querySelector('#share-event-type')?.value || 'update';
    const force = Boolean(this.querySelector('#share-force')?.checked);

    if (!projectId) {
      showToast('Project id is missing.', 'warning');
      return;
    }

    submit.disabled = true;
    status.textContent = 'Queueing project...';
    try {
      const payload = { event_type: eventType, force };
      if (sourceVersionRaw) payload.source_version = Number(sourceVersionRaw);
      const result = await this.api.shareRelayProject(projectId, payload);
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

  async materializeRelayMemories() {
    if (!this.api) return;
    const button = this.querySelector('#relay-materialize-submit');
    if (button) button.disabled = true;
    try {
      const result = await this.api.materializeRelayMemories(1000);
      const count = Number(result.materialized || 0).toLocaleString();
      showToast(`Synced ${count} relay memories.`, 'success');
      await this.loadOverview();
    } catch (error) {
      showToast(`Relay sync failed: ${this.errorMessage(error)}`, 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  async purgeRelayCurrentMemories() {
    if (!this.api) return;
    const visibleCount = Number(this.overview?.visible_memories || 0);
    if (visibleCount <= 0) {
      showToast('No received relay memories to clear.', 'info');
      return;
    }
    const countLabel = visibleCount.toLocaleString();
    const confirmed = confirm(
      `Clear ${countLabel} received relay memories? Raw relay events are kept, but hidden current rows will not sync back to Memories.`
    );
    if (!confirmed) return;

    const button = this.querySelector('#relay-purge-current-submit');
    if (button) button.disabled = true;
    try {
      const result = await this.api.purgeRelayCurrentMemories(10000);
      const count = Number(result.purged || 0).toLocaleString();
      const deleted = Number(result.materialized_deleted || 0).toLocaleString();
      showToast(`Cleared ${count} relay memories (${deleted} materialized rows).`, 'success');
      await this.loadOverview();
    } catch (error) {
      showToast(`Relay clear failed: ${this.errorMessage(error)}`, 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  async retryRelayDeadLetters({ queue = 'all', id = null } = {}) {
    if (!this.api) return;
    const target = id ? `${queue} job` : 'all dead-letter jobs';
    if (!confirm(`Retry ${target}?`)) return;

    try {
      const result = await this.api.retryRelayDeadLetters({
        queue,
        id,
        limit: id ? 1 : 1000,
      });
      showToast(`Requeued ${Number(result.retried || 0).toLocaleString()} relay jobs.`, 'success');
      await this.loadOverview();
    } catch (error) {
      showToast(`Relay retry failed: ${this.errorMessage(error)}`, 'error');
    }
  }

  handleRelayRealtime(data = {}) {
    const relayMemory = data.relay_memory || {};
    const source = relayMemory.source_node_id || 'relay';
    const action = data.action || (data.materialized !== undefined ? 'materialized' : 'updated');
    this.scheduleRealtimeRefresh(`${source} ${action}`);

    const now = Date.now();
    if (now - this.realtimeToastAt > 10000) {
      this.realtimeToastAt = now;
      const project = relayMemory.team_project_id || 'team hub';
      const message = relayMemory.source_memory_id
        ? `${source} shared ${relayMemory.source_memory_id} to ${project}.`
        : `Received relay ${action} update for ${project}.`;
      this.showRelayPush('Relay update', message);
    }
  }

  showRelayPush(title, message) {
    let stack = document.getElementById('relay-push-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.id = 'relay-push-stack';
      stack.className = 'relay-push-stack';
      document.body.appendChild(stack);
    }

    const item = document.createElement('article');
    item.className = 'relay-push';
    item.setAttribute('role', 'status');
    item.setAttribute('aria-live', 'polite');
    item.innerHTML = `
      <span class="relay-push-dot" aria-hidden="true"></span>
      <div class="relay-push-copy">
        <strong>${this.escapeHtml(title)}</strong>
        <span>${this.escapeHtml(message)}</span>
      </div>
      <button class="relay-push-close" type="button" aria-label="Close notification">&times;</button>
    `;

    const close = () => {
      item.classList.remove('visible');
      window.setTimeout(() => item.remove(), 180);
    };
    item.querySelector('.relay-push-close')?.addEventListener('click', close);

    stack.appendChild(item);
    window.requestAnimationFrame(() => item.classList.add('visible'));
    window.setTimeout(close, 6500);
  }

  scheduleRealtimeRefresh(label = 'Updated') {
    this.setLiveStatus(label);
    if (this.realtimeRefreshTimer) {
      window.clearTimeout(this.realtimeRefreshTimer);
    }
    this.realtimeRefreshTimer = window.setTimeout(async () => {
      this.realtimeRefreshTimer = null;
      if (this.loading) {
        this.scheduleRealtimeRefresh(label);
        return;
      }
      await this.loadOverview();
    }, 250);
  }

  setLiveStatus(label) {
    const target = this.querySelector('#relay-live-status');
    if (!target) return;
    const time = new Date().toLocaleTimeString();
    target.textContent = `${label} · ${time}`;
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
    this.renderDeadLetters(data.dead_letters || []);
    this.renderOutboxTable(data.recent_outbox);
    this.renderQueueTable(data.recent_queue);
    this.renderRelayMemories(data.recent_memories);
    this.renderDigests(data.recent_digests);
  }

  selectMemory(memoryId) {
    this.selectedMemoryId = memoryId || '';
    const input = this.querySelector('#share-memory-id');
    if (input) input.value = this.selectedMemoryId;
    const projectInput = this.querySelector('#share-project-id');
    const selected = this.shareCandidates.find((memory) => memory.id === this.selectedMemoryId);
    if (projectInput && selected?.project_id) {
      this.selectProject(selected.project_id);
    }
    this.renderMemoryOptions();
  }

  selectProject(projectId) {
    this.selectedProjectId = projectId || '';
    const projectInput = this.querySelector('#share-project-id');
    if (projectInput) {
      projectInput.value = this.selectedProjectId;
    }
    this.filterProjectCandidates(this.selectedProjectId);
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

  renderProjectOptions() {
    const target = this.querySelector('#relay-project-options');
    if (!target) return;
    if (!this.projectCandidates?.length) {
      target.innerHTML = this.renderEmpty('No local projects found');
      return;
    }
    if (!this.filteredProjectCandidates?.length) {
      target.innerHTML = this.renderEmpty('No matching projects');
      return;
    }
    target.innerHTML = this.filteredProjectCandidates.map((project) => {
      const projectId = String(project.id || project.name || '');
      const selected = projectId === this.selectedProjectId;
      const categories = (project.categories || []).slice(0, 3).join(', ');
      return `
        <button
          class="relay-project-option ${selected ? 'selected' : ''}"
          type="button"
          data-project-id="${this.escapeHtml(projectId)}"
        >
          <span class="relay-project-option-main">
            <strong>${this.escapeHtml(project.name || projectId)}</strong>
            <span>${this.escapeHtml(projectId)}</span>
          </span>
          <span class="relay-project-option-meta">
            ${Number(project.memory_count || 0).toLocaleString()} memories${categories ? ` · ${this.escapeHtml(categories)}` : ''}
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
                class="relay-input-readonly"
                value="${this.escapeHtml(data.source_node_id.value || '')}"
                placeholder="run Check Hub to set from your token"
                readonly
                tabindex="-1"
              >
              <small class="relay-field-hint">Read-only — the hub derives this from your token. Click Check Hub to sync it.</small>
            </label>
            <label class="relay-field relay-field-wide">
              <span class="relay-field-label-row">
                <span>Hub Token</span>
                <span id="relay-hub-token-badge">${this._hubTokenBadgeHtml(data.hub_token.configured)}</span>
              </span>
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
          </div>
          <div id="relay-hub-check-result" class="relay-hub-check-status" aria-live="polite"></div>
        </form>

        <form class="relay-panel" id="relay-pair-form">
          <div class="relay-panel-header">
            <h2>Pair with Invite</h2>
            <span class="relay-panel-meta">one-step setup</span>
          </div>
          <p class="relay-field-hint">
            Got an invite code from your team hub admin? Just paste it here — the
            code carries its Team Hub URL, so the node fills that in, redeems, and
            saves the hub URL, token, and source node id in one step. No manual
            URL or token copying.
          </p>
          <div class="relay-form-grid">
            <label class="relay-field relay-field-wide">
              <span>Invite Code</span>
              <input
                id="relay-pair-code"
                type="password"
                autocomplete="off"
                placeholder="paste the one-time invite code"
              >
            </label>
          </div>
          <div class="relay-actions">
            <button class="primary-button" id="relay-pair-submit" type="submit">Pair with Invite</button>
          </div>
          <div id="relay-pair-result" class="relay-hub-check-status" aria-live="polite"></div>
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

        <form class="relay-panel relay-field-wide" id="relay-sharing-form">
          <div class="relay-panel-header">
            <h2>Sharing Policy</h2>
            <span class="relay-panel-meta">this node → team hub</span>
          </div>
          <p class="relay-field-hint">
            Unchecked categories are skipped by Share and Auto-share. New categories
            show up here automatically and are shared by default — uncheck any you'd
            rather keep local. 'task' memories are always local-only.
          </p>
          <div class="relay-category-grid">
            ${data.category_policies.length
              ? data.category_policies.map((p) => `
                  <label class="relay-inline-check">
                    <input type="checkbox" name="share_category" value="${this.escapeHtml(p.category)}" ${p.shared ? 'checked' : ''}>
                    ${this.escapeHtml(p.category)}
                  </label>
                `).join('')
              : '<span class="relay-muted">No memories yet — categories will appear here once you have some.</span>'}
          </div>
          <div class="relay-actions">
            <button class="primary-button" id="relay-sharing-submit" type="submit">Save Sharing Policy</button>
          </div>
        </form>
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
            <label class="relay-field">
              <span>LLM Provider</span>
              <select id="relay-setting-llm-provider">
                <option value="anthropic" ${(data.llm_provider.value || 'anthropic') === 'openai' ? '' : 'selected'}>anthropic</option>
                <option value="openai" ${(data.llm_provider.value || 'anthropic') === 'openai' ? 'selected' : ''}>openai</option>
              </select>
              ${this.renderSettingHint(data.llm_provider)}
            </label>
            <label class="relay-field relay-field-wide">
              <span>LLM Endpoint</span>
              <input id="relay-setting-llm-base-url" type="url" placeholder="leave empty for provider default" value="${this.escapeHtml(data.llm_base_url.value || '')}">
              ${this.renderSettingHint(data.llm_base_url)}
            </label>
            <label class="relay-field relay-field-wide">
              <span class="relay-field-label-row">
                <span>LLM API Key</span>
                ${this._secretBadgeHtml(data.llm_api_key.configured, 'Key saved', 'No key saved')}
              </span>
              <input
                id="relay-setting-llm-api-key"
                type="password"
                autocomplete="new-password"
                placeholder="${data.llm_api_key.configured ? 'configured, enter new key to replace' : 'required for item/aggregate workers'}"
              >
              ${this.renderSettingHint(data.llm_api_key)}
            </label>
            <label class="relay-field">
              <span>LLM Model</span>
              <input id="relay-setting-llm-model" type="text" value="${this.escapeHtml(data.llm_model.value || '')}">
              ${this.renderSettingHint(data.llm_model)}
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
            ${this.renderSettingRow(data.llm_provider)}
            ${this.renderSettingRow(data.llm_base_url)}
            ${this.renderSettingRow(data.llm_api_key)}
            ${this.renderSettingRow(data.llm_model)}
          </div>
        </section>
      </section>

      <section class="relay-panel relay-identities">
        <div class="relay-panel-header">
          <h2>Pairing Invites</h2>
          <span class="relay-panel-meta">${this.invites.length} issued</span>
        </div>
        <p class="relay-field-hint">
          Issue a one-time code instead of registering identities by hand: the
          new member pastes it into their node's "Pair with Invite" and gets a
          token, node id, and hub URL configured automatically. Codes are shown
          once, are single-use, and expire.
        </p>
        <form id="relay-invite-form" class="relay-identity-create">
          <div class="relay-form-grid">
            <label class="relay-field relay-field-wide">
              <span>Hub URL <small class="relay-field-hint">embedded in the code (IP or domain) — defaults to MEM_MESH_PUBLIC_URL</small></span>
              <input id="invite-hub-url" type="text" autocomplete="off"
                placeholder="https://hub.example.com or http://10.0.0.5:8000"
                value="${this.escapeHtml(data.public_url?.value || '')}">
            </label>
            <label class="relay-field">
              <span>User ID</span>
              <input id="invite-user-id" type="text" autocomplete="off" required>
            </label>
            <label class="relay-field">
              <span>Display Name</span>
              <input id="invite-display-name" type="text" autocomplete="off" required>
            </label>
            <label class="relay-field">
              <span>Source Node ID <small class="relay-field-hint">optional — blank lets the node choose</small></span>
              <input id="invite-source-node" type="text" autocomplete="off">
            </label>
            <label class="relay-field">
              <span>Expires</span>
              <select id="invite-expiry">
                <option value="3600">1 hour</option>
                <option value="86400" selected>24 hours</option>
                <option value="604800">7 days</option>
              </select>
            </label>
            <div class="relay-scope-row relay-field-wide">
              <label><input type="checkbox" name="invite_scope" value="read" checked> read</label>
              <label><input type="checkbox" name="invite_scope" value="write" checked> write</label>
            </div>
          </div>
          <div class="relay-actions">
            <button class="primary-button" id="relay-invite-submit" type="submit">Issue Invite</button>
            <span class="relay-inline-status">The code is shown once — send it to the new member.</span>
          </div>
          <div id="relay-issued-invite" class="relay-issued-token hidden"></div>
        </form>
        <div class="relay-table-wrap">
          ${this.renderInviteTable(this.invites)}
        </div>
      </section>

      <section class="relay-panel relay-identities">
        <div class="relay-panel-header">
          <h2>Hub Identities</h2>
          <span class="relay-panel-meta">${data.identities.length} registered</span>
        </div>

        <form id="relay-identity-form" class="relay-identity-create">
          <div class="relay-form-grid">
            <label class="relay-field">
              <span>User ID</span>
              <input id="identity-user-id" type="text" autocomplete="off" required>
            </label>
            <label class="relay-field">
              <span>Display Name</span>
              <input id="identity-display-name" type="text" autocomplete="off" required>
            </label>
            <label class="relay-field">
              <span>Source Node ID</span>
              <input id="identity-source-node" type="text" autocomplete="off" value="${this.escapeHtml(data.source_node_id.value || '')}" required>
            </label>
            <label class="relay-field relay-field-wide">
              <span>Custom token <small class="relay-field-hint">optional — leave blank to auto-generate</small></span>
              <input id="identity-token" type="password" autocomplete="new-password" placeholder="blank = generate a secure token">
            </label>
            <div class="relay-scope-row relay-field-wide">
              <label><input type="checkbox" name="identity_scope" value="read" checked> read</label>
              <label><input type="checkbox" name="identity_scope" value="write" checked> write</label>
            </div>
          </div>
          <div class="relay-actions">
            <button class="primary-button" id="relay-identity-submit" type="submit">Register Identity</button>
            <span class="relay-inline-status">A generated token is shown once — copy it immediately.</span>
          </div>
          <div id="relay-issued-token" class="relay-issued-token hidden"></div>
        </form>

        <div class="relay-table-wrap">
          ${this.renderIdentityTable(data.identities)}
        </div>
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
                <label class="relay-inline-check"><input data-field="scope" type="checkbox" value="read" ${row.scopes.includes('read') ? 'checked' : ''}> read</label>
                <label class="relay-inline-check"><input data-field="scope" type="checkbox" value="write" ${row.scopes.includes('write') ? 'checked' : ''}> write</label>
              </td>
              <td>
                <label class="relay-inline-check"><input data-field="revoked" type="checkbox" ${row.revoked ? 'checked' : ''}> revoked</label>
                <span class="relay-muted">${this.formatDate(row.updated_at)}</span>
              </td>
              <td class="relay-table-actions">
                <button class="secondary-button relay-table-action" type="button" data-identity-save="${this.escapeHtml(row.token_hash_prefix)}">Save</button>
                <button class="secondary-button relay-table-action" type="button" data-identity-rotate="${this.escapeHtml(row.token_hash_prefix)}">Rotate</button>
                <button class="relay-table-action danger" type="button" data-identity-delete="${this.escapeHtml(row.token_hash_prefix)}">Delete</button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }

  renderInviteTable(rows) {
    if (!rows?.length) {
      return this.renderEmpty('No pairing invites');
    }
    const now = Date.now();
    return `
      <table class="relay-table">
        <thead>
          <tr>
            <th>User</th>
            <th>Node</th>
            <th>Scopes</th>
            <th>State</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => {
            const expired = row.expires_at && Date.parse(row.expires_at) < now;
            const state = row.redeemed_at
              ? `redeemed ${this.formatDate(row.redeemed_at)}`
              : row.revoked
                ? 'revoked'
                : expired
                  ? 'expired'
                  : `expires ${this.formatDate(row.expires_at)}`;
            const stateClass = row.redeemed_at ? 'status-completed' : (expired || row.revoked) ? 'status-pending' : 'status-in-progress';
            return `
              <tr>
                <td>
                  <strong>${this.escapeHtml(row.display_name)}</strong>
                  <span class="relay-muted">${this.escapeHtml(row.user_id)}</span>
                </td>
                <td>
                  ${this.escapeHtml(row.redeemed_source_node_id || row.source_node_id || 'node chooses')}
                  <code>${this.escapeHtml(row.code_prefix)}</code>
                </td>
                <td>${this.escapeHtml((row.scopes || []).join('/'))}</td>
                <td><span class="relay-status-chip ${stateClass}">${this.escapeHtml(state)}</span></td>
                <td class="relay-table-actions">
                  ${row.redeemed_at ? '' : `<button class="relay-table-action danger" type="button" data-invite-delete="${this.escapeHtml(row.code_prefix)}">Revoke</button>`}
                </td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    `;
  }

  applyShareDefaults() {
    if (!this.settings) return;
    // Left blank on purpose — the server auto-derives a per-memory version
    // from updated_at when omitted, which is now the sane default (see
    // shareMemory/shareProject). No static prefill.
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
      if (await this.copyText(token)) {
        showToast('Relay token copied.', 'success');
      } else {
        showToast('Copy failed.', 'error');
      }
    });
  }

  async copyText(text) {
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch {
        // fall through to legacy fallback below
      }
    }
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    let succeeded = false;
    try {
      succeeded = document.execCommand('copy');
    } catch {
      succeeded = false;
    }
    document.body.removeChild(textarea);
    return succeeded;
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

  renderDeadLetters(rows) {
    const target = this.querySelector('#relay-dead-letter-list');
    if (!target) return;
    if (!rows?.length) {
      target.innerHTML = this.renderEmpty('No dead letters');
      return;
    }
    target.innerHTML = `
      <div class="relay-dead-letter-header">
        <div>
          <strong>Dead letters</strong>
          <span>${rows.length.toLocaleString()} shown</span>
        </div>
        <button class="secondary-button relay-panel-button" id="relay-retry-dead-letters" type="button">
          Retry all
        </button>
      </div>
      <div class="relay-dead-letter-items">
        ${rows.map((row) => {
          const ref = row.queue === 'outbox'
            ? (row.idempotency_key || row.id)
            : (row.ref_id || row.raw_event_id || row.id);
          return `
            <article class="relay-dead-letter-item">
              <div class="relay-dead-letter-main">
                <div class="relay-dead-letter-meta">
                  <span class="relay-status-chip status-dead_letter">${this.escapeHtml(row.queue)}</span>
                  <span>${Number(row.attempts || 0).toLocaleString()} attempts</span>
                  <span>${this.formatDate(row.updated_at)}</span>
                </div>
                <code>${this.escapeHtml(ref)}</code>
                <p>${this.escapeHtml(row.last_error || 'No error recorded')}</p>
              </div>
              <button
                class="secondary-button relay-panel-button"
                type="button"
                data-retry-dead-letter
                data-queue="${this.escapeHtml(row.queue)}"
                data-job-id="${this.escapeHtml(row.id)}"
              >
                Retry
              </button>
            </article>
          `;
        }).join('')}
      </div>
    `;
  }

  renderRelayMemories(rows) {
    const target = this.querySelector('#relay-memory-table');
    if (!target) return;
    if (!rows?.length) {
      target.innerHTML = this.renderEmpty('No relay memories received');
      return;
    }
    target.innerHTML = `
      <table class="relay-table relay-memory-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Memory</th>
            <th>Project</th>
            <th>Source</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              <td>
                <span class="relay-status-chip ${this.statusClass(row.visible ? 'visible' : 'hidden')}">
                  ${row.visible ? 'visible' : 'hidden'}
                </span>
                ${row.enriched ? '<span class="relay-status-chip status-completed">enriched</span>' : '<span class="relay-status-chip status-pending">pending LLM</span>'}
              </td>
              <td>
                <div class="relay-memory-cell">
                  <strong>${this.escapeHtml(row.title || row.kind || 'relay memory')}</strong>
                  <span>${this.escapeHtml(row.abstract || row.content_preview || 'No content preview')}</span>
                  <code>${this.escapeHtml(row.source_memory_id)}</code>
                </div>
              </td>
              <td>
                <span>${this.escapeHtml(row.team_project_id)}</span>
                <br><span class="relay-muted">${this.escapeHtml(row.source_project_key)}</span>
              </td>
              <td>
                <span>${this.escapeHtml(row.source_node_id)}</span>
                <br><span class="relay-muted">v${Number(row.source_version || 0)}</span>
              </td>
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
    this.querySelector('#relay-dead-letter-list').innerHTML = this.renderEmpty('Dead letters unavailable');
    this.querySelector('#relay-outbox-table').innerHTML = this.renderEmpty('Outbox unavailable');
    this.querySelector('#relay-queue-table').innerHTML = this.renderEmpty('Worker queue unavailable');
    this.querySelector('#relay-memory-table').innerHTML = this.renderEmpty('Relay memories unavailable');
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

  formatTime(value) {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
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
