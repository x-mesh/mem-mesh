# Design Document

## Overview

mem-mesh Web UI는 기존 mem-mesh FastAPI 백엔드를 활용하여 웹 브라우저에서 메모리를 시각적으로 관리할 수 있는 단일 페이지 애플리케이션(SPA)입니다. 가벼운 프론트엔드 기술 스택을 사용하여 빠른 로딩과 반응성을 제공하며, 기존 REST API를 그대로 활용하여 백엔드 변경을 최소화합니다.

## Architecture

### High-Level Architecture

```
┌─────────────────┐    HTTP/REST    ┌─────────────────┐
│   Web Browser   │ ◄──────────────► │  FastAPI Server │
│                 │                  │                 │
│  ┌───────────┐  │                  │  ┌───────────┐  │
│  │ HTML/CSS  │  │                  │  │ REST APIs │  │
│  │ JavaScript│  │                  │  │ Static    │  │
│  │ Web Comp. │  │                  │  │ Files     │  │
│  └───────────┘  │                  │  └───────────┘  │
└─────────────────┘                  └─────────────────┘
                                               │
                                               ▼
                                     ┌─────────────────┐
                                     │ mem-mesh Core   │
                                     │ Services        │
                                     │ (Memory, Search,│
                                     │ Context, Stats) │
                                     └─────────────────┘
```

### Frontend Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Web UI Layer                         │
├─────────────────────────────────────────────────────────┤
│  Pages/Views                                            │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐      │
│  │ Dashboard   │ │ Search      │ │ Memory      │      │
│  │ Page        │ │ Page        │ │ Detail      │ ...  │
│  └─────────────┘ └─────────────┘ └─────────────┘      │
├─────────────────────────────────────────────────────────┤
│  Web Components                                         │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐      │
│  │ memory-card │ │ search-bar  │ │ context-    │      │
│  │             │ │             │ │ timeline    │ ...  │
│  └─────────────┘ └─────────────┘ └─────────────┘      │
├─────────────────────────────────────────────────────────┤
│  Services Layer                                         │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐      │
│  │ API Client  │ │ Cache       │ │ Router      │      │
│  │             │ │ Manager     │ │             │ ...  │
│  └─────────────┘ └─────────────┘ └─────────────┘      │
├─────────────────────────────────────────────────────────┤
│  Utilities                                              │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐      │
│  │ DOM Utils   │ │ Date Utils  │ │ Chart       │      │
│  │             │ │             │ │ Utils       │ ...  │
│  └─────────────┘ └─────────────┘ └─────────────┘      │
└─────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### 1. Static File Serving

FastAPI 서버에 정적 파일 서빙 기능을 추가합니다:

```python
# src/main.py에 추가
from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_web_ui():
    return FileResponse("static/index.html")
```

### 2. Core Web Components

#### 2.1 MemoryCard Component
```javascript
class MemoryCard extends HTMLElement {
  static get observedAttributes() {
    return ['memory-id', 'content', 'project', 'category', 'created-at', 'similarity-score'];
  }
  
  connectedCallback() {
    this.render();
    this.addEventListener('click', this.handleClick);
  }
  
  render() {
    // Render memory card with content preview, metadata, and actions
  }
  
  handleClick() {
    // Navigate to memory detail page
  }
}
```

#### 2.2 SearchBar Component
```javascript
class SearchBar extends HTMLElement {
  constructor() {
    super();
    this.debounceTimer = null;
    this.suggestions = [];
  }
  
  connectedCallback() {
    this.render();
    this.setupEventListeners();
  }
  
  handleInput(event) {
    // Debounced search with suggestions
    clearTimeout(this.debounceTimer);
    this.debounceTimer = setTimeout(() => {
      this.performSearch(event.target.value);
    }, 300);
  }
  
  async performSearch(query) {
    // Call search API and emit results
  }
}
```

#### 2.3 ContextTimeline Component
```javascript
class ContextTimeline extends HTMLElement {
  constructor() {
    super();
    this.memories = [];
    this.selectedMemoryId = null;
  }
  
  connectedCallback() {
    this.render();
  }
  
  render() {
    // Create SVG timeline with memory nodes and connections
  }
  
  async loadContext(memoryId, depth = 2) {
    // Fetch context data and update visualization
  }
}
```

