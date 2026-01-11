/**
 * Filter Panel Web Component
 * Provides filtering options for memories
 */

class FilterPanel extends HTMLElement {
  static get observedAttributes() {
    return ['collapsed', 'filters'];
  }
  
  constructor() {
    super();
    this.filters = {
      projects: [],
      categories: [],
      dateRange: { start: '', end: '' },
      tags: [],
      source: ''
    };
    this.availableOptions = {
      projects: [],
      categories: ['task', 'bug', 'idea', 'decision', 'incident', 'code_snippet'],
      tags: [],
      sources: []
    };
    this.isCollapsed = false;
  }
  
  connectedCallback() {
    this.render();
    this.setupEventListeners();
    this.loadAvailableOptions();
  }
  
  disconnectedCallback() {
    this.removeEventListeners();
  }
  
  attributeChangedCallback(name, oldValue, newValue) {
    if (oldValue !== newValue) {
      if (name === 'collapsed') {
        this.isCollapsed = newValue !== null;
      } else if (name === 'filters') {
        try {
          this.filters = JSON.parse(newValue);
        } catch {
          // Keep current filters if parsing fails
        }
      }
      this.render();
    }
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    this.addEventListener('change', this.handleFilterChange.bind(this));
    this.addEventListener('click', this.handleClick.bind(this));
  }
  
  /**
   * Remove event listeners
   */
  removeEventListeners() {
    this.removeEventListener('change', this.handleFilterChange);
    this.removeEventListener('click', this.handleClick);
  }
  
  /**
   * Handle filter changes
   */
  handleFilterChange(event) {
    const target = event.target;
    const filterType = target.getAttribute('data-filter-type');
    const filterValue = target.value;
    
    if (!filterType) return;
    
    switch (filterType) {
      case 'project':
        this.updateMultiSelectFilter('projects', filterValue, target.checked);
        break;
        
      case 'category':
        this.updateMultiSelectFilter('categories', filterValue, target.checked);
        break;
        
      case 'tag':
        this.updateMultiSelectFilter('tags', filterValue, target.checked);
        break;
        
      case 'source':
        this.filters.source = filterValue;
        break;
        
      case 'date-start':
        this.filters.dateRange.start = filterValue;
        break;
        
      case 'date-end':
        this.filters.dateRange.end = filterValue;
        break;
    }
    
    this.emitFilterChange();
  }
  
  /**
   * Handle click events
   */
  handleClick(event) {
    const target = event.target;
    
    if (target.classList.contains('toggle-btn')) {
      this.toggleCollapsed();
    } else if (target.classList.contains('clear-filters-btn')) {
      this.clearAllFilters();
    } else if (target.classList.contains('clear-filter-btn')) {
      const filterType = target.getAttribute('data-filter-type');
      this.clearFilter(filterType);
    }
  }
  
  /**
   * Update multi-select filter
   */
  updateMultiSelectFilter(filterType, value, checked) {
    if (checked) {
      if (!this.filters[filterType].includes(value)) {
        this.filters[filterType].push(value);
      }
    } else {
      this.filters[filterType] = this.filters[filterType].filter(item => item !== value);
    }
  }
  
  /**
   * Toggle collapsed state
   */
  toggleCollapsed() {
    this.isCollapsed = !this.isCollapsed;
    if (this.isCollapsed) {
      this.setAttribute('collapsed', '');
    } else {
      this.removeAttribute('collapsed');
    }
    this.render();
  }
  
  /**
   * Clear all filters
   */
  clearAllFilters() {
    this.filters = {
      projects: [],
      categories: [],
      dateRange: { start: '', end: '' },
      tags: [],
      source: ''
    };
    this.render();
    this.emitFilterChange();
  }
  
  /**
   * Clear specific filter
   */
  clearFilter(filterType) {
    switch (filterType) {
      case 'projects':
      case 'categories':
      case 'tags':
        this.filters[filterType] = [];
        break;
      case 'dateRange':
        this.filters.dateRange = { start: '', end: '' };
        break;
      case 'source':
        this.filters.source = '';
        break;
    }
    this.render();
    this.emitFilterChange();
  }
  
