/**
 * Create Memory Page Web Component
 * Provides interface for creating new memories
 */

class CreateMemoryPage extends HTMLElement {
  constructor() {
    super();
    this.formData = {
      content: '',
      project_id: '',
      category: 'task',
      tags: [],
      source: 'web-ui'
    };
    this.isDirty = false;
    this.autoSaveTimer = null;
  }
  
  connectedCallback() {
    this.render();
    this.setupEventListeners();
    this.loadDraftFromStorage();
    this.setupAutoSave();
  }
  
  disconnectedCallback() {
    this.clearAutoSave();
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    // Form submission
    const form = this.querySelector('#create-memory-form');
    if (form) {
      form.addEventListener('submit', this.handleSubmit.bind(this));
    }
    
    // Form field changes
    const contentTextarea = this.querySelector('#content');
    const projectInput = this.querySelector('#project_id');
    const categorySelect = this.querySelector('#category');
    const tagsInput = this.querySelector('#tags');
    
    if (contentTextarea) {
      contentTextarea.addEventListener('input', this.handleContentChange.bind(this));
      contentTextarea.addEventListener('keydown', this.handleKeydown.bind(this));
    }
    
    if (projectInput) {
      projectInput.addEventListener('input', this.handleProjectChange.bind(this));
    }
    
    if (categorySelect) {
      categorySelect.addEventListener('change', this.handleCategoryChange.bind(this));
    }
    
    if (tagsInput) {
      tagsInput.addEventListener('input', this.handleTagsChange.bind(this));
      tagsInput.addEventListener('keydown', this.handleTagsKeydown.bind(this));
    }
    
    // Cancel button
    const cancelBtn = this.querySelector('.cancel-btn');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', this.handleCancel.bind(this));
    }
    
    // Save draft button
    const saveDraftBtn = this.querySelector('.save-draft-btn');
    if (saveDraftBtn) {
      saveDraftBtn.addEventListener('click', this.saveDraft.bind(this));
    }
    
    // Clear draft button
    const clearDraftBtn = this.querySelector('.clear-draft-btn');
    if (clearDraftBtn) {
      clearDraftBtn.addEventListener('click', this.clearDraft.bind(this));
    }
    