### 3. API Client Service

```javascript
class APIClient {
  constructor(baseURL = '') {
    this.baseURL = baseURL;
    this.cache = new Map();
  }
  
  async get(endpoint, params = {}) {
    const url = this.buildURL(endpoint, params);
    const cacheKey = url.toString();
    
    if (this.cache.has(cacheKey)) {
      return this.cache.get(cacheKey);
    }
    
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`API Error: ${response.status}`);
    }
    
    const data = await response.json();
    this.cache.set(cacheKey, data);
    return data;
  }
  
  async post(endpoint, data) {
    const response = await fetch(`${this.baseURL}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    
    if (!response.ok) {
      throw new Error(`API Error: ${response.status}`);
    }
    
    this.invalidateCache();
    return response.json();
  }
  
  // Similar methods for PUT, DELETE
  
  invalidateCache() {
    this.cache.clear();
  }
}
```

### 4. Router Service

```javascript
class Router {
  constructor() {
    this.routes = new Map();
    this.currentRoute = null;
    
    window.addEventListener('popstate', this.handlePopState.bind(this));
  }
  
  register(path, handler) {
    this.routes.set(path, handler);
  }
  
  navigate(path, data = {}) {
    history.pushState(data, '', path);
    this.handleRoute(path, data);
  }
  
  handleRoute(path, data = {}) {
    const route = this.findRoute(path);
    if (route) {
      this.currentRoute = path;
      route.handler(data);
    }
  }
  
  findRoute(path) {
    // Pattern matching for dynamic routes like /memory/:id
    for (const [pattern, handler] of this.routes) {
      const match = this.matchRoute(pattern, path);
      if (match) {
        return { handler, params: match };
      }
    }
    return null;
  }
}
```

## Data Models

### 1. Frontend Data Models

```javascript
class Memory {
  constructor(data) {
    this.id = data.id;
    this.content = data.content;
    this.project_id = data.project_id;
    this.category = data.category;
    this.source = data.source;
    this.tags = data.tags || [];
    this.created_at = new Date(data.created_at);
    this.updated_at = data.updated_at ? new Date(data.updated_at) : null;
    this.similarity_score = data.similarity_score;
  }
  
  getPreview(maxLength = 200) {
    return this.content.length > maxLength 
      ? this.content.substring(0, maxLength) + '...'
      : this.content;
  }
  
  getFormattedDate() {
    return this.created_at.toLocaleDateString();
  }
  
  getCategoryIcon() {
    const icons = {
      task: '📋',
      bug: '🐛',
      idea: '💡',
      decision: '⚖️',
      incident: '🚨',
      code_snippet: '💻'
    };
    return icons[this.category] || '📝';
  }
}

class SearchResult {
  constructor(data) {
    this.memories = data.results.map(m => new Memory(m));
    this.total = data.total;
    this.query = data.query;
    this.filters = data.filters;
  }
}

class ContextData {
  constructor(data) {
    this.primary_memory = new Memory(data.primary_memory);
    this.related_memories = data.related_memories.map(m => new Memory(m));
    this.timeline = data.timeline;
  }
}
```

### 2. UI State Management

```javascript
class AppState {
  constructor() {
    this.currentPage = 'dashboard';
    this.searchQuery = '';
    this.searchFilters = {
      project_id: null,
      category: null,
      date_range: null
    };
    this.selectedMemory = null;
    this.theme = localStorage.getItem('theme') || 'light';
    this.sidebarOpen = true;
    
    this.listeners = new Map();
  }
  
  subscribe(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, []);
    }
    this.listeners.get(event).push(callback);
  }
  
  emit(event, data) {
    if (this.listeners.has(event)) {
      this.listeners.get(event).forEach(callback => callback(data));
    }
  }
  
  updateSearchQuery(query) {
    this.searchQuery = query;
    this.emit('searchQueryChanged', query);
  }
  
  updateSearchFilters(filters) {
    this.searchFilters = { ...this.searchFilters, ...filters };
    this.emit('searchFiltersChanged', this.searchFilters);
  }
  
  setTheme(theme) {
    this.theme = theme;
    localStorage.setItem('theme', theme);
    document.documentElement.setAttribute('data-theme', theme);
    this.emit('themeChanged', theme);
  }
}
```

## User Interface Design

### 1. Layout Structure

```html
<!DOCTYPE html>
<html lang="ko" data-theme="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>mem-mesh Web UI</title>
  <link rel="stylesheet" href="/static/css/main.css">
