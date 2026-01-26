/**
 * Memory Card Web Component
 * Displays individual memory information as a card
 */

class MemoryCard extends HTMLElement {
  static get observedAttributes() {
    return [
      'memory-id', 'content', 'project', 'category', 
      'created-at', 'updated-at', 'similarity-score', 'tags', 'source', 'search-query'
    ];
  }
  
  constructor() {
    super();
    this.memory = null;
    this.isExpanded = false;
    this.showDetailedDate = false;
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
                    </svg>`,
      'git-history': `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                       <path d="M9 12L11 14L15 10M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" stroke-width="2"/>
                       <path d="M8 12L10 14L16 8" stroke="currentColor" stroke-width="1"/>
                     </svg>`
    };
    return icons[category] || `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M14 2H6C5.46957 2 4.96086 2.21071 4.58579 2.58579C4.21071 2.96086 4 3.46957 4 4V20C4 20.5304 4.21071 21.0391 4.58579 21.4142C4.96086 21.7893 5.46957 22 6 22H18C18.5304 22 19.0391 21.7893 19.4142 21.4142C19.7893 21.0391 20 20.5304 20 20V8L14 2Z" stroke="currentColor" stroke-width="2"/>
                                <path d="M14 2V8H20" stroke="currentColor" stroke-width="2"/>
                                <path d="M16 13H8M16 17H8M10 9H8" stroke="currentColor" stroke-width="2"/>
                              </svg>`;
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
      code_snippet: '#10b981',
      'git-history': '#6366f1'
    };
    return colors[category] || '#64748b';
  }
  
  /**
   * Format date with option for detailed view
   */
  formatDate(dateStr, showDetailed = false) {
    if (!dateStr) return '';
    
    try {
      const date = new Date(dateStr);
      
      if (showDetailed || this.showDetailedDate) {
        // Show detailed date and time
        return date.toLocaleString('ko-KR', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false
        });
      }
      
      // Show relative date
      const now = new Date();
      const diffMs = now - date;
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
      const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
      const diffMinutes = Math.floor(diffMs / (1000 * 60));
      
      if (diffMinutes < 1) {
        return 'Just now';
      } else if (diffMinutes < 60) {
        return `${diffMinutes}분 전`;
      } else if (diffHours < 24) {
        return `${diffHours}시간 전`;
      } else if (diffDays === 0) {
        return 'Today';
      } else if (diffDays === 1) {
        return 'Yesterday';
      } else if (diffDays < 7) {
        return `${diffDays}일 전`;
      } else if (diffDays < 30) {
        const weeks = Math.floor(diffDays / 7);
        return `${weeks}주 전`;
      } else if (diffDays < 365) {
        const months = Math.floor(diffDays / 30);
        return `${months}개월 전`;
      } else {
        const years = Math.floor(diffDays / 365);
        return `${years}년 전`;
      }
    } catch {
      return dateStr;
    }
  }
  
  /**
   * Toggle date display format
   */
  toggleDateFormat() {
    this.showDetailedDate = !this.showDetailedDate;
    this.render();
  }
  
  /**
   * Check if content is a Q&A pair
   */
  isQAPair(content) {
    try {
      const parsed = JSON.parse(content);
      return parsed.type === 'qa_pair' && parsed.question && parsed.answer;
    } catch {
      return false;
    }
  }
  
  /**
   * Parse Q&A content
   */
  parseQAContent(content) {
    try {
      return JSON.parse(content);
    } catch {
      return null;
    }
  }
  
  /**
   * Highlight search query in text
   */
  highlightSearchQuery(text, query) {
    if (!query || !text) return this.escapeHtml(text);
    
    const escapedText = this.escapeHtml(text);
    const escapedQuery = this.escapeHtml(query);
    const regex = new RegExp(`(${escapedQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    
    return escapedText.replace(regex, '<mark class="search-highlight">$1</mark>');
  }
  
  /**
   * Get content preview
   */
  getContentPreview(content, maxLength = 200) {
    if (!content) return '';
    
    // Check if it's a Q&A pair
    if (this.isQAPair(content)) {
      const qa = this.parseQAContent(content);
      if (qa) {
        const questionPreview = qa.question.length > 100 ? 
          qa.question.substring(0, 100) + '...' : qa.question;
        const searchQuery = this.getAttribute('search-query');
        return searchQuery ? 
          `Q: ${this.highlightSearchQuery(questionPreview, searchQuery)}` :
          `Q: ${this.escapeHtml(questionPreview)}`;
      }
    }
    
    // Remove markdown formatting for preview
    const plainText = content
      .replace(/#{1,6}\s+/g, '') // Headers
      .replace(/\*\*(.*?)\*\*/g, '$1') // Bold
      .replace(/\*(.*?)\*/g, '$1') // Italic
      .replace(/`(.*?)`/g, '$1') // Inline code
      .replace(/\[(.*?)\]\(.*?\)/g, '$1') // Links
      .trim();
    
    let preview = plainText.length <= maxLength ? 
      plainText : 
      plainText.substring(0, maxLength).trim() + '...';
    
    // Apply search highlighting if search query exists
    const searchQuery = this.getAttribute('search-query');
    return searchQuery ? 
      this.highlightSearchQuery(preview, searchQuery) :
      this.escapeHtml(preview);
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
    
    // Check if this is a Q&A pair
    const isQA = this.isQAPair(memory.content);
    const qaData = isQA ? this.parseQAContent(memory.content) : null;
    
    this.className = 'memory-card';
    if (isQA) {
      this.classList.add('qa-pair');
    }
    
    // Generate content HTML based on type
    let contentHTML = '';
    if (isQA && qaData) {
      contentHTML = `
        <div class="qa-content">
          <div class="qa-question">
            <div class="qa-label">Q:</div>
            <div class="qa-text">${this.escapeHtml(qaData.question)}</div>
          </div>
          ${this.isExpanded ? `
            <div class="qa-answer">
              <div class="qa-label">A:</div>
              <div class="qa-text">${this.formatContent(qaData.answer)}</div>
            </div>
            ${qaData.conversation_id ? `
              <div class="qa-meta">
                <span class="conversation-id" title="Conversation ID">${qaData.conversation_id}</span>
                ${qaData.timestamp ? `
                  <span class="qa-timestamp timestamp-toggle" title="클릭하여 ${this.showDetailedDate ? '상대적' : '상세한'} 시간 보기">
                    ${this.formatDate(qaData.timestamp)}
                  </span>
                ` : ''}
              </div>
            ` : ''}
          ` : ''}
        </div>
      `;
    } else {
      contentHTML = `
        <div class="content-preview ${this.isExpanded ? 'hidden' : ''}">
          ${contentPreview}
        </div>
        <div class="content-full ${this.isExpanded ? '' : 'hidden'}">
          ${this.formatContent(fullContent)}
        </div>
      `;
    }
    
    this.innerHTML = `
      <div class="memory-card-header">
        <div class="memory-meta">
          <span class="category-badge" style="color: ${categoryColor}">
            ${categoryIcon} ${memory.category}${isQA ? ' (Q&A)' : ''}
          </span>
          ${memory.project_id ? `<span class="project-badge">${memory.project_id}</span>` : ''}
          ${memory.similarity_score !== null ? 
            `<span class="similarity-score" title="Similarity Score">${(memory.similarity_score * 100).toFixed(0)}%</span>` 
            : ''
          }
        </div>
        <div class="memory-actions">
          <button class="action-btn favorite-btn" title="Add to favorites" aria-label="Add to favorites">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2L15.09 8.26L22 9L17 14L18.18 21L12 17.77L5.82 21L7 14L2 9L8.91 8.26L12 2Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
            </svg>
          </button>
          <button class="action-btn share-btn" title="Share memory" aria-label="Share memory">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M10 13C10.4295 13.5741 10.9774 14.0491 11.6066 14.3929C12.2357 14.7367 12.9315 14.9411 13.6467 14.9923C14.3618 15.0435 15.0796 14.9403 15.7513 14.6897C16.4231 14.4392 17.0331 14.047 17.54 13.54L20.54 10.54C21.4508 9.59695 21.9548 8.33394 21.9434 7.02296C21.932 5.71198 21.4061 4.45791 20.4791 3.53087C19.5521 2.60383 18.298 2.07799 16.987 2.0666C15.676 2.0552 14.413 2.55918 13.47 3.47L11.75 5.18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M14 11C13.5705 10.4259 13.0226 9.95085 12.3934 9.60706C11.7643 9.26327 11.0685 9.05885 10.3533 9.00769C9.63819 8.95653 8.92037 9.05973 8.24864 9.31028C7.5769 9.56084 6.9669 9.95303 6.46 10.46L3.46 13.46C2.54918 14.403 2.04520 15.6661 2.05660 16.977C2.06799 18.288 2.59383 19.5421 3.52087 20.4691C4.44791 21.3962 5.70198 21.922 7.01296 21.9334C8.32394 21.9448 9.58695 21.4408 10.53 20.53L12.24 18.82" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </div>
      </div>
      
      <div class="memory-content">
        ${contentHTML}
        <div class="content-meta">
          ${(fullContent.length > 200 || isQA) ? `
            <button class="expand-btn" aria-label="${this.isExpanded ? 'Show less' : 'Show more'}">
              ${this.isExpanded ? 'Show less' : (isQA ? 'Show answer' : 'Show more')}
            </button>
          ` : ''}
          <div class="memory-timestamp">
            <time 
              datetime="${memory.created_at}" 
              title="클릭하여 ${this.showDetailedDate ? '상대적' : '상세한'} 시간 보기"
              class="timestamp-toggle"
            >
              ${formattedDate}
            </time>
            ${memory.source !== 'unknown' ? `<span class="source">via ${memory.source}</span>` : ''}
          </div>
        </div>
      </div>
      
      <div class="memory-footer">
        <div class="memory-tags">
          ${memory.tags.map(tag => `<span class="tag">#${tag}</span>`).join('')}
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
    
    // Timestamp toggle
    const timestampToggles = this.querySelectorAll('.timestamp-toggle');
    timestampToggles.forEach(toggle => {
      toggle.addEventListener('click', (event) => {
        event.stopPropagation();
        this.toggleDateFormat();
      });
    });
  }
  
  /**
   * Escape HTML to prevent XSS
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
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
    padding: 1px !important;
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
  }
  
  .project-badge {
    background: #f5f5f5 !important;
    color: #171717 !important;
    padding: 0.25rem 0.5rem;
    border-radius: var(--radius-sm);
    font-size: 0.75rem;
    font-weight: 500;
    border: 1px solid #e5e5e5;
  }
  
  [data-theme="dark"] .project-badge {
    background: #262626 !important;
    color: #a3a3a3 !important;
    border-color: #404040;
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
    text-transform: none !important;
  }
  
  .content-full a {
    color: var(--primary-color);
    text-decoration: none;
  }
  
  .content-full a:hover {
    text-decoration: underline;
  }
  
  .content-meta {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 1rem;
    margin-top: 0.5rem;
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
    flex-wrap: wrap;
    gap: 0.25rem;
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
    align-items: center;
    gap: 0.5rem;
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  
  .timestamp-toggle {
    cursor: pointer;
    padding: 0.125rem 0.25rem;
    border-radius: 3px;
    transition: background-color 0.2s ease;
  }
  
  .timestamp-toggle:hover {
    background-color: var(--bg-secondary);
    color: var(--text-secondary);
  }
  
  .source {
    font-style: italic;
  }
  
  .hidden {
    display: none !important;
  }
  
  /* Q&A Pair Styles */
  .memory-card.qa-pair {
    border-left: 4px solid var(--primary-color);
  }
  
  .qa-content {
    margin-bottom: 1rem;
  }
  
  .qa-question,
  .qa-answer {
    display: flex;
    gap: 0.75rem;
    margin-bottom: 1rem;
  }
  
  .qa-answer {
    margin-top: 1rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border-color);
  }
  
  .qa-label {
    font-weight: 600;
    color: var(--primary-color);
    min-width: 1.5rem;
    flex-shrink: 0;
  }
  
  .qa-text {
    flex: 1;
    line-height: 1.6;
  }
  
  .qa-question .qa-text {
    font-weight: 500;
  }
  
  .qa-meta {
    display: flex;
    gap: 1rem;
    margin-top: 1rem;
    padding-top: 0.5rem;
    border-top: 1px solid var(--border-color);
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  
  .conversation-id {
    font-family: var(--font-mono);
    background: var(--bg-secondary);
    padding: 0.125rem 0.375rem;
    border-radius: var(--border-radius-sm);
  }
  
  .qa-timestamp {
    font-style: italic;
  }
  
  .qa-timestamp.timestamp-toggle {
    cursor: pointer;
    padding: 0.125rem 0.25rem;
    border-radius: 3px;
    transition: background-color 0.2s ease;
  }
  
  .qa-timestamp.timestamp-toggle:hover {
    background-color: var(--bg-secondary);
    color: var(--text-secondary);
  }
  
  .search-highlight {
    background-color: #fef3c7;
    color: #92400e;
    padding: 0 0.125rem;
    border-radius: 2px;
    font-weight: 500;
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
  }
`;

document.head.appendChild(style);

export { MemoryCard };