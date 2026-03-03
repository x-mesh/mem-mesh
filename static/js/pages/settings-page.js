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

      <!-- Info -->
      <div class="settings-section">
        <div class="section-header">
          <span class="section-label">Information</span>
        </div>
        <div class="section-body settings-info">
          <div class="info-block">
            <span class="info-heading">Embedding Models</span>
            <p>Uses <code>sentence-transformers</code> for text-to-vector conversion.</p>
            <ul>
              <li><strong>all-MiniLM-L6-v2</strong> — Fast, lightweight English (384d)</li>
              <li><strong>intfloat/multilingual-e5-small</strong> — Multilingual (384d)</li>
            </ul>
          </div>
          <div class="info-block">
            <span class="info-heading">Migration</span>
            <p>When the model changes, existing memories need re-embedding. Runs in batches with live progress.</p>
          </div>
          <div class="info-block">
            <span class="info-heading">Configuration</span>
            <p>Set model via <code>MEM_MESH_EMBEDDING_MODEL</code> in <code>.env</code>.</p>
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

        container.innerHTML = `
      <div class="status-grid">
        <div class="status-cell">
          <span class="status-label">DB Model</span>
          <span class="status-value">${d.stored_model || '(not set)'}</span>
        </div>
        <div class="status-cell">
          <span class="status-label">DB Dimension</span>
          <span class="status-value">${d.stored_dimension || '(not set)'}</span>
        </div>
        <div class="status-cell">
          <span class="status-label">Current Model</span>
          <span class="status-value status-highlight">${d.current_model}</span>
        </div>
        <div class="status-cell">
          <span class="status-label">Current Dimension</span>
          <span class="status-value">${d.current_dimension}</span>
        </div>
        <div class="status-cell">
          <span class="status-label">Memories</span>
          <span class="status-value">${d.total_memories.toLocaleString()}</span>
        </div>
        <div class="status-cell">
          <span class="status-label">Vectors</span>
          <span class="status-value">${d.vector_count.toLocaleString()}</span>
        </div>
        <div class="status-cell">
          <span class="status-label">Last Migration</span>
          <span class="status-value">${d.last_migration ? new Date(d.last_migration).toLocaleString() : '(never)'}</span>
        </div>
        <div class="status-cell">
          <span class="status-label">Status</span>
          <span class="status-value ${ok ? '' : 'status-warn'}">${ok ? 'OK' : 'Migration needed'}</span>
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

/* Status grid */

.status-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-2);
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
