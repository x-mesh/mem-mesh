/**
 * Curation Page — two tabs (SSOT #3 F4).
 *
 * Pending: reconcile queue (human gate). Reviews PROPOSED relations
 *   (supersede/conflict) produced by the async reconcile worker:
 *   approve (deprecate old) / deprecate new (C3) / dismiss.
 * Activity: LLM worker queues (Enrichment/Digest/Reconcile) — per-status
 *   counts + recent processing log. Read-only.
 * REST: /api/curation/*.
 */

export class CurationPage extends HTMLElement {
  connectedCallback() {
    this._activeTab = 'pending';
    this._activityFilter = 'all';
    this._activityData = null;
    this._activityLoaded = false;
    this.innerHTML = this._skeleton();
    this._injectStyles();
    this.addEventListener('click', (e) => this._onClick(e));
    this._applyDeepLink();
    this.loadData();
  }

  /**
   * Honor /curation?tab=...&filter=... — the project-card progress bar links
   * here so a stuck/failing batch can be investigated in one click.
   */
  _applyDeepLink() {
    let params;
    try {
      params = new URLSearchParams(window.location.search);
    } catch (_) {
      return;
    }
    const filter = params.get('filter');
    if (filter && this.querySelector(`.cur-filter-btn[data-filter="${filter}"]`)) {
      this._activityFilter = filter;
      this.querySelectorAll('.cur-filter-btn').forEach((b) =>
        b.classList.toggle('cur-filter-active', b.dataset.filter === filter)
      );
    }
    const tab = params.get('tab');
    if (tab && this.querySelector(`.cur-tab-btn[data-tab="${tab}"]`)) {
      this._switchTab(tab);
    }
  }

  disconnectedCallback() {
    this._stopActivityPoll();
  }

  _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  _msg(text, isError = false) {
    const el = this.querySelector('.cur-msg');
    if (!el) return;
    el.textContent = text;
    el.className = `cur-msg${isError ? ' cur-msg-error' : ' cur-msg-ok'}`;
    if (text) setTimeout(() => {
      el.textContent = '';
      el.className = 'cur-msg';
    }, 2600);
  }

  _improveMsg(text, isError = false) {
    const el = this.querySelector('.cur-improve-msg');
    if (!el) return;
    el.textContent = text;
    // Keep the base class so a subsequent querySelector('.cur-improve-msg')
    // (e.g. a rapid second message) still finds this element.
    el.className = `cur-improve-msg${isError ? ' cur-msg-error' : ' cur-msg-ok'}`;
    if (text) setTimeout(() => {
      el.textContent = '';
      el.className = 'cur-improve-msg';
    }, 2600);
  }

  // ---- Pending tab (reconcile queue) --------------------------------------

  async loadData() {
    const api = window.app?.apiClient;
    const list = this.querySelector('.cur-list');
    if (!api) {
      list.innerHTML = '<div class="cur-empty">API client unavailable.</div>';
      return;
    }
    list.innerHTML = '<div class="cur-empty">Loading…</div>';
    try {
      const res = await api.getCurationQueue();
      this._render(res?.items || []);
    } catch (e) {
      list.innerHTML = `<div class="cur-empty cur-msg-error">Failed to load: ${this._esc(
        e.message
      )}</div>`;
    }
  }

  _render(items) {
    const list = this.querySelector('.cur-list');
    const count = this.querySelector('.cur-count');
    if (count) count.textContent = String(items.length);
    if (!items.length) {
      list.innerHTML =
        '<div class="cur-empty">No reconcile proposals to review.</div>';
      return;
    }
    list.innerHTML = items.map((it) => this._row(it)).join('');
  }

