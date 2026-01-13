/**
 * Searchable Combobox Component
 * A dropdown with search functionality
 */

class SearchableCombobox extends HTMLElement {
  static get observedAttributes() {
    return ['placeholder', 'value', 'disabled'];
  }
  
  constructor() {
    super();
    this.options = [];
    this.filteredOptions = [];
    this.selectedValue = '';
    this.selectedText = '';
    this.isOpen = false;
    this.searchQuery = '';
    this.highlightedIndex = -1;
  }
  
  connectedCallback() {
    // Render first to create the dropdown structure
    this.render();
    this.setupEventListeners();
    
    // Wait for child elements to be fully parsed
    // Use multiple checks to ensure options are loaded
    let retryCount = 0;
    const maxRetries = 10;
    
    const tryLoadOptions = () => {
      const options = this.loadOptions();
      if (options.length > 0) {
        console.log('[SearchableCombobox] Successfully loaded', options.length, 'options');
        this.setOptions(options);
        
        // Set initial value if specified
        const selectedOption = this.querySelector('option[selected]');
        if (selectedOption) {
          this.setValue(selectedOption.value, selectedOption.textContent);
        }
      } else if (retryCount < maxRetries) {
        retryCount++;
        console.warn(`[SearchableCombobox] No options found, retrying... (${retryCount}/${maxRetries})`);
        setTimeout(tryLoadOptions, 50);
      } else {
        console.error('[SearchableCombobox] Failed to load options after', maxRetries, 'attempts');
      }
    };
    
    // Start with immediate check
    setTimeout(tryLoadOptions, 0);
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
   * Set options for the combobox
   */
  setOptions(options) {
    this.options = options.map(opt => ({
      value: typeof opt === 'string' ? opt : opt.value,
      text: typeof opt === 'string' ? opt : opt.text,
      icon: typeof opt === 'object' ? opt.icon : null
    }));
    this.filteredOptions = [...this.options];
    this.updateDropdown();
  }
  
  /**
   * Get current value
   */
  getValue() {
    return this.selectedValue;
  }
  
  /**
   * Set current value
   */
  setValue(value, text = null) {
    this.selectedValue = value;
    const option = this.options.find(opt => opt.value === value);
    this.selectedText = text || (option ? option.text : value);
    
    const input = this.querySelector('.combobox-input');
    if (input) {
      input.value = this.selectedText;
    }
    
    this.dispatchEvent(new CustomEvent('change', {
      detail: { value: this.selectedValue, text: this.selectedText }
    }));
  }
  
  /**
   * Load options from child option elements
   */
  loadOptions() {
    const optionElements = this.querySelectorAll('option');
    console.log(`[SearchableCombobox] Found ${optionElements.length} option elements`);
    
    if (optionElements.length > 0) {
      const options = Array.from(optionElements).map(opt => ({
        value: opt.value,
        text: opt.textContent,
        icon: opt.getAttribute('data-icon')
      }));
      console.log('[SearchableCombobox] Loaded options:', options);
      return options;
    }
    return [];
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    // Input events
    const input = this.querySelector('.combobox-input');
    if (input) {
      input.addEventListener('input', this.handleInput.bind(this));
      input.addEventListener('focus', this.handleFocus.bind(this));
      input.addEventListener('blur', this.handleBlur.bind(this));
      input.addEventListener('keydown', this.handleKeydown.bind(this));
    }
    
    // Toggle button
    const toggle = this.querySelector('.combobox-toggle');
    if (toggle) {
      toggle.addEventListener('click', this.handleToggle.bind(this));
    }
    
    // Dropdown events
    const dropdown = this.querySelector('.combobox-dropdown');
    if (dropdown) {
      dropdown.addEventListener('mousedown', this.handleDropdownMousedown.bind(this));
    }
    
    // Global click to close
    document.addEventListener('click', this.handleGlobalClick.bind(this));
  }
  
  /**
   * Remove event listeners
   */
  removeEventListeners() {
    document.removeEventListener('click', this.handleGlobalClick.bind(this));
  }
  
  /**
   * Handle input changes
   */
  handleInput(event) {
    this.searchQuery = event.target.value;
    this.filterOptions();
    this.open();
    this.highlightedIndex = -1;
  }
  
  /**
   * Handle input focus
   */
  handleFocus() {
    this.open();
  }
  
  /**
   * Handle input blur
   */
  handleBlur(event) {
    // Delay to allow dropdown clicks
    setTimeout(() => {
      if (!this.contains(document.activeElement)) {
        this.close();
      }
    }, 150);
  }
  
  /**
   * Handle keyboard navigation
   */
  handleKeydown(event) {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        this.highlightNext();
        break;
      case 'ArrowUp':
        event.preventDefault();
        this.highlightPrevious();
        break;
      case 'Enter':
        event.preventDefault();
        if (this.highlightedIndex >= 0) {
          this.selectOption(this.filteredOptions[this.highlightedIndex]);
        }
        break;
      case 'Escape':
        this.close();
        break;
    }
  }
  
