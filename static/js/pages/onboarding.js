/**
 * Onboarding Page Component
 * Model selection and download progress for first-time setup
 */

class OnboardingPage extends HTMLElement {
  constructor() {
    super();
    this.isInitialized = false;
    this.models = [];
    this.selectedModel = null;
    this.pollInterval = null;
  }

  connectedCallback() {
    if (this.isInitialized) {
      this.checkAndResume();
      return;
    }
    this.isInitialized = true;
    this.render();
    this.loadModels();
    this.setupWebSocket();
  }

  disconnectedCallback() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
  }

  async checkAndResume() {
    // If already downloading, resume progress display
    try {
      const res = await fetch('/api/embeddings/loading-status');
      const data = await res.json();
      if (data.status === 'downloading' || data.status === 'loading') {
        this.showProgress(data);
        this.startPolling();
      } else if (data.status === 'ready') {
        // 모델이 이미 준비됨 — 모델 변경 UI 표시
        this.showModelChangeUI(data.model);
      }
    } catch (e) {
      // ignore
    }
  }

  render() {
    this.innerHTML = `
      <div class="onboarding-container">
        <div class="onboarding-header">
          <h1>Welcome to mem-mesh</h1>
          <p class="onboarding-subtitle">
            Select an embedding model to get started. The model converts your text into vectors for semantic search.
          </p>
        </div>

        <div id="model-cards" class="model-cards">
          <div class="loading-placeholder">Loading available models...</div>
        </div>

        <div id="progress-section" class="progress-section" style="display:none;">
          <div class="progress-info">
            <span id="progress-model" class="progress-model"></span>
            <span id="progress-status" class="progress-status"></span>
          </div>
          <div class="progress-bar-container">
            <div id="progress-bar" class="progress-bar" style="width:0%"></div>
          </div>
          <p id="progress-text" class="progress-text">Preparing...</p>
        </div>

        <div id="ready-section" class="ready-section" style="display:none;">
          <div class="ready-icon">&#10003;</div>
          <h2>Model Ready</h2>
          <p>Your embedding model is loaded and ready to use.</p>
          <button class="btn-primary" id="go-dashboard">Go to Dashboard</button>
        </div>

        <div id="error-section" class="error-section" style="display:none;">
          <h3>Download Failed</h3>
          <p id="error-message"></p>
          <button class="btn-secondary" id="retry-btn">Retry</button>
        </div>
      </div>

      <style>
        .onboarding-container {
          max-width: 800px;
          margin: 2rem auto;
          padding: 0 1.5rem;
        }
        .onboarding-header {
          text-align: center;
          margin-bottom: 2rem;
        }
        .onboarding-header h1 {
          font-size: 1.8rem;
          margin-bottom: 0.5rem;
        }
        .onboarding-subtitle {
          color: var(--text-secondary, #666);
          font-size: 0.95rem;
        }
        .model-cards {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
          gap: 1rem;
          margin-bottom: 2rem;
        }
        .model-card {
          border: 2px solid var(--border-color, #e0e0e0);
          border-radius: 12px;
          padding: 1.25rem;
          cursor: pointer;
          transition: border-color 0.2s, box-shadow 0.2s;
          position: relative;
          background: var(--bg-card, #fff);
        }
        .model-card:hover {
          border-color: var(--accent-color, #4f46e5);
          box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .model-card.selected {
          border-color: var(--accent-color, #4f46e5);
          box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.15);
        }
        .model-card-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 0.5rem;
        }
        .model-name {
          font-weight: 600;
          font-size: 0.95rem;
          font-family: monospace;
        }
        .model-badge {
          font-size: 0.7rem;
          padding: 2px 8px;
          border-radius: 10px;
          font-weight: 600;
        }
        .badge-recommended {
          background: var(--accent-color, #4f46e5);
          color: white;
        }
        .badge-cached {
          background: #22c55e;
          color: white;
        }
        .model-desc {
          color: var(--text-secondary, #666);
          font-size: 0.85rem;
          margin-bottom: 0.75rem;
        }
        .model-meta {
          display: flex;
          gap: 1rem;
          font-size: 0.8rem;
          color: var(--text-tertiary, #999);
        }
        .model-meta span {
          display: flex;
          align-items: center;
          gap: 0.25rem;
        }
        .select-btn {
          display: block;
          width: 100%;
          margin-top: 1rem;
          padding: 0.6rem;
          border: none;
          border-radius: 8px;
          background: var(--accent-color, #4f46e5);
          color: white;
          font-weight: 600;
          cursor: pointer;
          font-size: 0.9rem;
          transition: opacity 0.2s;
        }
        .select-btn:hover { opacity: 0.9; }
        .select-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .progress-section {
          text-align: center;
          padding: 2rem;
          border: 2px solid var(--border-color, #e0e0e0);
          border-radius: 12px;
          background: var(--bg-card, #fff);
        }
        .progress-info {
          display: flex;
          justify-content: space-between;
          margin-bottom: 0.75rem;
          font-size: 0.85rem;
        }
        .progress-model { font-weight: 600; font-family: monospace; }
        .progress-status { color: var(--text-secondary, #666); }
        .progress-bar-container {
          width: 100%;
          height: 8px;
          background: var(--bg-tertiary, #eee);
          border-radius: 4px;
          overflow: hidden;
        }
        .progress-bar {
          height: 100%;
          background: var(--accent-color, #4f46e5);
          border-radius: 4px;
          transition: width 0.5s ease;
        }
        .progress-bar.loading-pulse {
          animation: pulse-bar 1.5s ease-in-out infinite;
        }
        @keyframes pulse-bar {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
        .progress-text {
          margin-top: 0.75rem;
          font-size: 0.85rem;
          color: var(--text-secondary, #666);
        }
        .ready-section {
          text-align: center;
          padding: 3rem 2rem;
        }
        .ready-icon {
          font-size: 3rem;
          color: #22c55e;
          margin-bottom: 1rem;
        }
        .ready-section h2 { margin-bottom: 0.5rem; }
        .btn-primary {
          display: inline-block;
          margin-top: 1rem;
          padding: 0.75rem 2rem;
          background: var(--accent-color, #4f46e5);
          color: white;
          border: none;
          border-radius: 8px;
          font-weight: 600;
          cursor: pointer;
          font-size: 1rem;
        }
        .btn-primary:hover { opacity: 0.9; }
        .btn-secondary {
          display: inline-block;
          margin-top: 1rem;
          padding: 0.6rem 1.5rem;
          background: var(--bg-tertiary, #eee);
          color: var(--text-primary, #333);
          border: none;
          border-radius: 8px;
          cursor: pointer;
        }
        .error-section {
          text-align: center;
          padding: 2rem;
          color: #ef4444;
        }
        .loading-placeholder {
          text-align: center;
          padding: 2rem;
          color: var(--text-secondary, #666);
          grid-column: 1 / -1;
        }
      </style>
    `;

    // Event delegation
    this.addEventListener('click', (e) => {
      if (e.target.id === 'go-dashboard' || e.target.closest('#go-dashboard')) {
        window.app?.router?.navigate('/dashboard');
      }
      if (e.target.id === 'retry-btn') {
        this.hideAllSections();
        this.querySelector('#model-cards').style.display = '';
        this.loadModels();
      }
      if (e.target.classList.contains('select-btn')) {
        const model = e.target.dataset.model;
        if (model) this.selectModel(model);
      }
    });
  }

  async loadModels() {
    try {
      const res = await fetch('/api/embeddings/models');
      const data = await res.json();
      this.models = data.models || [];
      this.renderModelCards();

      // Check if already loading
      const statusRes = await fetch('/api/embeddings/loading-status');
      const status = await statusRes.json();
      if (status.status === 'downloading' || status.status === 'loading') {
        this.showProgress(status);
        this.startPolling();
      } else if (status.status === 'ready') {
        this.showModelChangeUI(status.model);
      }
    } catch (e) {
      this.querySelector('#model-cards').innerHTML = `
        <div class="loading-placeholder">Failed to load models. Is the server running?</div>
      `;
    }
  }

  renderModelCards() {
    const container = this.querySelector('#model-cards');
    if (!container) return;

    container.innerHTML = this.models.map(m => `
      <div class="model-card" data-model="${m.name}">
        <div class="model-card-header">
          <span class="model-name">${m.name}</span>
          <span>
            ${m.recommended ? '<span class="model-badge badge-recommended">Recommended</span>' : ''}
            ${m.cached ? '<span class="model-badge badge-cached">Cached</span>' : ''}
          </span>
        </div>
        <div class="model-desc">${m.description}</div>
        <div class="model-meta">
          <span>dim: ${m.dimension}</span>
          <span>${m.size}</span>
        </div>
        <button class="select-btn" data-model="${m.name}">
          ${m.cached ? 'Load Model' : 'Download & Load'}
        </button>
      </div>
    `).join('');
  }

  async selectModel(modelName) {
    // Disable all buttons
    this.querySelectorAll('.select-btn').forEach(btn => btn.disabled = true);

    try {
      const res = await fetch('/api/embeddings/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelName }),
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || 'Failed to select model');
      }

      this.showProgress(data);
      this.startPolling();
    } catch (e) {
      this.showError(e.message);
    }
  }

  showProgress(data) {
    this.querySelector('#model-cards').style.display = 'none';
    this.querySelector('#error-section').style.display = 'none';
    this.querySelector('#ready-section').style.display = 'none';

    const section = this.querySelector('#progress-section');
    section.style.display = '';

    this.updateProgress(data);
  }

  updateProgress(data) {
    const pct = Math.round((data.progress || 0) * 100);
    const bar = this.querySelector('#progress-bar');
    const text = this.querySelector('#progress-text');
    const model = this.querySelector('#progress-model');
    const status = this.querySelector('#progress-status');

    if (model) model.textContent = data.model || '';
    if (status) status.textContent = data.status || '';

    // loading 상태에서는 progress bar에 pulse 애니메이션 적용
    if (data.status === 'loading') {
      if (bar) {
        bar.style.width = Math.max(pct, 60) + '%';
        bar.classList.add('loading-pulse');
      }
    } else {
      if (bar) {
        bar.style.width = pct + '%';
        bar.classList.remove('loading-pulse');
      }
    }

    const messages = {
      downloading: 'Downloading model files...',
      loading: 'Loading model into memory (this may take a moment)...',
      ready: 'Model ready! Redirecting...',
      error: 'An error occurred.',
    };
    if (text) text.textContent = messages[data.status] || `${pct}%`;

    if (data.status === 'ready') {
      this.onModelReady();
    } else if (data.status === 'error') {
      this.showError(data.error || 'Unknown error');
    }
  }

  startPolling() {
    if (this.pollInterval) clearInterval(this.pollInterval);
    this.pollInterval = setInterval(async () => {
      try {
        const res = await fetch('/api/embeddings/loading-status');
        const data = await res.json();
        this.updateProgress(data);
        if (data.status === 'ready' || data.status === 'error') {
          clearInterval(this.pollInterval);
          this.pollInterval = null;
        }
      } catch (e) {
        // Server might be busy, keep polling
      }
    }, 1500);
  }

  setupWebSocket() {
    // Listen for model_download events via existing WebSocket
    window.addEventListener('ws:model_download', (e) => {
      const data = e.detail;
      if (data) this.updateProgress(data);
    });
  }

  onModelReady() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
    // 모델 변경 중이었으면 자동 대시보드 이동
    if (this._isChangingModel) {
      this._isChangingModel = false;
      setTimeout(() => {
        window.app?.router?.navigate('/dashboard');
      }, 800);
      return;
    }
    // 최초 온보딩이면 자동 대시보드 이동
    setTimeout(() => {
      window.app?.router?.navigate('/dashboard');
    }, 800);
  }

  showModelChangeUI(currentModel) {
    // 모델이 이미 로드된 상태에서 온보딩 페이지 접근 — 모델 변경 UI
    const header = this.querySelector('.onboarding-header');
    if (header) {
      header.innerHTML = `
        <h1>Change Embedding Model</h1>
        <p class="onboarding-subtitle">
          Current model: <code style="background:rgba(0,0,0,0.06);padding:2px 6px;border-radius:4px;font-size:0.85rem;">${currentModel || 'unknown'}</code>
        </p>
        <p class="onboarding-subtitle" style="margin-top:0.5rem;">
          Select a different model below. <strong>Warning:</strong> Changing the model requires re-embedding all memories.
        </p>
        <button class="btn-back" id="back-to-dashboard" style="margin-top:0.75rem;padding:0.4rem 1rem;border:1px solid var(--border-color,#e0e0e0);border-radius:6px;background:none;cursor:pointer;font-size:0.85rem;">
          &larr; Back to Dashboard
        </button>
      `;
      this.querySelector('#back-to-dashboard')?.addEventListener('click', () => {
        window.app?.router?.navigate('/dashboard');
      });
    }

    // 모델 카드에서 현재 모델 하이라이트
    const cards = this.querySelector('#model-cards');
    if (cards) {
      cards.style.display = '';
      cards.querySelectorAll('.model-card').forEach(card => {
        if (card.dataset.model === currentModel) {
          card.classList.add('selected');
          const btn = card.querySelector('.select-btn');
          if (btn) btn.textContent = 'Current Model';
        }
      });
    }

    // 모델 변경 시 플래그 설정
    this._isChangingModel = true;
  }

  showError(message) {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
    this.hideAllSections();
    const section = this.querySelector('#error-section');
    section.style.display = '';
    this.querySelector('#error-message').textContent = message;
  }

  hideAllSections() {
    this.querySelector('#model-cards').style.display = 'none';
    this.querySelector('#progress-section').style.display = 'none';
    this.querySelector('#ready-section').style.display = 'none';
    this.querySelector('#error-section').style.display = 'none';
  }
}

customElements.define('onboarding-page', OnboardingPage);

export { OnboardingPage };
