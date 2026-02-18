import { showToast } from '../utils/toast-notifications.js';

export class OAuthPage extends HTMLElement {
    constructor() {
        super();
        this.clients = [];
    }

    connectedCallback() {
        this.render();
        this.loadClients();
    }

    render() {
        this.innerHTML = `
            <div class="oauth-page page-container">
                <header class="page-header">
                    <div class="page-header-main">
                        <h1 class="page-title">OAuth Clients</h1>
                        <p class="page-subtitle">Manage OAuth clients for MCP authentication</p>
                    </div>
                    <button id="create-client-btn" class="btn btn-primary">
                        + New Client
                    </button>
                </header>
                
                <div class="oauth-content">
                    <div class="card">
                        <div class="card-header">
                            <h2>Client List</h2>
                            <button id="refresh-clients-btn" class="btn btn-secondary btn-sm">
                                Refresh
                            </button>
                        </div>
                        <div class="card-body" id="clients-container">
                            <div class="loading-state">
                                <div class="spinner"></div>
                                <p>Loading clients...</p>
                            </div>
                        </div>
                    </div>
                    
                    <div class="card">
                        <div class="card-header">
                            <h2>OAuth Configuration</h2>
                        </div>
                        <div class="card-body info-content">
                            <h3>Endpoints</h3>
                            <ul class="endpoint-list">
                                <li><code>GET /.well-known/oauth-authorization-server</code> - Metadata</li>
                                <li><code>GET /oauth/authorize</code> - Authorization Request</li>
                                <li><code>POST /oauth/token</code> - Token Issuance</li>
                                <li><code>POST /oauth/register</code> - Dynamic Client Registration</li>
                            </ul>
                            
                            <h3>Environment Variables</h3>
                            <ul>
                                <li><code>MEM_MESH_AUTH_ENABLED</code> - Enable global authentication</li>
                                <li><code>MEM_MESH_MCP_AUTH_ENABLED</code> - Enable MCP SSE authentication</li>
                                <li><code>MEM_MESH_WEB_AUTH_ENABLED</code> - Enable Web API authentication</li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
            
            <div id="create-modal" class="modal hidden">
                <div class="modal-backdrop"></div>
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>New OAuth Client</h3>
                        <button class="modal-close">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div class="form-group">
                            <label for="client-name">Client Name</label>
                            <input type="text" id="client-name" class="form-input" placeholder="e.g. My MCP Client">
                        </div>
                        <div class="form-group">
                            <label for="redirect-uris">Redirect URIs (one per line)</label>
                            <textarea id="redirect-uris" class="form-input" rows="3" placeholder="http://localhost:8080/callback"></textarea>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" id="cancel-create">Cancel</button>
                        <button class="btn btn-primary" id="confirm-create">Create</button>
                    </div>
                </div>
            </div>
            
            <div id="secret-modal" class="modal hidden">
                <div class="modal-backdrop"></div>
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Client Created Successfully</h3>
                        <button class="modal-close">&times;</button>
                    </div>
                    <div class="modal-body">
                        <p class="warning-text">⚠️ The client_secret will not be shown again after closing this dialog!</p>
                        <div class="secret-display">
                            <div class="form-group">
                                <label>Client ID</label>
                                <div class="copy-field">
                                    <code id="display-client-id"></code>
                                    <button class="btn btn-sm copy-btn" data-target="display-client-id">Copy</button>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>Client Secret</label>
                                <div class="copy-field">
                                    <code id="display-client-secret"></code>
                                    <button class="btn btn-sm copy-btn" data-target="display-client-secret">Copy</button>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-primary" id="close-secret-modal">OK</button>
                    </div>
                </div>
            </div>
            
            <style>
                .oauth-page { width: 100%; }
                .oauth-content { display: flex; flex-direction: column; gap: 1.5rem; }
                
                .page-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 1.5rem;
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
                
                .card-header h2 { font-size: 1.2rem; margin: 0; }
                .card-body { padding: 1.5rem; }
                
                .clients-table {
                    width: 100%;
                    border-collapse: collapse;
                }
                
                .clients-table th, .clients-table td {
                    padding: 0.75rem;
                    text-align: left;
                    border-bottom: 1px solid var(--border-color, #e0e0e0);
                }
                
                .clients-table th {
                    background: var(--table-header-bg, #f8f9fa);
                    font-weight: 600;
                }
                
                .clients-table td code {
                    background: var(--code-bg, #f1f3f5);
                    padding: 0.2rem 0.4rem;
                    border-radius: 4px;
                    font-size: 0.85em;
                }
                
                .status-badge {
                    display: inline-block;
                    padding: 0.25rem 0.5rem;
                    border-radius: 4px;
                    font-size: 0.8rem;
                    font-weight: 500;
                }
                
                .status-badge.active { background: #d4edda; color: #155724; }
                .status-badge.inactive { background: #f8d7da; color: #721c24; }
                
                .action-btns { display: flex; gap: 0.5rem; }
                .btn-danger { background: #dc3545; color: white; }
                .btn-danger:hover { background: #c82333; }
                
                .modal { position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; }
                .modal.hidden { display: none; }
                .modal-backdrop { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); }
                .modal-content { position: relative; background: var(--card-bg, #fff); border-radius: 12px; width: 90%; max-width: 500px; max-height: 90vh; overflow: auto; }
                .modal-header { display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.5rem; border-bottom: 1px solid var(--border-color, #e0e0e0); }
                .modal-header h3 { margin: 0; }
                .modal-close { background: none; border: none; font-size: 1.5rem; cursor: pointer; color: var(--text-secondary); }
                .modal-body { padding: 1.5rem; }
                .modal-footer { display: flex; justify-content: flex-end; gap: 0.5rem; padding: 1rem 1.5rem; border-top: 1px solid var(--border-color, #e0e0e0); }
                
                .form-group { margin-bottom: 1rem; }
                .form-group label { display: block; margin-bottom: 0.5rem; font-weight: 500; }
                .form-input { width: 100%; padding: 0.5rem; border: 1px solid var(--border-color, #ddd); border-radius: 6px; font-size: 1rem; }
                
                .warning-text { color: #856404; background: #fff3cd; padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; }
                
                .copy-field { display: flex; align-items: center; gap: 0.5rem; background: var(--code-bg, #f1f3f5); padding: 0.5rem; border-radius: 6px; }
                .copy-field code { flex: 1; word-break: break-all; }
                .copy-btn { flex-shrink: 0; }
                
                .btn { padding: 0.5rem 1rem; border: none; border-radius: 6px; cursor: pointer; font-size: 0.9rem; transition: all 0.2s; }
                .btn-primary { background: var(--text-primary, #171717); color: var(--bg-primary, #fff); }
                .btn-primary:hover { background: var(--text-secondary, #525252); }
                .btn-secondary { background: var(--secondary-bg, #e9ecef); color: var(--text-primary, #333); }
                .btn-secondary:hover { background: var(--secondary-hover, #dee2e6); }
                .btn-sm { padding: 0.35rem 0.75rem; font-size: 0.85rem; }
                
                .loading-state { display: flex; flex-direction: column; align-items: center; padding: 2rem; color: var(--text-secondary, #666); }
                .spinner { width: 40px; height: 40px; border: 3px solid var(--border-color, #e0e0e0); border-top-color: var(--primary-color, #007bff); border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 1rem; }
                @keyframes spin { to { transform: rotate(360deg); } }
                
                .empty-state { text-align: center; padding: 2rem; color: var(--text-secondary, #666); }
                
                .info-content h3 { margin-top: 1.5rem; margin-bottom: 0.5rem; font-size: 1.1rem; }
                .info-content h3:first-child { margin-top: 0; }
                .info-content ul { margin: 0.5rem 0; padding-left: 1.5rem; }
                .info-content li { margin-bottom: 0.5rem; color: var(--text-secondary, #666); }
                .info-content code { background: var(--code-bg, #f1f3f5); padding: 0.2rem 0.4rem; border-radius: 4px; font-family: monospace; font-size: 0.9em; }
                .endpoint-list { list-style: none; padding-left: 0; }
                .endpoint-list li { margin-bottom: 0.5rem; }
            </style>
        `;
        
        this.bindEvents();
    }