  /**
   * Handle toggle button click
   */
  handleToggle(event) {
    event.preventDefault();
    if (this.isOpen) {
      this.close();
    } else {
      this.open();
      const input = this.querySelector('.combobox-input');
      if (input) input.focus();
    }
  }
  
  /**
   * Handle dropdown mousedown
   */
  handleDropdownMousedown(event) {
    event.preventDefault();
    const optionEl = event.target.closest('.combobox-option');
    if (optionEl) {
      const value = optionEl.getAttribute('data-value');
      const option = this.filteredOptions.find(opt => opt.value === value);
      if (option) {
        this.selectOption(option);
      }
    }
  }
  
  /**
   * Handle global clicks
   */
  handleGlobalClick(event) {
    if (!this.contains(event.target)) {
      this.close();
    }
  }
  
  /**
   * Filter options based on search query
   */
  filterOptions() {
    if (!this.searchQuery) {
      this.filteredOptions = [...this.options];
    } else {
      const query = this.searchQuery.toLowerCase();
      this.filteredOptions = this.options.filter(option =>
        option.text.toLowerCase().includes(query) ||
        option.value.toLowerCase().includes(query)
      );
    }
    this.updateDropdown();
  }
  
  /**
   * Highlight next option
   */
  highlightNext() {
    this.highlightedIndex = Math.min(
      this.highlightedIndex + 1,
      this.filteredOptions.length - 1
    );
    this.updateHighlight();
  }
  
  /**
   * Highlight previous option
   */
  highlightPrevious() {
    this.highlightedIndex = Math.max(this.highlightedIndex - 1, -1);
    this.updateHighlight();
  }
  
  /**
   * Update highlight visual
   */
  updateHighlight() {
    const options = this.querySelectorAll('.combobox-option');
    options.forEach((opt, index) => {
      opt.classList.toggle('highlighted', index === this.highlightedIndex);
    });
    
    // Scroll highlighted option into view
    if (this.highlightedIndex >= 0) {
      const highlightedOption = options[this.highlightedIndex];
      if (highlightedOption) {
        highlightedOption.scrollIntoView({ block: 'nearest' });
      }
    }
  }
  
  /**
   * Select an option
   */
  selectOption(option) {
    this.setValue(option.value, option.text);
    this.close();
    
    const input = this.querySelector('.combobox-input');
    if (input) {
      input.value = option.text;
      this.searchQuery = option.text;
    }
  }
  
  /**
   * Open dropdown
   */
  open() {
    this.isOpen = true;
    this.classList.add('open');
    this.filterOptions();
  }
  
  /**
   * Close dropdown
   */
  close() {
    this.isOpen = false;
    this.classList.remove('open');
    this.highlightedIndex = -1;
  }
  
