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
    this._activeTab = 'improve';
    this._activityFilter = 'all';
    this._activityData = null;
    this._activityLoaded = false;
    this._activeReconcilerRunId = null;
    this._reconcilerRunModes = new Map();
    this._reconcilerProjectPolicy = null;
    this._reconcilerPollTimer = null;
    this._reconcilerRefreshInFlight = false;
    this.innerHTML = this._skeleton();
    this._injectStyles();
    this.addEventListener('click', (e) => this._onClick(e));
    this.addEventListener('submit', (e) => {
      const form = e.target.closest('.cur-reconciler-run-form');
      if (!form) return;
      e.preventDefault();
      this.startReconcilerRun(form);
    });
    this.addEventListener('change', (e) => {
      if (e.target.closest('.cur-reconciler-project')) {
        this.loadLatestReconcilerRun();
        this.loadReconcilerProposals();
        this.loadReconcilerPolicy();
      }
    });
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
    // Compare dataset values in JS rather than interpolating the URL param
    // into a querySelector string — an unescaped value there (e.g. a `"]`
    // sequence) is a selector-syntax break, not just a lookup miss.
    const filter = params.get('filter');
    if (filter) {
      const known = Array.from(this.querySelectorAll('.cur-filter-btn')).some(
        (b) => b.dataset.filter === filter
      );
      if (known) {
        this._activityFilter = filter;
        this.querySelectorAll('.cur-filter-btn').forEach((b) =>
          b.classList.toggle('cur-filter-active', b.dataset.filter === filter)
        );
      }
    }
    const tab = params.get('tab');
    if (tab) {
      const known = Array.from(this.querySelectorAll('.cur-tab-btn')).some(
        (b) => b.dataset.tab === tab
      );
      if (known) this._switchTab(tab);
    }
  }

  disconnectedCallback() {
    this._stopActivityPoll();
    this._stopReconcilerPolling();
  }

  _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  _errText(error) {
    return error?.data?.detail || error?.message || String(error);
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
      await this.loadReconcilerProposals();
    } catch (e) {
      list.innerHTML = `<div class="cur-empty cur-msg-error">Failed to load: ${this._esc(
        e.message
      )}</div>`;
    }
  }

  async loadReconcilerProposals() {
    const api = window.app?.apiClient;
    const list = this.querySelector('.cur-reconciler-list');
    if (!api || !list) return;
    const requestId = (this._reconcilerProposalRequestId || 0) + 1;
    this._reconcilerProposalRequestId = requestId;
    const projectId = this.querySelector('.cur-reconciler-project')?.value;
    const count = this.querySelector('.cur-reconciler-count');
    if (!projectId) {
      if (count) count.textContent = '0';
      list.innerHTML = '<div class="cur-empty">Select a project to view its Memory Reconciler proposals.</div>';
      return;
    }
    list.innerHTML = '<div class="cur-empty">Loading…</div>';
    try {
      api.invalidateCache?.('/curation/reconciler/proposals');
      const statuses = ['needs_approval', 'needs_review', 'preview', 'applied'];
      const responses = await Promise.all(statuses.map((status) => {
        const params = new URLSearchParams({ status, project_id: projectId });
        return api.get('/curation/reconciler/proposals?' + params.toString());
      }));
      let proposals = responses.flatMap((response) => response?.proposals || [])
        .sort((left, right) => String(right.created_at || '').localeCompare(String(left.created_at || '')));
      proposals = await this._resolveReconcilerProposalStates(api, proposals);
      if (this._reconcilerProposalRequestId !== requestId
          || this.querySelector('.cur-reconciler-project')?.value !== projectId) return;
      if (count) count.textContent = String(proposals.length);
      if (!proposals.length) {
        list.innerHTML = '<div class="cur-empty">No Memory Reconciler results for this project.</div>';
        return;
      }
      list.innerHTML = proposals.map((proposal) => this._reconcilerRow(proposal)).join('');
    } catch (error) {
      if (this._reconcilerProposalRequestId !== requestId
          || this.querySelector('.cur-reconciler-project')?.value !== projectId) return;
      list.innerHTML = '<div class="cur-empty cur-msg-error">Failed to load: '
        + this._esc(this._errText(error)) + '</div>';
    }
  }

  async _resolveReconcilerProposalStates(api, proposals) {
    const runIds = Array.from(new Set(
      proposals
        .filter((proposal) => proposal.status === 'needs_approval' && proposal.run_id)
        .map((proposal) => proposal.run_id)
    ));
    await Promise.all(runIds.map(async (runId) => {
      if (!this._reconcilerRunModes.has(runId) || this._reconcilerRunModes.get(runId) === null) {
        const request = api.get('/curation/reconciler/runs/' + encodeURIComponent(runId))
          .then((run) => Boolean(run?.dry_run))
          .catch(() => null);
        this._reconcilerRunModes.set(runId, request);
      }
      const mode = await this._reconcilerRunModes.get(runId);
      this._reconcilerRunModes.set(runId, mode);
    }));
    return proposals.map((proposal) => {
      if (proposal.status !== 'needs_approval') return proposal;
      const dryRun = this._reconcilerRunModes.get(proposal.run_id);
      if (dryRun === true) return { ...proposal, status: 'preview' };
      if (dryRun !== false) return { ...proposal, status: 'unverified' };
      return proposal;
    });
  }

  async loadReconcilerProjects() {
    const api = window.app?.apiClient;
    const select = this.querySelector('.cur-reconciler-project');
    if (!api || !select) return;
    const selected = select.value;
    select.innerHTML = '<option value="">Loading projects…</option>';
    try {
      api.invalidateCache?.('/projects');
      const data = await api.get('/projects');
      const projects = data?.projects || [];
      select.innerHTML = projects.length
        ? '<option value="">Select a project</option>' + projects.map((project) => {
          const projectId = String(project.id || project.project_id || '');
          return '<option value="' + this._esc(projectId) + '"'
            + (projectId === selected ? ' selected' : '') + '>'
            + this._esc(project.name || projectId) + ' · ' + this._esc(project.memory_count || 0)
            + ' memories</option>';
        }).join('')
        : '<option value="">No projects found</option>';
      await this.loadReconcilerPolicy();
      if (select.value) await this.loadLatestReconcilerRun();
    } catch (error) {
      select.innerHTML = '<option value="">Failed to load projects</option>';
      this._setReconcilerRunMessage(this._errText(error), true);
    }
  }

  async loadReconcilerPolicy() {
    const api = window.app?.apiClient;
    const projectId = this.querySelector('.cur-reconciler-project')?.value;
    const checkbox = this.querySelector('.cur-reconciler-external-llm');
    const retention = this.querySelector('.cur-reconciler-retain-evidence');
    const button = this.querySelector('.cur-reconciler-policy-save');
    if (!checkbox || !retention || !button) return;
    this._reconcilerProjectPolicy = null;
    checkbox.checked = false;
    checkbox.disabled = true;
    retention.checked = true;
    retention.disabled = true;
    button.disabled = true;
    if (!api || !projectId) return;
    try {
      const policy = await api.get('/projects/' + encodeURIComponent(projectId) + '/policy');
      if (this.querySelector('.cur-reconciler-project')?.value !== projectId) return;
      this._reconcilerProjectPolicy = policy;
      checkbox.checked = Boolean(policy.allow_external_llm);
      checkbox.disabled = false;
      retention.checked = policy.retain_evidence_content !== false;
      retention.disabled = false;
      button.disabled = false;
    } catch (error) {
      checkbox.disabled = true;
      retention.disabled = true;
      button.disabled = true;
      this._setReconcilerRunMessage(this._errText(error), true);
    }
  }

  async saveReconcilerPolicy() {
    const api = window.app?.apiClient;
    const projectId = this.querySelector('.cur-reconciler-project')?.value;
    const checkbox = this.querySelector('.cur-reconciler-external-llm');
    const retention = this.querySelector('.cur-reconciler-retain-evidence');
    const button = this.querySelector('.cur-reconciler-policy-save');
    if (!api || !projectId || !checkbox || !retention || !button || !this._reconcilerProjectPolicy) return;
    button.disabled = true;
    try {
      const current = this._reconcilerProjectPolicy;
      const saved = await api.put(
        '/projects/' + encodeURIComponent(projectId) + '/policy',
        {
          auto_noise_suppression: Boolean(current.auto_noise_suppression),
          auto_derived_relations: Boolean(current.auto_derived_relations),
          allow_external_llm: checkbox.checked,
          retain_evidence_content: retention.checked,
        }
      );
      if (this.querySelector('.cur-reconciler-project')?.value !== projectId) return;
      this._reconcilerProjectPolicy = saved;
      this._setReconcilerRunMessage('Project LLM policy saved.', false);
    } catch (error) {
      this._setReconcilerRunMessage(this._errText(error), true);
      if (this.querySelector('.cur-reconciler-project')?.value === projectId) {
        checkbox.checked = Boolean(this._reconcilerProjectPolicy?.allow_external_llm);
        retention.checked = this._reconcilerProjectPolicy?.retain_evidence_content !== false;
      }
    } finally {
      if (this.querySelector('.cur-reconciler-project')?.value === projectId) {
        button.disabled = false;
      }
    }
  }

  async startReconcilerRun(form) {
    const api = window.app?.apiClient;
    const projectId = form.querySelector('.cur-reconciler-project')?.value;
    const button = form.querySelector('.cur-reconciler-run-start');
    if (!api || !projectId || !button) {
      this._setReconcilerRunMessage(
        projectId ? 'API client unavailable.' : 'Select a project first.', true
      );
      return;
    }
    button.disabled = true;
    button.textContent = 'Starting…';
    this._setReconcilerRunMessage('', false);
    try {
      const anchorPath = form.querySelector('.cur-reconciler-anchor-path')?.value.trim();
      const fromDate = form.querySelector('.cur-reconciler-from-date')?.value;
      const throughDate = form.querySelector('.cur-reconciler-through-date')?.value;
      if (fromDate && throughDate && fromDate > throughDate) {
        throw new Error('From date must not exceed through date.');
      }
      const request = {
        project_id: projectId,
        dry_run: Boolean(form.querySelector('.cur-reconciler-dry-run')?.checked),
      };
      if (anchorPath) request.anchored_path = anchorPath;
      if (fromDate) request.created_after = new Date(`${fromDate}T00:00:00`).toISOString();
      if (throughDate) request.created_before = new Date(`${throughDate}T23:59:59.999`).toISOString();
      const run = await api.post('/curation/reconciler/runs', request);
      if (this.querySelector('.cur-reconciler-project')?.value !== projectId) return;
      this._renderReconcilerRun(run);
      this._startReconcilerPolling();
      await this.loadReconcilerProposals();
    } catch (error) {
      if (this.querySelector('.cur-reconciler-project')?.value !== projectId) return;
      this._setReconcilerRunMessage(this._errText(error), true);
    } finally {
      button.disabled = false;
      button.textContent = 'Start run';
    }
  }

  async loadLatestReconcilerRun() {
    const api = window.app?.apiClient;
    const projectId = this.querySelector('.cur-reconciler-project')?.value;
    this._stopReconcilerPolling();
    this._activeReconcilerRunId = null;
    const status = this.querySelector('.cur-reconciler-run-status');
    const refresh = this.querySelector('.cur-reconciler-run-refresh');
    const cancel = this.querySelector('.cur-reconciler-run-cancel');
    const progress = this.querySelector('.cur-reconciler-progress');
    if (status) status.textContent = '';
    if (refresh) refresh.hidden = true;
    if (cancel) cancel.hidden = true;
    if (progress) progress.hidden = true;
    this.loadReconcilerAlerts();
    if (!api || !projectId) return;
    try {
      api.invalidateCache?.('/curation/reconciler/runs');
      const params = new URLSearchParams({ project_id: projectId, limit: '1' });
      const response = await api.get('/curation/reconciler/runs?' + params.toString());
      if (this.querySelector('.cur-reconciler-project')?.value !== projectId) return;
      const run = response?.runs?.[0];
      if (!run) return;
      this._renderReconcilerRun(run);
      if (!new Set(['completed', 'needs_approval', 'partial_success', 'failed', 'cancelled']).has(run.status)) {
        this._startReconcilerPolling();
      }
    } catch (error) {
      if (this.querySelector('.cur-reconciler-project')?.value === projectId) {
        this._setReconcilerRunMessage(this._errText(error), true);
      }
    }
  }

  async refreshReconcilerRun() {
    const api = window.app?.apiClient;
    if (!api || !this._activeReconcilerRunId || this._reconcilerRefreshInFlight) return;
    const runId = this._activeReconcilerRunId;
    this._reconcilerRefreshInFlight = true;
    try {
      const run = await api.get(
        '/curation/reconciler/runs/' + encodeURIComponent(runId)
      );
      if (this._activeReconcilerRunId !== runId) return;
      this._renderReconcilerRun(run);
      await this.loadReconcilerProposals();
      if (new Set(['completed', 'needs_approval', 'partial_success', 'failed', 'cancelled']).has(run.status)) {
        await this.loadReconcilerAlerts();
      }
    } catch (error) {
      this._setReconcilerRunMessage(this._errText(error), true);
    } finally {
      this._reconcilerRefreshInFlight = false;
    }
  }

  async loadReconcilerAlerts() {
    const api = window.app?.apiClient;
    const projectId = this.querySelector('.cur-reconciler-project')?.value;
    const target = this.querySelector('.cur-reconciler-alerts');
    if (!target) return;
    target.hidden = true;
    target.textContent = '';
    if (!api || !projectId) return;
    try {
      const params = new URLSearchParams({ project_id: projectId });
      const metrics = await api.get('/curation/reconciler/metrics?' + params.toString());
      if (this.querySelector('.cur-reconciler-project')?.value !== projectId) return;
      const labels = {
        validation_failure: 'validation failures',
        automatic_rollback: 'automatic results cancelled',
        budget_exceeded: 'candidates over budget',
        candidate_failure: 'failed candidates',
        index_validation_failure: 'index or embedding validation failures',
        stale_result: 'stale results',
        provenance_gap: 'claims without source evidence',
        orphan_relation: 'relations without valid sources',
        replay_non_idempotency: 'input groups with duplicate results or activations',
        unresolved_contradiction: 'held proposals with unresolved contradictions',
        stale_anchor: 'open stale anchor episodes',
        judge_failure_increase: 'Judge failure rate',
        high_risk_proposal_increase: 'High-risk proposal rate',
        activation_budget_repeated: 'recent runs over the activation budget',
      };
      const alerts = Array.isArray(metrics?.alerts) ? metrics.alerts : [];
      target.textContent = alerts.map((item) => {
        const rateField = { judge_failure_increase: 'judge_failure_rate', high_risk_proposal_increase: 'high_risk_proposal_rate' }[item.kind];
        const previous = metrics.run_trends?.previous?.[rateField];
        const recent = metrics.run_trends?.recent?.[rateField];
        if (rateField && Number.isFinite(previous) && Number.isFinite(recent)) {
          return `${labels[item.kind]}: ${(previous * 100).toFixed(1)}% → ${(recent * 100).toFixed(1)}%`;
        }
        return `${Number(item.count) || 0} ${labels[item.kind] || item.kind}`;
      }).join(' · ');
      const trendNote = metrics?.run_trends?.ready === false
        ? 'Trend rates unavailable: two complete run windows are required.' : '';
      if (trendNote) target.textContent += (target.textContent ? ' · ' : '') + trendNote;
      target.hidden = !alerts.length && !trendNote;
    } catch (error) {
      if (this.querySelector('.cur-reconciler-project')?.value !== projectId) return;
      target.textContent = 'Project signals unavailable: ' + this._errText(error);
      target.hidden = false;
    }
  }

  async cancelReconcilerRun() {
    const api = window.app?.apiClient;
    const runId = this._activeReconcilerRunId;
    const button = this.querySelector('.cur-reconciler-run-cancel');
    if (!api || !runId || !button) return;
    button.disabled = true;
    try {
      const run = await api.post(
        '/curation/reconciler/runs/' + encodeURIComponent(runId) + '/cancel', {}
      );
      this._renderReconcilerRun(run);
      await this.loadReconcilerProposals();
    } catch (error) {
      this._setReconcilerRunMessage(this._errText(error), true);
      button.disabled = false;
    }
  }

  async deactivateReconcilerResult(button) {
    const api = window.app?.apiClient;
    const resultId = button.dataset.result;
    const revision = Number(button.dataset.revision);
    if (!api || !resultId || !Number.isInteger(revision) || revision < 0) return;
    button.disabled = true;
    try {
      await api.post('/curation/reconciler/results/' + encodeURIComponent(resultId) + '/cancel', {
        expected_revision: revision,
      });
      await this.loadReconcilerProposals();
      this._setReconcilerRunMessage('Derived result deactivated. Source memories are available in reads. Dependent overviews require regeneration.', false);
    } catch (error) {
      this._setReconcilerRunMessage(this._errText(error), true);
      button.disabled = false;
    }
  }

  _startReconcilerPolling() {
    this._stopReconcilerPolling();
    this._reconcilerPollTimer = setInterval(() => {
      this.refreshReconcilerRun();
    }, 5000);
  }

  _stopReconcilerPolling() {
    if (!this._reconcilerPollTimer) return;
    clearInterval(this._reconcilerPollTimer);
    this._reconcilerPollTimer = null;
  }

  _renderReconcilerRun(run) {
    this._activeReconcilerRunId = run?.id || run?.run_id || this._activeReconcilerRunId;
    if (this._activeReconcilerRunId) {
      this._reconcilerRunModes.set(this._activeReconcilerRunId, Boolean(run?.dry_run));
    }
    const status = this.querySelector('.cur-reconciler-run-status');
    const refresh = this.querySelector('.cur-reconciler-run-refresh');
    const cancel = this.querySelector('.cur-reconciler-run-cancel');
    if (!status || !run) return;
    const counts = Object.fromEntries(
      Object.entries(run.candidate_counts || {}).map(([key, value]) => [
        key,
        Math.max(0, Number(value) || 0),
      ])
    );
    const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
    const pending = counts.pending_judgment || 0;
    const processing = counts.processing || 0;
    const held = counts.needs_review || 0;
    const failed = counts.failed || 0;
    const approval = counts.needs_approval || 0;
    const preview = counts.preview || 0;
    const noOp = counts.no_op || 0;
    const active = Math.max(0, Number(run.active_result_count) || 0);
    const decided = Math.max(0, total - pending - processing);
    const isTerminal = new Set([
      'completed', 'needs_approval', 'partial_success', 'failed', 'cancelled',
    ]).has(run.status);
    const percent = total ? Math.min(100, Math.round((decided / total) * 100)) : (isTerminal ? 100 : 0);
    const progress = this.querySelector('.cur-reconciler-progress');
    const progressBar = progress?.querySelector('progress');
    const progressSummary = this.querySelector('.cur-reconciler-progress-summary');
    if (progressBar) {
      progressBar.value = percent;
      progressBar.setAttribute('aria-valuetext', `${decided} of ${total} candidates decided`);
    }
    if (progressSummary) {
      const parts = [`${decided}/${total} decided`, `${pending} pending`, `${processing} processing`];
      if (preview) parts.push(`${preview} preview`);
      if (approval) parts.push(`${approval} awaiting approval`);
      if (active) parts.push(`${active} active`);
      if (held) parts.push(`${held} held`);
      if (failed) parts.push(`${failed} failed`);
      if (noOp) parts.push(`${noOp} no-op`);
      parts.push(`${percent}%`);
      progressSummary.textContent = parts.join(' · ');
    }
    status.textContent = [
      'Run ' + (this._activeReconcilerRunId || ''),
      'Status: ' + (
        run.status === 'queued' ? 'waiting for candidate detector'
          : run.status === 'retryable' ? 'waiting for queue capacity'
            : run.status === 'detecting' ? 'detecting candidates'
              : processing ? 'judging' : pending ? 'waiting for worker' : run.status || 'unknown'
      ),
      'Inputs: ' + Math.max(0, Number(run.stats?.snapshot_count) || 0),
      run.stats?.deduplicated_candidate_count
        ? 'Already tracked: ' + Number(run.stats.deduplicated_candidate_count) + ' candidate group(s)'
        : null,
      run.stats?.judge_failed_calls
        ? 'Judge calls failed: ' + Number(run.stats.judge_failed_calls)
        : null,
      run.stats?.llm_calls
        ? `LLM usage reported: ${Number(run.stats.reported_usage_calls || 0)}/${Number(run.stats.llm_calls)} calls${run.stats.reported_usage_calls ? ` · ${Number(run.stats.reported_input_tokens || 0).toLocaleString()} input · ${Number(run.stats.reported_output_tokens || 0).toLocaleString()} output tokens` : ''}`
        : null,
      run.stats?.scope?.anchored_path ? 'Anchor: ' + run.stats.scope.anchored_path : null,
      run.stats?.scope?.created_after ? 'From: ' + run.stats.scope.created_after.slice(0, 10) : null,
      run.stats?.scope?.created_before ? 'Through: ' + run.stats.scope.created_before.slice(0, 10) : null,
    ].filter(Boolean).join(' · ');
    if (refresh) refresh.hidden = !this._activeReconcilerRunId;
    if (cancel) cancel.hidden = isTerminal;
    if (progress) progress.hidden = false;
    if (isTerminal) this._stopReconcilerPolling();
    const issue = Array.isArray(run.candidate_issues) ? run.candidate_issues[0] : null;
    if (issue) {
      this._setReconcilerRunMessage(
        `Candidate ${String(issue.candidate_id || '').slice(0, 11)}: ${issue.reason || 'Judgment failed.'} Start a new run after resolving the issue.`,
        true
      );
      return;
    }
    if (isTerminal && !total && run.stats?.deduplicated_candidate_count) {
      this._setReconcilerRunMessage(
        'No new proposals. The same input groups are already tracked in an earlier run.',
        false
      );
      return;
    }
    this._setReconcilerRunMessage(
      run.dry_run ? 'Dry-run output is a preview. It is not approved or activated.' : 'The reconcile worker processes candidates in the background.',
      false
    );
  }

  _setReconcilerRunMessage(text, isError = false) {
    const message = this.querySelector('.cur-reconciler-run-message');
    if (!message) return;
    message.textContent = text || '';
    message.classList.toggle('cur-msg-error', Boolean(isError));
  }

  _reconcilerRow(proposal) {
    const status = proposal.status || 'needs_approval';
    const displayStatus = status === 'applied' ? (proposal.result_status || 'unavailable') : status;
    const version = status === 'applied'
      ? 'result revision ' + this._esc(proposal.result_revision ?? '?')
      : 'proposal revision ' + this._esc(proposal.expected_revision);
    let claims = [];
    let explanation = {};
    try {
      claims = JSON.parse(proposal.claims_json || '[]');
    } catch (_) {
      claims = [];
    }
    try {
      explanation = JSON.parse(proposal.proposal_json || '{}');
    } catch (_) {
      explanation = {};
    }
    const sourceLink = (source) => {
      const id = String(source.memory_id || '');
      const href = '/memory/' + encodeURIComponent(id);
      return '<a class="cur-doc-src" href="' + href + '" data-route="' + href
        + '" title="' + this._esc(id + ' · ' + (source.input_hash || '')) + '">'
        + this._esc(id.slice(0, 8)) + '</a>';
    };
    const citedSources = [...new Map(claims.flatMap((claim) => claim.source_refs || [])
      .map((source) => [source.memory_id, source])).values()];
    let inputSources = [];
    try {
      inputSources = JSON.parse(proposal.input_sources_json || '[]');
    } catch (_) {
      inputSources = [];
    }
    const allSources = inputSources.length ? inputSources : citedSources;
    const representative = proposal.representative_memory_id
      ? sourceLink({ memory_id: proposal.representative_memory_id }) : '';
    const resultSummary = ['merge', 'supersede'].includes(proposal.action)
      ? '<p class="cur-reconciler-impact">' + allSources.length + ' inputs (' + citedSources.length + ' cited) → 1 derived result. Original memories remain unchanged.</p>'
      : '';
    const claimDetails = claims.map((claim) => {
      const conditions = Array.isArray(claim.conditions) ? claim.conditions : [];
      // Older proposals stored a condition string as individual characters.
      const legacyCharacters = conditions.length > 3
        && conditions.every((item) => typeof item === 'string' && item.length === 1);
      const conditionText = legacyCharacters ? conditions.join('') : conditions.join('; ');
      return '<li><span>' + this._esc(claim.text || '') + '</span>'
        + (conditions.length ? '<div class="cur-muted">Conditions: '
          + this._esc(conditionText) + '</div>' : '')
        + '<div class="cur-doc-sources">' + (claim.source_refs || []).map(sourceLink).join(' ')
        + '</div></li>';
    }).join('');
    const rationale = explanation.rationale || '';
    const processingIssue = proposal.error || '';
    const reviewReason = status === 'needs_review' ? ({
      contradiction: 'Contradiction',
      insufficient_evidence: 'Insufficient evidence',
      scope_mismatch: 'Project or scope mismatch',
      uncertain_provenance: 'Uncertain provenance',
      other: 'Other',
    }[explanation.review_reason] || 'Unclassified') : '';
    const explanationDetails = [
      ['preserved_conditions', 'Preserved conditions and exceptions'],
      ['removed_repetition', 'Removed repetition'],
      ['uncertainties', 'Uncertainties'],
    ].map(([key, title]) => {
      const values = Array.isArray(explanation[key]) ? explanation[key] : [];
      return values.length ? '<details class="cur-reconciler-claims"><summary>' + title
        + '</summary><ul>' + values.map((value) => '<li>' + this._esc(value) + '</li>').join('')
        + '</ul></details>' : '';
    }).join('');
    const actions = status === 'needs_approval'
      ? '<div class="cur-actions"><button class="cur-btn cur-approve cur-reconciler-approve" data-proposal="'
        + this._esc(proposal.id) + '" data-revision="' + this._esc(proposal.expected_revision)
        + '">Approve</button><button class="cur-btn cur-reject cur-reconciler-reject" data-proposal="'
        + this._esc(proposal.id) + '" data-revision="' + this._esc(proposal.expected_revision)
        + '">Reject</button></div>'
      : '<p class="cur-hint cur-reconciler-state-note">'
        + (status === 'preview'
          ? 'Dry-run preview. This proposal is not approved or active.'
          : status === 'applied' && proposal.result_status === 'active'
            ? 'Active derived result. Original memories remain available.'
            : status === 'applied'
              ? 'Derived result is ' + this._esc(proposal.result_status || 'unavailable') + '. Original memories remain available.'
          : status === 'unverified'
            ? 'Run mode could not be confirmed. Refresh to check whether this proposal can be activated.'
            : 'Held for review. No approval or activation is available for this result.')
        + '</p>';
    const resultLink = status === 'applied' && proposal.result_status === 'active' && proposal.result_id
      ? '<p class="cur-reconciler-result-link"><a href="/memory/' + encodeURIComponent(proposal.result_id)
        + '" data-route="/memory/' + encodeURIComponent(proposal.result_id)
        + '">Open derived result</a></p><button class="cur-btn cur-reconciler-result-deactivate" data-result="'
        + this._esc(proposal.result_id) + '" data-revision="' + this._esc(proposal.result_revision)
        + '">Deactivate derived result</button>' : '';
    return '<div class="cur-card cur-reconciler-card" data-proposal="'
      + this._esc(proposal.id) + '"><div class="cur-head"><span class="cur-type">'
      + this._esc(proposal.action || 'review') + '</span><span class="cur-muted">'
      + this._esc(proposal.project_id || '') + '</span><span class="cur-muted">'
      + this._esc(displayStatus) + ' · ' + version
      + '</span></div><div class="cur-rationale">'
      + this._esc(proposal.body || 'No synthesized body.') + '</div>'
      + resultSummary
      + (reviewReason ? '<p class="cur-reconciler-review-reason">Review reason: ' + this._esc(reviewReason) + '</p>' : '')
      + (representative ? '<p class="cur-reconciler-representative">Representative: '
        + representative + '</p>' : '')
      + (rationale ? '<p class="cur-reconciler-reason"><strong>Reason:</strong> '
        + this._esc(rationale) + '</p>' : '')
      + (processingIssue ? '<p class="cur-reconciler-error cur-msg-error"><strong>Processing issue:</strong> '
        + this._esc(processingIssue) + '</p>' : '')
      + explanationDetails
      + (claimDetails ? '<details class="cur-reconciler-claims"><summary>Claims and evidence ('
        + claims.length + ')</summary><ol>' + claimDetails + '</ol></details>' : '')
      + (allSources.length ? '<details class="cur-reconciler-versions"><summary>All input versions ('
        + allSources.length + ')</summary><ul>' + allSources.map((source) => '<li>'
        + sourceLink(source) + ' · hash <code>'
        + this._esc(String(source.input_hash || '').slice(0, 12)) + '</code></li>').join('')
        + '</ul></details>' : '') + resultLink + actions + '</div>';
  }

  _render(items) {
    const list = this.querySelector('.cur-list');
    const count = this.querySelector('.cur-count');
    if (count) count.textContent = String(items.length);
    if (!items.length) {
      list.innerHTML = '';
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
    if (tab === 'reconciler') {
      this.loadReconcilerProjects();
      this.loadReconcilerProposals();
    }
    if (tab === 'docs') {
      this.loadDocProposals();
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

  // ---- Docs tab (doc-promotion proposals) ---------------------------------

  _docMsg(text, isError = false) {
    const el = this.querySelector('.cur-doc-msg');
    if (!el) return;
    el.textContent = text;
    el.className = `cur-doc-msg${isError ? ' cur-msg-error' : ' cur-msg-ok'}`;
    if (text) setTimeout(() => {
      el.textContent = '';
      el.className = 'cur-doc-msg';
    }, 2600);
  }

  async loadDocProposals() {
    const api = window.app?.apiClient;
    const list = this.querySelector('.cur-doc-list');
    if (!api || !list) return;
    list.innerHTML = '<div class="cur-empty">Loading…</div>';
    try {
      api.invalidateCache?.('/curation/doc-proposals');
      const data = await api.getDocProposals();
      const proposals = data?.proposals || [];
      const countEl = this.querySelector('.cur-doc-count');
      if (countEl) countEl.textContent = String(proposals.length);
      this.renderDocProposals(proposals);
    } catch (err) {
      list.innerHTML = `<div class="cur-empty cur-msg-error">Failed to load: ${this._esc(err.message)}</div>`;
    }
  }

  renderDocProposals(proposals) {
    const list = this.querySelector('.cur-doc-list');
    if (!list) return;
    if (!proposals.length) {
      list.innerHTML = '<div class="cur-empty">No doc proposals. Generate one from a memory to promote it into a versioned doc.</div>';
      return;
    }
    list.innerHTML = proposals.map((p) => this._docCard(p)).join('');
  }

  _docCard(p) {
    const status = String(p.status || 'pending');
    const isPending = status === 'pending';
    // The server stores no original file content (only original_hash), so there
    // is no left/right diff — render the proposed doc in full plus its rationale
    // and the memories it folds in.
    const sources = (p.source_memory_ids || [])
      .map(
        (id) =>
          `<code class="cur-doc-src" title="${this._esc(id)}">${this._esc(
            String(id).slice(0, 8)
          )}</code>`
      )
      .join('');
    const actions = isPending
      ? `<div class="cur-actions">
          <button class="cur-btn cur-approve cur-doc-approve" data-proposal="${this._esc(p.id)}">✓ Approve</button>
          <button class="cur-btn cur-reject cur-doc-reject" data-proposal="${this._esc(p.id)}">✗ Reject</button>
        </div>`
      : `<div class="cur-doc-note cur-doc-note-${this._esc(status)}">${this._docNote(status)}</div>`;
    return `
      <div class="cur-card cur-doc-card" data-proposal="${this._esc(p.id)}">
        <div class="cur-head">
          <span class="cur-type cur-doc-status cur-doc-status-${this._esc(status)}">${this._esc(status)}</span>
          <code class="cur-doc-path">${this._esc(p.file_path || '')}</code>
        </div>
        ${p.rationale ? `<div class="cur-rationale">💡 ${this._esc(p.rationale)}</div>` : ''}
        ${sources ? `<div class="cur-doc-sources"><span class="cur-muted">Sources:</span> ${sources}</div>` : ''}
        <div class="cur-doc-proposed">
          <div class="cur-diff-label">Proposed content</div>
          <pre class="cur-diff-text cur-diff-new">${this._esc(p.proposed_content || '')}</pre>
        </div>
        ${actions}
      </div>`;
  }

  _docNote(status) {
    if (status === 'approved') {
      return 'Approved — awaiting the agent to apply it locally and report back.';
    }
    if (status === 'applied') {
      return 'Applied — the agent wrote this to the file in the target repo.';
    }
    if (status === 'rejected') {
      return 'Rejected.';
    }
    return this._esc(status);
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
    if (e.target.closest('.cur-reconciler-refresh')) {
      this.loadReconcilerProposals();
      this.loadLatestReconcilerRun();
      return;
    }
    if (e.target.closest('.cur-reconciler-run-refresh')) {
      this.refreshReconcilerRun();
      return;
    }
    if (e.target.closest('.cur-reconciler-policy-save')) {
      this.saveReconcilerPolicy();
      return;
    }
    if (e.target.closest('.cur-reconciler-run-cancel')) {
      this.cancelReconcilerRun();
      return;
    }
    const deactivateButton = e.target.closest('.cur-reconciler-result-deactivate');
    if (deactivateButton) {
      await this.deactivateReconcilerResult(deactivateButton);
      return;
    }
    if (e.target.closest('.cur-doc-refresh')) {
      this.loadDocProposals();
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

    const reconcilerApprove = e.target.closest('.cur-reconciler-approve');
    const reconcilerReject = e.target.closest('.cur-reconciler-reject');
    if (reconcilerApprove || reconcilerReject) {
      const button = reconcilerApprove || reconcilerReject;
      const decision = reconcilerApprove ? 'approve' : 'reject';
      try {
        await api.post(
          '/curation/reconciler/proposals/'
            + encodeURIComponent(button.dataset.proposal) + '/decision',
          {
            decision,
            expected_revision: Number(button.dataset.revision),
          }
        );
        this._msg(decision === 'approve' ? 'Proposal approved.' : 'Proposal rejected.');
        await this.loadReconcilerProposals();
      } catch (error) {
        this._msg('Failed: ' + this._errText(error), true);
      }
      return;
    }

    const docApprove = e.target.closest('.cur-doc-approve');
    const docReject = e.target.closest('.cur-doc-reject');
    if (docApprove || docReject) {
      const pid = (docApprove || docReject).dataset.proposal;
      try {
        if (docApprove) {
          await api.approveDocProposal(pid);
          this._docMsg('Approved — the agent will apply it locally and report back.');
        } else {
          if (!window.confirm('Reject this doc proposal?')) return;
          await api.rejectDocProposal(pid);
          this._docMsg('Proposal rejected.');
        }
        this.loadDocProposals();
      } catch (err) {
        this._docMsg(`Failed: ${err?.data?.message || err?.data?.detail || err.message}`, true);
      }
      return;
    }

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
          <button class="cur-tab-btn" data-tab="reconciler">Reconciler <span class="cur-reconciler-count">0</span></button>
          <button class="cur-tab-btn cur-tab-active" data-tab="improve">Improve</button>
          <button class="cur-tab-btn" data-tab="docs">Docs</button>
          <button class="cur-tab-btn" data-tab="activity">Activity</button>
        </div>

        <div class="cur-tab-panel cur-tab-panel-reconciler" data-tab-panel="reconciler" hidden>
          <div class="cur-header">
            <h1>Memory Reconciler</h1>
            <button class="cur-btn cur-reconciler-refresh">Refresh</button>
          </div>
          <p class="cur-hint">Review derived summaries and evidence. Canonical memories stay unchanged.</p>
          <form class="cur-reconciler-run-form">
            <label>Project
              <select class="cur-reconciler-project" required>
                <option value="">Select a project</option>
              </select>
            </label>
            <details class="cur-reconciler-scope">
              <summary>Limit run scope (optional)</summary>
              <div class="cur-reconciler-scope-fields">
                <label>Anchor path prefix <input class="cur-reconciler-anchor-path" type="text" placeholder="app/core/" maxlength="500"></label>
                <label>From date <input class="cur-reconciler-from-date" type="date"></label>
                <label>Through date <input class="cur-reconciler-through-date" type="date"></label>
              </div>
            </details>
            <label class="cur-reconciler-dry-run-label">
              <input class="cur-reconciler-dry-run" type="checkbox" checked>
              Dry run (do not activate derived results)
            </label>
            <button class="cur-btn cur-reconciler-run-start" type="submit">Start run</button>
            <button class="cur-btn cur-reconciler-run-refresh" type="button" hidden>Refresh run</button>
            <button class="cur-btn cur-reconciler-run-cancel" type="button" hidden>Cancel run</button>
            <span class="cur-reconciler-run-status" role="status" aria-live="polite"></span>
          </form>
          <div class="cur-reconciler-policy">
            <label><input class="cur-reconciler-external-llm" type="checkbox" disabled>
              Allow this project's memory evidence to be sent to an external LLM
            </label>
            <label><input class="cur-reconciler-retain-evidence" type="checkbox" checked disabled>
              Retain redacted evidence content in new runs
            </label>
            <button class="cur-btn cur-reconciler-policy-save" type="button" disabled>Save policy</button>
            <span class="cur-muted">Applies to dry-run and live runs. Existing results stay unchanged.</span>
          </div>
          <div class="cur-reconciler-progress" hidden>
            <progress max="100" value="0" aria-label="Reconciler run progress"></progress>
            <span class="cur-reconciler-progress-summary"></span>
          </div>
          <p class="cur-reconciler-alerts cur-hint" role="status" hidden></p>
          <p class="cur-reconciler-run-message cur-hint" role="status" aria-live="polite">Runs require the reconcile worker and a configured chat LLM.</p>
          <div class="cur-msg"></div>
          <div class="cur-list"></div>
          <div class="cur-reconciler-list"></div>
        </div>

        <div class="cur-tab-panel cur-tab-panel-improve" data-tab-panel="improve">
          <div class="cur-header">
            <h1>Improve Proposals <span class="cur-count-badge">(<span class="cur-improve-count">0</span>)</span></h1>
            <button class="cur-btn cur-improve-refresh">Refresh</button>
          </div>
          <p class="cur-hint">Rewritten content proposed by batch Improve. Nothing is applied until you approve — the memory's content only changes on approval.</p>
          <div class="cur-improve-msg"></div>
          <div class="cur-improve-list"></div>
        </div>

        <div class="cur-tab-panel cur-tab-panel-docs" data-tab-panel="docs" hidden>
          <div class="cur-header">
            <h1>Doc Promotion <span class="cur-count-badge">(<span class="cur-doc-count">0</span>)</span></h1>
            <button class="cur-btn cur-doc-refresh">Refresh</button>
          </div>
          <p class="cur-hint">High-value memories folded into versioned docs. Approving flips state only — the server writes no files. The agent in the target repo applies approved proposals locally (via the <code>doc_proposals</code> tool) and reports back.</p>
          <div class="cur-doc-msg"></div>
          <div class="cur-doc-list"></div>
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
      .cur-reconciler-run-form { display: flex; align-items: end; gap: 10px; flex-wrap: wrap; padding: 12px 0; }
      .cur-reconciler-scope { flex-basis: 100%; color: var(--text-secondary); font-size: 0.84rem; }
      .cur-reconciler-scope summary { cursor: pointer; }
      .cur-reconciler-scope-fields { display: flex; align-items: end; gap: 10px; flex-wrap: wrap; margin-top: 8px; }
      .cur-reconciler-scope-fields input { padding: 7px 9px; border: 1px solid var(--border-color); border-radius: 6px; background: var(--bg-primary); color: var(--text-primary); }
      .cur-reconciler-policy { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; font-size: 0.84rem; }
      .cur-reconciler-policy label { display: inline-flex; align-items: center; gap: 6px; }
      .cur-reconciler-run-form label { display: flex; align-items: center; gap: 8px; color: var(--text-primary); font-size: 0.88rem; }
      .cur-reconciler-run-form > label:first-child { align-items: start; flex-direction: column; gap: 4px; }
      .cur-reconciler-project { min-width: 220px; max-width: 100%; padding: 7px 9px; border: 1px solid var(--border-color); border-radius: 6px; background: var(--bg-primary); color: var(--text-primary); }
      .cur-reconciler-run-status { flex-basis: 100%; color: var(--text-secondary); font-size: 0.82rem; overflow-wrap: anywhere; }
      .cur-reconciler-run-message { min-height: 1.2em; }
      .cur-reconciler-progress { display: grid; gap: 5px; margin: 4px 0 12px; }
      .cur-reconciler-progress progress { width: 100%; height: 8px; accent-color: var(--success-color, #16a34a); }
      .cur-reconciler-progress-summary { color: var(--text-secondary); font-size: 0.82rem; }
      .cur-reconciler-alerts { border-left: 3px solid var(--error-color, #ef4444); padding-left: 10px; color: var(--text-primary); }
      .cur-reconciler-state-note { margin: 8px 0 0; }
      .cur-reconciler-result-link { margin: 8px 0; }
      .cur-reconciler-impact { margin: 10px 0 4px; color: var(--text-primary); font-size: 0.85rem; }
      .cur-reconciler-representative { margin: 4px 0 10px; color: var(--text-secondary); font-size: 0.84rem; }
      .cur-reconciler-versions { margin: 10px 0; font-size: 0.84rem; }
      .cur-reconciler-versions summary { cursor: pointer; }
      .cur-reconciler-versions ul { margin: 8px 0 0; padding-left: 20px; }
      .cur-reconciler-versions li { margin: 5px 0; overflow-wrap: anywhere; }
      .cur-reconciler-reason { color: var(--text-secondary); font-size: 0.85rem; line-height: 1.5; }
      .cur-reconciler-claims { margin: 10px 0; font-size: 0.84rem; }
      .cur-reconciler-claims li { margin: 8px 0; line-height: 1.5; }
      .cur-reconciler-claims summary { cursor: pointer; color: var(--text-primary); }
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
      .cur-doc-msg { min-height: 20px; font-size: 0.9rem; margin-bottom: 10px; }
      .cur-doc-path { font-size: 0.85rem; color: var(--text-primary); background: var(--bg-primary); border: 1px solid var(--border-color); border-radius: 6px; padding: 2px 8px; word-break: break-all; }
      .cur-doc-status { text-transform: uppercase; }
      .cur-doc-status-pending { color: var(--info, #3b82f6); border-color: var(--info, #3b82f6); }
      .cur-doc-status-approved { color: #16a34a; border-color: #16a34a; }
      .cur-doc-status-applied { color: var(--text-secondary); }
      .cur-doc-status-rejected { color: var(--error-color, #ef4444); border-color: var(--error-color, #ef4444); }
      .cur-doc-sources { font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 10px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
      .cur-doc-src { font-size: 0.74rem; color: var(--text-secondary); background: var(--bg-primary); border: 1px solid var(--border-color); border-radius: 6px; padding: 1px 6px; }
      .cur-doc-proposed { margin: 10px 0; }
      .cur-doc-note { font-size: 0.85rem; color: var(--text-secondary); padding: 6px 0; }
      .cur-doc-note-rejected { color: var(--error-color, #ef4444); }
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
      .cur-btn:disabled { opacity: 0.55; cursor: wait; }
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