  /**
   * Emit filter change event
   */
  emitFilterChange() {
    this.setAttribute('filters', JSON.stringify(this.filters));
    
    this.dispatchEvent(new CustomEvent('filters-change', {
      detail: { filters: this.filters },
      bubbles: true
    }));
  }
  
  /**
   * Load available filter options
   */
  async loadAvailableOptions() {
    try {
      // In a real implementation, this would fetch from the API
      // For now, we'll use mock data or get from app state
      if (window.app && window.app.apiClient) {
        const stats = await window.app.apiClient.getStats();
        
        // Extract available options from stats
        if (stats.by_project) {
          this.availableOptions.projects = Object.keys(stats.by_project);
        }
        
        if (stats.by_category) {
          this.availableOptions.categories = Object.keys(stats.by_category);
        }
        
        // For tags and sources, we might need separate API calls
        // or include them in the stats response
      }
      
      this.render();
    } catch (error) {
      console.warn('Failed to load filter options:', error);
    }
  }
  
  /**
   * Get category icon
   */
  getCategoryIcon(category) {
    const icons = {
      task: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><path d="m9 9 2 2 4-4"/></svg>',
      bug: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m8 2 1.88 1.88"/><path d="M14.12 3.88 16 2"/><path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1"/><path d="m12 20-5-6 6.5-1 3.5 7Z"/><path d="m8.5 8.5-1 1"/><path d="m16.5 8.5 1 1"/></svg>',
      idea: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16,17 21,12 16,7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>',
      decision: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="7.5,4.21 12,6.81 16.5,4.21"/><polyline points="7.5,19.79 7.5,14.6 3,12"/><polyline points="21,12 16.5,14.6 16.5,19.79"/><polyline points="3.27,6.96 12,12.01 20.73,6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>',
      incident: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      code_snippet: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16,18 22,12 16,6"/><polyline points="8,6 2,12 8,18"/></svg>'
    };
    return icons[category] || '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10,9 9,9 8,9"/></svg>';
  }
  
  /**
   * Get active filter count
   */
  getActiveFilterCount() {
    let count = 0;
    count += this.filters.projects.length;
    count += this.filters.categories.length;
    count += this.filters.tags.length;
    if (this.filters.source) count++;
    if (this.filters.dateRange.start || this.filters.dateRange.end) count++;
    return count;
  }
  
