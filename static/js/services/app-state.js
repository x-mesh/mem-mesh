/**
 * Application State Management
 * Centralized state management with event-driven updates
 */

export class AppState {
  constructor() {
    this.state = {
      currentPage: 'dashboard',
      searchQuery: '',
      searchFilters: {
        project_id: null,
        category: null,
        date_range: null,
        recency_weight: 0.0
      },
      selectedMemory: null,
      theme: this.getStoredTheme(),
      sidebarOpen: false,
      loading: false,
      error: null,
      user: null,
      recentSearches: this.getStoredRecentSearches(),
      favorites: this.getStoredFavorites()
    };
    
    this.listeners = new Map();
    this.history = [];
    this.maxHistorySize = 50;
    
    // Initialize
    this.init();
  }
  
  /**
   * Initialize state
   */
  init() {
    // Apply theme
    this.applyTheme(this.state.theme);
    
    // Listen for storage changes (for multi-tab sync)
    window.addEventListener('storage', this.handleStorageChange.bind(this));
  }
  
  /**
   * Subscribe to state changes
   */
  subscribe(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, []);
    }
    this.listeners.get(event).push(callback);
    
    // Return unsubscribe function
    return () => {
      const callbacks = this.listeners.get(event);
      if (callbacks) {
        const index = callbacks.indexOf(callback);
        if (index > -1) {
          callbacks.splice(index, 1);
        }
      }
    };
  }
  
  /**
   * Emit state change event
   */
  emit(event, data) {
    if (this.listeners.has(event)) {
      this.listeners.get(event).forEach(callback => {
        try {
          callback(data, this.state);
        } catch (error) {
          console.error('State listener error:', error);
        }
      });
    }
  }
  
  /**
   * Update state
   */
  setState(updates, emit = true) {
    const prevState = { ...this.state };
    
    // Apply updates
    if (typeof updates === 'function') {
      this.state = { ...this.state, ...updates(this.state) };
    } else {
      this.state = { ...this.state, ...updates };
    }
    
    // Add to history
    this.addToHistory(prevState);
    
    // Emit change event
    if (emit) {
      this.emit('stateChange', { prevState, newState: this.state });
    }
  }
  
  /**
   * Get current state
   */
  getState() {
    return { ...this.state };
  }
  
  /**
   * Add state to history
   */
  addToHistory(state) {
    this.history.push({
      state: { ...state },
      timestamp: Date.now()
    });
    
    // Limit history size
    if (this.history.length > this.maxHistorySize) {
      this.history.shift();
    }
  }
  
  /**
   * Handle storage changes (multi-tab sync)
   */
  handleStorageChange(event) {
    if (event.key === 'mem-mesh-theme') {
      const newTheme = event.newValue;
      if (newTheme && newTheme !== this.state.theme) {
        this.setTheme(newTheme, false); // Don't store again
      }
    }
  }
  
  /**
   * Page state methods
   */
  setCurrentPage(page) {
    this.setState({ currentPage: page });
    this.emit('pageChange', page);
  }
  
  getCurrentPage() {
    return this.state.currentPage;
  }
  
  /**
   * Search state methods
   */
  setSearchQuery(query) {
    this.setState({ searchQuery: query });
    this.emit('searchQueryChange', query);
    
    // Add to recent searches if not empty
    if (query.trim()) {
      this.addRecentSearch(query.trim());
    }
  }
  
  setSearchFilters(filters) {
    this.setState({
      searchFilters: { ...this.state.searchFilters, ...filters }
    });
    this.emit('searchFiltersChange', this.state.searchFilters);
  }
  
  clearSearchFilters() {
    this.setState({
      searchFilters: {
        project_id: null,
        category: null,
        date_range: null,
        recency_weight: 0.0
      }
    });
    this.emit('searchFiltersChange', this.state.searchFilters);
  }
  
  getSearchState() {
    return {
      query: this.state.searchQuery,
      filters: this.state.searchFilters
    };
  }
  
  /**
   * Memory state methods
   */
  setSelectedMemory(memory) {
    this.setState({ selectedMemory: memory });
    this.emit('memorySelect', memory);
  }
  
  getSelectedMemory() {
    return this.state.selectedMemory;
  }
  
  /**
   * Theme methods
   */
  setTheme(theme, store = true) {
    this.setState({ theme });
    this.applyTheme(theme);
    
    if (store) {
      localStorage.setItem('mem-mesh-theme', theme);
    }
    
    this.emit('themeChange', theme);
  }
  
  toggleTheme() {
    const newTheme = this.state.theme === 'light' ? 'dark' : 'light';
    this.setTheme(newTheme);
  }
  
  getTheme() {
    return this.state.theme;
  }
  
  applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    
    // Update theme toggle icon
    const themeIcon = document.querySelector('#theme-toggle .theme-icon');
    if (themeIcon) {
      themeIcon.textContent = theme === 'light' ? '🌙' : '☀️';
    }
  }
  
  getStoredTheme() {
    const stored = localStorage.getItem('mem-mesh-theme');
    if (stored) return stored;
    
    // Detect system preference
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark';
    }
    
    return 'light';
  }
  
  /**
   * UI state methods
   */
  setSidebarOpen(open) {
    this.setState({ sidebarOpen: open });
    this.emit('sidebarToggle', open);
  }
  
  toggleSidebar() {
    this.setSidebarOpen(!this.state.sidebarOpen);
  }
  
  setLoading(loading) {
    this.setState({ loading });
    this.emit('loadingChange', loading);
  }
  
  setError(error) {
    this.setState({ error });
    this.emit('errorChange', error);
  }
  
  clearError() {
    this.setError(null);
  }
  
  /**
   * Recent searches methods
   */
  addRecentSearch(query) {
    const recentSearches = [...this.state.recentSearches];
    
    // Remove if already exists
    const existingIndex = recentSearches.indexOf(query);
    if (existingIndex > -1) {
      recentSearches.splice(existingIndex, 1);
    }
    
    // Add to beginning
    recentSearches.unshift(query);
    
    // Limit to 10 recent searches
    if (recentSearches.length > 10) {
      recentSearches.pop();
    }
    
    this.setState({ recentSearches });
    localStorage.setItem('mem-mesh-recent-searches', JSON.stringify(recentSearches));
  }
  
  clearRecentSearches() {
    this.setState({ recentSearches: [] });
    localStorage.removeItem('mem-mesh-recent-searches');
  }
  
  getStoredRecentSearches() {
    try {
      const stored = localStorage.getItem('mem-mesh-recent-searches');
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  }
  
  /**
   * Favorites methods
   */
  addFavorite(memoryId) {
    const favorites = [...this.state.favorites];
    if (!favorites.includes(memoryId)) {
      favorites.push(memoryId);
      this.setState({ favorites });
      localStorage.setItem('mem-mesh-favorites', JSON.stringify(favorites));
    }
  }
  
  removeFavorite(memoryId) {
    const favorites = this.state.favorites.filter(id => id !== memoryId);
    this.setState({ favorites });
    localStorage.setItem('mem-mesh-favorites', JSON.stringify(favorites));
  }
  
  isFavorite(memoryId) {
    return this.state.favorites.includes(memoryId);
  }
  
  getStoredFavorites() {
    try {
      const stored = localStorage.getItem('mem-mesh-favorites');
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  }
  
  /**
   * Debug methods
   */
  getHistory() {
    return [...this.history];
  }
  
  exportState() {
    return {
      state: this.getState(),
      history: this.getHistory(),
      timestamp: Date.now()
    };
  }
}