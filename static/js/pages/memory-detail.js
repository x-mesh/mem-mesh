/**
 * Memory Detail Page Component
 * Shows detailed view of a single memory with context and editing capabilities
 */

class MemoryDetailPage extends HTMLElement {
  constructor() {
    super();
    this.memoryId = null;
    this.memory = null;
    this.contextData = [];
    this.isLoading = true;
    this.isEditing = false;
    this.originalContent = '';
    this.isInitialized = false; // 중복 초기화 방지
  }
  
  connectedCallback() {
    if (this.isInitialized) {
      console.log('Memory detail page already initialized, skipping...');
      return;
    }
    
    this.isInitialized = true;
    this.memoryId = this.getAttribute('memory-id');
    this.render();
    this.setupEventListeners();
    this.waitForAppAndLoadData();
  }
  
  /**
   * Wait for app initialization and then load data
   */
  async waitForAppAndLoadData() {
    // 앱이 초기화될 때까지 최대 5초 대기
    let attempts = 0;
    const maxAttempts = 50; // 100ms * 50 = 5초
    
    const checkApp = () => {
      console.log(`Checking app for memory detail (attempt ${attempts + 1}/${maxAttempts})...`);
      
      if (window.app && window.app.apiClient) {
        console.log('App is ready, loading memory data...');
        this.loadMemoryData();
        return true;
      }
      
      attempts++;
      if (attempts >= maxAttempts) {
        console.error('App initialization timeout, trying direct API call...');
        this.loadMemoryDataDirect();
        return false;
      }
      
      setTimeout(checkApp, 100);
      return false;
    };
    
    checkApp();
  }
  
  disconnectedCallback() {
    this.removeEventListeners();
  }
  
  static get observedAttributes() {
    return ['memory-id'];
  }
  
  attributeChangedCallback(name, oldValue, newValue) {
    if (name === 'memory-id' && oldValue !== newValue && this.isInitialized) {
      this.memoryId = newValue;
      this.loadMemoryData();
    }
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    this.addEventListener('click', this.handleClick.bind(this));
    this.addEventListener('memory-select', this.handleMemorySelect.bind(this));
    this.addEventListener('context-expand', this.handleContextExpand.bind(this));
    
    // Listen for keyboard shortcuts
    document.addEventListener('keydown', this.handleKeydown.bind(this));
  }
  
  /**
   * Remove event listeners
   */
  removeEventListeners() {
    document.removeEventListener('keydown', this.handleKeydown);
  }
  
  /**
   * Handle click events
   */
  handleClick(event) {
    const target = event.target;
    
    if (target.classList.contains('edit-btn')) {
      this.toggleEditMode();
    } else if (target.classList.contains('save-btn')) {
      this.saveMemory();
    } else if (target.classList.contains('cancel-btn')) {
      this.cancelEdit();
    } else if (target.classList.contains('delete-btn')) {
      this.deleteMemory();
    } else if (target.classList.contains('back-btn')) {
      this.goBack();
    } else if (target.classList.contains('share-btn')) {
      this.shareMemory();
    } else if (target.classList.contains('export-btn')) {
      this.exportMemory();
    } else if (target.classList.contains('refresh-btn')) {
      this.loadMemoryData();
    } else if (target.classList.contains('view-context-btn')) {
      const memoryId = target.getAttribute('data-memory-id');
      if (memoryId && window.app && window.app.router) {
        window.app.router.navigate(`/memory/${memoryId}`);
      }
    }
  }
  
  /**
   * Handle memory selection from context
   */
  handleMemorySelect(event) {
    const { memoryId } = event.detail;
    if (window.app && window.app.router) {
      window.app.router.navigate(`/memory/${memoryId}`);
    }
  }
  
  /**
   * Handle context expansion
   */
  handleContextExpand(event) {
    const { memoryId, depth } = event.detail;
    this.loadContextData(memoryId, depth);
  }
  
  /**
   * Handle keyboard shortcuts
   */
  handleKeydown(event) {
    // Only handle shortcuts when not editing
    if (this.isEditing) return;
    
    if (event.ctrlKey || event.metaKey) {
      switch (event.key) {
        case 'e':
          event.preventDefault();
          this.toggleEditMode();
          break;
        case 's':
          event.preventDefault();
          if (this.isEditing) {
            this.saveMemory();
          }
          break;
        case 'Escape':
          if (this.isEditing) {
            this.cancelEdit();
          }
          break;
      }
    }
  }
  
