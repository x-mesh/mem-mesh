/**
 * Memory Card Web Component
 * Displays individual memory information as a card
 */

class MemoryCard extends HTMLElement {
  static get observedAttributes() {
    return [
      'memory-id', 'content', 'project', 'category', 
      'created-at', 'updated-at', 'similarity-score', 'tags', 'source'
    ];
  }
  
  constructor() {
    super();
    this.memory = null;
    this.isExpanded = false;
  }
  
  connectedCallback() {
    this.render();
    this.setupEventListeners();
  }
  
  disconnectedCallback() {
    this.removeEventListeners();
  }
  
  attributeChangedCallback(name, oldValue, newValue) {
    if (oldValue !== newValue) {
      this.render();
    }
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    this.addEventListener('click', this.handleClick.bind(this));
    this.addEventListener('keydown', this.handleKeydown.bind(this));
    
    // Make focusable
    if (!this.hasAttribute('tabindex')) {
      this.setAttribute('tabindex', '0');
    }
    
    // Add ARIA role
    this.setAttribute('role', 'button');
    this.setAttribute('aria-label', 'View memory details');
  }
  
  /**
   * Remove event listeners
   */
  removeEventListeners() {
    this.removeEventListener('click', this.handleClick);
    this.removeEventListener('keydown', this.handleKeydown);
  }
  
  /**
   * Handle click events
   */
  handleClick(event) {
    // Don't navigate if clicking on action buttons
    if (event.target.closest('.memory-actions')) {
      return;
    }
    
    const memoryId = this.getAttribute('memory-id');
    if (memoryId) {
      // Dispatch custom event for navigation
      this.dispatchEvent(new CustomEvent('memory-select', {
        detail: { memoryId },
        bubbles: true
      }));
      
      // Navigate to memory detail page
      if (window.app && window.app.router) {
        window.app.router.navigate(`/memory/${memoryId}`);
      }
    }
  }
  
