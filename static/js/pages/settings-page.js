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
        this.rulesIndex = null;
        this.rulesCache = new Map();
    }

    connectedCallback() {
        this.render();
        this.loadStatus();
        this.loadRulesIndex();
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
                    <div class="page-header-main">
                        <h1 class="page-title">설정</h1>
                        <p class="page-subtitle">임베딩 모델과 규칙을 관리합니다</p>
                    </div>
                </header>
                
                <div class="settings-content">
                    <!-- Embedding Status Card -->
                    <div class="card">
                        <div class="card-header">
                            <h2>임베딩 상태</h2>
                            <button id="refresh-status-btn" class="btn btn-secondary btn-sm">
                                새로고침
                            </button>
                        </div>
                        <div class="card-body" id="embedding-status">
                            <div class="loading-state">
                                <div class="spinner"></div>
                                <p>상태 불러오는 중...</p>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Migration Card -->
                    <div class="card">
                        <div class="card-header">
                            <h2>임베딩 마이그레이션</h2>
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
                                    마이그레이션 시작
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

                    <!-- Rules Manager Card -->
                    <div class="card">
                        <div class="card-header">
                            <h2>Rules 관리자</h2>
                            <button id="refresh-rules-btn" class="btn btn-secondary btn-sm">
                                새로고침
                            </button>
                        </div>
                        <div class="card-body">
                            <p class="description">
                                필요한 rules를 선택해 병합하고, 복사하거나 저장할 수 있습니다.
                            </p>
                            <div class="rules-layout">
                                <div class="rules-panel">
                                    <div class="rules-list" id="rules-list">
                                        <div class="loading-state">
                                            <div class="spinner"></div>
                                            <p>rules 불러오는 중...</p>
                                        </div>
                                    </div>
                                    <div class="rules-actions">
                                        <button id="merge-rules-btn" class="btn btn-primary btn-sm">
                                            선택 병합
                                        </button>
                                        <button id="copy-rules-btn" class="btn btn-secondary btn-sm">
                                            복사
                                        </button>
                                        <button id="download-rules-btn" class="btn btn-secondary btn-sm">
                                            다운로드
                                        </button>
                                    </div>
                                    <div class="rules-save">
                                        <label for="rules-target-select">저장 대상</label>
                                        <div class="rules-save-row">
                                            <select id="rules-target-select" class="form-input"></select>
                                            <button id="save-rules-btn" class="btn btn-primary btn-sm">
                                                저장
                                            </button>
                                        </div>
                                    </div>
                                </div>
                                <div class="rules-panel">
                                    <label for="rules-output">병합 결과</label>
                                    <textarea id="rules-output" class="rules-textarea" rows="16" placeholder="rules를 선택한 뒤 병합하면 여기에 표시됩니다."></textarea>
                                    <div class="rules-hint">
                                        rules는 외부 툴에 복붙해서 사용하세요. 저장 시 선택한 대상 파일이 덮어써집니다.
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- OAuth Settings Card -->
                    <div class="card">
                        <div class="card-header">
                            <h2>OAuth / 인증</h2>
                        </div>
                        <div class="card-body">
                            <p class="description">
                                MCP 클라이언트 인증을 위한 OAuth 2.1 클라이언트를 관리합니다.
                            </p>
                            <div class="oauth-link-section">
                                <a href="/oauth" class="btn btn-primary" data-route="/oauth">
                                    OAuth 클라이언트 관리
                                </a>
                            </div>
                            <div class="oauth-info">
                                <h4>환경변수</h4>
                                <ul>
                                    <li><code>MEM_MESH_AUTH_ENABLED</code> - 전역 인증 활성화</li>
                                    <li><code>MEM_MESH_MCP_AUTH_ENABLED</code> - MCP SSE 인증</li>
                                    <li><code>MEM_MESH_WEB_AUTH_ENABLED</code> - Web API 인증</li>
                                </ul>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Info Card -->
                    <div class="card">
                        <div class="card-header">
                            <h2>정보</h2>
                        </div>
                        <div class="card-body info-content">
                            <h3>임베딩 모델</h3>
                            <p>현재 시스템은 <code>sentence-transformers</code> 라이브러리를 사용하여 텍스트를 벡터로 변환합니다.</p>
                            <ul>
                                <li><strong>all-MiniLM-L6-v2</strong>: 빠르고 가벼운 영어 모델 (384 dimensions)</li>
                                <li><strong>intfloat/multilingual-e5-small</strong>: 다국어 지원 모델 (384 dimensions)</li>
                            </ul>
                            
                            <h3>마이그레이션</h3>
                            <p>모델을 변경하면 기존 메모리들의 임베딩을 새 모델로 재생성해야 합니다. 
                            마이그레이션은 배치 단위로 처리되며, 진행 상황을 실시간으로 확인할 수 있습니다.</p>
                            
                            <h3>설정</h3>
                            <p>모델 설정은 <code>.env</code> 파일의 <code>MEM_MESH_EMBEDDING_MODEL</code> 환경변수로 변경할 수 있습니다.</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <style>
                .settings-page {
                    width: 100%;
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
                    background: var(--bg-tertiary, #f5f5f5);
                    color: var(--text-primary, #333);
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
                    background: var(--text-muted, #ccc);
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

                .rules-layout {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
                    gap: 1rem;
                }

                .rules-panel {
                    display: flex;
                    flex-direction: column;
                    gap: 0.75rem;
                }

                .rules-list {
                    border: 1px solid var(--border-color, #e0e0e0);
                    border-radius: 8px;
                    padding: 0.75rem;
                    max-height: 320px;
                    overflow: auto;
                    background: var(--card-bg, #fff);
                }

                .rules-item {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    padding: 0.35rem 0.25rem;
                }

                .rules-item small {
                    color: var(--text-secondary, #666);
                }

                .rules-actions {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.5rem;
                }

                .rules-save {
                    display: flex;
                    flex-direction: column;
                    gap: 0.35rem;
                }

                .rules-save-row {
                    display: flex;
                    gap: 0.5rem;
                }

                .rules-textarea {
                    width: 100%;
                    min-height: 260px;
                    padding: 0.75rem;
                    border: 1px solid var(--border-color, #e0e0e0);
                    border-radius: 8px;
                    background: var(--code-bg, #f5f5f5);
                    color: var(--text-primary, #333);
                    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
                    font-size: 0.9rem;
                    line-height: 1.4;
                }

                .rules-hint {
                    font-size: 0.85rem;
                    color: var(--text-secondary, #666);
                }
                
                .oauth-link-section {
                    margin-bottom: 1.5rem;
                }
                
                .oauth-info {
                    margin-top: 1rem;
                    padding-top: 1rem;
                    border-top: 1px solid var(--border-color, #e0e0e0);
                }
                
                .oauth-info h4 {
                    margin: 0 0 0.5rem 0;
                    font-size: 1rem;
                    color: var(--text-primary, #333);
                }
                
                .oauth-info ul {
                    margin: 0;
                    padding-left: 1.5rem;
                }
                
                .oauth-info li {
                    margin-bottom: 0.25rem;
                    color: var(--text-secondary, #666);
                    font-size: 0.9rem;
                }
                
                .oauth-info code {
                    background: var(--code-bg, #f1f3f5);
                    padding: 0.15rem 0.35rem;
                    border-radius: 4px;
                    font-family: monospace;
                    font-size: 0.85em;
                }
            </style>
        `;
        
        this.bindEvents();
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

    async loadRulesIndex() {
        const listContainer = this.querySelector('#rules-list');
        if (!listContainer) return;

        listContainer.innerHTML = `
            <div class="loading-state">
                <div class="spinner"></div>
                <p>Loading rules...</p>
            </div>
        `;

        try {
            const data = await window.app.apiClient.get('/rules');
            this.rulesIndex = data.rules || [];
            this.renderRulesList();
            this.renderRulesTargets();
        } catch (error) {
            console.error('Failed to load rules index:', error);
            listContainer.innerHTML = `
                <div class="error-message">
                    rules를 불러오지 못했습니다: ${error.message}
                </div>
            `;
        }
    }

    renderRulesList() {
        const listContainer = this.querySelector('#rules-list');
        if (!listContainer) return;

        if (!this.rulesIndex || this.rulesIndex.length === 0) {
            listContainer.innerHTML = '<p class="description">사용 가능한 rules가 없습니다.</p>';
            return;
        }

        listContainer.innerHTML = '';
        this.rulesIndex.forEach((rule) => {
            const item = document.createElement('label');
            item.className = 'rules-item';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = rule.id;
            if (rule.id === 'core') {
                checkbox.checked = true;
                checkbox.disabled = true;
            }
            const text = document.createElement('span');
            text.textContent = `${rule.title} (${rule.id})`;
            const meta = document.createElement('small');
            meta.textContent = rule.kind ? ` ${rule.kind}` : '';
            item.appendChild(checkbox);
            item.appendChild(text);
            item.appendChild(meta);
            listContainer.appendChild(item);
        });
    }

    renderRulesTargets() {
        const select = this.querySelector('#rules-target-select');
        if (!select) return;

        select.innerHTML = '';
        (this.rulesIndex || []).forEach((rule) => {
            const option = document.createElement('option');
            option.value = rule.id;
            option.textContent = `${rule.title} (${rule.id})`;
            select.appendChild(option);
        });
    }

    getSelectedRuleIds() {
        const checkboxes = this.querySelectorAll('#rules-list input[type="checkbox"]');
        const selected = Array.from(checkboxes)
            .filter((checkbox) => checkbox.checked)
            .map((checkbox) => checkbox.value);
        if (!selected.includes('core')) {
            selected.unshift('core');
        }
        return selected;
    }

    async fetchRuleContent(ruleId) {
        if (this.rulesCache.has(ruleId)) {
            return this.rulesCache.get(ruleId);
        }
        const data = await window.app.apiClient.get(`/rules/${encodeURIComponent(ruleId)}`);
        const content = data.content || '';
        this.rulesCache.set(ruleId, content);
        return content;
    }

    async mergeSelectedRules() {
        const ruleIds = this.getSelectedRuleIds();
        if (ruleIds.length === 0) {
            showToast('최소 1개 이상의 rule을 선택하세요.', 'warning');
            return;
        }

        try {
            const contents = [];
            for (const ruleId of ruleIds) {
                const content = await this.fetchRuleContent(ruleId);
                contents.push(content.trim());
            }
            const merged = `${contents.join('\n\n---\n\n')}\n`;
            const output = this.querySelector('#rules-output');
            if (output) {
                output.value = merged;
            }
            showToast('rules 병합 완료.', 'success');
        } catch (error) {
            console.error('Failed to merge rules:', error);
            showToast(`병합 실패: ${error.message}`, 'error');
        }
    }

    async copyMergedRules() {
        const output = this.querySelector('#rules-output');
        if (!output || !output.value.trim()) {
            showToast('복사할 병합 결과가 없습니다.', 'warning');
            return;
        }
        try {
            await navigator.clipboard.writeText(output.value);
            showToast('클립보드에 복사했습니다.', 'success');
        } catch (error) {
            console.error('Copy failed:', error);
            showToast('복사에 실패했습니다.', 'error');
        }
    }

    downloadMergedRules() {
        const output = this.querySelector('#rules-output');
        if (!output || !output.value.trim()) {
            showToast('다운로드할 병합 결과가 없습니다.', 'warning');
            return;
        }
        const blob = new Blob([output.value], { type: 'text/markdown' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = 'rules-bundle.md';
        link.click();
        URL.revokeObjectURL(link.href);
    }

    async saveMergedRules() {
        const output = this.querySelector('#rules-output');
        const select = this.querySelector('#rules-target-select');
        if (!output || !select) return;
        const content = output.value.trim();
        if (!content) {
            showToast('저장할 병합 결과가 없습니다.', 'warning');
            return;
        }
        const ruleId = select.value;
        try {
            await window.app.apiClient.put(`/rules/${encodeURIComponent(ruleId)}`, { content });
            showToast('rules를 저장했습니다.', 'success');
            this.rulesCache.set(ruleId, content);
        } catch (error) {
            console.error('Save failed:', error);
            showToast(`저장 실패: ${error.message}`, 'error');
        }
    }

    async loadStatus() {
        const statusContainer = this.querySelector('#embedding-status');
        if (!statusContainer) return;
        
            statusContainer.innerHTML = `
                <div class="loading-state">
                    <div class="spinner"></div>
                    <p>상태 불러오는 중...</p>
                </div>
            `;
        
        try {
            this.statusData = await window.app.apiClient.get('/embeddings/status');
            this.renderStatus(statusContainer);
            
            if (this.statusData.migration_in_progress) {
                this.startProgressPolling();
            }
        } catch (error) {
            console.error('Failed to load embedding status:', error);
            statusContainer.innerHTML = `
                <div class="error-message">
                    상태를 불러오지 못했습니다: ${error.message}
                </div>
            `;
        }
    }

    renderStatus(container) {
        const data = this.statusData;
        const statusClass = data.needs_migration ? 'status-warning' : 'status-ok';
        const statusLabel = data.needs_migration ? '마이그레이션 필요' : '정상';
        
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
                        ${statusLabel}
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
        btn.textContent = '시작 중...';
        progressSection.classList.remove('hidden');
        
        try {
            const result = await window.app.apiClient.post('/embeddings/migrate', null, { force, batch_size: batchSize });
            
            if (result.skipped) {
                showToast(result.message, 'info');
                btn.disabled = false;
                btn.textContent = '마이그레이션 시작';
                progressSection.classList.add('hidden');
                return;
            }
            
            // 마이그레이션이 시작되었으면 polling 시작
            if (result.success || result.progress) {
                btn.textContent = '⏳ Migrating...';
                this.startProgressPolling();
                showToast('마이그레이션을 시작했습니다.', 'info');
            } else if (result.error) {
                throw new Error(result.error);
            }
            
        } catch (error) {
            console.error('Migration error:', error);
            showToast(`Migration failed: ${error.message}`, 'error');
            btn.disabled = false;
            btn.textContent = '마이그레이션 시작';
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
            const progress = await window.app.apiClient.get('/embeddings/migration/progress');
            this.renderProgress(progress);
            
            if (!progress.in_progress) {
                clearInterval(this.migrationInterval);
                this.migrationInterval = null;
                
                const btn = this.querySelector('#start-migration-btn');
                const progressSection = this.querySelector('#migration-progress');
                
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '마이그레이션 시작';
                }
                
                if (progress.status === 'completed') {
                    showToast('마이그레이션이 완료되었습니다.', 'success');
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
                    btn.textContent = '마이그레이션 시작';
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
