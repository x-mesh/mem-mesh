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
        this.rulesCache = new Map();
        this.progressErrorCount = 0;
    }

    connectedCallback() {
        this.render();
        this.bindEvents();
        this.loadSystemInfo();
        this.loadStatus();
        this.loadRulesIndex();
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

      <!-- Embedding Status -->
      <div class="settings-section">
        <div class="section-header">
          <span class="section-label">Embedding Status</span>
          <button class="section-action" id="refresh-status-btn" title="Refresh">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"/></svg>
          </button>
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
          <p class="section-desc">Select rules to merge, then copy or save the result.</p>
          <div class="rules-grid">
            <div class="rules-col">
              <div class="rules-list" id="rules-list">
                <div class="settings-loading">
                  <div class="settings-spinner"></div>
                  <span>Loading rules...</span>
                </div>
              </div>
              <div class="rules-btns">
                <button id="merge-rules-btn" class="settings-btn-primary">Merge</button>
                <button id="copy-rules-btn" class="settings-btn">Copy</button>
                <button id="download-rules-btn" class="settings-btn">Download</button>
              </div>
              <div class="rules-save-row">
                <select id="rules-target-select" class="settings-select"></select>
                <button id="save-rules-btn" class="settings-btn-primary">Save</button>
              </div>
            </div>
            <div class="rules-col">
              <textarea id="rules-output" class="rules-textarea" rows="14" placeholder="Merged output will appear here..."></textarea>
            </div>
          </div>
        </div>
      </div>

      <!-- OAuth -->
      <div class="settings-section">
        <div class="section-header">
          <span class="section-label">OAuth / Authentication</span>
        </div>
        <div class="section-body">
          <p class="section-desc">Manage OAuth 2.1 clients for MCP authentication.</p>
          <div class="oauth-row">
            <a href="/oauth" class="settings-btn-primary" data-route="/oauth">Manage OAuth Clients</a>
          </div>
          <div class="oauth-env">
            <span class="env-title">Environment Variables</span>
            <div class="env-list">
              <div class="env-item"><code>MEM_MESH_AUTH_ENABLED</code><span>Global auth toggle</span></div>
              <div class="env-item"><code>MEM_MESH_MCP_AUTH_ENABLED</code><span>MCP SSE auth</span></div>
              <div class="env-item"><code>MEM_MESH_WEB_AUTH_ENABLED</code><span>Web API auth</span></div>
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
        this.querySelector('#refresh-status-btn')?.addEventListener('click', () => this.loadStatus());
        this.querySelector('#start-migration-btn')?.addEventListener('click', () => this.startMigration());
        this.querySelector('#refresh-rules-btn')?.addEventListener('click', () => this.loadRulesIndex());
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

    async loadRulesIndex() {
        const el = this.querySelector('#rules-list');
        if (!el) return;

        el.innerHTML = `<div class="settings-loading"><div class="settings-spinner"></div><span>Loading rules...</span></div>`;

        try {
            const data = await window.app.apiClient.get('/rules');
            this.rulesIndex = data.rules || [];
            this.renderRulesList();
            this.renderRulesTargets();
        } catch (error) {
            console.error('Failed to load rules index:', error);
            el.innerHTML = `<div class="settings-error">Failed to load rules: ${error.message}</div>`;
        }
    }

    renderRulesList() {
        const el = this.querySelector('#rules-list');
        if (!el) return;

        if (!this.rulesIndex || this.rulesIndex.length === 0) {
            el.innerHTML = '<span class="section-desc">No rules available.</span>';
            return;
        }

        el.innerHTML = '';
        this.rulesIndex.forEach((rule) => {
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
        (this.rulesIndex || []).forEach((rule) => {
            const opt = document.createElement('option');
            opt.value = rule.id;
            opt.textContent = `${rule.title} (${rule.id})`;
            select.appendChild(opt);
        });
    }

    getSelectedRuleIds() {
        const boxes = this.querySelectorAll('#rules-list input[type="checkbox"]');
        const selected = Array.from(boxes).filter(c => c.checked).map(c => c.value);
        if (!selected.includes('core')) selected.unshift('core');
        return selected;
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
}

.env-item span {
  color: var(--text-muted);
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

  .rules-grid {
    grid-template-columns: 1fr;
  }

  .migration-row {
    flex-direction: column;
    align-items: flex-start;
  }
}

@media (prefers-reduced-motion: reduce) {
  .settings-spinner {
    animation: none;
  }
}
`;

document.head.appendChild(style);
