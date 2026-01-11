/**
 * Search Bar Web Component
 * Provides search input with autocomplete and suggestions
 */

class SearchBar extends HTMLElement {
  static get observedAttributes() {
    return ['placeholder', 'value', 'disabled'];
  }
  
  constructor() {
    super();
    this.debounceTimer = null;
    this.suggestions = [];
    this.selectedSuggestionIndex = -1;
    this.isOpen = false;
    this.recentSearches = [];
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
    if (oldValue !== newValue) {
      this.render();
    }
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    const input = this.querySelector('.search-input');
    const clearBtn = this.querySelector('.clear-btn');
    const searchBtn = this.querySelector('.search-btn');
    
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
    document.addEventListener('click', this.handleDocumentClick.bind(this));
  }
  
  /**
   * Remove event listeners
   */
  removeEventListeners() {
    document.removeEventListener('click', this.handleDocumentClick);
  }
  
  /**
   * Handle input changes
   */
  handleInput(event) {
    const value = event.target.value;
    this.setAttribute('value', value);
    
    // Clear previous timer
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }
    
    // Debounce search
    this.debounceTimer = setTimeout(() => {
      this.performSearch(value);
    }, 300);
    
    // Show/hide clear button
    this.updateClearButton(value);
    
    // Emit input event
    this.dispatchEvent(new CustomEvent('search-input', {
      detail: { value },
      bubbles: true
    }));
  }
  
  /**
   * Handle keydown events
   */
  handleKeydown(event) {
    const suggestionsContainer = this.querySelector('.suggestions');
    const suggestions = suggestionsContainer?.querySelectorAll('.suggestion-item');
    
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
          this.selectSuggestion(selectedSuggestion.textContent);
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
  
  /**
   * Handle focus events
   */
  handleFocus(event) {
    const value = event.target.value;
    if (value.trim()) {
      this.showSuggestions();
    } else {
      this.showRecentSearches();
    }
  }
  
  /**
   * Handle blur events
   */
  handleBlur(event) {
    // Delay closing to allow suggestion clicks
    setTimeout(() => {
      this.closeSuggestions();
    }, 150);
  }
  
  /**
   * Handle document clicks
   */
  handleDocumentClick(event) {
    if (!this.contains(event.target)) {
      this.closeSuggestions();
    }
  }
  
  /**
   * Handle clear button
   */
  handleClear() {
    const input = this.querySelector('.search-input');
    if (input) {
      input.value = '';
      input.focus();
      this.setAttribute('value', '');
      this.updateClearButton('');
      this.closeSuggestions();
      
      // Emit clear event
      this.dispatchEvent(new CustomEvent('search-clear', {
        bubbles: true
      }));
    }
  }
  
  /**
   * Handle search button
   */
  handleSearch() {
    const input = this.querySelector('.search-input');
    const value = input?.value.trim() || '';
    
    if (value) {
      this.addToRecentSearches(value);
      this.closeSuggestions();
      
      // Emit search event
      this.dispatchEvent(new CustomEvent('search-submit', {
        detail: { query: value },
        bubbles: true
      }));
    }
  }
  
  /**
   * Perform search with debouncing
   */
  async performSearch(query) {
    if (!query.trim()) {
      this.showRecentSearches();
      return;
    }
    
    try {
      // Get suggestions from API or generate them
      const suggestions = await this.getSuggestions(query);
      this.suggestions = suggestions;
      this.showSuggestions();
      
    } catch (error) {
      console.error('Failed to get suggestions:', error);
      this.suggestions = [];
      this.showSuggestions();
    }
  }
  
  /**
   * Get search suggestions
   */
  async getSuggestions(query) {
    // For now, return simple suggestions based on query
    // In a real implementation, this would call the API
    const suggestions = [];
    
    // Add query variations
    if (query.length > 2) {
      suggestions.push(query);
      suggestions.push(`${query} in:content`);
      suggestions.push(`${query} category:task`);
      suggestions.push(`${query} category:bug`);
      suggestions.push(`${query} category:idea`);
    }
    
    return suggestions.slice(0, 5);
  }
  
  /**
   * Show suggestions dropdown
   */
  showSuggestions() {
    const suggestionsContainer = this.querySelector('.suggestions');
    if (!suggestionsContainer) return;
    
    const query = this.getAttribute('value') || '';
    const items = query.trim() ? this.suggestions : this.recentSearches;
    
    if (items.length === 0) {
      this.closeSuggestions();
      return;
    }
    
    suggestionsContainer.innerHTML = items.map((item, index) => `
      <div class="suggestion-item" data-index="${index}">
        <span class="suggestion-icon">${query.trim() ? '🔍' : '🕒'}</span>
        <span class="suggestion-text">${this.highlightQuery(item, query)}</span>
        ${!query.trim() ? '<button class="remove-suggestion" data-query="' + item + '">×</button>' : ''}
      </div>
    `).join('');
    
    // Setup suggestion click handlers
    suggestionsContainer.querySelectorAll('.suggestion-item').forEach(item => {
      item.addEventListener('click', () => {
        this.selectSuggestion(item.querySelector('.suggestion-text').textContent);
      });
    });
    
    // Setup remove handlers for recent searches
    suggestionsContainer.querySelectorAll('.remove-suggestion').forEach(btn => {
      btn.addEventListener('click', (event) => {
        event.stopPropagation();
        const query = btn.getAttribute('data-query');
        this.removeFromRecentSearches(query);
      });
    });
    
    suggestionsContainer.classList.remove('hidden');
    this.isOpen = true;
    this.selectedSuggestionIndex = -1;
  }
  
  /**
   * Show recent searches
   */
  showRecentSearches() {
    if (this.recentSearches.length > 0) {
      this.showSuggestions();
    }
  }
  
  /**
   * Close suggestions dropdown
   */
  closeSuggestions() {
    const suggestionsContainer = this.querySelector('.suggestions');
    if (suggestionsContainer) {
      suggestionsContainer.classList.add('hidden');
    }
    this.isOpen = false;
    this.selectedSuggestionIndex = -1;
  }
  
  /**
   * Select a suggestion
   */
  selectSuggestion(suggestion) {
    const input = this.querySelector('.search-input');
    if (input) {
      input.value = suggestion;
      this.setAttribute('value', suggestion);
      this.updateClearButton(suggestion);
    }
    
    this.addToRecentSearches(suggestion);
    this.closeSuggestions();
    
    // Emit search event
    this.dispatchEvent(new CustomEvent('search-submit', {
      detail: { query: suggestion },
      bubbles: true
    }));
  }
  
  /**
   * Update suggestion selection
   */
  updateSuggestionSelection() {
    const suggestions = this.querySelectorAll('.suggestion-item');
    suggestions.forEach((item, index) => {
      if (index === this.selectedSuggestionIndex) {
        item.classList.add('selected');
      } else {
        item.classList.remove('selected');
      }
    });
  }
  
  /**
   * Highlight query in suggestion text
   */
  highlightQuery(text, query) {
    if (!query.trim()) return text;
    
    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')})`, 'gi');
    return text.replace(regex, '<mark>$1</mark>');
  }
  
  /**
   * Update clear button visibility
   */
  updateClearButton(value) {
    const clearBtn = this.querySelector('.clear-btn');
    if (clearBtn) {
      clearBtn.style.display = value ? 'flex' : 'none';
    }
  }
  
  /**
   * Load recent searches from localStorage
   */
  loadRecentSearches() {
    try {
      const stored = localStorage.getItem('mem-mesh-recent-searches');
      this.recentSearches = stored ? JSON.parse(stored) : [];
    } catch {
      this.recentSearches = [];
    }
  }
  
  /**
   * Add to recent searches
   */
  addToRecentSearches(query) {
    if (!query.trim()) return;
    
    // Remove if already exists
    this.recentSearches = this.recentSearches.filter(item => item !== query);
    
    // Add to beginning
    this.recentSearches.unshift(query);
    
    // Limit to 10 items
    if (this.recentSearches.length > 10) {
      this.recentSearches.pop();
    }
    
    // Save to localStorage
    try {
      localStorage.setItem('mem-mesh-recent-searches', JSON.stringify(this.recentSearches));
    } catch (error) {
      console.warn('Failed to save recent searches:', error);
    }
  }
  
  /**
   * Remove from recent searches
   */
  removeFromRecentSearches(query) {
    this.recentSearches = this.recentSearches.filter(item => item !== query);
    
    try {
      localStorage.setItem('mem-mesh-recent-searches', JSON.stringify(this.recentSearches));
    } catch (error) {
      console.warn('Failed to save recent searches:', error);
    }
    
    // Refresh suggestions
    if (this.isOpen) {
      this.showSuggestions();
    }
  }
  
  /**
   * Get current value
   */
  get value() {
    return this.getAttribute('value') || '';
  }
  
  /**
   * Set value
   */
  set value(val) {
    this.setAttribute('value', val);
    const input = this.querySelector('.search-input');
    if (input) {
      input.value = val;
      this.updateClearButton(val);
    }
  }
  
  /**
   * Focus the input
   */
  focus() {
    const input = this.querySelector('.search-input');
    if (input) {
      input.focus();
    }
  }
  
  /**
   * Render the component
   */
  render() {
    const placeholder = this.getAttribute('placeholder') || 'Search memories...';
    const value = this.getAttribute('value') || '';
    const disabled = this.hasAttribute('disabled');
    
    this.className = 'search-bar';
    
    this.innerHTML = `
      <div class="search-container">
        <div class="search-input-container">
          <span class="search-icon">🔍</span>
          <input 
            type="text" 
            class="search-input" 
            placeholder="${placeholder}"
            value="${value}"
            ${disabled ? 'disabled' : ''}
            autocomplete="off"
            spellcheck="false"
          >
          <button class="clear-btn" style="display: ${value ? 'flex' : 'none'}" title="Clear search">
            ×
          </button>
          <button class="search-btn" title="Search">
            <span class="sr-only">Search</span>
            →
          </button>
        </div>
        <div class="suggestions hidden"></div>
      </div>
    `;
  }
}