  /**
   * Handle keyboard events
   */
  handleKeydown(event) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      this.handleClick(event);
    }
  }
  
  /**
   * Get memory data from attributes
   */
  getMemoryData() {
    return {
      id: this.getAttribute('memory-id'),
      content: this.getAttribute('content') || '',
      project_id: this.getAttribute('project'),
      category: this.getAttribute('category') || 'task',
      created_at: this.getAttribute('created-at'),
      updated_at: this.getAttribute('updated-at'),
      similarity_score: parseFloat(this.getAttribute('similarity-score')) || null,
      tags: this.parseTags(this.getAttribute('tags')),
      source: this.getAttribute('source') || 'unknown'
    };
  }
  
  /**
   * Parse tags from string
   */
  parseTags(tagsStr) {
    if (!tagsStr) return [];
    try {
      return JSON.parse(tagsStr);
    } catch {
      return tagsStr.split(',').map(tag => tag.trim()).filter(Boolean);
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
   * Get category color
   */
  getCategoryColor(category) {
    const colors = {
      task: '#2563eb',
      bug: '#ef4444',
      idea: '#f59e0b',
      decision: '#8b5cf6',
      incident: '#ef4444',
      code_snippet: '#10b981'
    };
    return colors[category] || '#64748b';
  }
  
  /**
   * Format date
   */
  formatDate(dateStr) {
    if (!dateStr) return '';
    
    try {
      const date = new Date(dateStr);
      const now = new Date();
      const diffMs = now - date;
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
      
      if (diffDays === 0) {
        return 'Today';
      } else if (diffDays === 1) {
        return 'Yesterday';
      } else if (diffDays < 7) {
        return `${diffDays} days ago`;
      } else {
        return date.toLocaleDateString();
      }
    } catch {
      return dateStr;
    }
  }
  
  /**
   * Get content preview
   */
  getContentPreview(content, maxLength = 200) {
    if (!content) return '';
    
    // Remove markdown formatting for preview
    const plainText = content
      .replace(/#{1,6}\s+/g, '') // Headers
      .replace(/\*\*(.*?)\*\*/g, '$1') // Bold
      .replace(/\*(.*?)\*/g, '$1') // Italic
      .replace(/`(.*?)`/g, '$1') // Inline code
      .replace(/\[(.*?)\]\(.*?\)/g, '$1') // Links
      .trim();
    
    if (plainText.length <= maxLength) {
      return plainText;
    }
    
    return plainText.substring(0, maxLength).trim() + '...';
  }
  
  /**
   * Toggle expanded state
   */
  toggleExpanded(event) {
    event.stopPropagation();
    this.isExpanded = !this.isExpanded;
    this.render();
  }
  
  /**
   * Handle favorite toggle
   */
  handleFavoriteToggle(event) {
    event.stopPropagation();
    
    const memoryId = this.getAttribute('memory-id');
    if (!memoryId) return;
    
    // Dispatch custom event
    this.dispatchEvent(new CustomEvent('memory-favorite-toggle', {
      detail: { memoryId },
      bubbles: true
    }));
  }
  
  /**
   * Handle share
   */
  handleShare(event) {
    event.stopPropagation();
    
    const memoryId = this.getAttribute('memory-id');
    if (!memoryId) return;
    
    const url = `${window.location.origin}/memory/${memoryId}`;
    
    if (navigator.share) {
      navigator.share({
        title: 'mem-mesh Memory',
        text: this.getContentPreview(this.getAttribute('content'), 100),
        url: url
      });
    } else {
      // Fallback: copy to clipboard
      navigator.clipboard.writeText(url).then(() => {
        // Show toast notification
        if (window.app && window.app.errorHandler) {
          window.app.errorHandler.showSuccess('Link copied to clipboard');
        }
      });
    }
  }
  
  /**
   * Render the component
   */
  render() {
    const memory = this.getMemoryData();
    const categoryIcon = this.getCategoryIcon(memory.category);
    const categoryColor = this.getCategoryColor(memory.category);
    const formattedDate = this.formatDate(memory.created_at);
    const contentPreview = this.getContentPreview(memory.content);
    const fullContent = memory.content;
    
    this.className = 'memory-card';
    
    this.innerHTML = `
      <div class="memory-card-header">
        <div class="memory-meta">
          <span class="category-badge" style="color: ${categoryColor}">
            ${categoryIcon} ${memory.category}
          </span>
          ${memory.project_id ? `<span class="project-badge">${memory.project_id}</span>` : ''}
          ${memory.similarity_score !== null ? 
            `<span class="similarity-score" title="Similarity Score">${(memory.similarity_score * 100).toFixed(0)}%</span>` 
            : ''
          }
        </div>
        <div class="memory-actions">
          <button class="action-btn favorite-btn" title="Add to favorites" aria-label="Add to favorites">
            ⭐
          </button>
          <button class="action-btn share-btn" title="Share memory" aria-label="Share memory">
            🔗
          </button>
        </div>
      </div>
      
      <div class="memory-content">
        <div class="content-preview ${this.isExpanded ? 'hidden' : ''}">
          ${contentPreview}
        </div>
        <div class="content-full ${this.isExpanded ? '' : 'hidden'}">
          ${this.formatContent(fullContent)}
        </div>
        ${fullContent.length > 200 ? `
          <button class="expand-btn" aria-label="${this.isExpanded ? 'Show less' : 'Show more'}">
            ${this.isExpanded ? 'Show less' : 'Show more'}
          </button>
        ` : ''}
      </div>
      
      <div class="memory-footer">
        <div class="memory-tags">
          ${memory.tags.map(tag => `<span class="tag">#${tag}</span>`).join('')}
        </div>
        <div class="memory-timestamp">
          <time datetime="${memory.created_at}" title="${new Date(memory.created_at).toLocaleString()}">
            ${formattedDate}
          </time>
          ${memory.source !== 'unknown' ? `<span class="source">via ${memory.source}</span>` : ''}
        </div>
      </div>
    `;
    
    // Setup action button listeners
    const favoriteBtn = this.querySelector('.favorite-btn');
    const shareBtn = this.querySelector('.share-btn');
    const expandBtn = this.querySelector('.expand-btn');
    
    if (favoriteBtn) {
      favoriteBtn.addEventListener('click', this.handleFavoriteToggle.bind(this));
    }
    
    if (shareBtn) {
      shareBtn.addEventListener('click', this.handleShare.bind(this));
    }
    
    if (expandBtn) {
      expandBtn.addEventListener('click', this.toggleExpanded.bind(this));
    }
  }
  
  /**
   * Format content with basic markdown support
   */
  formatContent(content) {
    if (!content) return '';
    
    return content
      .replace(/\n/g, '<br>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`(.*?)`/g, '<code>$1</code>')
      .replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  }
}

// Define the custom element
customElements.define('memory-card', MemoryCard);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .memory-card {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 1.5rem;
    margin-bottom: 1rem;
    box-shadow: var(--shadow-sm);
    transition: var(--transition);
    cursor: pointer;
    display: block;
  }
  
  .memory-card:hover {
    box-shadow: var(--shadow-md);
    transform: translateY(-1px);
    border-color: var(--border-hover);
  }
  
  .memory-card:focus {
    outline: 2px solid var(--primary-color);
    outline-offset: 2px;
  }
  
  .memory-card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1rem;
    gap: 1rem;
  }
  
  .memory-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
  }
  
  .category-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.875rem;
    font-weight: 500;
    text-transform: capitalize;
  }
  
  .project-badge {
    background: var(--bg-secondary);
    color: var(--text-secondary);
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
    font-weight: 500;
  }
  
  .similarity-score {
    background: var(--primary-color);
    color: white;
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
    font-weight: 600;
  }
  
  .memory-actions {
    display: flex;
    gap: 0.25rem;
  }
  
  .action-btn {
    background: none;
    border: none;
    padding: 0.25rem;
    border-radius: var(--border-radius-sm);
    cursor: pointer;
    font-size: 1rem;
    opacity: 0.6;
    transition: var(--transition);
  }
  
  .action-btn:hover {
    opacity: 1;
    background: var(--bg-secondary);
  }
  
  .memory-content {
    margin-bottom: 1rem;
    line-height: 1.6;
    color: var(--text-primary);
  }
  
  .content-preview,
  .content-full {
    margin-bottom: 0.5rem;
  }
  
  .content-full code {
    background: var(--bg-secondary);
    padding: 0.125rem 0.25rem;
    border-radius: var(--border-radius-sm);
    font-family: var(--font-mono);
    font-size: 0.875rem;
  }
  
  .content-full a {
    color: var(--primary-color);
    text-decoration: none;
  }
  
  .content-full a:hover {
    text-decoration: underline;
  }
  
  .expand-btn {
    background: none;
    border: none;
    color: var(--primary-color);
    cursor: pointer;
    font-size: 0.875rem;
    padding: 0;
    text-decoration: underline;
  }
  
  .expand-btn:hover {
    color: var(--primary-hover);
  }
  
  .memory-footer {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 1rem;
    flex-wrap: wrap;
  }
  
  .memory-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
  }
  
  .tag {
    background: var(--bg-secondary);
    color: var(--text-secondary);
    padding: 0.125rem 0.375rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
    font-weight: 500;
  }
  
  .memory-timestamp {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    font-size: 0.75rem;
    color: var(--text-muted);
    gap: 0.125rem;
  }
  
  .source {
    font-style: italic;
  }
  
  .hidden {
    display: none !important;
  }
  
  /* Responsive design */
  @media (max-width: 768px) {
    .memory-card {
      padding: 1rem;
    }
    
    .memory-card-header {
      flex-direction: column;
      gap: 0.5rem;
    }
    
    .memory-actions {
      align-self: flex-end;
    }
    
    .memory-footer {
      flex-direction: column;
      align-items: flex-start;
      gap: 0.5rem;
    }
    
    .memory-timestamp {
      align-items: flex-start;
    }
  }
`;

document.head.appendChild(style);

export { MemoryCard };