  /**
   * Load memory data
   */
  async loadMemoryData() {
    if (!this.memoryId) return;
    
    this.isLoading = true;
    this.render(); // 로딩 상태 즉시 렌더링
    
    try {
      // 앱과 API 클라이언트 가용성 재확인
      if (!window.app) {
        throw new Error('App not available');
      }
      
      if (!window.app.apiClient) {
        throw new Error('API client not available');
      }
      
      console.log('Loading memory data for ID:', this.memoryId);
      
      // Load memory details and context in parallel
      const [memory, contextResponse] = await Promise.all([
        window.app.apiClient.getMemory(this.memoryId),
        window.app.apiClient.getContext(this.memoryId, 2)
      ]);
      
      console.log('Memory loaded:', memory);
      console.log('Context loaded:', contextResponse);
      
      this.memory = memory;
      this.contextData = contextResponse.related_memories || [];
      this.originalContent = memory.content;
      
      console.log('Memory data set successfully, rendering with data');
      
    } catch (error) {
      console.error('Failed to load memory:', error);
      if (window.app && window.app.errorHandler) {
        window.app.errorHandler.showError('Failed to load memory details');
      }
      
      // Handle 404 - memory not found
      if (error.status === 404) {
        this.showNotFound();
        return;
      }
    } finally {
      this.isLoading = false;
      console.log('Rendering final state with isLoading:', this.isLoading);
      this.render();
    }
  }

  /**
   * Load memory data using direct API calls (fallback)
   */
  async loadMemoryDataDirect() {
    if (!this.memoryId) return;
    
    console.log('loadMemoryDataDirect called for ID:', this.memoryId);
    
    this.isLoading = true;
    this.render(); // 로딩 상태 즉시 렌더링
    
    try {
      console.log('Loading memory data via direct API calls...');
      
      // 먼저 모든 메모리를 검색해서 해당 ID를 찾음
      const searchUrl = new URL('/api/memories/search', window.location.origin);
      searchUrl.searchParams.append('query', ' ');
      searchUrl.searchParams.append('limit', '100');
      
      const searchResponse = await fetch(searchUrl);
      if (!searchResponse.ok) {
        throw new Error(`Search failed: ${searchResponse.status}`);
      }
      
      const searchResult = await searchResponse.json();
      const memory = searchResult.results?.find(m => m.id === this.memoryId);
      
      if (!memory) {
        throw new Error('Memory not found');
      }
      
      // 컨텍스트 데이터 로드
      const contextUrl = new URL(`/api/memories/${this.memoryId}/context`, window.location.origin);
      contextUrl.searchParams.append('depth', '2');
      
      const contextResponse = await fetch(contextUrl);
      let contextData = [];
      
      if (contextResponse.ok) {
        const contextResult = await contextResponse.json();
        contextData = contextResult.related_memories || [];
      } else {
        console.warn('Context loading failed, continuing without context');
      }
      
      console.log('Direct API - Memory loaded:', memory);
      console.log('Direct API - Context loaded:', contextData);
      
      this.memory = memory;
      this.contextData = contextData;
      this.originalContent = memory.content;
      
      console.log('Direct API - Memory data set successfully');
      
    } catch (error) {
      console.error('Direct API - Failed to load memory:', error);
      this.showError('메모리를 불러오는데 실패했습니다. 페이지를 새로고침해주세요.');
    } finally {
      this.isLoading = false;
      console.log('Direct API - Rendering final state');
      this.render();
    }
  }
  
  /**
   * Load context data
   */
  async loadContextData(memoryId = this.memoryId, depth = 2) {
    try {
      if (window.app && window.app.apiClient) {
        const contextResponse = await window.app.apiClient.getContext(memoryId, depth);
        this.contextData = contextResponse.related_memories || [];
        this.updateContextDisplay();
      }
    } catch (error) {
      console.error('Failed to load context:', error);
    }
  }
  