    bindEvents() {
        this.querySelector('#refresh-clients-btn')?.addEventListener('click', () => this.loadClients());
        this.querySelector('#create-client-btn')?.addEventListener('click', () => this.showCreateModal());
        this.querySelector('#cancel-create')?.addEventListener('click', () => this.hideCreateModal());
        this.querySelector('#confirm-create')?.addEventListener('click', () => this.createClient());
        this.querySelector('#close-secret-modal')?.addEventListener('click', () => this.hideSecretModal());
        
        this.querySelectorAll('.modal-close').forEach(btn => {
            btn.addEventListener('click', () => {
                this.hideCreateModal();
                this.hideSecretModal();
            });
        });
        
        this.querySelectorAll('.modal-backdrop').forEach(backdrop => {
            backdrop.addEventListener('click', () => {
                this.hideCreateModal();
                this.hideSecretModal();
            });
        });
        
        this.querySelectorAll('.copy-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.copyToClipboard(e));
        });
    }

    async loadClients() {
        const container = this.querySelector('#clients-container');
        if (!container) return;
        
        container.innerHTML = `
            <div class="loading-state">
                <div class="spinner"></div>
                <p>Loading clients...</p>
            </div>
        `;
        
        try {
            const response = await fetch('/api/oauth/clients');
            if (!response.ok) throw new Error('Failed to fetch clients');
            
            const data = await response.json();
            this.clients = data.clients || [];
            this.renderClients(container);
        } catch (error) {
            console.error('Failed to load clients:', error);
            container.innerHTML = `<div class="error-message">Failed to load clients: ${error.message}</div>`;
        }
    }

    renderClients(container) {
        if (this.clients.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <p>No OAuth clients registered.</p>
                    <p>Create a new client to start MCP authentication.</p>
                </div>
            `;
            return;
        }
        
        container.innerHTML = `
            <table class="clients-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Client ID</th>
                        <th>Status</th>
                        <th>Created</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${this.clients.map(client => `
                        <tr>
                            <td>${this.escapeHtml(client.client_name)}</td>
                            <td><code>${client.client_id}</code></td>
                            <td><span class="status-badge ${client.is_active ? 'active' : 'inactive'}">${client.is_active ? 'Active' : 'Inactive'}</span></td>
                            <td>${new Date(client.created_at).toLocaleDateString()}</td>
                            <td class="action-btns">
                                <button class="btn btn-sm btn-secondary" onclick="document.querySelector('oauth-page').regenerateSecret('${client.client_id}')">Regenerate Secret</button>
                                <button class="btn btn-sm btn-danger" onclick="document.querySelector('oauth-page').deleteClient('${client.client_id}')">Delete</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    }

    showCreateModal() {
        this.querySelector('#create-modal')?.classList.remove('hidden');
        this.querySelector('#client-name')?.focus();
    }

    hideCreateModal() {
        this.querySelector('#create-modal')?.classList.add('hidden');
        this.querySelector('#client-name').value = '';
        this.querySelector('#redirect-uris').value = '';
    }

    hideSecretModal() {
        this.querySelector('#secret-modal')?.classList.add('hidden');
    }

    async createClient() {
        const clientName = this.querySelector('#client-name')?.value.trim();
        const redirectUrisText = this.querySelector('#redirect-uris')?.value.trim();
        
        if (!clientName) {
            showToast('Please enter a client name.', 'warning');
            return;
        }
        
        const redirectUris = redirectUrisText ? redirectUrisText.split('\n').map(u => u.trim()).filter(u => u) : [];
        
        try {
            const response = await fetch('/api/oauth/clients', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    client_name: clientName,
                    redirect_uris: redirectUris,
                    scopes: ['read', 'write'],
                    grant_types: ['authorization_code', 'refresh_token'],
                }),
            });
            
            if (!response.ok) throw new Error('Failed to create client');
            
            const client = await response.json();
            
            this.hideCreateModal();
            this.showSecretModal(client.client_id, client.client_secret);
            await this.loadClients();
            
            showToast('OAuth client created successfully.', 'success');
        } catch (error) {
            console.error('Create client error:', error);
            showToast(`Failed to create client: ${error.message}`, 'error');
        }
    }

    showSecretModal(clientId, clientSecret) {
        this.querySelector('#display-client-id').textContent = clientId;
        this.querySelector('#display-client-secret').textContent = clientSecret;
        this.querySelector('#secret-modal')?.classList.remove('hidden');
    }

    async deleteClient(clientId) {
        if (!confirm('Are you sure you want to delete this client?\nAll tokens will be invalidated.')) {
            return;
        }
        
        try {
            const response = await fetch(`/api/oauth/clients/${clientId}`, { method: 'DELETE' });
            if (!response.ok) throw new Error('Failed to delete client');
            
            await this.loadClients();
            showToast('Client deleted successfully.', 'success');
        } catch (error) {
            console.error('Delete client error:', error);
            showToast(`Failed to delete: ${error.message}`, 'error');
        }
    }

    async regenerateSecret(clientId) {
        if (!confirm('Regenerate the secret?\nAll tokens issued with the existing secret will be invalidated.')) {
            return;
        }
        
        try {
            const response = await fetch(`/api/oauth/clients/${clientId}/regenerate-secret`, { method: 'POST' });
            if (!response.ok) throw new Error('Failed to regenerate secret');
            
            const data = await response.json();
            this.showSecretModal(clientId, data.client_secret);
            showToast('Secret regenerated successfully.', 'success');
        } catch (error) {
            console.error('Regenerate secret error:', error);
            showToast(`Failed to regenerate secret: ${error.message}`, 'error');
        }
    }

    async copyToClipboard(event) {
        const targetId = event.target.dataset.target;
        const targetElement = this.querySelector(`#${targetId}`);
        if (!targetElement) return;
        
        try {
            await navigator.clipboard.writeText(targetElement.textContent);
            showToast('Copied to clipboard.', 'success');
        } catch (error) {
            showToast('Failed to copy.', 'error');
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

customElements.define('oauth-page', OAuthPage);