</head>
<body>
  <div id="app">
    <!-- Header -->
    <header class="app-header">
      <div class="header-content">
        <h1 class="logo">mem-mesh</h1>
        <nav class="main-nav">
          <a href="/" class="nav-link">Dashboard</a>
          <a href="/search" class="nav-link">Search</a>
          <a href="/projects" class="nav-link">Projects</a>
          <a href="/analytics" class="nav-link">Analytics</a>
        </nav>
        <div class="header-actions">
          <button id="theme-toggle" class="icon-button">🌙</button>
          <button id="create-memory" class="primary-button">+ New Memory</button>
        </div>
      </div>
    </header>
    
    <!-- Main Content -->
    <main id="main-content" class="main-content">
      <!-- Dynamic content will be loaded here -->
    </main>
    
    <!-- Sidebar (for filters, navigation) -->
    <aside id="sidebar" class="sidebar">
      <!-- Dynamic sidebar content -->
    </aside>
  </div>
  
  <!-- Loading overlay -->
  <div id="loading-overlay" class="loading-overlay hidden">
    <div class="spinner"></div>
  </div>
  
  <!-- Toast notifications -->
  <div id="toast-container" class="toast-container"></div>
  
  <script type="module" src="/static/js/main.js"></script>
</body>
</html>
```

### 2. CSS Architecture

```css
/* CSS Custom Properties for theming */
:root {
  --primary-color: #2563eb;
  --secondary-color: #64748b;
  --success-color: #10b981;
  --warning-color: #f59e0b;
  --error-color: #ef4444;
  
  --bg-primary: #ffffff;
  --bg-secondary: #f8fafc;
  --text-primary: #1e293b;
  --text-secondary: #64748b;
  --border-color: #e2e8f0;
  
  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
  --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1);
  
  --border-radius: 0.5rem;
  --transition: all 0.2s ease-in-out;
}

[data-theme="dark"] {
  --bg-primary: #0f172a;
  --bg-secondary: #1e293b;
  --text-primary: #f1f5f9;
  --text-secondary: #94a3b8;
  --border-color: #334155;
}

/* Layout */
.app-header {
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border-color);
  padding: 1rem 2rem;
  position: sticky;
  top: 0;
  z-index: 100;
}

.main-content {
  padding: 2rem;
  max-width: 1200px;
  margin: 0 auto;
}

/* Components */
.memory-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  padding: 1.5rem;
  margin-bottom: 1rem;
  box-shadow: var(--shadow-sm);
  transition: var(--transition);
  cursor: pointer;
}

.memory-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.search-bar {
  position: relative;
  width: 100%;
  max-width: 600px;
}

.search-input {
  width: 100%;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  font-size: 1rem;
  background: var(--bg-primary);
  color: var(--text-primary);
}

/* Responsive Design */
@media (max-width: 768px) {
  .app-header {
    padding: 1rem;
  }
  
  .main-content {
    padding: 1rem;
  }
  
  .main-nav {
    display: none;
  }
  
  .memory-card {
    padding: 1rem;
  }
}
```

### 3. Page Templates

#### Dashboard Page
```javascript
class DashboardPage {
  constructor(apiClient, appState) {
    this.apiClient = apiClient;
    this.appState = appState;
  }
  