  /**
   * Toggle edit mode
   */
  toggleEditMode() {
    this.isEditing = !this.isEditing;
    this.updateEditMode();
  }
  
  /**
   * Save memory changes
   */
  async saveMemory() {
    const contentTextarea = this.querySelector('.edit-content');
    const projectInput = this.querySelector('.edit-project');
    const categorySelect = this.querySelector('.edit-category');
    const tagsInput = this.querySelector('.edit-tags');
    
    if (!contentTextarea) return;
    
    const updatedData = {
      content: contentTextarea.value.trim(),
      project_id: projectInput?.value.trim() || null,
      category: categorySelect?.value || this.memory.category,
      tags: tagsInput?.value.split(',').map(tag => tag.trim()).filter(Boolean) || []
    };
    
    if (!updatedData.content) {
      if (window.app && window.app.errorHandler) {
        window.app.errorHandler.showError('Content cannot be empty');
      }
      return;
    }
    
    try {
      if (window.app && window.app.apiClient) {
        const updatedMemory = await window.app.apiClient.updateMemory(this.memoryId, updatedData);
        this.memory = updatedMemory;
        this.originalContent = updatedMemory.content;
        this.isEditing = false;
        
        if (window.app && window.app.errorHandler) {
          window.app.errorHandler.showSuccess('Memory updated successfully');
        }
        
        this.render();
      }
    } catch (error) {
      console.error('Failed to save memory:', error);
      if (window.app && window.app.errorHandler) {
        window.app.errorHandler.showError('Failed to save changes');
      }
    }
  }
  
  /**
   * Cancel edit mode
   */
  cancelEdit() {
    this.isEditing = false;
    this.render();
  }
  
  /**
   * Delete memory
   */
  async deleteMemory() {
    if (!confirm('Are you sure you want to delete this memory? This action cannot be undone.')) {
      return;
    }
    
    try {
      if (window.app && window.app.apiClient) {
        await window.app.apiClient.deleteMemory(this.memoryId);
        
        if (window.app && window.app.errorHandler) {
          window.app.errorHandler.showSuccess('Memory deleted successfully');
        }
        
        // Navigate back to search or dashboard
        this.goBack();
      }
    } catch (error) {
      console.error('Failed to delete memory:', error);
      if (window.app && window.app.errorHandler) {
        window.app.errorHandler.showError('Failed to delete memory');
      }
    }
  }
  
  /**
   * Go back to previous page
   */
  goBack() {
    if (window.history.length > 1) {
      window.history.back();
    } else {
      if (window.app && window.app.router) {
        window.app.router.navigate('/search');
      }
    }
  }
  
  /**
   * Share memory
   */
  shareMemory() {
    const url = `${window.location.origin}/memory/${this.memoryId}`;
    const title = 'mem-mesh Memory';
    const text = this.memory.content.substring(0, 100) + '...';
    
    if (navigator.share) {
      navigator.share({ title, text, url });
    } else {
      // Fallback: copy to clipboard
      navigator.clipboard.writeText(url).then(() => {
        if (window.app && window.app.errorHandler) {
          window.app.errorHandler.showSuccess('Link copied to clipboard');
        }
      });
    }
  }
  