    // Preview toggle
    const previewToggle = this.querySelector('.preview-toggle');
    if (previewToggle) {
      previewToggle.addEventListener('click', this.togglePreview.bind(this));
    }
  }
  
  /**
   * Handle form submission
   */
  async handleSubmit(event) {
    event.preventDefault();
    
    if (!this.validateForm()) {
      return;
    }
    
    try {
      this.setLoading(true);
      
      const memoryData = {
        content: this.formData.content.trim(),
        project_id: this.formData.project_id.trim() || undefined,
        category: this.formData.category,
        tags: this.formData.tags.filter(tag => tag.trim()),
        source: this.formData.source
      };
      
      const response = await window.app.apiClient.createMemory(memoryData);
      
      if (response && response.id) {
        // Clear draft
        this.clearDraftFromStorage();
        
        // Show success message
        this.showSuccessMessage('Memory created successfully!');
        
        // Navigate to the new memory
        setTimeout(() => {
          window.app.router.navigate(`/memory/${response.id}`);
        }, 1000);
      }
      
    } catch (error) {
      console.error('Failed to create memory:', error);
      this.showErrorMessage(error.message || 'Failed to create memory');
    } finally {
      this.setLoading(false);
    }
  }
  
  /**
   * Handle content change
   */
  handleContentChange(event) {
    this.formData.content = event.target.value;
    this.markDirty();
    this.updateCharacterCount();
    this.updatePreview();
  }
  
  /**
   * Handle project change
   */
  handleProjectChange(event) {
    this.formData.project_id = event.target.value;
    this.markDirty();
    this.validateProjectId();
  }
  
  /**
   * Handle category change
   */
  handleCategoryChange(event) {
    this.formData.category = event.target.value;
    this.markDirty();
  }
  
  /**
   * Handle tags change
   */
  handleTagsChange(event) {
    const tagsText = event.target.value;
    this.formData.tags = tagsText.split(',').map(tag => tag.trim()).filter(tag => tag);
    this.markDirty();
    this.updateTagsDisplay();
  }
  
  /**
   * Handle tags keydown for autocomplete
   */
  handleTagsKeydown(event) {
    if (event.key === 'Tab' || event.key === 'Enter') {
      // TODO: Implement tag autocomplete
    }
  }
  
  /**
   * Handle textarea keydown
   */
  handleKeydown(event) {
    // Ctrl+Enter or Cmd+Enter to submit
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault();
      this.handleSubmit(event);
    }
    
    // Tab for indentation
    if (event.key === 'Tab') {
      event.preventDefault();
      const textarea = event.target;
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      
      textarea.value = textarea.value.substring(0, start) + '  ' + textarea.value.substring(end);
      textarea.selectionStart = textarea.selectionEnd = start + 2;
      
      this.handleContentChange(event);
    }
  }
  
  /**
   * Handle cancel
   */
  handleCancel() {
    if (this.isDirty) {
      if (confirm('You have unsaved changes. Are you sure you want to leave?')) {
        window.app.router.navigate('/');
      }
    } else {
      window.app.router.navigate('/');
    }
  }
  
  /**
   * Mark form as dirty
   */
  markDirty() {
    this.isDirty = true;
    this.updateSaveStatus();
  }
  
  /**
   * Validate form
   */
  validateForm() {
    const errors = [];
    
    // Content is required and must be between 10-10000 characters
    if (!this.formData.content.trim()) {
      errors.push('Content is required');
    } else if (this.formData.content.trim().length < 10) {
      errors.push('Content must be at least 10 characters');
    } else if (this.formData.content.trim().length > 10000) {
      errors.push('Content must be less than 10,000 characters');
    }
    
    // Project ID format validation
    if (this.formData.project_id && !/^[a-z0-9_-]+$/.test(this.formData.project_id)) {
      errors.push('Project ID can only contain lowercase letters, numbers, underscores, and hyphens');
    }
    
    if (errors.length > 0) {
      this.showErrorMessage(errors.join('\n'));
      return false;
    }
    
    return true;
  }
  
  /**
   * Validate project ID
   */
  validateProjectId() {
    const projectInput = this.querySelector('#project_id');
    const projectError = this.querySelector('.project-error');
    
    if (this.formData.project_id && !/^[a-z0-9_-]+$/.test(this.formData.project_id)) {
      projectInput.classList.add('error');
      if (projectError) {
        projectError.textContent = 'Only lowercase letters, numbers, underscores, and hyphens allowed';
        projectError.style.display = 'block';
      }
    } else {
      projectInput.classList.remove('error');
      if (projectError) {
        projectError.style.display = 'none';
      }
    }
  }
  
  /**
   * Update character count
   */
  updateCharacterCount() {
    const charCount = this.querySelector('.char-count');
    if (charCount) {
      const count = this.formData.content.length;
      charCount.textContent = `${count}/10,000`;
      
      if (count < 10) {
        charCount.className = 'char-count error';
      } else if (count > 9000) {
        charCount.className = 'char-count warning';
      } else {
        charCount.className = 'char-count';
      }
    }
  }
  
  /**
   * Update tags display
   */
  updateTagsDisplay() {
    const tagsDisplay = this.querySelector('.tags-display');
    if (tagsDisplay) {
      if (this.formData.tags.length > 0) {
        tagsDisplay.innerHTML = this.formData.tags.map(tag => 
          `<span class="tag">${tag}</span>`
        ).join('');
        tagsDisplay.style.display = 'flex';
      } else {
        tagsDisplay.style.display = 'none';
      }
    }
  }
  
  /**
   * Update preview
   */
  updatePreview() {
    const preview = this.querySelector('.preview-content');
    if (preview && preview.style.display !== 'none') {
      // Simple markdown-like preview
      let html = this.formData.content
        .replace(/\n/g, '<br>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code>$1</code>');
      
      preview.innerHTML = html || '<em>Preview will appear here...</em>';
    }
  }
  
  /**
   * Toggle preview
   */
  togglePreview() {
    const textarea = this.querySelector('#content');
    const preview = this.querySelector('.preview-content');
    const toggle = this.querySelector('.preview-toggle');
    
    if (preview.style.display === 'none') {
      textarea.style.display = 'none';
      preview.style.display = 'block';
      toggle.textContent = 'Edit';
      this.updatePreview();
    } else {
      textarea.style.display = 'block';
      preview.style.display = 'none';
      toggle.textContent = 'Preview';
    }
  }
  
  /**
   * Setup auto-save
   */
  setupAutoSave() {
    this.autoSaveTimer = setInterval(() => {
      if (this.isDirty) {
        this.saveDraftToStorage();
      }
    }, 30000); // Auto-save every 30 seconds
  }
  
  /**
   * Clear auto-save
   */
  clearAutoSave() {
    if (this.autoSaveTimer) {
      clearInterval(this.autoSaveTimer);
      this.autoSaveTimer = null;
    }
  }
  
  /**
   * Save draft to localStorage
   */
  saveDraftToStorage() {
    try {
      localStorage.setItem('mem-mesh-draft', JSON.stringify({
        ...this.formData,
        timestamp: Date.now()
      }));
      this.updateSaveStatus('Draft saved');
    } catch (error) {
      console.error('Failed to save draft:', error);
    }
  }
  
  /**
   * Load draft from localStorage
   */
  loadDraftFromStorage() {
    try {
      const draft = localStorage.getItem('mem-mesh-draft');
      if (draft) {
        const draftData = JSON.parse(draft);
        
        // Check if draft is not too old (24 hours)
        if (Date.now() - draftData.timestamp < 24 * 60 * 60 * 1000) {
          this.formData = { ...draftData };
          this.populateForm();
          this.showDraftNotice();
        }
      }
    } catch (error) {
      console.error('Failed to load draft:', error);
    }
  }
  
  /**
   * Clear draft from localStorage
   */
  clearDraftFromStorage() {
    localStorage.removeItem('mem-mesh-draft');
    this.updateSaveStatus();
  }
  
  /**
   * Save draft manually
   */
  saveDraft() {
    this.saveDraftToStorage();
    this.isDirty = false;
  }
  
  /**
   * Clear draft manually
   */
  clearDraft() {
    if (confirm('Are you sure you want to clear the draft?')) {
      this.clearDraftFromStorage();
      this.resetForm();
      this.isDirty = false;
      this.updateSaveStatus();
    }
  }
  
  /**
   * Populate form with data
   */
  populateForm() {
    const contentTextarea = this.querySelector('#content');
    const projectInput = this.querySelector('#project_id');
    const categorySelect = this.querySelector('#category');
    const tagsInput = this.querySelector('#tags');
    
    if (contentTextarea) contentTextarea.value = this.formData.content;
    if (projectInput) projectInput.value = this.formData.project_id;
    if (categorySelect) categorySelect.value = this.formData.category;
    if (tagsInput) tagsInput.value = this.formData.tags.join(', ');
    
    this.updateCharacterCount();
    this.updateTagsDisplay();
    this.updatePreview();
  }
  
  /**
   * Reset form
   */
  resetForm() {
    this.formData = {
      content: '',
      project_id: '',
      category: 'task',
      tags: [],
      source: 'web-ui'
    };
    this.populateForm();
  }
  
  /**
   * Show draft notice
   */
  showDraftNotice() {
    const notice = this.querySelector('.draft-notice');
    if (notice) {
      notice.style.display = 'block';
    }
  }
  
  /**
   * Update save status
   */
  updateSaveStatus(message = '') {
    const status = this.querySelector('.save-status');
    if (status) {
      if (message) {
        status.textContent = message;
        status.className = 'save-status saved';
        setTimeout(() => {
          status.textContent = this.isDirty ? 'Unsaved changes' : '';
          status.className = this.isDirty ? 'save-status unsaved' : 'save-status';
        }, 2000);
      } else {
        status.textContent = this.isDirty ? 'Unsaved changes' : '';
        status.className = this.isDirty ? 'save-status unsaved' : 'save-status';
      }
    }
  }
  
  /**
   * Set loading state
   */
  setLoading(loading) {
    const submitBtn = this.querySelector('.submit-btn');
    const form = this.querySelector('#create-memory-form');
    
    if (loading) {
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Creating...';
      }
      if (form) form.classList.add('loading');
    } else {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Create Memory';
      }
      if (form) form.classList.remove('loading');
    }
  }
  
  /**
   * Show success message
   */
  showSuccessMessage(message) {
    const messageEl = this.querySelector('.form-message');
    if (messageEl) {
      messageEl.textContent = message;
      messageEl.className = 'form-message success';
      messageEl.style.display = 'block';
    }
  }
  
  /**
   * Show error message
   */
  showErrorMessage(message) {
    const messageEl = this.querySelector('.form-message');
    if (messageEl) {
      messageEl.textContent = message;
      messageEl.className = 'form-message error';
      messageEl.style.display = 'block';
    }
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'create-memory-page';
    
    this.innerHTML = `
      <div class="page-header">
        <h1>Create New Memory</h1>
        <div class="header-actions">
          <div class="save-status"></div>
          <button class="save-draft-btn secondary-button">Save Draft</button>
          <button class="clear-draft-btn secondary-button">Clear Draft</button>
        </div>
      </div>
      
      <div class="draft-notice" style="display: none;">
        <p><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10,9 9,9 8,9"/></svg> Draft loaded from previous session</p>
      </div>
      
      <div class="form-message" style="display: none;"></div>
      
      <form id="create-memory-form" class="create-form">
        <div class="form-group">
          <label for="content">Content *</label>
          <div class="content-editor">
            <div class="editor-toolbar">
              <button type="button" class="preview-toggle">Preview</button>
              <div class="char-count">0/10,000</div>
            </div>
            <textarea 
              id="content" 
              name="content" 
              placeholder="Enter your memory content here... (minimum 10 characters)"
              rows="12"
              required
            ></textarea>
            <div class="preview-content" style="display: none;"></div>
          </div>
        </div>
        
        <div class="form-row">
          <div class="form-group">
            <label for="project_id">Project ID</label>
            <input 
              type="text" 
              id="project_id" 
              name="project_id" 
              placeholder="e.g., my-project"
              pattern="[a-z0-9_-]+"
            />
            <div class="project-error form-error" style="display: none;"></div>
            <small class="form-help">Optional. Use lowercase letters, numbers, underscores, and hyphens only.</small>
          </div>
          
          <div class="form-group">
            <label for="category">Category *</label>
            <select id="category" name="category" required>
              <option value="task">Task</option>
              <option value="bug">Bug</option>
              <option value="idea">Idea</option>
              <option value="decision">Decision</option>
              <option value="incident">Incident</option>
              <option value="code_snippet">Code Snippet</option>
            </select>
          </div>
        </div>
        
        <div class="form-group">
          <label for="tags">Tags</label>
          <input 
            type="text" 
            id="tags" 
            name="tags" 
            placeholder="Enter tags separated by commas"
          />
          <div class="tags-display" style="display: none;"></div>
          <small class="form-help">Separate multiple tags with commas</small>
        </div>
        
        <div class="form-actions">
          <button type="button" class="cancel-btn secondary-button">Cancel</button>
          <button type="submit" class="submit-btn primary-button">Create Memory</button>
        </div>
      </form>
    `;
  }
}