  async render() {
    const stats = await this.apiClient.get('/memories/stats');
    const recentMemories = await this.apiClient.get('/memories/search', { limit: 5 });
    
    return `
      <div class="dashboard">
        <div class="dashboard-header">
          <h2>Memory Dashboard</h2>
          <p>Overview of your stored memories</p>
        </div>
        
        <div class="stats-grid">
          <div class="stat-card">
            <h3>${stats.total_memories}</h3>
            <p>Total Memories</p>
          </div>
          <div class="stat-card">
            <h3>${stats.unique_projects}</h3>
            <p>Projects</p>
          </div>
          <div class="stat-card">
            <h3>${Object.keys(stats.categories_breakdown).length}</h3>
            <p>Categories</p>
          </div>
        </div>
        
        <div class="dashboard-content">
          <div class="recent-memories">
            <h3>Recent Memories</h3>
            <div class="memory-list">
              ${recentMemories.results.map(memory => 
                `<memory-card 
                   memory-id="${memory.id}"
                   content="${memory.content}"
                   project="${memory.project_id || 'Global'}"
                   category="${memory.category}"
                   created-at="${memory.created_at}">
                 </memory-card>`
              ).join('')}
            </div>
          </div>
          
          <div class="category-chart">
            <h3>Category Distribution</h3>
            <canvas id="category-chart"></canvas>
          </div>
        </div>
      </div>
    `;
  }
}
```

#### Search Page
```javascript
class SearchPage {
  constructor(apiClient, appState) {
    this.apiClient = apiClient;
    this.appState = appState;
    this.currentResults = [];
  }
  
  async render() {
    return `
      <div class="search-page">
        <div class="search-header">
          <search-bar placeholder="Search your memories..."></search-bar>
          <button id="advanced-search-toggle" class="secondary-button">
            Advanced Filters
          </button>
        </div>
        
        <div id="search-filters" class="search-filters hidden">
          <div class="filter-group">
            <label>Project</label>
            <select id="project-filter">
              <option value="">All Projects</option>
            </select>
          </div>
          <div class="filter-group">
            <label>Category</label>
            <select id="category-filter">
              <option value="">All Categories</option>
              <option value="task">Task</option>
              <option value="bug">Bug</option>
              <option value="idea">Idea</option>
              <option value="decision">Decision</option>
              <option value="incident">Incident</option>
              <option value="code_snippet">Code Snippet</option>
            </select>
          </div>
          <div class="filter-group">
            <label>Date Range</label>
            <input type="date" id="date-from">
            <input type="date" id="date-to">
          </div>
        </div>
        
        <div id="search-results" class="search-results">
          <div class="no-results">
            <p>Enter a search query to find memories</p>
          </div>
        </div>
        
        <div id="search-pagination" class="pagination hidden"></div>
      </div>
    `;
  }
  
  async performSearch(query, filters = {}) {
    const params = { query, ...filters };
    const results = await this.apiClient.get('/memories/search', params);
    this.displayResults(results);
  }
  
  displayResults(results) {
    const container = document.getElementById('search-results');
    if (results.results.length === 0) {
      container.innerHTML = '<div class="no-results"><p>No memories found</p></div>';
      return;
    }
    
    container.innerHTML = results.results.map(memory => 
      `<memory-card 
         memory-id="${memory.id}"
         content="${memory.content}"
         project="${memory.project_id || 'Global'}"
         category="${memory.category}"
         created-at="${memory.created_at}"
         similarity-score="${memory.similarity_score}">
       </memory-card>`
    ).join('');
  }
}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: UI State Consistency
*For any* user interaction that changes application state, the UI should reflect the new state within 100ms and all related components should be synchronized.
**Validates: Requirements 1.8, 2.12, 7.8**

### Property 2: Search Result Accuracy
*For any* search query, all displayed results should match the query criteria and be sorted by relevance score in descending order.
**Validates: Requirements 2.3, 2.4, 2.5, 2.10**

### Property 3: Memory Card Data Integrity
*For any* memory displayed in a memory card, all metadata (project, category, date, content preview) should accurately represent the source memory data.
**Validates: Requirements 2.4, 3.3, 3.4**

### Property 4: Navigation State Preservation
*For any* page navigation, the browser URL should reflect the current page state and be bookmarkable/shareable.
**Validates: Requirements 8.7, 8.8**

### Property 5: Responsive Layout Adaptation
*For any* screen size change, the UI layout should adapt appropriately without content overflow or accessibility issues.
**Validates: Requirements 7.1, 7.2, 7.3**

### Property 6: API Error Handling
*For any* API request failure, the UI should display a user-friendly error message and maintain application stability.
**Validates: Requirements 1.10, 10.5, 12.9**

