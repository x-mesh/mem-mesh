/**
 * Settings Page Web Component
 * Embedding Model Management UI
 */

import { showToast } from '../utils/toast-notifications.js';

export class SettingsPage extends HTMLElement {
    constructor() {
        super();
        this.statusData = null;
        this.migrationInterval = null;
    }

    connectedCallback() {
        this.render();
        this.loadStatus();
    }

    disconnectedCallback() {
        if (this.migrationInterval) {
            clearInterval(this.migrationInterval);
            this.migrationInterval = null;
        }
    }

    render() {
        this.innerHTML = `
            <div class="settings-page page-container">
                <header class="page-header">
                    <h1>⚙️ Settings</h1>
                    <p class="page-subtitle">Embedding Model Management</p>
                </header>
                
                <div class="settings-content">
                    <!-- Embedding Status Card -->
                    <div class="card">
                        <div class="card-header">
                            <h2>📊 Embedding Model Status</h2>
                            <button id="refresh-status-btn" class="btn btn-secondary btn-sm">
                                🔄 Refresh
                            </button>
                        </div>
                        <div class="card-body" id="embedding-status">
                            <div class="loading-state">
                                <div class="spinner"></div>
                                <p>Loading status...</p>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Migration Card -->
                    <div class="card">
                        <div class="card-header">
                            <h2>🔄 Embedding Migration</h2>
                        </div>
                        <div class="card-body" id="migration-section">
                            <p class="description">
                                임베딩 모델이 변경되었거나 벡터 데이터를 재생성해야 할 때 마이그레이션을 실행하세요.
                            </p>
                            <div class="migration-controls">
                                <div class="form-group checkbox-group">
                                    <label>
                                        <input type="checkbox" id="force-migration"> 
                                        Force Migration (모델이 같아도 재임베딩)
                                    </label>
                                </div>
                                <div class="form-group inline-group">
                                    <label for="batch-size">Batch Size:</label>
                                    <input type="number" id="batch-size" class="form-input" value="100" min="10" max="500" style="width: 100px;">
                                </div>
                                <button id="start-migration-btn" class="btn btn-primary">
                                    🚀 Start Migration
                                </button>
                            </div>
                            <div id="migration-progress" class="migration-progress hidden">
                                <div class="progress-container">
                                    <div class="progress-bar" id="progress-bar"></div>
                                </div>
                                <div class="progress-stats" id="progress-stats"></div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Info Card -->
                    <div class="card">
                        <div class="card-header">
                            <h2>ℹ️ Information</h2>
                        </div>
                        <div class="card-body info-content">
                            <h3>Embedding Model</h3>
                            <p>현재 시스템은 <code>sentence-transformers</code> 라이브러리를 사용하여 텍스트를 벡터로 변환합니다.</p>
                            <ul>
                                <li><strong>all-MiniLM-L6-v2</strong>: 빠르고 가벼운 영어 모델 (384 dimensions)</li>
                                <li><strong>intfloat/multilingual-e5-small</strong>: 다국어 지원 모델 (384 dimensions)</li>
                            </ul>
                            
                            <h3>Migration</h3>
                            <p>모델을 변경하면 기존 메모리들의 임베딩을 새 모델로 재생성해야 합니다. 
                            마이그레이션은 배치 단위로 처리되며, 진행 상황을 실시간으로 확인할 수 있습니다.</p>
                            
                            <h3>Configuration</h3>
                            <p>모델 설정은 <code>.env</code> 파일의 <code>MEM_MESH_EMBEDDING_MODEL</code> 환경변수로 변경할 수 있습니다.</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <style>
                .settings-page {
                    max-width: 900px;
                    margin: 0 auto;
                    padding: 2rem;
                }
                
                .page-header {
                    margin-bottom: 2rem;
                }
                
                .page-header h1 {
                    font-size: 2rem;
                    margin-bottom: 0.5rem;
                }
                
                .page-subtitle {
                    color: var(--text-secondary, #666);
                    font-size: 1.1rem;
                }
                
                .settings-content {
                    display: flex;
                    flex-direction: column;
                    gap: 1.5rem;
                }
                
                .card {
                    background: var(--card-bg, #fff);
                    border-radius: 12px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                    overflow: hidden;
                }
                
                .card-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 1rem 1.5rem;
                    background: var(--card-header-bg, #f8f9fa);
                    border-bottom: 1px solid var(--border-color, #e0e0e0);
                }
                
                .card-header h2 {
                    font-size: 1.2rem;
                    margin: 0;
                }
                
                .card-body {
                    padding: 1.5rem;
                }
                
                .status-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 1rem;
                }
                
                .status-item {
                    padding: 1rem;
                    background: var(--status-item-bg, #f8f9fa);
                    border-radius: 8px;
                }
                
                .status-item.full-width {
                    grid-column: 1 / -1;
                }
                
                .status-item label {
                    display: block;
                    font-size: 0.85rem;
                    color: var(--text-secondary, #666);
                    margin-bottom: 0.25rem;
                }
                
                .status-item .value {
                    font-size: 1.1rem;
                    font-weight: 600;
                }
                
                .status-item .value.highlight {
                    color: var(--text-primary);
                    font-weight: 700;
                }
                
                .status-item .value.status-ok {
                    color: var(--success-color, #28a745);
                }
                
                .status-item .value.status-warning {
                    color: var(--warning-color, #ffc107);
                }
                
                .migration-controls {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 1rem;
                    align-items: center;
                    margin-top: 1rem;
                }
                
                .checkbox-group label {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    cursor: pointer;
                }
                
                .inline-group {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                }
                
                .form-input {
                    padding: 0.5rem;
                    border: 1px solid var(--border-color, #ddd);
                    border-radius: 6px;
                    font-size: 1rem;
                }
                
                .btn {
                    padding: 0.5rem 1rem;
                    border: none;
                    border-radius: 6px;
                    cursor: pointer;
                    font-size: 0.9rem;
                    transition: all 0.2s;
                }
                
                .btn-primary {
                    background: var(--text-primary, #171717);
                    color: var(--bg-primary, #fff);
                }
                
                .btn-primary:hover {
                    background: var(--text-secondary, #525252);
                }
                
                .btn-primary:disabled {
                    background: #ccc;
                    cursor: not-allowed;
                }
                
                .btn-secondary {
                    background: var(--secondary-bg, #e9ecef);
                    color: var(--text-primary, #333);
                }
                
                .btn-secondary:hover {
                    background: var(--secondary-hover, #dee2e6);
                }
                
                .btn-sm {
                    padding: 0.35rem 0.75rem;
                    font-size: 0.85rem;
                }
                
                .migration-progress {
                    margin-top: 1.5rem;
                    padding: 1rem;
                    background: var(--progress-bg, #f8f9fa);
                    border-radius: 8px;
                }
                
                .migration-progress.hidden {
                    display: none;
                }
                
                .progress-container {
                    height: 24px;
                    background: var(--progress-track, #e9ecef);
                    border-radius: 12px;
                    overflow: hidden;
                    margin-bottom: 1rem;
                }
                
                .progress-bar {
                    height: 100%;
                    background: linear-gradient(90deg, var(--text-secondary, #525252), var(--text-muted, #a3a3a3));
                    border-radius: 12px;
                    transition: width 0.3s ease;
                    width: 0%;
                }
                
                .progress-stats {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 0.5rem;
                }
                
                .progress-stats .stat {
                    display: flex;
                    justify-content: space-between;
                    padding: 0.5rem;
                    background: var(--stat-bg, #fff);
                    border-radius: 4px;
                }
                
                .progress-stats .stat .label {
                    color: var(--text-secondary, #666);
                }
                
                .progress-stats .stat .value.error {
                    color: var(--error-color, #dc3545);
                }
                
                .info-content h3 {
                    margin-top: 1.5rem;
                    margin-bottom: 0.5rem;
                    font-size: 1.1rem;
                }
                
                .info-content h3:first-child {
                    margin-top: 0;
                }
                
                .info-content p {
                    color: var(--text-secondary, #666);
                    line-height: 1.6;
                }
                
                .info-content ul {
                    margin: 0.5rem 0;
                    padding-left: 1.5rem;
                }
                
                .info-content li {
                    margin-bottom: 0.5rem;
                    color: var(--text-secondary, #666);
                }
                
                .info-content code {
                    background: var(--code-bg, #f1f3f5);
                    padding: 0.2rem 0.4rem;
                    border-radius: 4px;
                    font-family: monospace;
                    font-size: 0.9em;
                }
                
                .loading-state {
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    padding: 2rem;
                    color: var(--text-secondary, #666);
                }
                
                .spinner {
                    width: 40px;
                    height: 40px;
                    border: 3px solid var(--border-color, #e0e0e0);
                    border-top-color: var(--primary-color, #007bff);
                    border-radius: 50%;
                    animation: spin 1s linear infinite;
                    margin-bottom: 1rem;
                }
                
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
                
                .error-message {
                    padding: 1rem;
                    background: var(--error-bg, #f8d7da);
                    color: var(--error-color, #721c24);
                    border-radius: 8px;
                }
                
                .description {
                    color: var(--text-secondary, #666);
                    margin-bottom: 1rem;
                }
            </style>
        `;
        
        this.bindEvents();
    }

