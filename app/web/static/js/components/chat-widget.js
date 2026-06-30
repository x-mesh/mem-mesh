/**
 * Floating chat assistant widget (M1d).
 *
 * A draggable launcher that expands into a chat panel. Talks to the
 * /api/chat/v1/stream SSE endpoint (POST + fetch ReadableStream), rendering
 * tool-call progress and the assistant's answer. Position persists in
 * localStorage; mounted once globally so it floats across all dashboard pages.
 */

const POS_KEY = 'memmesh.chat.pos';
const STREAM_URL = '/api/chat/v1/stream';

export class ChatWidget extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.open = false;
    this.busy = false;
    this.sessionId = null;
    this.messages = []; // {role, text}
    this._drag = null;
  }

  connectedCallback() {
    this.shadowRoot.innerHTML = this._template();
    this._els = {
      launcher: this.shadowRoot.querySelector('.launcher'),
      panel: this.shadowRoot.querySelector('.panel'),
      list: this.shadowRoot.querySelector('.messages'),
      input: this.shadowRoot.querySelector('textarea'),
      send: this.shadowRoot.querySelector('.send'),
      status: this.shadowRoot.querySelector('.status'),
    };
    this._restorePosition();
    this._bind();
  }

  // ----- layout / drag --------------------------------------------------

  _restorePosition() {
    let pos = null;
    try {
      pos = JSON.parse(localStorage.getItem(POS_KEY) || 'null');
    } catch (_) {
      pos = null;
    }
    if (pos && typeof pos.x === 'number' && typeof pos.y === 'number') {
      this.style.left = `${this._clampX(pos.x)}px`;
      this.style.top = `${this._clampY(pos.y)}px`;
      this.style.right = 'auto';
      this.style.bottom = 'auto';
    }
  }

  _clampX(x) {
    return Math.max(8, Math.min(x, window.innerWidth - 72));
  }
  _clampY(y) {
    return Math.max(8, Math.min(y, window.innerHeight - 72));
  }

  _bind() {
    const l = this._els.launcher;
    l.addEventListener('pointerdown', (e) => this._onDown(e));
    window.addEventListener('pointermove', (e) => this._onMove(e));
    window.addEventListener('pointerup', (e) => this._onUp(e));
    this.shadowRoot.querySelector('.close').addEventListener('click', () => this._toggle(false));
    this._els.send.addEventListener('click', () => this._submit());
    this._els.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this._submit();
      }
    });
  }

  _onDown(e) {
    const rect = this.getBoundingClientRect();
    this._drag = {
      startX: e.clientX,
      startY: e.clientY,
      offX: e.clientX - rect.left,
      offY: e.clientY - rect.top,
      moved: false,
    };
    this._els.launcher.setPointerCapture?.(e.pointerId);
  }

  _onMove(e) {
    if (!this._drag) return;
    const dx = e.clientX - this._drag.startX;
    const dy = e.clientY - this._drag.startY;
    if (!this._drag.moved && Math.hypot(dx, dy) < 4) return;
    this._drag.moved = true;
    const x = this._clampX(e.clientX - this._drag.offX);
    const y = this._clampY(e.clientY - this._drag.offY);
    this.style.left = `${x}px`;
    this.style.top = `${y}px`;
    this.style.right = 'auto';
    this.style.bottom = 'auto';
  }

  _onUp() {
    if (!this._drag) return;
    if (this._drag.moved) {
      const rect = this.getBoundingClientRect();
      try {
        localStorage.setItem(POS_KEY, JSON.stringify({ x: rect.left, y: rect.top }));
      } catch (_) {
        /* ignore quota errors */
      }
    } else {
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
    // page memory id from the route (e.g. /memories/{id} or /memory/{id})
    const m = window.location.pathname.match(/\/memor(?:y|ies)\/([\w-]+)/);
    this.pageMemoryId = m ? m[1] : null;
    // project context, if the dashboard exposes one
    this.projectId =
      window.app?.appState?.currentProjectId ||
      window.__MEMMESH_PROJECT_ID__ ||
      null;
  }

  // ----- chat -----------------------------------------------------------

  async _submit() {
    const text = this._els.input.value.trim();
    if (!text || this.busy) return;
    this._els.input.value = '';
    this._addMessage('user', text);
    const bubble = this._addMessage('assistant', '');
    this._setBusy(true);
    this._setStatus('Thinking…');
    try {
      await this._stream(text, bubble);
    } catch (err) {
      bubble.textContent = `Error: ${err.message}`;
      bubble.classList.add('error');
    } finally {
      this._setBusy(false);
      this._setStatus('');
    }
  }

  async _stream(text, bubble) {
    const body = {
      messages: [{ role: 'user', content: text }],
      session_id: this.sessionId || undefined,
      project_id: this.projectId || undefined,
      page_memory_id: this.pageMemoryId || undefined,
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
      buf += decoder.decode(value, { stream: true });
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
        this._setStatus(`🔧 ${payload.name}…`);
        break;
      case 'tool_result':
        this._setStatus(`${payload.ok ? '✓' : '✗'} ${payload.name}`);
        break;
      case 'message':
        bubble.textContent = payload.text || '';
        this._scroll();
        break;
      case 'done':
        if (payload.truncated) this._setStatus('(stopped at step limit)');
        break;
      case 'error':
        bubble.textContent = `Error: ${payload.detail || 'request failed'}`;
        bubble.classList.add('error');
        break;
    }
  }

  // ----- rendering ------------------------------------------------------

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
  }

  _setStatus(text) {
    this._els.status.textContent = text || '';
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
          width: 56px;
          height: 56px;
          border-radius: 50%;
          background: #111827;
          color: #fff;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: grab;
          box-shadow: 0 6px 20px rgba(0,0,0,0.25);
          touch-action: none;
          user-select: none;
        }
        .launcher:active { cursor: grabbing; }
        .launcher.hidden { display: none; }
        .launcher svg { width: 26px; height: 26px; }
        .panel {
          display: none;
          flex-direction: column;
          width: 380px;
          max-width: calc(100vw - 32px);
          height: 540px;
          max-height: calc(100vh - 48px);
          background: #fff;
          color: #111827;
          border: 1px solid #e5e7eb;
          border-radius: 14px;
          box-shadow: 0 18px 50px rgba(0,0,0,0.28);
          overflow: hidden;
        }
        .panel.open { display: flex; }
        .header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 14px;
          border-bottom: 1px solid #f0f0f0;
          font-weight: 600;
          font-size: 14px;
        }
        .close {
          border: none;
          background: transparent;
          font-size: 18px;
          cursor: pointer;
          color: #6b7280;
          line-height: 1;
        }
        .messages {
          flex: 1;
          overflow-y: auto;
          padding: 14px;
          display: flex;
          flex-direction: column;
          gap: 10px;
          background: #fafafa;
        }
        .msg {
          padding: 8px 12px;
          border-radius: 12px;
          max-width: 85%;
          white-space: pre-wrap;
          word-break: break-word;
          font-size: 13.5px;
          line-height: 1.45;
        }
        .msg.user { align-self: flex-end; background: #111827; color: #fff; border-bottom-right-radius: 4px; }
        .msg.assistant { align-self: flex-start; background: #fff; border: 1px solid #e5e7eb; border-bottom-left-radius: 4px; }
        .msg.error { color: #b91c1c; border-color: #fecaca; }
        .status { padding: 0 14px; min-height: 18px; font-size: 12px; color: #6b7280; }
        .composer {
          display: flex;
          gap: 8px;
          padding: 12px 14px;
          border-top: 1px solid #f0f0f0;
        }
        textarea {
          flex: 1;
          resize: none;
          height: 38px;
          max-height: 120px;
          padding: 8px 10px;
          border: 1px solid #e5e7eb;
          border-radius: 10px;
          font: inherit;
          font-size: 13.5px;
        }
        .send {
          border: none;
          background: #111827;
          color: #fff;
          border-radius: 10px;
          padding: 0 16px;
          font-weight: 600;
          cursor: pointer;
        }
        .send:disabled { opacity: 0.5; cursor: not-allowed; }
        @media (max-width: 480px) {
          .panel { width: calc(100vw - 16px); height: calc(100vh - 90px); }
        }
      </style>
      <div class="launcher" title="Ask the memory assistant">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
      </div>
      <div class="panel">
        <div class="header">
          <span>Memory Assistant</span>
          <button class="close" title="Close">×</button>
        </div>
        <div class="messages"></div>
        <div class="status"></div>
        <div class="composer">
          <textarea placeholder="Ask about your memories…" rows="1"></textarea>
          <button class="send">Send</button>
        </div>
      </div>
    `;
  }
}

customElements.define('chat-widget', ChatWidget);
