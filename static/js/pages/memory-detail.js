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
    this.addEventListener('change', this.handleChange.bind(this));
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
    } else if (target.classList.contains('open-new-tab-btn')) {
      event.stopPropagation(); // 부모 클릭 이벤트 방지
      const memoryId = target.getAttribute('data-memory-id');
      if (memoryId) {
        const url = `${window.location.origin}/memory/${memoryId}`;
        window.open(url, '_blank');
      }
    } else if (target.classList.contains('refresh-context-btn')) {
      this.loadContextData();
    } else if (target.closest('.context-item')) {
      // 전체 context-item 클릭 시에도 해당 메모리로 이동
      const contextItem = target.closest('.context-item');
      const memoryId = contextItem.getAttribute('data-memory-id');
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
        case 'r':
          event.preventDefault();
          this.loadContextData();
          break;
        case 'Escape':
          if (this.isEditing) {
            this.cancelEdit();
          }
          break;
      }
    }
    
    // 숫자 키로 관련 메모리 빠른 접근
    if (event.key >= '1' && event.key <= '9' && !this.isEditing) {
      const index = parseInt(event.key) - 1;
      if (this.contextData && this.contextData[index]) {
        const memoryId = this.contextData[index].id;
        if (window.app && window.app.router) {
          window.app.router.navigate(`/memory/${memoryId}`);
        }
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
      
      const api = window.app?.apiClient;
      if (!api) throw new Error('APIClient not available');

      const memory = await api.getMemory(this.memoryId);

      let contextData = [];
      try {
        const contextResult = await api.getContext(this.memoryId, 2);
        contextData = contextResult.related_memories || [];
      } catch {
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
      this.showError('Failed to load memory. Please refresh the page.');
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
          <p class="keyboard-hint">Use Ctrl+R to refresh</p>
        </div>
      `;
    }
    
    return this.contextData.map((memory, index) => `
      <div class="context-item clickable" data-memory-id="${memory.id}" title="Click to view this memory (or press ${index + 1})">
        <div class="context-item-number">${index + 1}</div>
        <div class="context-item-body">
          <div class="context-item-header">
            <span class="context-category">${this.getCategoryIcon(memory.category)} ${memory.category || 'unknown'}</span>
            <span class="context-score">${Math.round((memory.similarity_score || 0) * 100)}% match</span>
          </div>
          <div class="context-item-content">
            ${this.escapeHtml((memory.content || '').substring(0, 150))}${(memory.content || '').length > 150 ? '...' : ''}
          </div>
          <div class="context-item-footer">
            <span class="context-date">${this.formatDate(memory.created_at)}</span>
            <div class="context-actions">
              <button class="view-context-btn" data-memory-id="${memory.id}" title="View memory details">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M1 12S5 4 12 4S23 12 23 12S19 20 12 20S1 12 1 12Z" stroke="currentColor" stroke-width="2"/>
                  <circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2"/>
                </svg>
              </button>
              <button class="open-new-tab-btn" data-memory-id="${memory.id}" title="Open in new tab">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M18 13V19C18 19.5304 17.7893 20.0391 17.4142 20.4142C17.0391 20.7893 16.5304 18 16 18H5C4.46957 18 3.96086 17.7893 3.58579 17.4142C3.21071 17.0391 3 16.5304 3 16V5C3 4.46957 3.21071 3.96086 3.58579 3.58579C3.96086 3.21071 4.46957 3 5 3H11" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  <path d="M15 3H21V9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  <path d="M10 14L21 3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    `).join('');
  }
  
  /**
   * Handle change events
   */
  handleChange(event) {
    const target = event.target;
    
    if (target.classList.contains('context-sort')) {
      this.sortContextData(target.value);
    }
  }
  
  /**
   * Sort context data
   */
  sortContextData(sortBy) {
    if (!this.contextData || this.contextData.length === 0) return;
    
    const sortedData = [...this.contextData];
    
    switch (sortBy) {
      case 'similarity':
        sortedData.sort((a, b) => (b.similarity_score || 0) - (a.similarity_score || 0));
        break;
      case 'date':
        sortedData.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        break;
      case 'category':
        sortedData.sort((a, b) => (a.category || '').localeCompare(b.category || ''));
        break;
      default:
        return;
    }
    
    this.contextData = sortedData;
    this.updateContextDisplay();
  }
  
  /**
   * Update context display
   */
  updateContextDisplay() {
    const contextList = this.querySelector('.context-list');
    if (contextList) {
      contextList.innerHTML = this.renderContextList();
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
      task: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
               <path d="M9 12L11 14L15 10M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" stroke-width="2"/>
             </svg>`,
      bug: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M8 2V5M16 2V5M8 19L16 5M16 19L8 5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            </svg>`,
      idea: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
               <path d="M9 21H15M12 3C8.68629 3 6 5.68629 6 9C6 11.973 7.818 14.441 10.5 15.5V17C10.5 17.8284 11.1716 18.5 12 18.5C12.8284 18.5 13.5 17.8284 13.5 17V15.5C16.182 14.441 18 11.973 18 9C18 5.68629 15.3137 3 12 3Z" stroke="currentColor" stroke-width="2"/>
             </svg>`,
      decision: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M12 3L2 12L12 21L22 12L12 3Z" stroke="currentColor" stroke-width="2"/>
                </svg>`,
      incident: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M12 9V13M12 17H12.01M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" stroke-width="2"/>
                </svg>`,
      code_snippet: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M16 18L22 12L16 6M8 6L2 12L8 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>`
    };
    return icons[category] || `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M14 2H6C5.46957 2 4.96086 2.21071 4.58579 2.58579C4.21071 2.96086 4 3.46957 4 4V20C4 20.5304 4.21071 21.0391 4.58579 21.4142C4.96086 21.7893 5.46957 22 6 22H18C18.5304 22 19.0391 21.7893 19.4142 21.4142C19.7893 21.0391 20 20.5304 20 20V8L14 2Z" stroke="currentColor" stroke-width="2"/>
                                <path d="M14 2V8H20" stroke="currentColor" stroke-width="2"/>
                                <path d="M16 13H8M16 17H8M10 9H8" stroke="currentColor" stroke-width="2"/>
                              </svg>`;
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
      // 코드 블록 처리 (```language ... ```)
      const codeBlockRegex = /```(\w+)?\n([\s\S]*?)```/g;
      const codeBlocks = [];
      let formatted = content;
      
      // 코드 블록을 임시로 저장하고 플레이스홀더로 교체
      formatted = formatted.replace(codeBlockRegex, (match, language, code) => {
        const placeholder = `__CODE_BLOCK_${codeBlocks.length}__`;
        const lang = language || 'plaintext';
        const escapedCode = this.escapeHtml(code.trim());
        codeBlocks.push(`<pre class="line-numbers"><code class="language-${lang}">${escapedCode}</code></pre>`);
        return placeholder;
      });
      
      // 마크다운 테이블 처리 (HTML 이스케이프 전)
      const tableBlocks = [];
      formatted = formatted.replace(
        /(?:^|\n)((?:\|[^\n]+\|\n?)+)/g,
        (match, tableText) => {
          const rows = tableText.trim().split('\n').filter(r => r.trim());
          if (rows.length < 2) return match;
          // 구분선 행 확인 (|---|---|)
          const sepIdx = rows.findIndex(r => {
            const cells = r.split('|').slice(1, -1);
            return cells.length > 0 && cells.every(c => /^[\s:-]+$/.test(c));
          });
          if (sepIdx < 0) return match;

          const parseRow = (row) => row.split('|').slice(1, -1).map(c => c.trim());
          const headerCells = parseRow(rows[sepIdx - 1] || rows[0]);
          const bodyRows = rows.slice(sepIdx + 1);

          let html = '<table class="md-table"><thead><tr>';
          headerCells.forEach(c => {
            const escaped = this.escapeHtml(c).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            html += `<th>${escaped}</th>`;
          });
          html += '</tr></thead><tbody>';
          bodyRows.forEach(row => {
            html += '<tr>';
            parseRow(row).forEach(c => {
              const escaped = this.escapeHtml(c)
                .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
                .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
              html += `<td>${escaped}</td>`;
            });
            html += '</tr>';
          });
          html += '</tbody></table>';

          const placeholder = `__TABLE_BLOCK_${tableBlocks.length}__`;
          tableBlocks.push(html);
          return `\n${placeholder}\n`;
        }
      );

      // 인라인 코드 처리 전에 나머지 HTML 이스케이프
      formatted = this.escapeHtml(formatted);

      // 간단한 마크다운 변환
      formatted = formatted
        .replace(/\n/g, '<br>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
      
      // URL 링크 변환
      formatted = formatted.replace(
        /\[([^\]]+)\]\(([^)]+)\)/g, 
        '<a href="$2" target="_blank" rel="noopener">$1</a>'
      );
      
      // 코드 블록 플레이스홀더를 실제 코드로 교체
      codeBlocks.forEach((block, index) => {
        formatted = formatted.replace(`__CODE_BLOCK_${index}__`, block);
      });

      // 테이블 플레이스홀더를 실제 테이블로 교체
      tableBlocks.forEach((block, index) => {
        formatted = formatted.replace(`__TABLE_BLOCK_${index}__`, block);
      });
      
      // Prism.js로 문법 강조 적용 (다음 틱에서 실행)
      setTimeout(() => {
        if (window.Prism) {
          window.Prism.highlightAll();
        }
      }, 0);
      
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
   * Get tags as array (handle both string and array formats)
   */
  getTagsArray() {
    if (!this.memory || !this.memory.tags) return [];
    
    // 이미 배열인 경우
    if (Array.isArray(this.memory.tags)) {
      return this.memory.tags;
    }
    
    // 문자열인 경우 JSON 파싱 시도
    if (typeof this.memory.tags === 'string') {
      try {
        const parsed = JSON.parse(this.memory.tags);
        return Array.isArray(parsed) ? parsed : [];
      } catch (error) {
        // JSON 파싱 실패 시 쉼표로 분리 시도
        return this.memory.tags.split(',').map(tag => tag.trim()).filter(tag => tag);
      }
    }
    
    return [];
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'memory-detail-page page-container';
    
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
            <button class="refresh-btn" title="Refresh">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M1 4V10H7M23 20V14H17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M20.49 9C19.9828 7.56678 19.1209 6.28392 17.9845 5.27493C16.8482 4.26595 15.4745 3.56905 13.9917 3.24575C12.5089 2.92246 10.9652 2.98546 9.51691 3.42597C8.06861 3.86648 6.76302 4.66921 5.64 5.76L1 10M23 14L18.36 18.24C17.237 19.3308 15.9314 20.1335 14.4831 20.574C13.0348 21.0145 11.4911 21.0775 10.0083 20.7542C8.52547 20.431 7.1518 19.7341 6.01547 18.7251C4.87913 17.7161 4.01717 16.4332 3.51 15" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </button>
            <button class="share-btn" title="Share memory">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M10 13C10.4295 13.5741 10.9774 14.0491 11.6066 14.3929C12.2357 14.7367 12.9315 14.9411 13.6467 14.9923C14.3618 15.0435 15.0796 14.9403 15.7513 14.6897C16.4231 14.4392 17.0331 14.047 17.54 13.54L20.54 10.54C21.4508 9.59695 21.9548 8.33394 21.9434 7.02296C21.932 5.71198 21.4061 4.45791 20.4791 3.53087C19.5521 2.60383 18.298 2.07799 16.987 2.0666C15.676 2.0552 14.413 2.55918 13.47 3.47L11.75 5.18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M14 11C13.5705 10.4259 13.0226 9.95085 12.3934 9.60706C11.7643 9.26327 11.0685 9.05885 10.3533 9.00769C9.63819 8.95653 8.92037 9.05973 8.24864 9.31028C7.5769 9.56084 6.9669 9.95303 6.46 10.46L3.46 13.46C2.54918 14.403 2.04520 15.6661 2.05660 16.977C2.06799 18.288 2.59383 19.5421 3.52087 20.4691C4.44791 21.3962 5.70198 21.922 7.01296 21.9334C8.32394 21.9448 9.58695 21.4408 10.53 20.53L12.24 18.82" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </button>
            <button class="export-btn" title="Export memory">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M21 15V19C21 19.5304 20.7893 20.0391 20.4142 20.4142C20.0391 20.7893 19.5304 21 19 21H5C4.46957 21 3.96086 20.7893 3.58579 20.4142C3.21071 20.0391 3 19.5304 3 19V15" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M7 10L12 15L17 10" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M12 15V3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </button>
            <button class="edit-btn" title="Edit memory (Ctrl+E)">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M11 4H4C3.46957 4 2.96086 4.21071 2.58579 4.58579C2.21071 4.96086 2 5.46957 2 6V20C2 20.5304 2.21071 21.0391 2.58579 21.4142C2.96086 21.7893 3.46957 22 4 22H18C18.5304 22 19.0391 21.7893 19.4142 21.4142C19.7893 21.0391 20 20.5304 20 20V13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M18.5 2.50023C18.8978 2.1024 19.4374 1.87891 20 1.87891C20.5626 1.87891 21.1022 2.1024 21.5 2.50023C21.8978 2.89805 22.1213 3.43762 22.1213 4.00023C22.1213 4.56284 21.8978 5.1024 21.5 5.50023L12 15.0002L8 16.0002L9 12.0002L18.5 2.50023Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              Edit
            </button>
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
            ${this.memory.client ? `
              <div class="meta-item">
                <span class="meta-label">Client:</span>
                <span class="client-badge client-${this.memory.client}">${this.memory.client}</span>
              </div>
            ` : ''}
          </div>
          
          <div class="memory-body">
            <!-- View Mode -->
            <div class="view-mode">
              <div class="memory-text">
                ${formattedContent}
              </div>
              
              ${this.memory.tags && this.getTagsArray().length > 0 ? `
                <div class="memory-tags">
                  ${this.getTagsArray().map(tag => `<span class="tag">#${tag}</span>`).join('')}
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
                    value="${this.getTagsArray().join(', ')}"
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
              <div class="context-title">
                <h3>Related Memories</h3>
                <span class="context-count">${this.contextData.length} found</span>
              </div>
              <div class="context-controls">
                <button class="refresh-context-btn" title="Refresh related memories">
                  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M1 4V10H7M23 20V14H17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M20.49 9C19.9828 7.56678 19.1209 6.28392 17.9845 5.27493C16.8482 4.26595 15.4745 3.56905 13.9917 3.24575C12.5089 2.92246 10.9652 2.98546 9.51691 3.42597C8.06861 3.86648 6.76302 4.66921 5.64 5.76L1 10M23 14L18.36 18.24C17.237 19.3308 15.9314 20.1335 14.4831 20.574C13.0348 21.0145 11.4911 21.0775 10.0083 20.7542C8.52547 20.431 7.1518 19.7341 6.01547 18.7251C4.87913 17.7161 4.01717 16.4332 3.51 15" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                </button>
                <select class="context-sort" title="Sort related memories">
                  <option value="similarity">By Similarity</option>
                  <option value="date">By Date</option>
                  <option value="category">By Category</option>
                </select>
              </div>
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
    padding: var(--space-6) 0; /* 상하 패딩만 유지, 좌우는 main-content에서 처리 */
    width: 100%;
  }
  
  .memory-header {
    margin-bottom: 2rem;
  }
  
  .memory-detail-page .header-actions {
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
  
  .memory-detail-page .memory-content {
    display: grid;
    gap: 2rem;
  }

  /* 데스크톱: 2컬럼 레이아웃 */
  @media (min-width: 1025px) {
    .memory-detail-page .memory-content {
      grid-template-columns: 1fr 400px;
    }
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
  }
  
  .project-badge {
    background: var(--primary-color);
    color: white;
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.875rem;
    font-weight: 500;
  }

  .client-badge {
    background: var(--bg-tertiary, #374151);
    color: var(--text-primary);
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.875rem;
    font-weight: 500;
    font-family: 'SF Mono', 'Cascadia Code', monospace;
  }
  .client-claude_code { background: #d97706; color: #fff; }
  .client-cursor { background: #7c3aed; color: #fff; }
  .client-kiro { background: #059669; color: #fff; }
  .client-web { background: #2563eb; color: #fff; }

  .memory-body {
    padding: 2rem;
  }
  
  .memory-text {
    font-size: 1rem;
    line-height: 1.7;
    color: var(--text-primary);
    margin-bottom: 2rem;
    text-transform: none !important;
  }

  .memory-text strong {
    color: var(--text-primary);
    font-weight: 600;
  }

  .memory-text em {
    color: var(--text-primary);
  }

  .memory-text code {
    background: var(--bg-secondary);
    color: var(--text-primary);
    padding: 0.125rem 0.25rem;
    border-radius: var(--border-radius-sm);
    font-family: var(--font-mono);
    font-size: 0.875rem;
    text-transform: none !important;
  }

  .memory-text a {
    color: var(--primary-color);
    text-decoration: none;
  }

  .memory-text a:hover {
    text-decoration: underline;
  }

  .memory-text .md-table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.75rem 0;
    font-size: 0.875rem;
    color: var(--text-primary);
  }
  .memory-text .md-table th,
  .memory-text .md-table td {
    border: 1px solid var(--border-color, #e0e0e0);
    padding: 0.5rem 0.75rem;
    text-align: left;
    color: var(--text-primary);
  }
  .memory-text .md-table th {
    background: var(--bg-secondary, #f5f5f5);
    font-weight: 600;
  }
  .memory-text .md-table tr:hover {
    background: var(--bg-hover, rgba(0,0,0,0.02));
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
    display: flex;
    flex-direction: column;
  }

  /* 데스크톱: sticky 사이드바 */
  @media (min-width: 1025px) {
    .memory-sidebar {
      position: sticky;
      top: 2rem;
      height: calc(100vh - 4rem);
    }
  }

  .context-section {
    margin-bottom: 0;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  /* 데스크톱: 사이드바 높이 가득 채우기 */
  @media (min-width: 1025px) {
    .context-section {
      height: 100%;
    }
  }
  
  .context-header {
    padding: 1rem 1.5rem;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  
  .context-title {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  
  .context-header h3 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
  }
  
  .context-count {
    font-size: 0.75rem;
    color: var(--text-secondary);
  }
  
  .context-controls {
    display: flex;
    gap: 0.5rem;
    align-items: center;
  }
  
  .refresh-context-btn {
    padding: 0.25rem;
    background: none;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm);
    cursor: pointer;
    color: var(--text-secondary);
    transition: var(--transition);
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
  }
  
  .refresh-context-btn:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }
  
  .refresh-context-btn svg {
    width: 14px;
    height: 14px;
  }
  
  .context-sort {
    padding: 0.25rem 0.5rem;
    font-size: 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm);
    background: var(--bg-primary);
    color: var(--text-secondary);
    cursor: pointer;
    min-width: 100px;
  }
  
  .context-sort:focus {
    outline: none;
    border-color: var(--primary-color);
  }
  
  .context-list {
    padding: 1rem;

    /* 수정 3: 400px 제한을 풀고, 남은 공간을 모두 차지하도록 설정 */
    /* max-height: 400px;  <-- 이거 지우기 */
    flex: 1;               /* <-- 남은 공간 채우기 */
    overflow-y: auto;      /* <-- 내용이 넘치면 이 안에서 스크롤 */
  }
  .no-context {
    text-align: center;
    padding: 2rem;
    color: var(--text-muted);
  }
  
  .keyboard-hint {
    font-size: 0.75rem;
    margin-top: 0.5rem;
    opacity: 0.7;
  }
  
  .context-item {
    padding: 1rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    margin-bottom: 0.75rem;
    background: var(--bg-secondary);
    transition: var(--transition);
    position: relative;
    display: flex;
    gap: 0.75rem;
  }
  
  .context-item-number {
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    background: var(--primary-color);
    color: white;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    font-weight: 600;
    margin-top: 0.25rem;
  }
  
  .context-item-body {
    flex: 1;
    min-width: 0;
  }
  
  .context-item.clickable {
    cursor: pointer;
  }
  
  .context-item:last-child {
    margin-bottom: 0;
  }
  
  .context-item:hover {
    border-color: var(--primary-color);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    transform: translateY(-1px);
  }
  
  .context-item.clickable:hover {
    background: var(--bg-tertiary);
  }
  
  .context-item:hover .context-item-number {
    background: var(--primary-hover);
  }
  
  .context-item-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
  }
  
  .context-category {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--text-secondary);
  }
  
  .context-category svg {
    width: 14px;
    height: 14px;
    flex-shrink: 0;
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
  
  .context-actions {
    display: flex;
    gap: 0.5rem;
    opacity: 0;
    transition: var(--transition);
  }
  
  .context-item:hover .context-actions {
    opacity: 1;
  }
  
  .context-date {
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  
  .view-context-btn,
  .open-new-tab-btn {
    padding: 0.25rem;
    font-size: 0.75rem;
    background: var(--primary-color);
    color: white;
    border: none;
    border-radius: var(--border-radius-sm);
    cursor: pointer;
    transition: var(--transition);
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
  }
  
  .view-context-btn svg,
  .open-new-tab-btn svg {
    width: 12px;
    height: 12px;
  }
  
  .view-context-btn:hover {
    background: var(--primary-hover);
  }
  
  .open-new-tab-btn {
    background: var(--text-secondary);
  }
  
  .open-new-tab-btn:hover {
    background: var(--text-primary);
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
    .memory-detail-page .memory-content {
      grid-template-columns: 1fr;
      gap: 1rem;
    }

    .memory-detail-page .memory-sidebar {
      position: static;
      height: auto;
    }

    .memory-detail-page .context-section {
      max-height: 250px;
      height: auto;
    }
  }

  @media (max-width: 768px) {
    .memory-detail-page {
      padding: var(--space-4) 0; /* 모바일에서 상하 패딩 줄임 */
    }

    .memory-detail-page .context-section {
      max-height: 200px; /* 모바일에서 더 작게 */
      height: auto;
    }
    
    .memory-detail-page .header-actions {
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
    
    .context-header {
      flex-direction: column;
      gap: 0.75rem;
      align-items: stretch;
    }
    
    .context-title {
      text-align: center;
    }
    
    .context-controls {
      justify-content: center;
    }
    
    .context-actions {
      opacity: 1; /* 모바일에서는 항상 표시 */
    }
  }
`;

document.head.appendChild(style);

export { MemoryDetailPage };