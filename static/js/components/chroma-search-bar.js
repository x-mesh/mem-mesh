/**
 * Chroma-Style Search Bar Web Component
 * Modern, prominent search interface with animations and focus states
 * Requirements: 6.1, 6.2
 */

class ChromaSearchBar extends HTMLElement {
  static get observedAttributes() {
    return ['placeholder', 'value', 'disabled', 'size', 'variant'];
  }
  
  constructor() {
    super();
    this.debounceTimer = null;
    this.suggestions = [];
    this.selectedSuggestionIndex = -1;
    this.isOpen = false;
    this.recentSearches = [];
    this.popularQueries = [
      'task management',
      'bug fixes',
      'code snippets',
      'project ideas',
      'decisions'
    ];
  }
  
  connectedCallback() {
    this.render();
    this.setupEventListeners();
    this.loadRecentSearches();
  }
  
  disconnectedCallback() {
    this.removeEventListeners();
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }
  }
  
  attributeChangedCallback(name, oldValue, newValue) {
    if (oldValue !== newValue && this.isConnected) {
      if (name === 'value') {
        // value 변경 시에는 render하지 않고 input value만 업데이트
        const input = this.querySelector('.chroma-search-input');
        if (input && input.value !== newValue) {
          input.value = newValue;
          this.updateClearButton(newValue);
        }
      } else {
        this.render();
        this.setupEventListeners();
      }
    }
  }
  
  setupEventListeners() {
    const input = this.querySelector('.chroma-search-input');
    const clearBtn = this.querySelector('.chroma-clear-btn');
    const searchBtn = this.querySelector('.chroma-search-btn');
    const container = this.querySelector('.chroma-search-container');
    
    if (input) {
      input.addEventListener('input', this.handleInput.bind(this));
      input.addEventListener('keydown', this.handleKeydown.bind(this));
      input.addEventListener('focus', this.handleFocus.bind(this));
      input.addEventListener('blur', this.handleBlur.bind(this));
    }
    
    if (clearBtn) {
      clearBtn.addEventListener('click', this.handleClear.bind(this));
    }
    
    if (searchBtn) {
      searchBtn.addEventListener('click', this.handleSearch.bind(this));
    }
    
    // Global click handler to close suggestions
    this._documentClickHandler = this.handleDocumentClick.bind(this);
    document.addEventListener('click', this._documentClickHandler);
  }
  
  removeEventListeners() {
    if (this._documentClickHandler) {
      document.removeEventListener('click', this._documentClickHandler);
    }
  }
  
  handleInput(event) {
    const value = event.target.value;
    this.setAttribute('value', value);
    
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }
    
    this.debounceTimer = setTimeout(() => {
      this.performSuggestionSearch(value);
    }, 200);
    
    this.updateClearButton(value);
    
    this.dispatchEvent(new CustomEvent('search-input', {
      detail: { value },
      bubbles: true
    }));
  }
  
  handleKeydown(event) {
    const suggestionsContainer = this.querySelector('.chroma-suggestions');
    const suggestions = suggestionsContainer?.querySelectorAll('.chroma-suggestion-item');
    
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        this.selectedSuggestionIndex = Math.min(
          this.selectedSuggestionIndex + 1,
          (suggestions?.length || 0) - 1
        );
        this.updateSuggestionSelection();
        break;
        
      case 'ArrowUp':
        event.preventDefault();
        this.selectedSuggestionIndex = Math.max(
          this.selectedSuggestionIndex - 1,
          -1
        );
        this.updateSuggestionSelection();
        break;
        
      case 'Enter':
        event.preventDefault();
        if (this.selectedSuggestionIndex >= 0 && suggestions) {
          const selectedSuggestion = suggestions[this.selectedSuggestionIndex];
          const text = selectedSuggestion.querySelector('.chroma-suggestion-text')?.textContent;
          if (text) this.selectSuggestion(text);
        } else {
          this.handleSearch();
        }
        break;
        
      case 'Escape':
        this.closeSuggestions();
        event.target.blur();
        break;
        
      case 'Tab':
        this.closeSuggestions();
        break;
    }
  }
  
  handleFocus(event) {
    const container = this.querySelector('.chroma-search-container');
    container?.classList.add('focused');
    
    const value = event.target.value;
    if (value.trim()) {
      this.showSuggestions();
    } else {
      this.showRecentAndPopular();
    }
  }
  
  handleBlur(event) {
    const container = this.querySelector('.chroma-search-container');
    container?.classList.remove('focused');
    
    setTimeout(() => {
      this.closeSuggestions();
    }, 200);
  }
  
  handleDocumentClick(event) {
    if (!this.contains(event.target)) {
      this.closeSuggestions();
    }
  }
  
  handleClear() {
    const input = this.querySelector('.chroma-search-input');
    if (input) {
      input.value = '';
      input.focus();
      this.setAttribute('value', '');
      this.updateClearButton('');
      this.closeSuggestions();
      
      this.dispatchEvent(new CustomEvent('search-clear', {
        bubbles: true
      }));
    }
  }
  
  handleSearch() {
    const input = this.querySelector('.chroma-search-input');
    const value = input?.value.trim() || '';
    
    if (value) {
      this.addToRecentSearches(value);
      this.closeSuggestions();
      
      this.dispatchEvent(new CustomEvent('search-submit', {
        detail: { query: value },
        bubbles: true
      }));
    }
  }
  
  async performSuggestionSearch(query) {
    if (!query.trim()) {
      this.showRecentAndPopular();
      return;
    }
    
    try {
      const suggestions = await this.getSuggestions(query);
      this.suggestions = suggestions;
      this.showSuggestions();
    } catch (error) {
      console.error('Failed to get suggestions:', error);
      this.suggestions = [];
      this.showSuggestions();
    }
  }
  
  async getSuggestions(query) {
    const suggestions = [];
    const lowerQuery = query.toLowerCase();
    
    // Add matching recent searches first
    const matchingRecent = this.recentSearches
      .filter(s => s.toLowerCase().includes(lowerQuery))
      .slice(0, 3);
    
    matchingRecent.forEach(s => {
      suggestions.push({ type: 'recent', text: s });
    });
    
    // Try to get suggestions from API
    try {
      if (window.app && window.app.apiClient && query.length >= 2) {
        const response = await window.app.apiClient.searchMemories(query, { limit: 5 });
        if (response.results && response.results.length > 0) {
          response.results.forEach(memory => {
            // Extract a meaningful snippet from content
            const content = memory.content || '';
            const snippet = content.length > 60 ? content.substring(0, 60) + '...' : content;
            if (!suggestions.find(s => s.text === snippet)) {
              suggestions.push({ 
                type: 'result', 
                text: snippet,
                memoryId: memory.id,
                category: memory.category
              });
            }
          });
        }
      }
    } catch (error) {
      console.warn('Failed to fetch API suggestions:', error);
    }
    
    // Add query variations as fallback
    if (query.length > 1 && suggestions.length < 3) {
      if (!suggestions.find(s => s.text === query)) {
        suggestions.push({ type: 'search', text: query });
      }
      
      const categories = ['task', 'bug', 'idea', 'decision', 'code_snippet'];
      const matchingCategory = categories.find(c => c.includes(lowerQuery));
      if (matchingCategory && !suggestions.find(s => s.text.includes('category:'))) {
        suggestions.push({ type: 'filter', text: `category:${matchingCategory}` });
      }
    }
    
    return suggestions.slice(0, 8);
  }
  
  showSuggestions() {
    const suggestionsContainer = this.querySelector('.chroma-suggestions');
    if (!suggestionsContainer) return;
    
    const query = this.getAttribute('value') || '';
    
    if (this.suggestions.length === 0) {
      this.closeSuggestions();
      return;
    }
    
    suggestionsContainer.innerHTML = `
      <div class="chroma-suggestions-header">
        <span>Suggestions</span>
        <span class="chroma-keyboard-hint">↑↓ to navigate, Enter to select</span>
      </div>
      ${this.suggestions.map((item, index) => `
        <div class="chroma-suggestion-item" data-index="${index}" data-type="${item.type}"${item.memoryId ? ` data-memory-id="${item.memoryId}"` : ''}>
          <span class="chroma-suggestion-icon">${this.getSuggestionIcon(item.type)}</span>
          <span class="chroma-suggestion-text">${this.highlightQuery(item.text, query)}</span>
          ${item.category ? `<span class="chroma-suggestion-category">${item.category}</span>` : ''}
          <span class="chroma-suggestion-type">${this.getSuggestionLabel(item.type)}</span>
        </div>
      `).join('')}
    `;
    
    this.setupSuggestionListeners(suggestionsContainer);
    suggestionsContainer.classList.remove('hidden');
    suggestionsContainer.setAttribute('aria-expanded', 'true');
    this.isOpen = true;
    this.selectedSuggestionIndex = -1;
  }
  
  showRecentAndPopular() {
    const suggestionsContainer = this.querySelector('.chroma-suggestions');
    if (!suggestionsContainer) return;
    
    const hasRecent = this.recentSearches.length > 0;
    
    let html = '';
    
    if (hasRecent) {
      html += `
        <div class="chroma-suggestions-header">
          <span>Recent Searches</span>
          <button class="chroma-clear-history-btn" type="button">Clear</button>
        </div>
        ${this.recentSearches.slice(0, 5).map((item, index) => `
          <div class="chroma-suggestion-item" data-index="${index}" data-type="recent">
            <span class="chroma-suggestion-icon">${this.getSuggestionIcon('recent')}</span>
            <span class="chroma-suggestion-text">${item}</span>
            <button class="chroma-remove-item-btn" data-query="${item}" type="button">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>
        `).join('')}
      `;
    }
    
    html += `
      <div class="chroma-suggestions-header">
        <span>Popular Searches</span>
      </div>
      ${this.popularQueries.map((item, index) => `
        <div class="chroma-suggestion-item" data-index="${hasRecent ? this.recentSearches.length + index : index}" data-type="popular">
          <span class="chroma-suggestion-icon">${this.getSuggestionIcon('popular')}</span>
          <span class="chroma-suggestion-text">${item}</span>
        </div>
      `).join('')}
    `;
    
    suggestionsContainer.innerHTML = html;
    this.setupSuggestionListeners(suggestionsContainer);
    suggestionsContainer.classList.remove('hidden');
    this.isOpen = true;
    this.selectedSuggestionIndex = -1;
  }
  
  setupSuggestionListeners(container) {
    container.querySelectorAll('.chroma-suggestion-item').forEach(item => {
      item.addEventListener('click', (e) => {
        if (e.target.closest('.chroma-remove-item-btn')) return;
        
        const type = item.getAttribute('data-type');
        const memoryId = item.getAttribute('data-memory-id');
        const text = item.querySelector('.chroma-suggestion-text')?.textContent;
        
        // If it's a result type with memoryId, navigate to memory detail
        if (type === 'result' && memoryId && window.app && window.app.router) {
          this.closeSuggestions();
          window.app.router.navigate(`/memory/${memoryId}`);
          return;
        }
        
        if (text) this.selectSuggestion(text);
      });
    });
    
    container.querySelectorAll('.chroma-remove-item-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const query = btn.getAttribute('data-query');
        this.removeFromRecentSearches(query);
      });
    });
    
    const clearHistoryBtn = container.querySelector('.chroma-clear-history-btn');
    if (clearHistoryBtn) {
      clearHistoryBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.clearRecentSearches();
      });
    }
  }
  
  getSuggestionIcon(type) {
    const icons = {
      recent: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12,6 12,12 16,14"/></svg>`,
      search: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>`,
      filter: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="22,3 2,3 10,12.46 10,19 14,21 14,12.46 22,3"/></svg>`,
      popular: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>`,
      result: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`
    };
    return icons[type] || icons.search;
  }
  
  getSuggestionLabel(type) {
    const labels = {
      recent: 'Recent',
      search: 'Search',
      filter: 'Filter',
      popular: 'Popular',
      result: 'Memory'
    };
    return labels[type] || '';
  }
  
  closeSuggestions() {
    const suggestionsContainer = this.querySelector('.chroma-suggestions');
    if (suggestionsContainer) {
      suggestionsContainer.classList.add('hidden');
    }
    this.isOpen = false;
    this.selectedSuggestionIndex = -1;
  }
  
  selectSuggestion(suggestion) {
    const input = this.querySelector('.chroma-search-input');
    if (input) {
      input.value = suggestion;
      this.setAttribute('value', suggestion);
      this.updateClearButton(suggestion);
    }
    
    this.addToRecentSearches(suggestion);
    this.closeSuggestions();
    
    this.dispatchEvent(new CustomEvent('search-submit', {
      detail: { query: suggestion },
      bubbles: true
    }));
  }
  
  updateSuggestionSelection() {
    const suggestions = this.querySelectorAll('.chroma-suggestion-item');
    suggestions.forEach((item, index) => {
      if (index === this.selectedSuggestionIndex) {
        item.classList.add('selected');
        item.scrollIntoView({ block: 'nearest' });
      } else {
        item.classList.remove('selected');
      }
    });
  }
  
  highlightQuery(text, query) {
    if (!query.trim()) return text;
    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return text.replace(regex, '<mark>$1</mark>');
  }
  
  updateClearButton(value) {
    const clearBtn = this.querySelector('.chroma-clear-btn');
    if (clearBtn) {
      clearBtn.style.opacity = value ? '1' : '0';
      clearBtn.style.pointerEvents = value ? 'auto' : 'none';
    }
  }
  
  loadRecentSearches() {
    try {
      const stored = localStorage.getItem('mem-mesh-recent-searches');
      this.recentSearches = stored ? JSON.parse(stored) : [];
    } catch {
      this.recentSearches = [];
    }
  }
  
  addToRecentSearches(query) {
    if (!query.trim()) return;
    
    this.recentSearches = this.recentSearches.filter(item => item !== query);
    this.recentSearches.unshift(query);
    
    if (this.recentSearches.length > 10) {
      this.recentSearches.pop();
    }
    
    try {
      localStorage.setItem('mem-mesh-recent-searches', JSON.stringify(this.recentSearches));
    } catch (error) {
      console.warn('Failed to save recent searches:', error);
    }
  }
  
  removeFromRecentSearches(query) {
    this.recentSearches = this.recentSearches.filter(item => item !== query);
    
    try {
      localStorage.setItem('mem-mesh-recent-searches', JSON.stringify(this.recentSearches));
    } catch (error) {
      console.warn('Failed to save recent searches:', error);
    }
    
    if (this.isOpen) {
      this.showRecentAndPopular();
    }
  }
  
  clearRecentSearches() {
    this.recentSearches = [];
    try {
      localStorage.removeItem('mem-mesh-recent-searches');
    } catch (error) {
      console.warn('Failed to clear recent searches:', error);
    }
    
    if (this.isOpen) {
      this.showRecentAndPopular();
    }
  }
  
  get value() {
    return this.getAttribute('value') || '';
  }
  
  set value(val) {
    this.setAttribute('value', val);
    const input = this.querySelector('.chroma-search-input');
    if (input) {
      input.value = val;
      this.updateClearButton(val);
    }
  }
  
  focus() {
    const input = this.querySelector('.chroma-search-input');
    if (input) {
      input.focus();
    }
  }
  
  render() {
    const placeholder = this.getAttribute('placeholder') || 'Search your memories...';
    const value = this.getAttribute('value') || '';
    const disabled = this.hasAttribute('disabled');
    const size = this.getAttribute('size') || 'default'; // 'small', 'default', 'large'
    const variant = this.getAttribute('variant') || 'default'; // 'default', 'hero'
    
    this.className = `chroma-search-bar chroma-search-${size} chroma-search-${variant}`;
    
    this.innerHTML = `
      <div class="chroma-search-container">
        <div class="chroma-search-input-wrapper">
          <span class="chroma-search-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8"/>
              <path d="m21 21-4.35-4.35"/>
            </svg>
          </span>
          <input 
            type="text" 
            class="chroma-search-input" 
            placeholder="${placeholder}"
            value="${value}"
            ${disabled ? 'disabled' : ''}
            autocomplete="off"
            spellcheck="false"
            aria-label="Search memories"
            role="combobox"
            aria-expanded="false"
            aria-haspopup="listbox"
          >
          <button 
            class="chroma-clear-btn" 
            type="button"
            style="opacity: ${value ? '1' : '0'}; pointer-events: ${value ? 'auto' : 'none'}"
            title="Clear search"
            aria-label="Clear search"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
          <button 
            class="chroma-search-btn" 
            type="button"
            title="Search"
            aria-label="Submit search"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="9,18 15,12 9,6"/>
            </svg>
          </button>
        </div>
        <div class="chroma-suggestions hidden" role="listbox" aria-label="Search suggestions"></div>
      </div>
    `;
  }
}

// Define the custom element
customElements.define('chroma-search-bar', ChromaSearchBar);

export { ChromaSearchBar };