### Property 7: Theme Consistency
*For any* theme change (light/dark), all UI components should consistently apply the new theme colors and maintain readability.
**Validates: Requirements 7.5, 7.6**

### Property 8: Memory Content Formatting
*For any* memory content display, code snippets should be syntax highlighted and long content should be properly truncated with expand options.
**Validates: Requirements 3.3, 4.11, 10.8**

### Property 9: Context Visualization Accuracy
*For any* memory context display, the timeline should show related memories in chronological order with correct relationship indicators.
**Validates: Requirements 5.3, 5.4, 5.5, 5.6**

### Property 10: Search Performance
*For any* search operation, the UI should complete the search and display results within 1 second including loading indicators.
**Validates: Requirements 12.2, 12.5**

### Property 11: Form Validation Consistency
*For any* form input, client-side validation should match server-side validation rules and provide immediate feedback.
**Validates: Requirements 4.3, 4.6, 4.8**

### Property 12: Cache Invalidation
*For any* data modification operation (create, update, delete), the local cache should be invalidated and fresh data should be fetched.
**Validates: Requirements 10.10, 12.6**

## Error Handling

### 1. API Error Handling
```javascript
class ErrorHandler {
  static handleAPIError(error, context = '') {
    const errorMap = {
      400: 'Invalid request. Please check your input.',
      401: 'Authentication required.',
      403: 'Access denied.',
      404: 'Resource not found.',
      422: 'Validation error. Please check your input.',
      500: 'Server error. Please try again later.',
      503: 'Service unavailable. Please try again later.'
    };
    
    const message = errorMap[error.status] || 'An unexpected error occurred.';
    
    this.showToast({
      type: 'error',
      title: 'Error',
      message: `${context ? context + ': ' : ''}${message}`,
      duration: 5000
    });
    
    console.error('API Error:', error);
  }
  
  static showToast({ type, title, message, duration = 3000 }) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
      <div class="toast-content">
        <strong>${title}</strong>
        <p>${message}</p>
      </div>
      <button class="toast-close">&times;</button>
    `;
    
    document.getElementById('toast-container').appendChild(toast);
    
    setTimeout(() => {
      toast.remove();
    }, duration);
  }
}
```

### 2. Component Error Boundaries
```javascript
class ErrorBoundary {
  static wrap(component) {
    return class extends component {
      connectedCallback() {
        try {
          super.connectedCallback();
        } catch (error) {
          this.handleError(error);
        }
      }
      
      handleError(error) {
        console.error('Component Error:', error);
        this.innerHTML = `
          <div class="error-boundary">
            <h3>Something went wrong</h3>
            <p>This component encountered an error. Please refresh the page.</p>
            <button onclick="location.reload()">Refresh Page</button>
          </div>
        `;
      }
    };
  }
}
```

## Testing Strategy

### 1. Unit Testing
- **Component Testing**: Test individual Web Components in isolation
- **Service Testing**: Test API client, router, and utility functions
- **State Management Testing**: Test application state updates and event handling

### 2. Integration Testing
- **API Integration**: Test communication with FastAPI backend
- **Component Integration**: Test component interactions and data flow
- **Router Integration**: Test navigation and URL handling

### 3. End-to-End Testing
- **User Workflows**: Test complete user journeys (search, create, edit memory)
- **Cross-browser Testing**: Test on Chrome, Firefox, Safari, Edge
- **Responsive Testing**: Test on different screen sizes and devices

### 4. Performance Testing
- **Load Time Testing**: Measure initial page load and subsequent navigation
- **Search Performance**: Test search response times with large datasets
- **Memory Usage**: Monitor JavaScript memory usage and potential leaks

### 5. Accessibility Testing
- **Screen Reader Testing**: Test with NVDA, JAWS, VoiceOver
- **Keyboard Navigation**: Test all functionality with keyboard only
- **Color Contrast**: Verify WCAG 2.1 AA compliance

### Testing Tools
- **Unit Tests**: Jest with jsdom for DOM testing
- **E2E Tests**: Playwright for cross-browser testing
- **Performance**: Lighthouse CI for automated performance auditing
- **Accessibility**: axe-core for automated accessibility testing