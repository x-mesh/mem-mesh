/**
 * Edit Memory Page Web Component
 * Provides interface for editing existing memories
 */

class EditMemoryPage extends HTMLElement {
  static get observedAttributes() {
    return ['memory-id'];
  }
  
  constructor() {
    super();
    this.memoryId = null;
    this.originalData = null;
    this.formData = {
      content: '',
      project_id: '',
      category: 'task',
      tags: [],
      source: 'web-ui'
    };
    this.isDirty = false;
    this.isLoading = false;
  }
  
  connectedCallback() {
    this.render();
    this.setupEventListeners();
    if (this.memoryId) {
      this.loadMemory();
    }
  }
  
  attributeChangedCallback(name, oldValue, newValue) {
    if (name === 'memory-id' && oldValue !== newValue) {
      this.memoryId = newValue;
      if (this.isConnected) {
        this.loadMemory();
      }
    }
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    // Form submission
    const form = this.querySelector('#edit-memory-form');
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
    }
    
    // Cancel button
    const cancelBtn = this.querySelector('.cancel-btn');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', this.handleCancel.bind(this));
    }
    
    // Reset button
    const resetBtn = this.querySelector('.reset-btn');
    if (resetBtn) {
      resetBtn.addEventListener('click', this.handleReset.bind(this));
    }
    
    // Delete button
    const deleteBtn = this.querySelector('.delete-btn');
    if (deleteBtn) {
      deleteBtn.addEventListener('click', this.handleDelete.bind(this));
    }
    
    // Preview toggle
    const previewToggle = this.querySelector('.preview-toggle');
    if (previewToggle) {
      previewToggle.addEventListener('click', this.togglePreview.bind(this));
    }
  }
  
  /**
   * Load memory data
   */
  async loadMemory() {
    if (!this.memoryId) return;
    
    try {
      this.setLoading(true);
      
      const memory = await window.app.apiClient.getMemory(this.memoryId);
      
      if (memory) {
        this.originalData = { ...memory };
        this.formData = {
          content: memory.content || '',
          project_id: memory.project_id || '',
          category: memory.category || 'task',
          tags: memory.tags || [],
          source: memory.source || 'web-ui'
        };
        
        this.populateForm();
        this.updateTitle();
        this.isDirty = false;
        this.updateSaveStatus();
      }
      
    } catch (error) {
      console.error('Failed to load memory:', error);
      this.showErrorMessage(error.message || 'Failed to load memory');
    } finally {
      this.setLoading(false);
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
      
      const response = await window.app.apiClient.updateMemory(this.memoryId, memoryData);
      
      if (response) {
        this.originalData = { ...response };
        this.isDirty = false;
        this.updateSaveStatus();
        
        // Show success message
        this.showSuccessMessage('Memory updated successfully!');
        
        // Navigate back to memory detail after a short delay
        setTimeout(() => {
          window.app.router.navigate(`/memory/${this.memoryId}`);
        }, 1000);
      }
      
    } catch (error) {
      console.error('Failed to update memory:', error);
      this.showErrorMessage(error.message || 'Failed to update memory');
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
        window.app.router.navigate(`/memory/${this.memoryId}`);
      }
    } else {
      window.app.router.navigate(`/memory/${this.memoryId}`);
    }
  }
  
  /**
   * Handle reset
   */
  handleReset() {
    if (confirm('Are you sure you want to reset all changes?')) {
      this.formData = {
        content: this.originalData.content || '',
        project_id: this.originalData.project_id || '',
        category: this.originalData.category || 'task',
        tags: this.originalData.tags || [],
        source: this.originalData.source || 'web-ui'
      };
      
      this.populateForm();
      this.isDirty = false;
      this.updateSaveStatus();
    }
  }
  
  /**
   * Handle delete
   */
  async handleDelete() {
    const confirmMessage = `Are you sure you want to delete this memory?\n\nThis action cannot be undone.`;
    
    if (confirm(confirmMessage)) {
      try {
        this.setLoading(true);
        
        await window.app.apiClient.deleteMemory(this.memoryId);
        
        this.showSuccessMessage('Memory deleted successfully!');
        
        // Navigate to dashboard after a short delay
        setTimeout(() => {
          window.app.router.navigate('/');
        }, 1000);
        
      } catch (error) {
        console.error('Failed to delete memory:', error);
        this.showErrorMessage(error.message || 'Failed to delete memory');
      } finally {
        this.setLoading(false);
      }
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
    
    // Content is required and must be between 10-50000 characters
    if (!this.formData.content.trim()) {
      errors.push('Content is required');
    } else if (this.formData.content.trim().length < 10) {
      errors.push('Content must be at least 10 characters');
    } else if (this.formData.content.trim().length > 50000) {
      errors.push('Content must be less than 50,000 characters');
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
      charCount.textContent = `${count}/50,000`;
      
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
   * Update page title
   */
  updateTitle() {
    const title = this.querySelector('.page-title');
    if (title && this.originalData) {
      const preview = this.originalData.content.substring(0, 50);
      title.textContent = `Edit: ${preview}${this.originalData.content.length > 50 ? '...' : ''}`;
    }
  }
  
  /**
   * Update save status
   */
  updateSaveStatus() {
    const status = this.querySelector('.save-status');
    if (status) {
      if (this.isDirty) {
        status.textContent = 'Unsaved changes';
        status.className = 'save-status unsaved';
      } else {
        status.textContent = 'All changes saved';
        status.className = 'save-status saved';
      }
    }
  }
  
  /**
   * Set loading state
   */
  setLoading(loading) {
    this.isLoading = loading;
    
    const submitBtn = this.querySelector('.submit-btn');
    const deleteBtn = this.querySelector('.delete-btn');
    const form = this.querySelector('#edit-memory-form');
    
    if (loading) {
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Saving...';
      }
      if (deleteBtn) {
        deleteBtn.disabled = true;
      }
      if (form) form.classList.add('loading');
    } else {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Save Changes';
      }
      if (deleteBtn) {
        deleteBtn.disabled = false;
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
    this.className = 'edit-memory-page';
    
    this.innerHTML = `
      <div class="page-header">
        <div class="page-header-main">
          <h1 class="page-title">Edit Memory</h1>
        </div>
        <div class="page-header-actions">
          <div class="save-status"></div>
          <button class="reset-btn secondary-button">Reset</button>
          <button class="delete-btn danger-button">Delete</button>
        </div>
      </div>
      
      <div class="form-message" style="display: none;"></div>
      
      <form id="edit-memory-form" class="edit-form">
        <div class="form-group">
          <label for="content">Content *</label>
          <div class="content-editor">
            <div class="editor-toolbar">
              <button type="button" class="preview-toggle">Preview</button>
              <div class="char-count">0/50,000</div>
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
          <button type="submit" class="submit-btn primary-button">Save Changes</button>
        </div>
      </form>
    `;
  }
}

// Define the custom element
customElements.define('edit-memory-page', EditMemoryPage);

// Add component styles (reuse most styles from create-memory.js)
const style = document.createElement('style');
style.textContent = `
  .edit-memory-page {
    max-width: 800px;
    margin: 0 auto;
    padding: var(--space-6) 0; /* 상하 패딩만 유지, 좌우는 main-content에서 처리 */
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
  
  .edit-form {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 2rem;
  }
  
  .edit-form.loading {
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
  .secondary-button,
  .danger-button {
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
  
  .danger-button {
    background: var(--error-color);
    color: white;
  }
  
  .danger-button:hover:not(:disabled) {
    background: var(--error-hover);
  }
  
  .danger-button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  
  /* Responsive design */
  @media (max-width: 768px) {
    .edit-memory-page {
      padding: var(--space-4) 0; /* 모바일에서 상하 패딩 줄임 */
    }
    
    .form-row {
      grid-template-columns: 1fr;
    }
    
    .edit-form {
      padding: 1rem;
    }
    
    .form-actions {
      flex-direction: column-reverse;
    }
    
    .primary-button,
    .secondary-button,
    .danger-button {
      width: 100%;
    }
  }
`;

document.head.appendChild(style);

export { EditMemoryPage };