// Define the custom element
customElements.define('search-bar', SearchBar);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .search-bar {
    position: relative;
    width: 100%;
    max-width: 600px;
  }
  
  .search-container {
    position: relative;
  }
  
  .search-input-container {
    position: relative;
    display: flex;
    align-items: center;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    transition: var(--transition);
  }
  
  .search-input-container:focus-within {
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
  }
  
  .search-icon {
    padding: 0.75rem;
    color: var(--text-muted);
    font-size: 1rem;
  }
  
  .search-input {
    flex: 1;
    padding: 0.75rem 0;
    border: none;
    background: transparent;
    font-size: 1rem;
    color: var(--text-primary);
    outline: none;
  }
  
  .search-input::placeholder {
    color: var(--text-muted);
  }
  
  .search-input:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  
  .clear-btn,
  .search-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    border: none;
    background: none;
    color: var(--text-muted);
    cursor: pointer;
    border-radius: var(--border-radius-sm);
    transition: var(--transition);
    margin: 0.25rem;
  }
  
  .clear-btn:hover,
  .search-btn:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }
  
  .search-btn {
    color: var(--primary-color);
    font-weight: bold;
  }
  
  .suggestions {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-top: none;
    border-radius: 0 0 var(--border-radius) var(--border-radius);
    box-shadow: var(--shadow-lg);
    z-index: 1000;
    max-height: 300px;
    overflow-y: auto;
  }
  
  .suggestion-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem;
    cursor: pointer;
    transition: var(--transition);
    border-bottom: 1px solid var(--border-color);
  }
  
  .suggestion-item:last-child {
    border-bottom: none;
  }
  
  .suggestion-item:hover,
  .suggestion-item.selected {
    background: var(--bg-secondary);
  }
  
  .suggestion-icon {
    font-size: 0.875rem;
    opacity: 0.6;
  }
  
  .suggestion-text {
    flex: 1;
    font-size: 0.875rem;
  }
  
  .suggestion-text mark {
    background: var(--primary-color);
    color: white;
    padding: 0.125rem 0.25rem;
    border-radius: var(--border-radius-sm);
  }
  
  .remove-suggestion {
    width: 1.5rem;
    height: 1.5rem;
    border: none;
    background: none;
    color: var(--text-muted);
    cursor: pointer;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.25rem;
    line-height: 1;
    transition: var(--transition);
  }
  
  .remove-suggestion:hover {
    background: var(--error-color);
    color: white;
  }
  
  .hidden {
    display: none !important;
  }
  
  /* Responsive design */
  @media (max-width: 768px) {
    .search-bar {
      max-width: none;
    }
    
    .search-input-container {
      border-radius: var(--border-radius-lg);
    }
    
    .search-input {
      font-size: 1rem;
    }
  }
`;

document.head.appendChild(style);

export { SearchBar };