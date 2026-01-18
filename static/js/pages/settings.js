/**
 * Settings Page - Embedding Model Management
 * 임베딩 모델 상태 확인 및 마이그레이션 관리
 */

import { apiClient } from '../services/api-client.js';
import { showToast } from '../utils/toast-notifications.js';

class SettingsPage {
    constructor() {
        this.container = null;
        this.statusData = null;
        this.migrationInterval = null;
    }

    async render(container) {
        this.container = container;
        
        container.innerHTML = `
            <div class="settings-page page-container">
                <header class="page-header">
                    <div class="page-header-main">
                        <h1 class="page-title">Settings</h1>
                        <p class="page-subtitle">Embedding Model Management</p>
                    </div>
                </header>
                
                <div class="settings-content">
                    <!-- Embedding Status Card -->
                    <div class="card embedding-status-card">
                        <div class="card-header">
                            <h2>📊 Embedding Model Status</h2>
                            <button id="refresh-status-btn" class="btn btn-secondary btn-sm">
                                🔄 Refresh
                            </button>
                        </div>
                        <div class="card-body" id="embedding-status">
                            <div class="loading-spinner">Loading...</div>
                        </div>
                    </div>
                    
                    <!-- Migration Card -->
                    <div class="card migration-card">
                        <div class="card-header">
                            <h2>🔄 Embedding Migration</h2>
                        </div>
                        <div class="card-body" id="migration-section">
                            <p class="description">
                                임베딩 모델이 변경되었거나 벡터 데이터를 재생성해야 할 때 마이그레이션을 실행하세요.
                            </p>
                            <div class="migration-controls">
                                <div class="form-group">
                                    <label>
                                        <input type="checkbox" id="force-migration"> 
                                        Force Migration (모델이 같아도 재임베딩)
                                    </label>
                                </div>
                                <div class="form-group">
                                    <label for="batch-size">Batch Size:</label>
                                    <input type="number" id="batch-size" value="100" min="10" max="500">
                                </div>
                                <button id="start-migration-btn" class="btn btn-primary">
                                    🚀 Start Migration
                                </button>
                            </div>
                            <div id="migration-progress" class="migration-progress hidden">
                                <div class="progress-bar-container">
                                    <div class="progress-bar" id="progress-bar"></div>
                                </div>
                                <div class="progress-stats" id="progress-stats"></div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Info Card -->
                    <div class="card info-card">
                        <div class="card-header">
                            <h2>ℹ️ Information</h2>
                        </div>
                        <div class="card-body">
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
        `;
        
        this.bindEvents();
        await this.loadStatus();
    }

    bindEvents() {
        document.getElementById('refresh-status-btn')?.addEventListener('click', () => this.loadStatus());
        document.getElementById('start-migration-btn')?.addEventListener('click', () => this.startMigration());
    }

    async loadStatus() {
        const statusContainer = document.getElementById('embedding-status');
        if (!statusContainer) return;
        
        statusContainer.innerHTML = '<div class="loading-spinner">Loading...</div>';
        
        try {
            const response = await fetch('/api/embeddings/status');
            if (!response.ok) throw new Error('Failed to fetch status');
            
            this.statusData = await response.json();
            this.renderStatus(statusContainer);
            
            // 마이그레이션 진행 중이면 폴링 시작
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
                        ${statusIcon} ${data.needs_migration ? 'Migration Required' : 'Models Match'}
                    </span>
                </div>
            </div>
        `;
    }

    async startMigration() {
        const force = document.getElementById('force-migration')?.checked || false;
        const batchSize = parseInt(document.getElementById('batch-size')?.value) || 100;
        const btn = document.getElementById('start-migration-btn');
        const progressSection = document.getElementById('migration-progress');
        
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
            
            if (result.success) {
                this.startProgressPolling();
            } else {
                throw new Error(result.error || 'Migration failed');
            }
        } catch (error) {
            console.error('Migration error:', error);
            showToast(`Migration failed: ${error.message}`, 'error');
            btn.disabled = false;
            btn.textContent = '🚀 Start Migration';
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
            
            if (!progress.in_progress && progress.status === 'completed') {
                clearInterval(this.migrationInterval);
                this.migrationInterval = null;
                
                const btn = document.getElementById('start-migration-btn');
                btn.disabled = false;
                btn.textContent = '🚀 Start Migration';
                
                showToast('Migration completed successfully!', 'success');
                await this.loadStatus();
            }
        } catch (error) {
            console.error('Progress update error:', error);
        }
    }

    renderProgress(progress) {
        const progressBar = document.getElementById('progress-bar');
        const progressStats = document.getElementById('progress-stats');
        
        if (progressBar) {
            progressBar.style.width = `${progress.percent}%`;
        }
        
        if (progressStats) {
            progressStats.innerHTML = `
                <div class="stat">
                    <span class="label">Progress:</span>
                    <span class="value">${progress.percent}%</span>
                </div>
                <div class="stat">
                    <span class="label">Processed:</span>
                    <span class="value">${progress.processed.toLocaleString()} / ${progress.total.toLocaleString()}</span>
                </div>
                <div class="stat">
                    <span class="label">Failed:</span>
                    <span class="value ${progress.failed > 0 ? 'error' : ''}">${progress.failed}</span>
                </div>
                <div class="stat">
                    <span class="label">Status:</span>
                    <span class="value">${progress.message}</span>
                </div>
            `;
        }
    }

    destroy() {
        if (this.migrationInterval) {
            clearInterval(this.migrationInterval);
            this.migrationInterval = null;
        }
    }
}

export const settingsPage = new SettingsPage();
