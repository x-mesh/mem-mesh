/**
 * Floating chat assistant widget.
 *
 * A draggable launcher that expands into a chat panel. Talks to the
 * /api/chat/v1/stream SSE endpoint (POST + fetch ReadableStream), rendering
 * token-by-token streaming, tool-call progress, a spinner + elapsed timer.
 * The panel is draggable (by its header) and resizable from the top-left grip.
 * Position and size persist in localStorage; mounted once globally so it
 * floats across all dashboard pages. On a memory detail page it picks up the
 * memory id so the assistant can answer about the current memory.
 */

const POS_KEY = 'memmesh.chat.pos';
const SIZE_KEY = 'memmesh.chat.size';
const STREAM_URL = '/api/chat/v1/stream';
const MIN_W = 320;
const MIN_H = 360;

export class ChatWidget extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.open = false;
    this.busy = false;
    this.available = false;
    this.sessionId = null;
    this.panelW = 380;
    this.panelH = 540;
    this._drag = null;
    this._timer = null;
    this._gotDelta = false;
  }

  connectedCallback() {
    this.shadowRoot.innerHTML = this._template();
    this._els = {
      launcher: this.shadowRoot.querySelector('.launcher'),
      panel: this.shadowRoot.querySelector('.panel'),
      header: this.shadowRoot.querySelector('.header'),
      grip: this.shadowRoot.querySelector('.grip'),
      list: this.shadowRoot.querySelector('.messages'),
      input: this.shadowRoot.querySelector('textarea'),
      send: this.shadowRoot.querySelector('.send'),
      spinner: this.shadowRoot.querySelector('.spinner'),
      elapsed: this.shadowRoot.querySelector('.elapsed'),
      tool: this.shadowRoot.querySelector('.tool-status'),
      chip: this.shadowRoot.querySelector('.context-chip'),
    };
    this._restoreSize();
    this._restorePosition();
    this._bind();
    // Hidden until the server confirms a provider is configured + enabled.
    this.style.display = 'none';
    this._checkAvailability();
    window.addEventListener('memmesh:chat-settings-changed', () =>
      this._checkAvailability()
    );
    // Live-refresh the context chip when SPA navigation changes the page while open.
    window.addEventListener('memmesh:page-changed', () => {
      if (this.open) this._capturePageContext();
    });
  }

  async _checkAvailability() {
    try {
      const res = await fetch('/api/chat/v1/status', {
        headers: { Accept: 'application/json' },
      });
      const data = await res.json().catch(() => ({}));
      this.available = !!data.available;
    } catch (_) {
      this.available = false;
    }
    this.style.display = this.available ? '' : 'none';
    if (!this.available && this.open) this._toggle(false);
  }

  // ----- persistence ----------------------------------------------------

  _restorePosition() {
    const pos = this._readJSON(POS_KEY);
    if (pos && typeof pos.x === 'number' && typeof pos.y === 'number') {
      this.style.left = `${this._clampX(pos.x)}px`;
      this.style.top = `${this._clampY(pos.y)}px`;
      this.style.right = 'auto';
      this.style.bottom = 'auto';
    }
  }

  _restoreSize() {
    const size = this._readJSON(SIZE_KEY);
    if (size && size.w && size.h) {
      this.panelW = Math.max(MIN_W, size.w);
      this.panelH = Math.max(MIN_H, size.h);
    }
    this._applySize();
  }

  _applySize() {
    if (!this._els) return;
    this._els.panel.style.width = `${this.panelW}px`;
    this._els.panel.style.height = `${this.panelH}px`;
  }

  _readJSON(key) {
    try {
      return JSON.parse(localStorage.getItem(key) || 'null');
    } catch (_) {
      return null;
    }
  }

  _save(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (_) {
      /* ignore quota errors */
    }
  }

  _clampX(x) {
    return Math.max(8, Math.min(x, window.innerWidth - 64));
  }
  _clampY(y) {
    return Math.max(8, Math.min(y, window.innerHeight - 64));
  }

  // ----- pointer (drag launcher / drag panel / resize) ------------------

  _bind() {
    this._els.launcher.addEventListener('pointerdown', (e) => this._onDown(e, 'launcher'));
    this._els.header.addEventListener('pointerdown', (e) => this._onDown(e, 'panel'));
    this._els.grip.addEventListener('pointerdown', (e) => this._onDown(e, 'resize'));
    window.addEventListener('pointermove', (e) => this._onMove(e));
    window.addEventListener('pointerup', () => this._onUp());
    this.shadowRoot.querySelector('.close').addEventListener('click', () => this._toggle(false));
    this.shadowRoot.querySelector('.digest-btn').addEventListener('click', () => this._submitDigest());
    this._els.send.addEventListener('click', () => this._submit());
    this._els.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this._submit();
      }
    });
  }

  _onDown(e, mode) {
    // don't start a drag when interacting with header buttons
    if (mode === 'panel' && e.target.closest('.close, .digest-btn')) return;
    const rect = this.getBoundingClientRect();
    this._drag = {
      mode,
      startX: e.clientX,
      startY: e.clientY,
      offX: e.clientX - rect.left,
      offY: e.clientY - rect.top,
      left: rect.left,
      top: rect.top,
      w: this.panelW,
      h: this.panelH,
      moved: false,
    };
    e.target.setPointerCapture?.(e.pointerId);
    if (mode === 'resize') e.preventDefault();
  }

  _onMove(e) {
    const d = this._drag;
    if (!d) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    if (!d.moved && Math.hypot(dx, dy) < 4) return;
    d.moved = true;

    if (d.mode === 'resize') {
      // top-left grip: drag up/left to grow, keeping the bottom-right anchored
      const maxW = window.innerWidth - 24;
      const maxH = window.innerHeight - 24;
      const newW = Math.max(MIN_W, Math.min(d.w - dx, maxW));
      const newH = Math.max(MIN_H, Math.min(d.h - dy, maxH));
      this.panelW = newW;
      this.panelH = newH;
      this._applySize();
      this.style.left = `${d.left + (d.w - newW)}px`;
      this.style.top = `${d.top + (d.h - newH)}px`;
      this.style.right = 'auto';
      this.style.bottom = 'auto';
    } else {
      this.style.left = `${this._clampX(e.clientX - d.offX)}px`;
      this.style.top = `${this._clampY(e.clientY - d.offY)}px`;
      this.style.right = 'auto';
      this.style.bottom = 'auto';
    }
  }

  _onUp() {
    const d = this._drag;
    if (!d) return;
    if (d.moved) {
      const rect = this.getBoundingClientRect();
      this._save(POS_KEY, { x: rect.left, y: rect.top });
      if (d.mode === 'resize') this._save(SIZE_KEY, { w: this.panelW, h: this.panelH });
    } else if (d.mode === 'launcher') {
      this._toggle(!this.open);
    }
    this._drag = null;
  }

  _toggle(open) {
    this.open = open;
    this._els.panel.classList.toggle('open', open);
    this._els.launcher.classList.toggle('hidden', open);
    if (open) {
      this._capturePageContext();
      setTimeout(() => this._els.input.focus(), 50);
    }
  }

  _capturePageContext() {
    const path = window.location.pathname;
    const page = { route: path, label: null, memory_id: null, project_id: null };
    let chip = '';
    let m;
    if ((m = path.match(/\/memor(?:y|ies)\/([\w-]+)/)) || (m = path.match(/\/edit\/([\w-]+)/))) {
      page.memory_id = m[1];
      page.label = path.includes('/edit/') ? 'edit memory' : 'memory detail';
      chip = `📄 ${page.label} ${m[1].slice(0, 8)}`;
    } else if ((m = path.match(/\/project\/([\w-]+)/))) {
      page.project_id = decodeURIComponent(m[1]);
      page.label = 'project detail';
      chip = `📁 project ${page.project_id}`;
    } else {
      const NAMES = {
        '/': 'dashboard',
        '/dashboard': 'dashboard',
        '/settings': 'settings',
        '/search': 'search',
        '/analytics': 'analytics',
        '/work': 'work',
        '/projects': 'projects',
        '/memories': 'memories',
        '/relay': 'relay',
        '/security': 'security',
        '/monitoring': 'monitoring',
        '/connect': 'connect',
      };
      page.label = NAMES[path] || path.replace(/^\//, '') || 'dashboard';
      chip = `⚲ ${page.label}`;
    }
    // fall back to an app-provided project id if the route didn't carry one
    page.project_id =
      page.project_id ||
      window.app?.appState?.currentProjectId ||
      window.__MEMMESH_PROJECT_ID__ ||
      null;

    this.pageContext = page;
    this._els.chip.textContent = chip;
    this._els.chip.style.display = chip ? '' : 'none';

    // On a memory page, enrich the id-only chip with the memory's title.
    if (page.memory_id) this._enrichChipWithTitle(page.memory_id);
  }

  async _enrichChipWithTitle(memoryId) {
    try {
      const memory = await window.app?.apiClient?.getMemory(memoryId);
      // Page may have changed during the fetch — keep the chip in sync.
      if (!memory || this.pageContext?.memory_id !== memoryId) return;
      const title = this._memoryTitle(memory);
      if (title) this._els.chip.textContent = `📄 ${title} (${memoryId.slice(0, 8)})`;
    } catch {
      /* leave the id-only chip in place on failure */
    }
  }

  _memoryTitle(memory) {
    const raw = (memory.title || memory.content || '').trim();
    if (!raw) return '';
    const firstLine = raw.split('\n')[0].trim();
    return firstLine.length > 40 ? `${firstLine.slice(0, 40)}…` : firstLine;
  }

  // On a memory page the route carries no project; borrow it from the memory
  // so tools that require project_id (weekly_review, list_pins) can run.
  async _ensureProjectId() {
    const pc = this.pageContext;
    if (!pc || pc.project_id || !pc.memory_id) return;
    try {
      const memory = await window.app?.apiClient?.getMemory(pc.memory_id);
      if (memory?.project_id && this.pageContext?.memory_id === pc.memory_id) {
        this.pageContext.project_id = memory.project_id;
      }
    } catch {
      /* leave it unset; the backend will ask the user to name a project */
    }
  }

  // ----- chat -----------------------------------------------------------

  _submitDigest() {
    this._submit(
      'Give me a digest of recent activity over the last 14 days: key decisions, ' +
        'notable bugs/incidents, open work pins, and recurring themes. Use ' +
        'weekly_review and search to gather the data, then summarize concisely ' +
        'and cite memory ids.',
      '📊 Digest of recent activity (last 14 days)'
    );
  }

  async _submit(overrideText, displayText) {
    const text = overrideText || this._els.input.value.trim();
    if (!text || this.busy) return;
    if (!overrideText) this._els.input.value = '';
    this._capturePageContext(); // refresh in case the user navigated
    await this._ensureProjectId(); // adopt the memory's project for digest/list_pins
    this._addMessage('user', displayText || text);
    const bubble = this._addMessage('assistant', '');
    this._gotDelta = false;
    this._setBusy(true);
    this._setTool('');
    let ok = true;
    try {
      await this._stream(text, bubble);
    } catch (err) {
      ok = false;
      bubble.textContent = `Error: ${err.message}`;
      bubble.classList.add('error');
    } finally {
      this._setBusy(false);
      this._setTool('');
      if (ok && bubble.textContent.trim()) {
        this._appendSaveAction(text, bubble.dataset.md || bubble.textContent);
      }
    }
  }

  _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  _appendSaveAction(userText, answerText) {
    const wrap = document.createElement('div');
    wrap.className = 'msg-actions';
    const btn = document.createElement('button');
    btn.className = 'save-memory-btn';
    btn.type = 'button';
    btn.textContent = '💾 Save as memory';
    btn.addEventListener('click', () => this._openSaveModal(userText, answerText));
    wrap.appendChild(btn);
    this._els.list.appendChild(wrap);
    this._scroll();
  }

  async _openSaveModal(userText, answerText) {
    const overlay = document.createElement('div');
    overlay.className = 'cm-save-overlay';
    overlay.innerHTML = this._saveModalTemplate();
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.querySelector('.cm-close').addEventListener('click', close);
    overlay.querySelector('.cm-cancel').addEventListener('click', close);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close();
    });
    const body = overlay.querySelector('.cm-body');
    overlay.querySelector('.cm-save').style.display = 'none';
    body.innerHTML =
      '<div class="cm-status"><span class="cm-spinner"></span>Distilling this into a memory…</div>';
    try {
      const res = await fetch('/api/chat/v1/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: `User asked: ${userText}\n\nAssistant answered: ${answerText}`,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.message || `HTTP ${res.status}`);
      this._renderSaveProposal(overlay, data.proposed || {});
    } catch (err) {
      body.innerHTML = `<div class="cm-status cm-error">${this._esc(err.message)}</div>`;
    }
  }

  _renderSaveProposal(overlay, p) {
    const CATS = ['decision', 'bug', 'incident', 'idea', 'code_snippet'];
    const body = overlay.querySelector('.cm-body');
    const saveBtn = overlay.querySelector('.cm-save');
    body.innerHTML = `
      <label class="cm-field">
        <span>Content</span>
        <textarea class="cm-content">${this._esc(p.content || '')}</textarea>
      </label>
      <div class="cm-row">
        <label class="cm-field">
          <span>Category</span>
          <select class="cm-category">
            ${CATS.map((c) => `<option value="${c}" ${p.category === c ? 'selected' : ''}>${c}</option>`).join('')}
          </select>
        </label>
        <label class="cm-field">
          <span>Tags</span>
          <input class="cm-tags" type="text" value="${this._esc((p.tags || []).join(', '))}">
        </label>
      </div>`;
    saveBtn.style.display = '';
    saveBtn.onclick = () => this._saveMemory(overlay);
  }

  async _saveMemory(overlay) {
    const content = overlay.querySelector('.cm-content')?.value.trim() || '';
    const category = overlay.querySelector('.cm-category')?.value || 'idea';
    const tags = (overlay.querySelector('.cm-tags')?.value || '')
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);
    const msg = overlay.querySelector('.cm-foot-msg');
    if (content.length < 10) {
      msg.textContent = 'Content is too short.';
      return;
    }
    const btn = overlay.querySelector('.cm-save');
    btn.disabled = true;
    msg.innerHTML = '<span class="cm-spinner"></span>Saving…';
    try {
      const res = await fetch('/api/chat/v1/save-memory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content,
          category,
          tags,
          project_id: this.pageContext?.project_id || undefined,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.message || `HTTP ${res.status}`);
      msg.textContent = `Saved as ${data.category} (${String(data.id).slice(0, 8)}).`;
      msg.classList.add('cm-ok');
      setTimeout(() => overlay.remove(), 1300);
    } catch (err) {
      msg.textContent = `Save failed: ${err.message}`;
      btn.disabled = false;
    }
  }

  _saveModalTemplate() {
    return `
      <style>
        .cm-save-overlay {
          position: fixed; inset: 0; z-index: 2147483600;
          background: rgba(0,0,0,0.5);
          display: flex; align-items: center; justify-content: center; padding: 24px;
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        .cm-modal {
          width: min(640px, 96vw); max-height: 88vh; display: flex; flex-direction: column;
          background: #fff; color: #111827; border: 1px solid #e5e7eb; border-radius: 14px;
          box-shadow: 0 24px 60px rgba(0,0,0,0.35); overflow: hidden;
        }
        .cm-head { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid #f0f0f0; font-weight: 600; }
        .cm-close { border: none; background: transparent; font-size: 22px; cursor: pointer; color: #6b7280; }
        .cm-body { padding: 16px 18px; overflow-y: auto; }
        .cm-status { padding: 24px; text-align: center; color: #6b7280; }
        .cm-error { color: #b91c1c; }
        .cm-field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #6b7280; margin-bottom: 12px; }
        .cm-field textarea { height: 200px; resize: vertical; padding: 10px; border: 1px solid #e5e7eb; border-radius: 8px; font: inherit; font-size: 13px; white-space: pre-wrap; }
        .cm-row { display: flex; gap: 12px; flex-wrap: wrap; }
        .cm-row .cm-field { flex: 1; min-width: 160px; }
        .cm-field select, .cm-field input { padding: 7px 8px; border: 1px solid #e5e7eb; border-radius: 8px; font: inherit; }
        .cm-foot { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 12px 18px; border-top: 1px solid #f0f0f0; }
        .cm-foot-msg { font-size: 12px; color: #b91c1c; }
        .cm-foot-msg.cm-ok { color: #166534; }
        .cm-actions { display: flex; gap: 8px; }
        .cm-cancel, .cm-save { padding: 8px 16px; border-radius: 8px; cursor: pointer; font-weight: 600; border: 1px solid #e5e7eb; }
        .cm-cancel { background: transparent; color: #374151; }
        .cm-save { background: #111827; color: #fff; border-color: #111827; }
        .cm-save:disabled { opacity: 0.5; cursor: not-allowed; }
        .cm-spinner {
          width: 14px; height: 14px; border: 2px solid #d1d5db; border-top-color: #111827;
          border-radius: 50%; display: inline-block; vertical-align: middle; margin-right: 8px;
          animation: cm-spin 0.7s linear infinite;
        }
        @keyframes cm-spin { to { transform: rotate(360deg); } }
      </style>
      <div class="cm-modal">
        <div class="cm-head">
          <span>💾 Save as memory</span>
          <button class="cm-close" title="Close">×</button>
        </div>
        <div class="cm-body"></div>
        <div class="cm-foot">
          <span class="cm-foot-msg"></span>
          <span class="cm-actions">
            <button class="cm-cancel">Cancel</button>
            <button class="cm-save">Save</button>
          </span>
        </div>
      </div>`;
  }

  async _stream(text, bubble) {
    const body = {
      messages: [{ role: 'user', content: text }],
      session_id: this.sessionId || undefined,
      page: this.pageContext || undefined,
    };
    const res = await fetch(STREAM_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
    });
    if (!res.ok || !res.body) {
      let detail = `HTTP ${res.status}`;
      try {
        detail = (await res.json()).detail || detail;
      } catch (_) {
        /* non-json error body */
      }
      throw new Error(detail);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      // sse_starlette emits CRLF; normalize the whole buffer (a \r\n can
      // straddle a chunk boundary) so \n\n framing works.
      buf = (buf + decoder.decode(value, { stream: true })).replace(/\r\n/g, '\n');
      let idx;
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        this._onFrame(frame, bubble);
      }
    }
  }

  _onFrame(frame, bubble) {
    let event = 'message';
    let data = '';
    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) data += line.slice(5).trim();
    }
    if (!data) return;
    let payload;
    try {
      payload = JSON.parse(data);
    } catch (_) {
      return;
    }
    switch (event) {
      case 'session':
        this.sessionId = payload.session_id || this.sessionId;
        break;
      case 'tool_call':
        this._setTool(`🔧 ${payload.name}…`);
        break;
      case 'tool_result':
        this._setTool(`${payload.ok ? '✓' : '✗'} ${payload.name}`);
        break;
      case 'delta':
        this._gotDelta = true;
        bubble.textContent += payload.text || '';
        this._scroll();
        break;
      case 'message':
        // streamed deltas already built the text; only set on no-stream fallback
        if (!this._gotDelta) {
          bubble.dataset.md = payload.text || '';
          bubble.innerHTML = this._renderMarkdown(payload.text || '');
          this._scroll();
        }
        break;
      case 'done':
        // Streaming kept the raw text (partial markdown is unsafe to render
        // mid-stream); render the finished message once here.
        if (this._gotDelta && !bubble.classList.contains('error')) {
          bubble.dataset.md = bubble.textContent;
          bubble.innerHTML = this._renderMarkdown(bubble.textContent);
          this._scroll();
        }
        if (payload.truncated) this._setTool('(stopped at step limit)');
        else this._setTool('');
        break;
      case 'error':
        bubble.textContent = `Error: ${payload.detail || 'request failed'}`;
        bubble.classList.add('error');
        break;
    }
  }

  // ----- rendering ------------------------------------------------------

  // Minimal, dependency-free markdown → HTML. Escapes first, so output is
  // XSS-safe; supports code fences/inline code, headings, lists, bold/italic,
  // and http(s) links — enough for assistant replies.
  _mdEscape(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;'); // prevent href attribute breakout
  }

  _mdInline(text) {
    const codes = [];
    let t = String(text).replace(/`([^`]+)`/g, (_m, c) => {
      codes.push(this._mdEscape(c));
      return `\x00C${codes.length - 1}\x00`;
    });
    t = this._mdEscape(t);
    // Stash links before the emphasis passes so a '*' in a URL isn't mangled.
    const links = [];
    t = t.replace(/\[([^\]\x00]+)\]\((https?:\/\/[^\s)]+)\)/g, (_m, txt, url) => {
      links.push(`<a href="${url}" target="_blank" rel="noopener noreferrer">${txt}</a>`);
      return `\x00L${links.length - 1}\x00`;
    });
    t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    t = t.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
    t = t.replace(/\x00L(\d+)\x00/g, (_m, i) => links[+i]);
    t = t.replace(/\x00C(\d+)\x00/g, (_m, i) => `<code class="md-code">${codes[+i]}</code>`);
    return t;
  }

  _renderMarkdown(src) {
    const fences = [];
    // Strip NUL bytes first — they are the sentinel for code/link placeholders.
    const s = String(src).replace(/\x00/g, '').replace(/```[ \t]*[\w-]*\n?([\s\S]*?)```/g, (_m, code) => {
      fences.push(this._mdEscape(code.replace(/\n$/, '')));
      return `\x00F${fences.length - 1}\x00`;
    });
    const out = [];
    let list = null;
    const closeList = () => {
      if (list) {
        out.push(`</${list}>`);
        list = null;
      }
    };
    for (const line of s.split('\n')) {
      const fence = line.match(/^\x00F(\d+)\x00$/);
      if (fence) {
        closeList();
        out.push(`<pre class="md-pre"><code>${fences[+fence[1]]}</code></pre>`);
        continue;
      }
      const h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        closeList();
        const lvl = h[1].length;
        out.push(`<h${lvl} class="md-h">${this._mdInline(h[2])}</h${lvl}>`);
        continue;
      }
      const ul = line.match(/^\s*[-*+]\s+(.*)$/);
      if (ul) {
        if (list !== 'ul') {
          closeList();
          out.push('<ul class="md-list">');
          list = 'ul';
        }
        out.push(`<li>${this._mdInline(ul[1])}</li>`);
        continue;
      }
      const ol = line.match(/^\s*\d+\.\s+(.*)$/);
      if (ol) {
        if (list !== 'ol') {
          closeList();
          out.push('<ol class="md-list">');
          list = 'ol';
        }
        out.push(`<li>${this._mdInline(ol[1])}</li>`);
        continue;
      }
      if (line.trim() === '') {
        closeList();
        continue;
      }
      closeList();
      out.push(`<p class="md-p">${this._mdInline(line)}</p>`);
    }
    closeList();
    return out.join('');
  }

  _addMessage(role, text) {
    const el = document.createElement('div');
    el.className = `msg ${role}`;
    el.textContent = text;
    this._els.list.appendChild(el);
    this._scroll();
    return el;
  }

  _setBusy(busy) {
    this.busy = busy;
    this._els.send.disabled = busy;
    this._els.input.disabled = busy;
    this._els.spinner.style.display = busy ? '' : 'none';
    if (busy) this._startTimer();
    else this._stopTimer();
  }

  _startTimer() {
    const start = performance.now();
    this._els.elapsed.textContent = '0.0s';
    clearInterval(this._timer);
    this._timer = setInterval(() => {
      this._els.elapsed.textContent = `${((performance.now() - start) / 1000).toFixed(1)}s`;
    }, 100);
  }

  _stopTimer() {
    clearInterval(this._timer);
    this._timer = null;
  }

  _setTool(text) {
    this._els.tool.textContent = text || '';
  }

  _scroll() {
    this._els.list.scrollTop = this._els.list.scrollHeight;
  }

  _template() {
    return `
      <style>
        :host {
          position: fixed;
          right: 24px;
          bottom: 24px;
          z-index: 2147483000;
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        .launcher {
          width: 56px; height: 56px; border-radius: 50%;
          background: #111827; color: #fff;
          display: flex; align-items: center; justify-content: center;
          cursor: grab; box-shadow: 0 6px 20px rgba(0,0,0,0.25);
          touch-action: none; user-select: none;
        }
        .launcher:active { cursor: grabbing; }
        .launcher.hidden { display: none; }
        .launcher svg { width: 26px; height: 26px; }
        .panel {
          display: none; flex-direction: column; position: relative;
          width: 380px; height: 540px;
          max-width: calc(100vw - 32px); max-height: calc(100vh - 48px);
          background: #fff; color: #111827;
          border: 1px solid #e5e7eb; border-radius: 14px;
          box-shadow: 0 18px 50px rgba(0,0,0,0.28); overflow: hidden;
        }
        .panel.open { display: flex; }
        .grip {
          position: absolute; top: 0; left: 0; width: 18px; height: 18px;
          cursor: nwse-resize; z-index: 3; touch-action: none;
          background:
            linear-gradient(135deg, transparent 0 40%, #cbd5e1 40% 50%, transparent 50% 70%, #cbd5e1 70% 80%, transparent 80%);
        }
        .header {
          display: flex; align-items: center; justify-content: space-between;
          padding: 12px 14px; border-bottom: 1px solid #f0f0f0;
          font-weight: 600; font-size: 14px; cursor: move; touch-action: none;
          user-select: none;
        }
        .close {
          border: none; background: transparent; font-size: 18px; cursor: pointer;
          color: #6b7280; line-height: 1;
        }
        .header-actions { display: flex; align-items: center; gap: 6px; }
        .digest-btn { border: none; background: transparent; font-size: 15px; cursor: pointer; line-height: 1; padding: 2px; }
        .context-chip {
          margin: 8px 14px 0; padding: 4px 8px; align-self: flex-start;
          background: #eff6ff; color: #1d4ed8; border-radius: 8px; font-size: 11.5px;
        }
        .messages {
          flex: 1; overflow-y: auto; padding: 14px;
          display: flex; flex-direction: column; gap: 10px; background: #fafafa;
        }
        .msg {
          padding: 8px 12px; border-radius: 12px; max-width: 85%;
          white-space: pre-wrap; word-break: break-word;
          font-size: 13.5px; line-height: 1.45;
        }
        .msg.user { align-self: flex-end; background: #111827; color: #fff; border-bottom-right-radius: 4px; }
        .msg.assistant { align-self: flex-start; background: #fff; border: 1px solid #e5e7eb; border-bottom-left-radius: 4px; }
        .msg.error { color: #b91c1c; border-color: #fecaca; }
        .msg .md-p { margin: 0 0 8px; }
        .msg .md-p:last-child, .msg .md-list:last-child, .msg .md-pre:last-child { margin-bottom: 0; }
        .msg .md-p:first-child, .msg .md-h:first-child { margin-top: 0; }
        .msg .md-h { margin: 10px 0 4px; font-weight: 600; line-height: 1.3; }
        .msg h1.md-h { font-size: 1.25em; }
        .msg h2.md-h { font-size: 1.15em; }
        .msg h3.md-h, .msg h4.md-h, .msg h5.md-h, .msg h6.md-h { font-size: 1.05em; }
        .msg .md-list { margin: 4px 0 8px; padding-left: 20px; }
        .msg .md-list li { margin: 2px 0; }
        .msg .md-code { background: #f3f4f6; padding: 1px 5px; border-radius: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9em; }
        .msg .md-pre { background: #f6f8fa; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px; margin: 6px 0; overflow-x: auto; white-space: pre; }
        .msg .md-pre code { background: none; padding: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.88em; }
        .msg.assistant a { color: #2563eb; text-decoration: underline; }
        .msg-actions { align-self: flex-start; margin-top: -4px; }
        .save-memory-btn {
          border: 1px solid #e5e7eb; background: #fff; color: #374151;
          border-radius: 8px; padding: 3px 8px; font-size: 11.5px; cursor: pointer;
        }
        .save-memory-btn:hover { background: #f3f4f6; }
        .status {
          display: flex; align-items: center; gap: 8px;
          padding: 4px 14px; min-height: 20px; font-size: 12px; color: #6b7280;
        }
        .spinner {
          width: 12px; height: 12px; border: 2px solid #d1d5db;
          border-top-color: #111827; border-radius: 50%;
          animation: spin 0.7s linear infinite; display: none;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .elapsed { font-variant-numeric: tabular-nums; }
        .tool-status { color: #374151; }
        .composer {
          display: flex; gap: 8px; padding: 12px 14px; border-top: 1px solid #f0f0f0;
        }
        textarea {
          flex: 1; resize: none; height: 38px; max-height: 120px;
          padding: 8px 10px; border: 1px solid #e5e7eb; border-radius: 10px;
          font: inherit; font-size: 13.5px;
        }
        .send {
          border: none; background: #111827; color: #fff; border-radius: 10px;
          padding: 0 16px; font-weight: 600; cursor: pointer;
        }
        .send:disabled { opacity: 0.5; cursor: not-allowed; }
        @media (max-width: 480px) {
          .panel { width: calc(100vw - 16px) !important; height: calc(100vh - 90px) !important; }
        }
      </style>
      <div class="launcher" title="Ask the memory assistant">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
      </div>
      <div class="panel">
        <div class="grip" title="Drag to resize"></div>
        <div class="header">
          <span>Memory Assistant</span>
          <span class="header-actions">
            <button class="digest-btn" title="Digest recent activity">📊</button>
            <button class="close" title="Close">×</button>
          </span>
        </div>
        <div class="context-chip" style="display:none"></div>
        <div class="messages"></div>
        <div class="status">
          <span class="spinner"></span>
          <span class="elapsed"></span>
          <span class="tool-status"></span>
        </div>
        <div class="composer">
          <textarea placeholder="Ask about your memories…" rows="1"></textarea>
          <button class="send">Send</button>
        </div>
      </div>
    `;
  }
}

customElements.define('chat-widget', ChatWidget);
