/**
 * Curation Page — reconcile 큐(사람 게이트, SSOT #3 F4).
 *
 * 비동기 reconcile 워커가 만든 PROPOSED 관계(supersede/conflict)를 검토해
 * 승인(old 폐기) / NEW 폐기(C3) / 유지(dismiss) 한다. REST: /api/curation/*.
 */

export class CurationPage extends HTMLElement {
  connectedCallback() {
    this.innerHTML = this._skeleton();
    this._injectStyles();
    this.addEventListener('click', (e) => this._onClick(e));
    this.loadData();
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

  async loadData() {
    const api = window.app?.apiClient;
    const list = this.querySelector('.cur-list');
    if (!api) {
      list.innerHTML = '<div class="cur-empty">API client unavailable.</div>';
      return;
    }
    list.innerHTML = '<div class="cur-empty">불러오는 중…</div>';
    try {
      const res = await api.getCurationQueue();
      this._render(res?.items || []);
    } catch (e) {
      list.innerHTML = `<div class="cur-empty cur-msg-error">불러오기 실패: ${this._esc(
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
        '<div class="cur-empty">검토할 reconcile 제안이 없습니다.</div>';
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
        )}">✓ 승인 · old 폐기</button>`
      : '';
    const mergeBlock = isMerge
      ? `
        <div class="cur-merge">
          <h4>🔀 병합 결과 (LLM 제안 · 편집 가능)</h4>
          <textarea class="cur-merged">${this._esc(meta.merged_text || '')}</textarea>
        </div>`
      : '';
    const mergeBtn = isMerge
      ? `<button class="cur-btn cur-approve-merge" data-relation="${this._esc(
          it.id
        )}">🔀 병합 승인</button>`
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
          )}">✗ NEW 폐기</button>
          <button class="cur-btn cur-dismiss" data-relation="${this._esc(
            it.id
          )}">유지 · dismiss</button>
        </div>
      </div>`;
  }

  async _onClick(e) {
    const api = window.app?.apiClient;
    if (!api) return;
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
        this._msg('승인됨 — old 메모리를 deprecated로 변경했습니다.');
      } else if (merge) {
        const card = merge.closest('.cur-card');
        const mergedText = card?.querySelector('.cur-merged')?.value || null;
        if (!window.confirm('두 메모리를 병합하고 원본 2개를 폐기할까요?')) return;
        await api.approveCurationMerge(merge.dataset.relation, mergedText);
        this._msg('병합됨 — 새 메모리를 생성하고 원본 2개를 폐기했습니다.');
      } else if (reject) {
        if (!window.confirm('이 NEW 메모리를 폐기(deprecated)할까요?')) return;
        await api.rejectCurationNew(reject.dataset.memory);
        this._msg('NEW 메모리를 폐기했습니다.');
      } else if (dismiss) {
        await api.dismissCuration(dismiss.dataset.relation);
        this._msg('제안을 유지(dismiss)했습니다.');
      }
      this.loadData();
    } catch (err) {
      this._msg(`실패: ${err.message}`, true);
    }
  }

  _skeleton() {
    return `
      <div class="cur-page">
        <div class="cur-header">
          <h1>Reconcile 큐레이션 <span class="cur-count-badge">(<span class="cur-count">0</span>)</span></h1>
          <button class="cur-btn cur-refresh">새로고침</button>
        </div>
        <p class="cur-hint">비동기 reconcile 워커가 감지한 모순/중복 제안입니다. 승인 시에만 메모리가 폐기됩니다.</p>
        <div class="cur-msg"></div>
        <div class="cur-list"></div>
      </div>`;
  }

  _injectStyles() {
    if (document.getElementById('curation-page-styles')) return;
    const style = document.createElement('style');
    style.id = 'curation-page-styles';
    style.textContent = `
      .cur-page { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
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
      @media (max-width: 640px) { .cur-cols { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }
}

customElements.define('curation-page', CurationPage);