  _row(it) {
    const meta = it.metadata || {};
    const isSupersede = it.relation_type === 'supersedes';
    const isMerge = meta.verdict === 'merge';
    const approveBtn = isSupersede
      ? `<button class="cur-btn cur-approve" data-relation="${this._esc(
          it.id
        )}">✓ Approve · deprecate old</button>`
      : '';
    const mergeBlock = isMerge
      ? `
        <div class="cur-merge">
          <h4>🔀 Merged result (LLM proposal · editable)</h4>
          <textarea class="cur-merged">${this._esc(meta.merged_text || '')}</textarea>
        </div>`
      : '';
    const mergeBtn = isMerge
      ? `<button class="cur-btn cur-approve-merge" data-relation="${this._esc(
          it.id
        )}">🔀 Approve merge</button>`
      : '';
    return `
      <div class="cur-card" data-relation="${this._esc(it.id)}">
        <div class="cur-head">
          <span class="cur-type cur-type-${this._esc(it.relation_type)}">${this._esc(
            it.relation_type
          )}</span>
          ${meta.verdict ? `<span class="cur-verdict">${this._esc(meta.verdict)}</span>` : ''}
        </div>
        ${meta.rationale ? `<div class="cur-rationale">💡 ${this._esc(meta.rationale)}</div>` : ''}
        <div class="cur-cols">
          <div class="cur-col">
            <h4>NEW (source · <code>${this._esc(String(it.source_id).slice(0, 8))}</code>)</h4>
            <pre>${this._esc(it.source_preview || '')}</pre>
          </div>
          <div class="cur-col">
            <h4>OLD (target · <code>${this._esc(String(it.target_id).slice(0, 8))}</code>)</h4>
            <pre>${this._esc(it.target_preview || '')}</pre>
          </div>
        </div>
        ${mergeBlock}
        <div class="cur-actions">
          ${approveBtn}
          ${mergeBtn}
          <button class="cur-btn cur-reject" data-memory="${this._esc(
            it.source_id
          )}">✗ Deprecate new</button>
          <button class="cur-btn cur-dismiss" data-relation="${this._esc(
            it.id
          )}">Keep · dismiss</button>
        </div>
      </div>`;
  }

  // ---- Activity tab (worker queues) ---------------------------------------

  async loadActivity(opts = {}) {
    const api = window.app?.apiClient;
    const list = this.querySelector('.cur-activity-list');
    if (!api) {
      if (list) list.innerHTML = '<div class="cur-empty">API client unavailable.</div>';
      return;
    }
    // Silent (poll) refreshes must not flash a "Loading…" wipe.
    if (!opts.silent && list) {
      list.innerHTML = '<div class="cur-empty">Loading…</div>';
    }
    try {
      // Status endpoints must never serve APIClient's permanent GET cache, or
      // the 3s poll just re-returns the first (stale) snapshot forever.
      api.invalidateCache?.('/curation/activity');
      const res = await api.get('/curation/activity');
      this._activityData = res?.workers || [];
      this._activityLoaded = true;
      this.renderActivity();
    } catch (e) {
      if (!opts.silent && list) {
        list.innerHTML = `<div class="cur-empty cur-msg-error">Failed to load: ${this._esc(
          e.message
        )}</div>`;
      }
    }
  }

  _startActivityPoll() {
    this._stopActivityPoll();
    // Mirror the relay Operations tab: live 3s refresh while viewing.
    this._activityPollTimer = setInterval(() => {
      if (this._activeTab === 'activity' && !document.hidden) {
        this.loadActivity({ silent: true });
      }
    }, 3000);
  }

  _stopActivityPoll() {
    if (this._activityPollTimer) {
      clearInterval(this._activityPollTimer);
      this._activityPollTimer = null;
    }
  }

  renderActivity() {
    const list = this.querySelector('.cur-activity-list');
    if (!list) return;
    const workers = this._activityData || [];
    const f = this._activityFilter;
    const filtered =
      f === 'all'
        ? workers
        : workers.filter((w) => w.key === f || String(w.key).startsWith(f + ':'));
    if (!filtered.length) {
      list.innerHTML = '<div class="cur-empty">No worker activity.</div>';
      return;
    }
    list.innerHTML = filtered.map((w) => this._workerCard(w)).join('');
  }