  /**
   * Export memory
   */
  exportMemory() {
    const exportData = {
      ...this.memory,
      context: this.contextData,
      exported_at: new Date().toISOString()
    };
    
    const blob = new Blob([JSON.stringify(exportData, null, 2)], {
      type: 'application/json'
    });
    
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `memory-${this.memoryId}-${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
  

  /**
   * Update edit mode
   */
  updateEditMode() {
    const viewMode = this.querySelector('.view-mode');
    const editMode = this.querySelector('.edit-mode');
    const editBtn = this.querySelector('.edit-btn');
    
    if (viewMode) {
      viewMode.style.display = this.isEditing ? 'none' : 'block';
    }
    
    if (editMode) {
      editMode.style.display = this.isEditing ? 'block' : 'none';
    }
    
    if (editBtn) {
      editBtn.style.display = this.isEditing ? 'none' : 'inline-flex';
    }
    
    // Focus on content textarea when entering edit mode
    if (this.isEditing) {
      setTimeout(() => {
        const textarea = this.querySelector('.edit-content');
        if (textarea) {
          textarea.focus();
          textarea.setSelectionRange(textarea.value.length, textarea.value.length);
        }
      }, 100);
    }
  }
  
  /**
   * Render context list (simple list instead of complex timeline)
   */
  renderContextList() {
    if (!this.contextData || this.contextData.length === 0) {
      return `
        <div class="no-context">
          <p>No related memories found.</p>
        </div>
      `;
    }
    
    return this.contextData.map(memory => `
      <div class="context-item" data-memory-id="${memory.id}">
        <div class="context-item-header">
          <span class="context-category">${this.getCategoryIcon(memory.category)} ${memory.category || 'unknown'}</span>
          <span class="context-score">${Math.round((memory.similarity_score || 0) * 100)}% match</span>
        </div>
        <div class="context-item-content">
          ${this.escapeHtml((memory.content || '').substring(0, 150))}${(memory.content || '').length > 150 ? '...' : ''}
        </div>
        <div class="context-item-footer">
          <span class="context-date">${this.formatDate(memory.created_at)}</span>
          <button class="view-context-btn" data-memory-id="${memory.id}">View →</button>
        </div>
      </div>
    `).join('');
  }
  
  /**
   * Update context display
   */
  updateContextDisplay() {
    const contextTimeline = this.querySelector('context-timeline');
    if (contextTimeline) {
      contextTimeline.setAttribute('context-data', JSON.stringify(this.contextData));
    }
  }
  
  /**
   * Show not found message
   */
  showNotFound() {
    this.innerHTML = `
      <div class="memory-not-found">
        <div class="not-found-content">
          <h1>Memory Not Found</h1>
          <p>The memory you're looking for doesn't exist or has been deleted.</p>
          <button class="back-btn">Go Back</button>
        </div>
      </div>
    `;
  }
  
  /**
   * Show error message
   */
  showError(message) {
    this.innerHTML = `
      <div class="memory-error">
        <div class="error-content">
          <h1>⚠️ Error</h1>
          <p>${message}</p>
          <div class="error-actions">
            <button class="retry-btn">Retry</button>
            <button class="back-btn">Go Back</button>
          </div>
        </div>
      </div>
    `;
    
    // 이벤트 리스너 추가
    const retryBtn = this.querySelector('.retry-btn');
    const backBtn = this.querySelector('.back-btn');
    
    if (retryBtn) {
      retryBtn.addEventListener('click', () => {
        if (window.app && window.app.apiClient) {
          this.loadMemoryData();
        } else {
          this.loadMemoryDataDirect();
        }
      });
    }
    
    if (backBtn) {
      backBtn.addEventListener('click', () => {
        if (window.app && window.app.router) {
          window.app.router.navigate('/');
        } else {
          window.history.back();
        }
      });
    }
  }
  
  /**
   * Get category icon
   */
  getCategoryIcon(category) {
    const icons = {
      task: '📋',
      bug: '🐛',
      idea: '💡',
      decision: '⚖️',
      incident: '🚨',
      code_snippet: '💻'
    };
    return icons[category] || '📝';
  }
  
  /**
   * Format date
   */
  formatDate(dateStr) {
    if (!dateStr) return '';
    
    try {
      const date = new Date(dateStr);
      return date.toLocaleString();
    } catch {
      return dateStr;
    }
  }
  
  /**
   * Format content with markdown
   */
  formatContent(content) {
    if (!content) return '';
    
    try {
      // 안전한 HTML 이스케이프 먼저 수행
      let formatted = this.escapeHtml(content);
      
      // 간단한 마크다운 변환 (안전하게)
      formatted = formatted
        .replace(/\n/g, '<br>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');
      
      // URL 링크 변환 (더 안전한 패턴)
      formatted = formatted.replace(
        /\[([^\]]+)\]\(([^)]+)\)/g, 
        '<a href="$2" target="_blank" rel="noopener">$1</a>'
      );
      
      return formatted;
    } catch (error) {
      console.error('Error formatting content:', error);
      return this.escapeHtml(content);
    }
  }
  
  /**
   * Escape HTML
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'memory-detail-page';
    
    console.log('=== RENDER START ===');
    console.log('isLoading:', this.isLoading);
    console.log('memory exists:', !!this.memory);
    console.log('memory id:', this.memory?.id);
    
    if (this.isLoading) {
      console.log('Rendering loading state');
      this.innerHTML = `
        <div class="memory-loading">
          <div class="loading-spinner"></div>
          <p>Loading memory...</p>
        </div>
      `;
      console.log('Loading state rendered');
      return;
    }
    
    if (!this.memory) {
      console.log('No memory data, showing not found');
      this.showNotFound();
      return;
    }
    
    console.log('Rendering memory content for:', this.memory.id);
    
    // 메모리 콘텐츠 안전하게 포맷
    const formattedContent = this.formatContent(this.memory.content);
    console.log('Content formatted successfully');
    
    const htmlContent = `
      <div class="memory-header">
        <div class="header-actions">
          <button class="back-btn" title="Go back">← Back</button>
          <div class="header-buttons">
            <button class="refresh-btn" title="Refresh">🔄</button>
            <button class="share-btn" title="Share memory">🔗</button>
            <button class="export-btn" title="Export memory">📤</button>
            <button class="edit-btn" title="Edit memory (Ctrl+E)">✏️ Edit</button>
            <button class="delete-btn" title="Delete memory">🗑️</button>
          </div>
        </div>
      </div>
      
      <div class="memory-content">
        <div class="memory-main">
          <div class="memory-meta">
            <div class="meta-item">
              <span class="meta-label">Category:</span>
              <span class="category-badge">
                ${this.getCategoryIcon(this.memory.category)} ${this.memory.category}
              </span>
            </div>
            ${this.memory.project_id ? `
              <div class="meta-item">
                <span class="meta-label">Project:</span>
                <span class="project-badge">${this.memory.project_id}</span>
              </div>
            ` : ''}
            <div class="meta-item">
              <span class="meta-label">Created:</span>
              <span class="meta-value">${this.formatDate(this.memory.created_at)}</span>
            </div>
            ${this.memory.updated_at !== this.memory.created_at ? `
              <div class="meta-item">
                <span class="meta-label">Updated:</span>
                <span class="meta-value">${this.formatDate(this.memory.updated_at)}</span>
              </div>
            ` : ''}
            ${this.memory.source && this.memory.source !== 'unknown' ? `
              <div class="meta-item">
                <span class="meta-label">Source:</span>
                <span class="meta-value">${this.memory.source}</span>
              </div>
            ` : ''}
          </div>
          
          <div class="memory-body">
            <!-- View Mode -->
            <div class="view-mode">
              <div class="memory-text">
                ${formattedContent}
              </div>
              
              ${this.memory.tags && this.memory.tags.length > 0 ? `
                <div class="memory-tags">
                  ${this.memory.tags.map(tag => `<span class="tag">#${tag}</span>`).join('')}
                </div>
              ` : ''}
            </div>
            
            <!-- Edit Mode -->
            <div class="edit-mode" style="display: none;">
              <div class="edit-form">
                <div class="form-group">
                  <label for="edit-content">Content:</label>
                  <textarea 
                    id="edit-content" 
                    class="edit-content" 
                    rows="10"
                    placeholder="Enter memory content..."
                  >${this.escapeHtml(this.memory.content)}</textarea>
                </div>
                
                <div class="form-row">
                  <div class="form-group">
                    <label for="edit-project">Project:</label>
                    <input 
                      type="text" 
                      id="edit-project" 
                      class="edit-project" 
                      value="${this.memory.project_id || ''}"
                      placeholder="Project ID"
                    >
                  </div>
                  
                  <div class="form-group">
                    <label for="edit-category">Category:</label>
                    <select id="edit-category" class="edit-category">
                      <option value="task" ${this.memory.category === 'task' ? 'selected' : ''}>📋 Task</option>
                      <option value="bug" ${this.memory.category === 'bug' ? 'selected' : ''}>🐛 Bug</option>
                      <option value="idea" ${this.memory.category === 'idea' ? 'selected' : ''}>💡 Idea</option>
                      <option value="decision" ${this.memory.category === 'decision' ? 'selected' : ''}>⚖️ Decision</option>
                      <option value="incident" ${this.memory.category === 'incident' ? 'selected' : ''}>🚨 Incident</option>
                      <option value="code_snippet" ${this.memory.category === 'code_snippet' ? 'selected' : ''}>💻 Code Snippet</option>
                    </select>
                  </div>
                </div>
                
                <div class="form-group">
                  <label for="edit-tags">Tags:</label>
                  <input 
                    type="text" 
                    id="edit-tags" 
                    class="edit-tags" 
                    value="${(this.memory.tags || []).join(', ')}"
                    placeholder="Enter tags separated by commas"
                  >
                </div>
                
                <div class="edit-actions">
                  <button class="save-btn">💾 Save Changes</button>
                  <button class="cancel-btn">❌ Cancel</button>
                </div>
              </div>
            </div>
          </div>
        </div>
        
        <div class="memory-sidebar">
          <div class="context-section">
            <div class="context-header">
              <h3>Related Memories</h3>
            </div>
            <div class="context-list">
              ${this.renderContextList()}
            </div>
          </div>
        </div>
      </div>
    `;
    
    console.log('HTML content prepared, setting innerHTML');
    this.innerHTML = htmlContent;
    console.log('innerHTML set successfully');
    
    // Update edit mode display if needed
    if (this.isEditing) {
      console.log('Updating edit mode');
      this.updateEditMode();
    }
    
    console.log('=== RENDER COMPLETE ===');
  }
}

// Define the custom element
customElements.define('memory-detail-page', MemoryDetailPage);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .memory-detail-page {
    padding: 2rem;
    max-width: 1400px;
    margin: 0 auto;
  }
  