// Define the custom element
customElements.define('create-memory-page', CreateMemoryPage);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .create-memory-page {
    max-width: 800px;
    margin: 0 auto;
    padding: var(--space-6) 0; /* 상하 패딩만 유지, 좌우는 main-content에서 처리 */
  }
  
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border-color);
  }
  
  .page-header h1 {
    margin: 0;
    color: var(--text-primary);
  }
  
  .header-actions {
    display: flex;
    align-items: center;
    gap: 1rem;
  }
  
  .save-status {
    font-size: 0.875rem;
    color: var(--text-muted);
  }
  
  .save-status.saved {
    color: var(--success-color);
  }
  
  .save-status.unsaved {
    color: var(--warning-color);
  }
  
  .draft-notice {
    background: var(--warning-bg);
    border: 1px solid var(--warning-color);
    border-radius: var(--border-radius);
    padding: 1rem;
    margin-bottom: 1rem;
  }
  
  .draft-notice p {
    margin: 0;
    color: var(--warning-text);
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  
  .draft-notice p svg {
    width: 16px;
    height: 16px;
    stroke: currentColor;
    flex-shrink: 0;
  }
  
  .form-message {
    padding: 1rem;
    border-radius: var(--border-radius);
    margin-bottom: 1rem;
    font-weight: 500;
  }
  
  .form-message.success {
    background: var(--success-bg);
    color: var(--success-text);
    border: 1px solid var(--success-color);
  }
  
  .form-message.error {
    background: var(--error-bg);
    color: var(--error-text);
    border: 1px solid var(--error-color);
  }
  
  .create-form {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 2rem;
  }
  
  .create-form.loading {
    opacity: 0.7;
    pointer-events: none;
  }
  
  .form-group {
    margin-bottom: 1.5rem;
  }
  
  .form-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }
  
  .form-group label {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 500;
    color: var(--text-primary);
  }
  
  .form-group input,
  .form-group select,
  .form-group textarea {
    width: 100%;
    padding: 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 1rem;
    transition: var(--transition);
  }
  
  .form-group input:focus,
  .form-group select:focus,
  .form-group textarea:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px var(--primary-color-alpha);
  }
  
  .form-group input.error {
    border-color: var(--error-color);
  }
  
  .form-group textarea {
    resize: vertical;
    min-height: 200px;
    font-family: var(--font-mono);
    line-height: 1.5;
  }
  
  .content-editor {
    position: relative;
  }
  
  .editor-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.5rem;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-bottom: none;
    border-radius: var(--border-radius) var(--border-radius) 0 0;
  }
  
  .preview-toggle {
    background: none;
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    padding: 0.25rem 0.75rem;
    border-radius: var(--border-radius-sm);
    cursor: pointer;
    font-size: 0.875rem;
    transition: var(--transition);
  }
  
  .preview-toggle:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }
  
  .char-count {
    font-size: 0.875rem;
    color: var(--text-muted);
  }
  
  .char-count.warning {
    color: var(--warning-color);
  }
  
  .char-count.error {
    color: var(--error-color);
  }
  
  .preview-content {
    padding: 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: 0 0 var(--border-radius) var(--border-radius);
    background: var(--bg-primary);
    min-height: 200px;
    line-height: 1.6;
    color: var(--text-primary);
  }
  
  .preview-content code {
    background: var(--bg-secondary);
    padding: 0.125rem 0.25rem;
    border-radius: var(--border-radius-sm);
    font-family: var(--font-mono);
    font-size: 0.875rem;
  }
  
  .form-error {
    color: var(--error-color);
    font-size: 0.875rem;
    margin-top: 0.25rem;
  }
  
  .form-help {
    color: var(--text-muted);
    font-size: 0.875rem;
    margin-top: 0.25rem;
    display: block;
  }
  
  .tags-display {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 0.5rem;
  }
  
  .tag {
    background: var(--primary-color);
    color: white;
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
    font-weight: 500;
  }
  
  .form-actions {
    display: flex;
    justify-content: flex-end;
    gap: 1rem;
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border-color);
  }
  
  .primary-button,
  .secondary-button {
    padding: 0.75rem 1.5rem;
    border-radius: var(--border-radius);
    font-weight: 500;
    cursor: pointer;
    transition: var(--transition);
    border: none;
    font-size: 1rem;
  }
  
  .primary-button {
    background: var(--primary-color);
    color: white;
  }
  
  .primary-button:hover:not(:disabled) {
    background: var(--primary-hover);
  }
  
  .primary-button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  
  .secondary-button {
    background: var(--bg-secondary);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
  }
  
  .secondary-button:hover {
    background: var(--bg-tertiary);
  }
  
  /* Responsive design */
  @media (max-width: 768px) {
    .create-memory-page {
      padding: var(--space-4) 0; /* 모바일에서 상하 패딩 줄임 */
    }
    
    .page-header {
      flex-direction: column;
      align-items: flex-start;
      gap: 1rem;
    }
    
    .header-actions {
      align-self: stretch;
      justify-content: space-between;
    }
    
    .form-row {
      grid-template-columns: 1fr;
    }
    
    .create-form {
      padding: 1rem;
    }
    
    .form-actions {
      flex-direction: column-reverse;
    }
    
    .primary-button,
    .secondary-button {
      width: 100%;
    }
  }
`;

document.head.appendChild(style);

export { CreateMemoryPage };