  _subjectLink(s) {
    const shortId = String(s.memory_id).replace(/^relay:/, '').slice(0, 8);
    const title = s.title
      ? `<span class="cur-subject-title">${this._esc(s.title)}</span>`
      : '<span class="cur-subject-title cur-muted">(untitled)</span>';
    if (!s.exists) {
      return `<span class="cur-subject cur-subject-gone" title="memory no longer exists">
        <code>${this._esc(shortId)}</code> ${title} <span class="cur-muted">· deleted</span>
      </span>`;
    }
    const href = `/memory/${encodeURIComponent(s.memory_id)}`;
    return `<a class="cur-subject" href="${href}" data-route="${href}" title="${this._esc(
      s.memory_id
    )}"><code>${this._esc(shortId)}</code> ${title}</a>`;
  }

  _shortTime(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      return d.toLocaleString();
    } catch (_) {
      return iso;
    }
  }

  _workerCard(w) {
    const counts = w.counts || {};
    const order = ['pending', 'processing', 'done', 'dead_letter', 'stale'];
    const keys = Object.keys(counts).sort((a, b) => {
      const ia = order.indexOf(a);
      const ib = order.indexOf(b);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
    const badges = keys.length
      ? keys
          .map(
            (s) =>
              `<span class="cur-badge cur-badge-${this._esc(s)}">${this._esc(
                s
              )} <b>${this._esc(String(counts[s]))}</b></span>`
          )
          .join('')
      : '<span class="cur-badge">empty</span>';
    const isMaintenance = String(w.key).startsWith('maintenance:');
    const recentRows = (w.recent || [])
      .map((r) => {
        // last_error only means "failing" on dead_letter / pending-retry rows;
        // a done row keeps no error (cleared on success), and stale snapshots
        // from before that fix must not read as failures.
        const failing =
          r.status === 'dead_letter' ||
          (r.status === 'pending' && (r.attempts || 0) > 0);
        const err = failing && r.last_error
          ? `<div class="cur-recent-err">${this._esc(r.last_error)}</div>`
          : '';
        const retryBtn = isMaintenance && r.status === 'dead_letter'
          ? `<button class="cur-btn cur-retry-job" data-retry-job="${this._esc(
              String(r.id)
            )}" title="Requeue this failed job">retry</button>`
          : '';
        const op = r.operation
          ? `<span class="cur-recent-op">${this._esc(r.operation)}</span>`
          : '';
        const subjects = (r.subjects || []).length
          ? `<div class="cur-recent-subjects">${(r.subjects || [])
              .map((s) => this._subjectLink(s))
              .join('')}</div>`
          : `<code class="cur-recent-id" title="queue job id">${this._esc(
              String(r.id).slice(0, 8)
            )}</code>`;
        return `
          <div class="cur-recent-row">
            <div class="cur-recent-main">
              ${op}${subjects}
            </div>
            ${retryBtn}
            <span class="cur-recent-status cur-badge-${this._esc(
              r.status
            )}">${this._esc(r.status)}</span>
            <span class="cur-recent-time">${this._esc(
              this._shortTime(r.updated_at)
            )}</span>
            ${err}
          </div>`;
      })
      .join('');
    const recentBlock =
      w.recent && w.recent.length
        ? `<div class="cur-recent">${recentRows}</div>`
        : '<div class="cur-recent-empty">No recent activity.</div>';
    // Progress: how many of the total jobs have finished (done + stale count as
    // resolved). "N of M" answers "how far along is this batch".
    const done = (counts.done || 0) + (counts.stale || 0);
    const failed = counts.dead_letter || 0;
    const active = (counts.pending || 0) + (counts.processing || 0);
    const total = done + failed + active;
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    const running = (counts.processing || 0) > 0;
    const progress = total > 0
      ? `<div class="cur-progress">
           <div class="cur-progress-bar"><div class="cur-progress-fill${failed ? ' has-failed' : ''}" style="width:${pct}%"></div></div>
           <div class="cur-progress-label">
             <span class="cur-progress-count">${done} / ${total} done</span>
             ${active ? `<span class="cur-muted">· ${active} left${running ? ' · running' : ''}</span>` : ''}
             ${failed ? `<span class="cur-progress-failed">· ${failed} failed</span>` : ''}
           </div>
         </div>`
      : '';
    // Cancel control: only maintenance (enrich/improve) jobs are cancelable,
    // and only when there's a pending backlog to stop.
    const cancelBtn = isMaintenance && (counts.pending || 0) > 0
      ? `<button class="cur-btn cur-cancel" data-cancel-op="${this._esc(
          String(w.key).split(':')[1] || ''
        )}">Cancel ${counts.pending} pending</button>`
      : '';
    // Retry control: requeue this operation's dead-lettered jobs.
    const retryAllBtn = isMaintenance && failed > 0
      ? `<button class="cur-btn cur-retry" data-retry-op="${this._esc(
          String(w.key).split(':')[1] || ''
        )}">Retry ${failed} failed</button>`
      : '';
    return `
      <div class="cur-card cur-worker" data-worker="${this._esc(w.key)}">
        <div class="cur-worker-head">
          <h3>${this._esc(w.label || w.key)}</h3>
          ${running ? '<span class="cur-worker-live">● running</span>' : ''}
          ${retryAllBtn}
          ${cancelBtn}
        </div>
        ${progress}
        <div class="cur-badges">${badges}</div>
        ${recentBlock}
      </div>`;
  }

  // ---- Tabs & events ------------------------------------------------------

  _switchTab(tab) {
    if (!tab || tab === this._activeTab) return;
    this._activeTab = tab;
    this.querySelectorAll('.cur-tab-btn').forEach((b) =>
      b.classList.toggle('cur-tab-active', b.dataset.tab === tab)
    );
    this.querySelectorAll('.cur-tab-panel').forEach((p) => {
      p.hidden = p.dataset.tabPanel !== tab;
    });
    if (tab === 'activity') {
      if (!this._activityLoaded) this.loadActivity();
      this._startActivityPoll();
    } else {
      this._stopActivityPoll();
    }
    if (tab === 'improve') {
      this.loadImproveProposals();
    }
  }

  async loadImproveProposals() {
    const api = window.app?.apiClient;
    const list = this.querySelector('.cur-improve-list');
    if (!api || !list) return;
    list.innerHTML = '<div class="cur-empty">Loading…</div>';
    try {
      api.invalidateCache?.('/maintenance/proposals');
      const data = await api.get('/maintenance/proposals');
      const proposals = data?.proposals || [];
      const countEl = this.querySelector('.cur-improve-count');
      if (countEl) countEl.textContent = String(proposals.length);
      this.renderImproveProposals(proposals);
    } catch (err) {
      list.innerHTML = `<div class="cur-empty">Failed to load: ${this._esc(err.message)}</div>`;
    }
  }

  renderImproveProposals(proposals) {
    const list = this.querySelector('.cur-improve-list');
    if (!list) return;
    if (!proposals.length) {
      list.innerHTML = '<div class="cur-empty">No pending improve proposals. Run Improve from a project’s Maintenance action.</div>';
      return;
    }
    list.innerHTML = proposals.map((p) => `
      <div class="cur-card cur-improve-card" data-proposal="${this._esc(p.id)}">
        <div class="cur-head">
          <span class="cur-type">improve</span>
          <span class="cur-muted">${this._esc(p.project_id || '')} · ${this._esc(p.memory_id)}</span>
          ${p.stale ? '<span class="cur-type cur-type-supersedes">stale — memory changed</span>' : ''}
        </div>
        ${p.rationale ? `<p class="cur-hint">${this._esc(p.rationale)}</p>` : ''}
        <div class="cur-diff">
          <div class="cur-diff-col">
            <div class="cur-diff-label">Current</div>
            <pre class="cur-diff-text cur-diff-old">${this._esc(p.original_content || '')}</pre>
          </div>
          <div class="cur-diff-col">
            <div class="cur-diff-label">Proposed</div>
            <pre class="cur-diff-text cur-diff-new">${this._esc(p.proposed_content || '')}</pre>
          </div>
        </div>
        <div class="cur-actions">
          <button class="cur-btn cur-improve-approve" data-proposal="${this._esc(p.id)}" ${p.stale ? 'disabled title="Memory changed since this proposal"' : ''}>Approve &amp; apply</button>
          <button class="cur-btn cur-improve-reject" data-proposal="${this._esc(p.id)}">Reject</button>
        </div>
      </div>`).join('');
  }

  async _onClick(e) {
    const tabBtn = e.target.closest('.cur-tab-btn');
    if (tabBtn) {
      this._switchTab(tabBtn.dataset.tab);
      return;
    }
    const filterBtn = e.target.closest('.cur-filter-btn');
    if (filterBtn) {
      this._activityFilter = filterBtn.dataset.filter || 'all';
      this.querySelectorAll('.cur-filter-btn').forEach((b) =>
        b.classList.toggle(
          'cur-filter-active',
          b.dataset.filter === this._activityFilter
        )
      );
      this.renderActivity();
      return;
    }
    if (e.target.closest('.cur-activity-refresh')) {
      this.loadActivity();
      return;
    }
    if (e.target.closest('.cur-improve-refresh')) {
      this.loadImproveProposals();
      return;
    }
    const cancelBtn = e.target.closest('.cur-cancel');
    if (cancelBtn) {
      const op = cancelBtn.dataset.cancelOp || '';
      const api = window.app?.apiClient;
      if (!api) return;
      if (!window.confirm(`Cancel all pending ${op || 'maintenance'} jobs? A job already running finishes; the rest are dropped.`)) return;
      cancelBtn.disabled = true;
      try {
        const res = await api.post('/maintenance/cancel', op ? { operation: op } : {});
        this._msg(`Cancelled ${res?.cancelled ?? 0} pending ${op} job(s).`);
        this.loadActivity({ silent: true });
      } catch (err) {
        this._msg(`Cancel failed: ${err?.data?.detail || err.message}`, true);
        cancelBtn.disabled = false;
      }
      return;
    }
    const retryBtn = e.target.closest('.cur-retry, .cur-retry-job');
    if (retryBtn) {
      const api = window.app?.apiClient;
      if (!api) return;
      const payload = retryBtn.dataset.retryJob
        ? { job_id: retryBtn.dataset.retryJob }
        : retryBtn.dataset.retryOp
          ? { operation: retryBtn.dataset.retryOp }
          : {};
      retryBtn.disabled = true;
      try {
        const res = await api.post('/maintenance/retry', payload);
        this._msg(`Requeued ${res?.retried ?? 0} failed job(s).`);
        this.loadActivity({ silent: true });
      } catch (err) {
        this._msg(`Retry failed: ${err?.data?.detail || err.message}`, true);
        retryBtn.disabled = false;
      }
      return;
    }

    const api = window.app?.apiClient;
    if (!api) return;

    const improveApprove = e.target.closest('.cur-improve-approve');
    const improveReject = e.target.closest('.cur-improve-reject');
    if (improveApprove || improveReject) {
      const pid = (improveApprove || improveReject).dataset.proposal;
      try {
        if (improveApprove) {
          if (!window.confirm('Apply this rewrite to the memory’s content?')) return;
          await api.post(`/maintenance/proposals/${encodeURIComponent(pid)}/approve`);
          this._improveMsg('Applied — the memory content was updated.');
        } else {
          await api.post(`/maintenance/proposals/${encodeURIComponent(pid)}/reject`);
          this._improveMsg('Proposal rejected.');
        }
        this.loadImproveProposals();
      } catch (err) {
        this._improveMsg(`Failed: ${err?.data?.detail || err.message}`, true);
      }
      return;
    }
    if (e.target.closest('.cur-refresh')) {
      this.loadData();
      return;
    }
    const approve = e.target.closest('.cur-approve');
    const merge = e.target.closest('.cur-approve-merge');
    const reject = e.target.closest('.cur-reject');
    const dismiss = e.target.closest('.cur-dismiss');
    if (!approve && !merge && !reject && !dismiss) return;

    try {
      if (approve) {
        await api.approveCurationSupersede(approve.dataset.relation);
        this._msg('Approved — the old memory was deprecated.');
      } else if (merge) {
        const card = merge.closest('.cur-card');
        const mergedText = card?.querySelector('.cur-merged')?.value || null;
        if (!window.confirm('Merge the two memories and deprecate both originals?')) return;
        await api.approveCurationMerge(merge.dataset.relation, mergedText);
        this._msg('Merged — created a new memory and deprecated both originals.');
      } else if (reject) {
        if (!window.confirm('Deprecate this new memory?')) return;
        await api.rejectCurationNew(reject.dataset.memory);
        this._msg('The new memory was deprecated.');
      } else if (dismiss) {
        await api.dismissCuration(dismiss.dataset.relation);
        this._msg('Proposal dismissed.');
      }
      this.loadData();
    } catch (err) {
      this._msg(`Failed: ${err.message}`, true);
    }
  }

  _skeleton() {
    return `
      <div class="cur-page">
        <div class="cur-tabs">
          <button class="cur-tab-btn cur-tab-active" data-tab="pending">Reconcile</button>
          <button class="cur-tab-btn" data-tab="improve">Improve</button>
          <button class="cur-tab-btn" data-tab="activity">Activity</button>
        </div>

        <div class="cur-tab-panel cur-tab-panel-pending" data-tab-panel="pending">
          <div class="cur-header">
            <h1>Reconcile Curation <span class="cur-count-badge">(<span class="cur-count">0</span>)</span></h1>
            <button class="cur-btn cur-refresh">Refresh</button>
          </div>
          <p class="cur-hint">Conflict/duplicate proposals detected by the async reconcile worker. Memories are deprecated only on approval.</p>
          <div class="cur-msg"></div>
          <div class="cur-list"></div>
        </div>

        <div class="cur-tab-panel cur-tab-panel-improve" data-tab-panel="improve" hidden>
          <div class="cur-header">
            <h1>Improve Proposals <span class="cur-count-badge">(<span class="cur-improve-count">0</span>)</span></h1>
            <button class="cur-btn cur-improve-refresh">Refresh</button>
          </div>
          <p class="cur-hint">Rewritten content proposed by batch Improve. Nothing is applied until you approve — the memory's content only changes on approval.</p>
          <div class="cur-improve-msg"></div>
          <div class="cur-improve-list"></div>
        </div>

        <div class="cur-tab-panel cur-tab-panel-activity" data-tab-panel="activity" hidden>
          <div class="cur-header">
            <h1>Worker Activity</h1>
            <button class="cur-btn cur-activity-refresh">Refresh</button>
          </div>
          <p class="cur-hint">LLM worker queues — per-status counts and recent processing log.</p>
          <div class="cur-filters">
            <button class="cur-filter-btn cur-filter-active" data-filter="all">All</button>
            <button class="cur-filter-btn" data-filter="item">Enrichment</button>
            <button class="cur-filter-btn" data-filter="aggregate">Digest</button>
            <button class="cur-filter-btn" data-filter="reconcile">Reconcile</button>
            <button class="cur-filter-btn" data-filter="maintenance">Maintenance</button>
          </div>
          <div class="cur-activity-list"></div>
        </div>
      </div>`;
  }

  _injectStyles() {
    if (document.getElementById('curation-page-styles')) return;
    const style = document.createElement('style');
    style.id = 'curation-page-styles';
    style.textContent = `
      .cur-page { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
      .cur-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border-color); margin-bottom: 18px; }
      .cur-tab-btn { padding: 8px 16px; border: none; background: transparent; color: var(--text-secondary); cursor: pointer; font-size: 0.95rem; border-bottom: 2px solid transparent; margin-bottom: -1px; }
      .cur-tab-btn:hover { color: var(--text-primary); }
      .cur-tab-active { color: var(--text-primary); border-bottom-color: var(--info, #3b82f6); font-weight: 600; }
      .cur-header { display: flex; justify-content: space-between; align-items: center; }
      .cur-header h1 { font-size: 1.4rem; color: var(--text-primary); }
      .cur-count-badge { color: var(--text-secondary); font-weight: 400; }
      .cur-hint { color: var(--text-secondary); font-size: 0.9rem; margin: 6px 0 14px; }
      .cur-msg { min-height: 20px; font-size: 0.9rem; margin-bottom: 10px; }
      .cur-msg-ok { color: var(--text-secondary); }
      .cur-msg-error { color: var(--error-color, #ef4444); }
      .cur-empty { color: var(--text-secondary); text-align: center; padding: 40px 0; }
      .cur-card { background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 12px; padding: 14px 16px; margin-bottom: 14px; }
      .cur-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
      .cur-type { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border-color); color: var(--text-secondary); }
      .cur-type-supersedes { color: #b45309; border-color: #f59e0b; }
      .cur-diff { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 10px 0; }
      .cur-diff-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-secondary); margin-bottom: 4px; }
      .cur-diff-text { white-space: pre-wrap; word-break: break-word; font-size: 0.82rem; line-height: 1.5; max-height: 260px; overflow: auto; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border-color); margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
      .cur-diff-old { background: var(--bg-tertiary); color: var(--text-secondary); }
      .cur-diff-new { background: color-mix(in oklch, var(--success-color, #16a34a) 8%, var(--bg-secondary)); color: var(--text-primary); }
      .cur-improve-msg { min-height: 20px; font-size: 0.9rem; margin-bottom: 10px; }
      @media (max-width: 640px) { .cur-diff { grid-template-columns: 1fr; } }
      .cur-type-conflicts { color: var(--error-color, #ef4444); border-color: var(--error-color, #ef4444); }
      .cur-verdict { font-size: 0.8rem; color: var(--text-secondary); }
      .cur-rationale { font-size: 0.88rem; color: var(--info, #3b82f6); margin-bottom: 10px; }
      .cur-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
      .cur-col h4 { margin: 0 0 6px; font-size: 0.72rem; text-transform: uppercase; color: var(--text-secondary); }
      .cur-col h4 code { color: var(--text-secondary); }
      .cur-col pre { background: var(--bg-primary); color: var(--text-primary); border: 1px solid var(--border-color); border-radius: 8px; padding: 8px 10px; margin: 0; max-height: 160px; overflow: auto; white-space: pre-wrap; word-break: break-word; font-size: 0.82rem; }
      .cur-merge { margin-bottom: 12px; }
      .cur-merge h4 { margin: 0 0 6px; font-size: 0.72rem; text-transform: uppercase; color: var(--info, #3b82f6); }
      .cur-merged { width: 100%; box-sizing: border-box; min-height: 90px; resize: vertical; background: var(--bg-primary); color: var(--text-primary); border: 1px solid var(--border-color); border-radius: 8px; padding: 8px 10px; font: inherit; font-size: 0.85rem; white-space: pre-wrap; }
      .cur-approve-merge { border-color: var(--info, #3b82f6); color: var(--info, #3b82f6); }
      .cur-actions { display: flex; gap: 8px; flex-wrap: wrap; }
      .cur-btn { padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border-color); background: var(--bg-primary); color: var(--text-primary); cursor: pointer; font-size: 0.85rem; }
      .cur-btn:hover { background: var(--bg-tertiary, var(--bg-secondary)); }
      .cur-approve { border-color: #16a34a; color: #16a34a; }
      .cur-reject { border-color: var(--error-color, #ef4444); color: var(--error-color, #ef4444); }
      .cur-filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
      .cur-filter-btn { padding: 5px 12px; border-radius: 999px; border: 1px solid var(--border-color); background: var(--bg-primary); color: var(--text-secondary); cursor: pointer; font-size: 0.82rem; }
      .cur-filter-btn:hover { background: var(--bg-tertiary, var(--bg-secondary)); color: var(--text-primary); }
      .cur-filter-active { border-color: var(--info, #3b82f6); color: var(--info, #3b82f6); }
      .cur-worker-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
      .cur-worker-head h3 { margin: 0; font-size: 1.05rem; color: var(--text-primary); }
      .cur-cancel { margin-left: auto; padding: 4px 10px; font-size: 0.78rem; border-color: var(--error-color, #ef4444); color: var(--error-color, #ef4444); background: transparent; }
      .cur-cancel:hover { background: var(--error-color, #ef4444); color: #fff; }
      .cur-cancel:disabled { opacity: 0.5; cursor: default; }
      .cur-retry { margin-left: auto; padding: 4px 10px; font-size: 0.78rem; border-color: var(--warning-color, #d97706); color: var(--warning-color, #d97706); background: transparent; }
      .cur-retry + .cur-cancel { margin-left: 0; }
      .cur-retry:hover { background: var(--warning-color, #d97706); color: #fff; }
      .cur-retry:disabled, .cur-retry-job:disabled { opacity: 0.5; cursor: default; }
      .cur-retry-job { padding: 2px 8px; font-size: 0.72rem; border-color: var(--warning-color, #d97706); color: var(--warning-color, #d97706); background: transparent; }
      .cur-retry-job:hover { background: var(--warning-color, #d97706); color: #fff; }
      .cur-worker-key { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-secondary); }
      .cur-badges { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
      .cur-badge { font-size: 0.76rem; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--border-color); background: var(--bg-primary); color: var(--text-secondary); }
      .cur-badge b { color: var(--text-primary); font-weight: 600; }
      .cur-recent-status { padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border-color); background: var(--bg-primary); color: var(--text-secondary); font-size: 0.74rem; }
      .cur-badge-processing { border-color: #3b82f6; color: #3b82f6; }
      .cur-badge-done { border-color: #16a34a; color: #16a34a; }
      .cur-badge-dead_letter { border-color: var(--error-color, #ef4444); color: var(--error-color, #ef4444); }
      .cur-badge-stale { border-color: #f59e0b; color: #b45309; }
      .cur-recent { display: flex; flex-direction: column; gap: 6px; }
      .cur-recent-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 0.82rem; padding: 6px 8px; background: var(--bg-primary); border: 1px solid var(--border-color); border-radius: 8px; }
      .cur-worker-live { font-size: 0.72rem; color: var(--success-color, #16a34a); font-weight: 600; }
      .cur-progress { margin: 8px 0 10px; }
      .cur-progress-bar { height: 6px; border-radius: 999px; background: var(--bg-tertiary); overflow: hidden; }
      .cur-progress-fill { height: 100%; background: var(--success-color, #16a34a); border-radius: 999px; transition: width 0.4s ease; }
      .cur-progress-fill.has-failed { background: linear-gradient(90deg, var(--success-color, #16a34a), var(--error-color, #ef4444)); }
      .cur-progress-label { margin-top: 4px; font-size: 0.78rem; color: var(--text-secondary); display: flex; gap: 6px; flex-wrap: wrap; }
      .cur-progress-count { font-weight: 600; color: var(--text-primary); }
      .cur-progress-failed { color: var(--error-color, #ef4444); }
      .cur-recent-id { color: var(--text-secondary); }
      .cur-recent-main { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; flex: 1; }
      .cur-recent-op { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.04em; padding: 1px 7px; border-radius: 999px; border: 1px solid var(--border-color); color: var(--text-secondary); }
      .cur-recent-subjects { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
      .cur-subject { display: inline-flex; align-items: baseline; gap: 6px; text-decoration: none; color: var(--text-primary); max-width: 100%; }
      .cur-subject:hover .cur-subject-title { text-decoration: underline; }
      .cur-subject code { color: var(--text-secondary); font-size: 0.74rem; flex-shrink: 0; }
      .cur-subject-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 46ch; }
      .cur-subject-gone { color: var(--text-muted); }
      .cur-muted { color: var(--text-muted); }
      .cur-recent-time { color: var(--text-secondary); margin-left: auto; white-space: nowrap; }
      .cur-recent-err { flex-basis: 100%; color: var(--error-color, #ef4444); font-size: 0.78rem; word-break: break-word; }
      .cur-recent-empty { color: var(--text-secondary); font-size: 0.85rem; padding: 8px 0; }
      @media (max-width: 640px) { .cur-cols { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }
}

customElements.define('curation-page', CurationPage);