  .memory-header {
    margin-bottom: 2rem;
  }
  
  .header-actions {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border-color);
  }
  
  .back-btn {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: none;
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    padding: 0.5rem 1rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    transition: var(--transition);
  }
  
  .back-btn:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }
  
  .header-buttons {
    display: flex;
    gap: 0.5rem;
  }
  
  .header-buttons button {
    padding: 0.5rem 1rem;
    border: 1px solid var(--border-color);
    background: var(--bg-primary);
    color: var(--text-secondary);
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    transition: var(--transition);
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  
  .header-buttons button:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }
  
  .edit-btn {
    background: var(--primary-color) !important;
    color: white !important;
    border-color: var(--primary-color) !important;
  }
  
  .edit-btn:hover {
    background: var(--primary-hover) !important;
  }
  
  .delete-btn:hover {
    background: var(--error-color) !important;
    color: white !important;
    border-color: var(--error-color) !important;
  }
  
  .memory-content {
    display: grid;
    grid-template-columns: 1fr 400px;
    gap: 2rem;
  }
  
  .memory-main {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    overflow: hidden;
  }
  
  .memory-meta {
    padding: 1.5rem;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
  }
  
  .meta-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  
  .meta-label {
    font-size: 0.875rem;
    color: var(--text-secondary);
    font-weight: 500;
  }
  
  .meta-value {
    font-size: 0.875rem;
    color: var(--text-primary);
  }
  
  .category-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    background: var(--bg-tertiary);
    color: var(--text-primary);
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.875rem;
    font-weight: 500;
    text-transform: capitalize;
  }
  
  .project-badge {
    background: var(--primary-color);
    color: white;
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.875rem;
    font-weight: 500;
  }
  
  .memory-body {
    padding: 2rem;
  }
  
  .memory-text {
    font-size: 1rem;
    line-height: 1.7;
    color: var(--text-primary);
    margin-bottom: 2rem;
  }
  
  .memory-text code {
    background: var(--bg-secondary);
    padding: 0.125rem 0.25rem;
    border-radius: var(--border-radius-sm);
    font-family: var(--font-mono);
    font-size: 0.875rem;
  }
  
  .memory-text a {
    color: var(--primary-color);
    text-decoration: none;
  }
  
  .memory-text a:hover {
    text-decoration: underline;
  }
  
  .memory-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  
  .tag {
    background: var(--bg-secondary);
    color: var(--text-secondary);
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
    font-weight: 500;
  }
  
  /* Edit Mode Styles */
  .edit-form {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }
  
  .form-group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  
  .form-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }
  
  .form-group label {
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--text-secondary);
  }
  
  .edit-content {
    width: 100%;
    padding: 1rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 1rem;
    line-height: 1.5;
    resize: vertical;
    min-height: 200px;
    font-family: inherit;
  }
  
  .edit-project,
  .edit-tags {
    padding: 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.875rem;
  }
  
  .edit-category {
    padding: 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.875rem;
    cursor: pointer;
  }
  
  .edit-content:focus,
  .edit-project:focus,
  .edit-tags:focus,
  .edit-category:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
  }
  
  .edit-actions {
    display: flex;
    gap: 1rem;
    justify-content: flex-end;
  }
  
  .save-btn,
  .cancel-btn {
    padding: 0.75rem 1.5rem;
    border: none;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
    transition: var(--transition);
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  
  .save-btn {
    background: var(--primary-color);
    color: white;
  }
  
  .save-btn:hover {
    background: var(--primary-hover);
  }
  
  .cancel-btn {
    background: var(--bg-secondary);
    color: var(--text-secondary);
    border: 1px solid var(--border-color);
  }
  
  .cancel-btn:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }
  
  .memory-sidebar {
    position: sticky;
    top: 2rem;
    height: fit-content;
  }
  
  .context-section {
    margin-bottom: 2rem;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    overflow: hidden;
  }
  
  .context-header {
    padding: 1rem 1.5rem;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
  }
  
  .context-header h3 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
  }
  
  .context-list {
    padding: 1rem;
    max-height: 400px;
    overflow-y: auto;
  }
  
  .no-context {
    text-align: center;
    padding: 2rem;
    color: var(--text-muted);
  }
  
  .context-item {
    padding: 1rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    margin-bottom: 0.75rem;
    background: var(--bg-secondary);
    transition: var(--transition);
  }
  
  .context-item:last-child {
    margin-bottom: 0;
  }
  
  .context-item:hover {
    border-color: var(--primary-color);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  }
  
  .context-item-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
  }
  
  .context-category {
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--text-secondary);
    text-transform: capitalize;
  }
  
  .context-score {
    font-size: 0.75rem;
    color: var(--primary-color);
    font-weight: 500;
  }
  
  .context-item-content {
    font-size: 0.875rem;
    color: var(--text-primary);
    line-height: 1.5;
    margin-bottom: 0.75rem;
  }
  
  .context-item-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  
  .context-date {
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  
  .view-context-btn {
    padding: 0.25rem 0.5rem;
    font-size: 0.75rem;
    background: var(--primary-color);
    color: white;
    border: none;
    border-radius: var(--border-radius-sm);
    cursor: pointer;
    transition: var(--transition);
  }
  
  .view-context-btn:hover {
    background: var(--primary-hover);
  }
  
  /* Loading State */
  .memory-loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 4rem;
    color: var(--text-muted);
  }
  
  .loading-spinner {
    width: 2rem;
    height: 2rem;
    border: 2px solid var(--border-color);
    border-top: 2px solid var(--primary-color);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-bottom: 1rem;
  }
  
  @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }
  
  /* Not Found State */
  .memory-not-found {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 400px;
  }
  
  .not-found-content {
    text-align: center;
    color: var(--text-muted);
  }
  
  .not-found-content h1 {
    margin: 0 0 1rem 0;
    font-size: 2rem;
    color: var(--text-primary);
  }
  
  .not-found-content p {
    margin: 0 0 2rem 0;
    font-size: 1rem;
  }
  
  /* Responsive Design */
  @media (max-width: 1024px) {
    .memory-content {
      grid-template-columns: 1fr;
      gap: 1rem;
    }
    
    .memory-sidebar {
      position: static;
      order: -1;
    }
  }
  
  @media (max-width: 768px) {
    .memory-detail-page {
      padding: 1rem;
    }
    
    .header-actions {
      flex-direction: column;
      gap: 1rem;
      align-items: stretch;
    }
    
    .header-buttons {
      justify-content: center;
      flex-wrap: wrap;
    }
    
    .memory-meta {
      flex-direction: column;
      gap: 0.75rem;
    }
    
    .memory-body {
      padding: 1rem;
    }
    
    .form-row {
      grid-template-columns: 1fr;
    }
    
    .edit-actions {
      flex-direction: column;
    }
  }
`;

document.head.appendChild(style);

export { MemoryDetailPage };