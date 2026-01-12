/**
 * Chroma-Style Filter Panel Web Component
 * Advanced filtering with chips, date range, and more
 * Requirements: 6.4
 */

class FilterPanel extends HTMLElement {
  static get observedAttributes() {
    return ['category', 'project', 'date-from', 'date-to', 'source'];
  }
  
  constructor() {
    super();
    this.filters = {
      category: '',
      project: '',
      dateFrom: '',
      dateTo: '',
      source: '',
      tags: []
    };
    this.isExpanded = false;
    this.availableSources = ['mcp', 'web', 'api', 'manual'];
    this.availableTags = [];
  }
  
  connectedCallback() {
    this.loadFiltersFromAttributes();
    this.render();
    this.setupEventListeners();
    this.loadAvailableTags();
  }
  
  attributeChangedCallback(name, oldValue, newValue) {
    if (oldValue !== newValue) {
      this.loadFiltersFromAttributes();
      if (this.isConnected) {
        this.updateFilterDisplay();
      }
    }
  }
  
  loadFiltersFromAttributes() {
    this.filters.category = this.getAttribute('category') || '';
    this.filters.project = this.getAttribute('project') || '';
    this.filters.dateFrom = this.getAttribute('date-from') || '';
    this.filters.dateTo = this.getAttribute('date-to') || '';
    this.filters.source = this.getAttribute('source') || '';
  }
  
  async loadAvailableTags() {
    try {
      if (window.app && window.app.apiClient) {
        // In a real implementation, fetch available tags from API
        this.availableTags = ['architecture', 'database', 'frontend', 'backend', 'testing', 'deployment'];
      }
    } catch (error) {
      console.warn('Failed to load tags:', error);
    }
  }
  