    bindEvents() {
        this.querySelector('#refresh-status-btn')?.addEventListener('click', () => this.loadStatus());
        this.querySelector('#start-migration-btn')?.addEventListener('click', () => this.startMigration());
    }

    async loadStatus() {
        const statusContainer = this.querySelector('#embedding-status');
        if (!statusContainer) return;
        
        statusContainer.innerHTML = `
            <div class="loading-state">
                <div class="spinner"></div>
                <p>Loading status...</p>
            </div>
        `;
        
        try {
            const response = await fetch('/api/embeddings/status');
            if (!response.ok) throw new Error('Failed to fetch status');
            
            this.statusData = await response.json();
            this.renderStatus(statusContainer);
            
            if (this.statusData.migration_in_progress) {
                this.startProgressPolling();
            }
        } catch (error) {
            console.error('Failed to load embedding status:', error);
            statusContainer.innerHTML = `
                <div class="error-message">
                    ❌ Failed to load status: ${error.message}
                </div>
            `;
        }
    }

    renderStatus(container) {
        const data = this.statusData;
        const statusClass = data.needs_migration ? 'status-warning' : 'status-ok';
        const statusIcon = data.needs_migration ? '⚠️' : '✅';
        
        container.innerHTML = `
            <div class="status-grid">
                <div class="status-item">
                    <label>DB Stored Model</label>
                    <span class="value">${data.stored_model || '(not set)'}</span>
                </div>
                <div class="status-item">
                    <label>DB Stored Dimension</label>
                    <span class="value">${data.stored_dimension || '(not set)'}</span>
                </div>
                <div class="status-item">
                    <label>Current Model</label>
                    <span class="value highlight">${data.current_model}</span>
                </div>
                <div class="status-item">
                    <label>Current Dimension</label>
                    <span class="value">${data.current_dimension}</span>
                </div>
                <div class="status-item">
                    <label>Total Memories</label>
                    <span class="value">${data.total_memories.toLocaleString()}</span>
                </div>
                <div class="status-item">
                    <label>Vector Table Count</label>
                    <span class="value">${data.vector_count.toLocaleString()}</span>
                </div>
                <div class="status-item">
                    <label>Last Migration</label>
                    <span class="value">${data.last_migration ? new Date(data.last_migration).toLocaleString() : '(never)'}</span>
                </div>
                <div class="status-item full-width">
                    <label>Status</label>
                    <span class="value ${statusClass}">
                        ${statusIcon} ${data.needs_migration ? 'Migration Required - Model Mismatch' : 'Models Match - No Migration Needed'}
                    </span>
                </div>
            </div>
        `;
    }