  /**
   * Render the component
   */
  render() {
    const activeCount = this.getActiveFilterCount();
    
    this.className = `filter-panel ${this.isCollapsed ? 'collapsed' : ''}`;
    
    this.innerHTML = `
      <div class="filter-header">
        <div class="filter-title">
          <span class="filter-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="22,3 2,3 10,12.46 10,19 14,21 14,12.46 22,3"/></svg></span>
          <span>Filters</span>
          ${activeCount > 0 ? `<span class="active-count">${activeCount}</span>` : ''}
        </div>
        <div class="filter-actions">
          ${activeCount > 0 ? '<button class="clear-filters-btn" title="Clear all filters">Clear All</button>' : ''}
          <button class="toggle-btn" title="${this.isCollapsed ? 'Expand filters' : 'Collapse filters'}">
            ${this.isCollapsed ? '▼' : '▲'}
          </button>
        </div>
      </div>
      
      <div class="filter-content ${this.isCollapsed ? 'hidden' : ''}">
        <!-- Project Filter -->
        <div class="filter-section">
          <div class="filter-section-header">
            <h4>Projects</h4>
            ${this.filters.projects.length > 0 ? 
              '<button class="clear-filter-btn" data-filter-type="projects" title="Clear project filters">×</button>' 
              : ''
            }
          </div>
          <div class="filter-options">
            ${this.availableOptions.projects.length > 0 ? 
              this.availableOptions.projects.map(project => `
                <label class="filter-option">
                  <input 
                    type="checkbox" 
                    data-filter-type="project" 
                    value="${project}"
                    ${this.filters.projects.includes(project) ? 'checked' : ''}
                  >
                  <span class="checkmark"></span>
                  <span class="option-label">${project}</span>
                </label>
              `).join('') 
              : '<p class="no-options">No projects found</p>'
            }
          </div>
        </div>
        
        <!-- Category Filter -->
        <div class="filter-section">
          <div class="filter-section-header">
            <h4>Categories</h4>
            ${this.filters.categories.length > 0 ? 
              '<button class="clear-filter-btn" data-filter-type="categories" title="Clear category filters">×</button>' 
              : ''
            }
          </div>
          <div class="filter-options">
            ${this.availableOptions.categories.map(category => `
              <label class="filter-option">
                <input 
                  type="checkbox" 
                  data-filter-type="category" 
                  value="${category}"
                  ${this.filters.categories.includes(category) ? 'checked' : ''}
                >
                <span class="checkmark"></span>
                <span class="option-label">
                  ${this.getCategoryIcon(category)} ${category}
                </span>
              </label>
            `).join('')}
          </div>
        </div>
        
        <!-- Date Range Filter -->
        <div class="filter-section">
          <div class="filter-section-header">
            <h4>Date Range</h4>
            ${(this.filters.dateRange.start || this.filters.dateRange.end) ? 
              '<button class="clear-filter-btn" data-filter-type="dateRange" title="Clear date filters">×</button>' 
              : ''
            }
          </div>
          <div class="date-range-inputs">
            <div class="date-input-group">
              <label for="date-start">From:</label>
              <input 
                type="date" 
                id="date-start"
                data-filter-type="date-start" 
                value="${this.filters.dateRange.start}"
              >
            </div>
            <div class="date-input-group">
              <label for="date-end">To:</label>
              <input 
                type="date" 
                id="date-end"
                data-filter-type="date-end" 
                value="${this.filters.dateRange.end}"
              >
            </div>
          </div>
        </div>
        
        <!-- Tags Filter -->
        <div class="filter-section">
          <div class="filter-section-header">
            <h4>Tags</h4>
            ${this.filters.tags.length > 0 ? 
              '<button class="clear-filter-btn" data-filter-type="tags" title="Clear tag filters">×</button>' 
              : ''
            }
          </div>
          <div class="filter-options">
            ${this.availableOptions.tags.length > 0 ? 
              this.availableOptions.tags.map(tag => `
                <label class="filter-option">
                  <input 
                    type="checkbox" 
                    data-filter-type="tag" 
                    value="${tag}"
                    ${this.filters.tags.includes(tag) ? 'checked' : ''}
                  >
                  <span class="checkmark"></span>
                  <span class="option-label">#${tag}</span>
                </label>
              `).join('') 
              : '<p class="no-options">No tags found</p>'
            }
          </div>
        </div>
        
        <!-- Source Filter -->
        <div class="filter-section">
          <div class="filter-section-header">
            <h4>Source</h4>
            ${this.filters.source ? 
              '<button class="clear-filter-btn" data-filter-type="source" title="Clear source filter">×</button>' 
              : ''
            }
          </div>
          <div class="source-select">
            <select data-filter-type="source" value="${this.filters.source}">
              <option value="">All sources</option>
              ${this.availableOptions.sources.map(source => `
                <option value="${source}" ${this.filters.source === source ? 'selected' : ''}>
                  ${source}
                </option>
              `).join('')}
            </select>
          </div>
        </div>
      </div>
    `;
  }
  
  /**
   * Get current filters
   */
  getFilters() {
    return { ...this.filters };
  }
  
  /**
   * Set filters
   */
  setFilters(filters) {
    this.filters = { ...filters };
    this.render();
  }
  
  /**
   * Reset filters
   */
  reset() {
    this.clearAllFilters();
  }
}