  setupEventListeners() {
    // Category chips
    this.addEventListener('click', (e) => {
      const chip = e.target.closest('.filter-chip');
      if (chip) {
        const filterType = chip.getAttribute('data-filter-type');
        const filterValue = chip.getAttribute('data-filter-value');
        this.handleChipClick(filterType, filterValue, chip);
      }
      
      // Toggle advanced filters
      if (e.target.closest('.toggle-advanced-btn')) {
        this.toggleAdvancedFilters();
      }
      
      // Clear all filters
      if (e.target.closest('.clear-filters-btn')) {
        this.clearAllFilters();
      }
      
      // Apply filters button
      if (e.target.closest('.apply-filters-btn')) {
        this.applyFilters();
      }
      
      // Remove active filter tag
      if (e.target.closest('.active-filter-remove')) {
        const tag = e.target.closest('.active-filter-tag');
        const filterType = tag.getAttribute('data-filter-type');
        this.removeFilter(filterType);
      }
    });
    
    // Input changes
    this.addEventListener('change', (e) => {
      const target = e.target;
      
      if (target.classList.contains('project-filter-input')) {
        this.filters.project = target.value;
      }
      
      if (target.classList.contains('source-filter-select')) {
        this.filters.source = target.value;
      }
      
      if (target.classList.contains('date-from-input')) {
        this.filters.dateFrom = target.value;
      }
      
      if (target.classList.contains('date-to-input')) {
        this.filters.dateTo = target.value;
      }
    });
    
    // Enter key on inputs
    this.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && (
        e.target.classList.contains('project-filter-input') ||
        e.target.classList.contains('tag-filter-input')
      )) {
        this.applyFilters();
      }
    });
  }
  
  handleChipClick(filterType, filterValue, chip) {
    if (filterType === 'category') {
      const isActive = chip.classList.contains('active');
      
      // Deselect all category chips
      this.querySelectorAll('.filter-chip[data-filter-type="category"]').forEach(c => {
        c.classList.remove('active');
      });
      
      // Toggle the clicked chip
      if (!isActive) {
        chip.classList.add('active');
        this.filters.category = filterValue;
      } else {
        this.filters.category = '';
      }
      
      this.emitFilterChange();
    }
  }
  
  toggleAdvancedFilters() {
    this.isExpanded = !this.isExpanded;
    const advancedSection = this.querySelector('.advanced-filters');
    const toggleBtn = this.querySelector('.toggle-advanced-btn');
    
    if (advancedSection) {
      advancedSection.classList.toggle('expanded', this.isExpanded);
    }
    
    if (toggleBtn) {
      toggleBtn.classList.toggle('expanded', this.isExpanded);
      toggleBtn.querySelector('.toggle-text').textContent = this.isExpanded ? '간단히 보기' : '고급 필터';
    }
  }
  
  clearAllFilters() {
    this.filters = {
      category: '',
      project: '',
      dateFrom: '',
      dateTo: '',
      source: '',
      tags: []
    };
    
    // Reset UI
    this.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
    this.querySelectorAll('input, select').forEach(el => {
      if (el.type === 'text' || el.type === 'date') el.value = '';
      if (el.tagName === 'SELECT') el.selectedIndex = 0;
    });
    
    this.updateActiveFiltersDisplay();
    this.emitFilterChange();
  }
  
  removeFilter(filterType) {
    switch (filterType) {
      case 'category':
        this.filters.category = '';
        this.querySelectorAll('.filter-chip[data-filter-type="category"]').forEach(c => {
          c.classList.remove('active');
        });
        break;
      case 'project':
        this.filters.project = '';
        const projectInput = this.querySelector('.project-filter-input');
        if (projectInput) projectInput.value = '';
        break;
      case 'source':
        this.filters.source = '';
        const sourceSelect = this.querySelector('.source-filter-select');
        if (sourceSelect) sourceSelect.selectedIndex = 0;
        break;
      case 'date':
        this.filters.dateFrom = '';
        this.filters.dateTo = '';
        const dateFromInput = this.querySelector('.date-from-input');
        const dateToInput = this.querySelector('.date-to-input');
        if (dateFromInput) dateFromInput.value = '';
        if (dateToInput) dateToInput.value = '';
        break;
    }
    
    this.updateActiveFiltersDisplay();
    this.emitFilterChange();
  }
  
  applyFilters() {
    this.updateActiveFiltersDisplay();
    this.emitFilterChange();
  }
  
  updateActiveFiltersDisplay() {
    const container = this.querySelector('.active-filters');
    if (!container) return;
    
    const activeFilters = [];
    
    if (this.filters.category) {
      activeFilters.push({
        type: 'category',
        label: `카테고리: ${this.filters.category}`,
        value: this.filters.category
      });
    }
    
    if (this.filters.project) {
      activeFilters.push({
        type: 'project',
        label: `프로젝트: ${this.filters.project}`,
        value: this.filters.project
      });
    }
    
    if (this.filters.source) {
      activeFilters.push({
        type: 'source',
        label: `소스: ${this.filters.source}`,
        value: this.filters.source
      });
    }
    
    if (this.filters.dateFrom || this.filters.dateTo) {
      const dateLabel = this.filters.dateFrom && this.filters.dateTo
        ? `${this.filters.dateFrom} ~ ${this.filters.dateTo}`
        : this.filters.dateFrom
          ? `${this.filters.dateFrom} 이후`
          : `${this.filters.dateTo} 이전`;
      activeFilters.push({
        type: 'date',
        label: `기간: ${dateLabel}`,
        value: `${this.filters.dateFrom}-${this.filters.dateTo}`
      });
    }
    
    if (activeFilters.length === 0) {
      container.innerHTML = '';
      container.style.display = 'none';
      return;
    }
    
    container.style.display = 'flex';
    container.innerHTML = `
      <span class="active-filters-label">활성 필터:</span>
      ${activeFilters.map(f => `
        <span class="active-filter-tag" data-filter-type="${f.type}">
          ${f.label}
          <button class="active-filter-remove" type="button" aria-label="Remove filter">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </span>
      `).join('')}
      <button class="clear-filters-btn" type="button">모두 지우기</button>
    `;
  }
  
  updateFilterDisplay() {
    // Update category chips
    this.querySelectorAll('.filter-chip[data-filter-type="category"]').forEach(chip => {
      const value = chip.getAttribute('data-filter-value');
      chip.classList.toggle('active', value === this.filters.category);
    });
    
    // Update inputs
    const projectInput = this.querySelector('.project-filter-input');
    if (projectInput) projectInput.value = this.filters.project;
    
    const sourceSelect = this.querySelector('.source-filter-select');
    if (sourceSelect) sourceSelect.value = this.filters.source;
    
    const dateFromInput = this.querySelector('.date-from-input');
    if (dateFromInput) dateFromInput.value = this.filters.dateFrom;
    
    const dateToInput = this.querySelector('.date-to-input');
    if (dateToInput) dateToInput.value = this.filters.dateTo;
    
    this.updateActiveFiltersDisplay();
  }
  
  emitFilterChange() {
    this.dispatchEvent(new CustomEvent('filter-change', {
      detail: { ...this.filters },
      bubbles: true
    }));
  }
  
  getFilters() {
    return { ...this.filters };
  }
  
  setFilters(filters) {
    this.filters = { ...this.filters, ...filters };
    this.updateFilterDisplay();
  }
  
  render() {
    this.className = 'filter-panel chroma-filter-panel';
    
    this.innerHTML = `
      <div class="filter-panel-header">
        <div class="quick-filters">
          <span class="filter-label">카테고리</span>
          <div class="filter-chips-row">
            <button class="filter-chip ${!this.filters.category ? 'active' : ''}" data-filter-type="category" data-filter-value="">
              전체
            </button>
            <button class="filter-chip ${this.filters.category === 'task' ? 'active' : ''}" data-filter-type="category" data-filter-value="task">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="m9 12 2 2 4-4"/></svg>
              Task
            </button>
            <button class="filter-chip ${this.filters.category === 'bug' ? 'active' : ''}" data-filter-type="category" data-filter-value="bug">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
              Bug
            </button>
            <button class="filter-chip ${this.filters.category === 'idea' ? 'active' : ''}" data-filter-type="category" data-filter-value="idea">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v1"/><path d="M12 21v1"/></svg>
              Idea
            </button>
            <button class="filter-chip ${this.filters.category === 'decision' ? 'active' : ''}" data-filter-type="category" data-filter-value="decision">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="m9 12 2 2 4-4"/></svg>
              Decision
            </button>
            <button class="filter-chip ${this.filters.category === 'code_snippet' ? 'active' : ''}" data-filter-type="category" data-filter-value="code_snippet">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16,18 22,12 16,6"/><polyline points="8,6 2,12 8,18"/></svg>
              Code
            </button>
          </div>
        </div>
        
        <button class="toggle-advanced-btn" type="button">
          <span class="toggle-text">고급 필터</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6,9 12,15 18,9"/>
          </svg>
        </button>
      </div>
      
      <div class="advanced-filters ${this.isExpanded ? 'expanded' : ''}">
        <div class="filter-row">
          <div class="filter-group">
            <label class="filter-group-label">프로젝트</label>
            <input 
              type="text" 
              class="project-filter-input filter-input" 
              placeholder="프로젝트 ID..."
              value="${this.filters.project}"
            >
          </div>
          
          <div class="filter-group">
            <label class="filter-group-label">소스</label>
            <select class="source-filter-select filter-select">
              <option value="">모든 소스</option>
              ${this.availableSources.map(s => `
                <option value="${s}" ${this.filters.source === s ? 'selected' : ''}>${s}</option>
              `).join('')}
            </select>
          </div>
        </div>
        
        <div class="filter-row">
          <div class="filter-group">
            <label class="filter-group-label">기간</label>
            <div class="date-range-inputs">
              <input 
                type="date" 
                class="date-from-input filter-input" 
                value="${this.filters.dateFrom}"
                placeholder="시작일"
              >
              <span class="date-separator">~</span>
              <input 
                type="date" 
                class="date-to-input filter-input" 
                value="${this.filters.dateTo}"
                placeholder="종료일"
              >
            </div>
          </div>
        </div>
        
        <div class="filter-actions">
          <button class="apply-filters-btn" type="button">필터 적용</button>
        </div>
      </div>
      
      <div class="active-filters" style="display: none;"></div>
    `;
    
    this.updateActiveFiltersDisplay();
  }
}

customElements.define('filter-panel', FilterPanel);

export { FilterPanel };