    async startMigration() {
        const force = this.querySelector('#force-migration')?.checked || false;
        const batchSize = parseInt(this.querySelector('#batch-size')?.value) || 100;
        const btn = this.querySelector('#start-migration-btn');
        const progressSection = this.querySelector('#migration-progress');
        
        if (!confirm('Are you sure you want to start the migration? This may take some time.')) {
            return;
        }
        
        btn.disabled = true;
        btn.textContent = '⏳ Starting...';
        progressSection.classList.remove('hidden');
        
        try {
            const response = await fetch(`/api/embeddings/migrate?force=${force}&batch_size=${batchSize}`, {
                method: 'POST'
            });
            
            if (!response.ok) throw new Error('Failed to start migration');
            
            const result = await response.json();
            
            if (result.skipped) {
                showToast(result.message, 'info');
                btn.disabled = false;
                btn.textContent = '🚀 Start Migration';
                progressSection.classList.add('hidden');
                return;
            }
            
            // 마이그레이션이 시작되었으면 polling 시작
            if (result.success || result.progress) {
                btn.textContent = '⏳ Migrating...';
                this.startProgressPolling();
                showToast('Migration started!', 'info');
            } else if (result.error) {
                throw new Error(result.error);
            }
            
        } catch (error) {
            console.error('Migration error:', error);
            showToast(`Migration failed: ${error.message}`, 'error');
            btn.disabled = false;
            btn.textContent = '🚀 Start Migration';
            progressSection.classList.add('hidden');
        }
    }