// Define the custom element
customElements.define('filter-panel', FilterPanel);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .filter-panel {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    overflow: hidden;
    transition: var(--transition);
  }
  
  .filter-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
    cursor: pointer;
  }
  
  .filter-title {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-weight: 600;
    color: var(--text-primary);
  }
  
  .filter-icon {
    font-size: 1.125rem;
    display: inline-flex;
    align-items: center;
  }
  
  .filter-icon svg {
    width: 16px;
    height: 16px;
    stroke: currentColor;
  }
  
  .active-count {
    background: var(--primary-color);
    color: white;
    padding: 0.125rem 0.5rem;
    border-radius: var(--border-radius-full);
    font-size: 0.75rem;
    font-weight: 600;
    min-width: 1.25rem;
    text-align: center;
  }
  
  .filter-actions {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  
  .clear-filters-btn {
    background: none;
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
    font-size: 0.75rem;
    cursor: pointer;
    transition: var(--transition);
  }
  
  .clear-filters-btn:hover {
    background: var(--error-color);
    color: white;
    border-color: var(--error-color);
  }
  
  .toggle-btn {
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: 1rem;
    cursor: pointer;
    padding: 0.25rem;
    border-radius: var(--border-radius-sm);
    transition: var(--transition);
  }
  
  .toggle-btn:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }
  
  .filter-content {
    padding: 1rem;
    max-height: 600px;
    overflow-y: auto;
  }
  
  .filter-content.hidden {
    display: none;
  }
  
  .filter-section {
    margin-bottom: 1.5rem;
  }
  
  .filter-section:last-child {
    margin-bottom: 0;
  }
  
  .filter-section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.75rem;
  }
  
  .filter-section-header h4 {
    margin: 0;
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--text-primary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  
  .clear-filter-btn {
    background: none;
    border: none;
    color: var(--text-muted);
    font-size: 1.25rem;
    cursor: pointer;
    padding: 0;
    width: 1.5rem;
    height: 1.5rem;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: var(--transition);
  }
  
  .clear-filter-btn:hover {
    background: var(--error-color);
    color: white;
  }
  
  .filter-options {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  
  .filter-option {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    cursor: pointer;
    padding: 0.5rem;
    border-radius: var(--border-radius-sm);
    transition: var(--transition);
  }
  
  .filter-option:hover {
    background: var(--bg-secondary);
  }
  
  .filter-option input[type="checkbox"] {
    display: none;
  }
  
  .checkmark {
    width: 1rem;
    height: 1rem;
    border: 2px solid var(--border-color);
    border-radius: var(--border-radius-sm);
    position: relative;
    transition: var(--transition);
    flex-shrink: 0;
  }
  
  .filter-option input[type="checkbox"]:checked + .checkmark {
    background: var(--primary-color);
    border-color: var(--primary-color);
  }
  
  .filter-option input[type="checkbox"]:checked + .checkmark::after {
    content: '✓';
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    color: white;
    font-size: 0.75rem;
    font-weight: bold;
  }
  
  .option-label {
    font-size: 0.875rem;
    color: var(--text-primary);
    flex: 1;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  
  .option-label svg {
    width: 16px;
    height: 16px;
    stroke: currentColor;
    flex-shrink: 0;
  }
  
  .no-options {
    color: var(--text-muted);
    font-size: 0.875rem;
    font-style: italic;
    margin: 0;
    padding: 0.5rem;
    text-align: center;
  }
  
  .date-range-inputs {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }
  
  .date-input-group {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  
  .date-input-group label {
    font-size: 0.75rem;
    color: var(--text-secondary);
    font-weight: 500;
  }
  
  .date-input-group input[type="date"] {
    padding: 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.875rem;
    transition: var(--transition);
  }
  
  .date-input-group input[type="date"]:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
  }
  
  .source-select select {
    width: 100%;
    padding: 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.875rem;
    cursor: pointer;
    transition: var(--transition);
  }
  
  .source-select select:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
  }
  
  /* Collapsed state */
  .filter-panel.collapsed .filter-header {
    border-bottom: none;
  }
  
  /* Responsive design */
  @media (max-width: 768px) {
    .filter-panel {
      margin-bottom: 1rem;
    }
    
    .filter-header {
      padding: 0.75rem;
    }
    
    .filter-content {
      padding: 0.75rem;
      max-height: 400px;
    }
    
    .date-range-inputs {
      gap: 0.5rem;
    }
  }
`;

document.head.appendChild(style);

export { FilterPanel };