  /**
   * Highlight search query in text
   */
  highlightSearchQuery(text, query) {
    if (!query) return this.escapeHtml(text);
    
    const escapedText = this.escapeHtml(text);
    const escapedQuery = this.escapeHtml(query);
    const regex = new RegExp(`(${escapedQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    
    return escapedText.replace(regex, '<mark class="search-highlight">$1</mark>');
  }
  
  /**
   * Update dropdown content
   */
  updateDropdown() {
    const dropdown = this.querySelector('.combobox-dropdown');
    if (!dropdown) return;
    
    if (this.filteredOptions.length === 0) {
      dropdown.innerHTML = '<div class="combobox-no-results">No results found</div>';
    } else {
      dropdown.innerHTML = this.filteredOptions.map(option => `
        <div class="combobox-option" data-value="${this.escapeHtml(option.value)}">
          ${option.icon ? `<span class="option-icon">${option.icon}</span>` : ''}
          <span class="option-text">${this.highlightSearchQuery(option.text, this.searchQuery)}</span>
        </div>
      `).join('');
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
    const placeholder = this.getAttribute('placeholder') || 'Select...';
    const disabled = this.hasAttribute('disabled');
    
    this.innerHTML = `
      <div class="combobox-container">
        <input 
          type="text" 
          class="combobox-input"
          placeholder="${placeholder}"
          ${disabled ? 'disabled' : ''}
          autocomplete="off"
        />
        <button 
          type="button" 
          class="combobox-toggle"
          ${disabled ? 'disabled' : ''}
          tabindex="-1"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6,9 12,15 18,9"></polyline>
          </svg>
        </button>
        <div class="combobox-dropdown"></div>
      </div>
    `;
  }
}

// Define the custom element
customElements.define('searchable-combobox', SearchableCombobox);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  searchable-combobox {
    position: relative;
    display: block;
    width: 100%;
  }
  
  .combobox-container {
    position: relative;
    display: flex;
    align-items: center;
  }
  
  .combobox-input {
    flex: 1;
    padding: 0.5rem 2rem 0.5rem 0.75rem;
    border: 1px solid var(--border-color, #d1d5db);
    border-radius: var(--border-radius, 6px);
    background: var(--bg-primary, white);
    color: var(--text-primary, #111827);
    font-size: 0.875rem;
    outline: none;
    transition: border-color 0.2s ease;
  }
  
  .combobox-input:focus {
    border-color: var(--primary-color, #3b82f6);
    box-shadow: 0 0 0 2px var(--primary-color-alpha, rgba(59, 130, 246, 0.1));
  }
  
  .combobox-input:disabled {
    background: var(--bg-disabled, #f9fafb);
    color: var(--text-disabled, #9ca3af);
    cursor: not-allowed;
  }
  
  .combobox-toggle {
    position: absolute;
    right: 0.5rem;
    background: none;
    border: none;
    color: var(--text-secondary, #6b7280);
    cursor: pointer;
    padding: 0.25rem;
    border-radius: 2px;
    transition: color 0.2s ease;
  }
  
  .combobox-toggle:hover:not(:disabled) {
    color: var(--text-primary, #111827);
  }
  
  .combobox-toggle:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
  
  .combobox-toggle svg {
    transition: transform 0.2s ease;
  }
  
  searchable-combobox.open .combobox-toggle svg {
    transform: rotate(180deg);
  }
  
  .combobox-dropdown {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: 1000;
    background: var(--bg-primary, white);
    border: 1px solid var(--border-color, #d1d5db);
    border-radius: var(--border-radius, 6px);
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    max-height: 200px;
    overflow-y: auto;
    display: none;
    margin-top: 2px;
  }
  
  searchable-combobox.open .combobox-dropdown {
    display: block;
  }
  
  .combobox-option {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    cursor: pointer;
    font-size: 0.875rem;
    color: var(--text-primary, #111827);
    transition: background-color 0.2s ease;
  }
  
  .combobox-option:hover,
  .combobox-option.highlighted {
    background: var(--bg-secondary, #f3f4f6);
  }
  
  .option-icon {
    font-size: 0.875rem;
  }
  
  .option-text {
    flex: 1;
  }
  
  .combobox-no-results {
    padding: 0.75rem;
    text-align: center;
    color: var(--text-muted, #9ca3af);
    font-size: 0.875rem;
    font-style: italic;
  }
  
  .search-highlight {
    background-color: #fef3c7;
    color: #92400e;
    padding: 0;
    border-radius: 2px;
  }
`;

document.head.appendChild(style);

export { SearchableCombobox };