    startProgressPolling() {
        if (this.migrationInterval) {
            clearInterval(this.migrationInterval);
        }
        
        this.migrationInterval = setInterval(async () => {
            await this.updateProgress();
        }, 1000);
    }

    async updateProgress() {
        try {
            const response = await fetch('/api/embeddings/migration/progress');
            if (!response.ok) throw new Error('Failed to fetch progress');
            
            const progress = await response.json();
            this.renderProgress(progress);
            
            if (!progress.in_progress) {
                clearInterval(this.migrationInterval);
                this.migrationInterval = null;
                
                const btn = this.querySelector('#start-migration-btn');
                const progressSection = this.querySelector('#migration-progress');
                
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '🚀 Start Migration';
                }
                
                if (progress.status === 'completed') {
                    showToast('Migration completed successfully!', 'success');
                    await this.loadStatus();
                    
                    // 3초 후 progress section 숨기기
                    setTimeout(() => {
                        if (progressSection) {
                            progressSection.classList.add('hidden');
                        }
                    }, 3000);
                } else if (progress.status === 'failed') {
                    showToast(`Migration failed: ${progress.message}`, 'error');
                    if (progressSection) {
                        progressSection.classList.add('hidden');
                    }
                }
            }
        } catch (error) {
            console.error('Progress update error:', error);
            // 연속 에러 발생 시 polling 중단
            if (this.progressErrorCount >= 3) {
                clearInterval(this.migrationInterval);
                this.migrationInterval = null;
                this.progressErrorCount = 0;
                
                const btn = this.querySelector('#start-migration-btn');
                const progressSection = this.querySelector('#migration-progress');
                
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '🚀 Start Migration';
                }
                if (progressSection) {
                    progressSection.classList.add('hidden');
                }
                
                showToast('Progress monitoring failed. Please check migration status manually.', 'error');
            } else {
                this.progressErrorCount = (this.progressErrorCount || 0) + 1;
            }
        }
    }

    renderProgress(progress) {
        const progressBar = this.querySelector('#progress-bar');
        const progressStats = this.querySelector('#progress-stats');
        
        // 기본값 설정
        const percent = progress.percent || 0;
        const processed = progress.processed || 0;
        const total = progress.total || 0;
        const failed = progress.failed || 0;
        const message = progress.message || 'Initializing...';
        
        if (progressBar) {
            progressBar.style.width = `${percent}%`;
        }
        
        if (progressStats) {
            progressStats.innerHTML = `
                <div class="stat">
                    <span class="label">Progress:</span>
                    <span class="value">${percent}%</span>
                </div>
                <div class="stat">
                    <span class="label">Processed:</span>
                    <span class="value">${processed.toLocaleString()} / ${total.toLocaleString()}</span>
                </div>
                <div class="stat">
                    <span class="label">Failed:</span>
                    <span class="value ${failed > 0 ? 'error' : ''}">${failed}</span>
                </div>
                <div class="stat">
                    <span class="label">Status:</span>
                    <span class="value">${message}</span>
                </div>
            `;
        }
    }
}

customElements.define('settings-page', SettingsPage);
