/**
 * Services Tests
 * Tests for API client, router, app state, and other services
 */

import { describe, it, expect, beforeEach, afterEach, createMock } from './test-runner.js';
import { APIClient, APIError } from '../services/api-client.js';
import { Router } from '../services/router.js';
import { AppState } from '../services/app-state.js';

describe('APIClient', () => {
  let apiClient;
  let originalFetch;
  
  beforeEach(() => {
    apiClient = new APIClient('/api');
    originalFetch = global.fetch;
  });
  
  afterEach(() => {
    global.fetch = originalFetch;
  });
  
  it('should build URLs correctly', () => {
    const url = apiClient.buildURL('/memories', { limit: 10, category: 'task' });
    expect(url.pathname).toBe('/api/memories');
    expect(url.searchParams.get('limit')).toBe('10');
    expect(url.searchParams.get('category')).toBe('task');
  });
  
  it('should generate cache keys', () => {
    const url = new URL('/api/memories', 'http://localhost');
    const key1 = apiClient.getCacheKey('GET', url);
    const key2 = apiClient.getCacheKey('POST', url, { data: 'test' });
    
    expect(key1).toBe('GET:http://localhost/api/memories');
    expect(key2).toBe('POST:http://localhost/api/memories:{"data":"test"}');
  });
  
  it('should make GET requests', async () => {
    const mockResponse = { memories: [{ id: '1', content: 'test' }] };
    
    global.fetch = createMock(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(mockResponse),
      headers: { get: () => 'application/json' }
    }));
    
    const result = await apiClient.get('/memories');
    
    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(URL),
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        })
      })
    );
    
    expect(result).toEqual(mockResponse);
  });
  
  it('should make POST requests', async () => {
    const requestData = { content: 'New memory', category: 'task' };
    const mockResponse = { id: '123', ...requestData };
    
    global.fetch = createMock(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(mockResponse),
      headers: { get: () => 'application/json' }
    }));
    
    const result = await apiClient.post('/memories', requestData);
    
    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(URL),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(requestData),
        headers: expect.objectContaining({
          'Content-Type': 'application/json'
        })
      })
    );
    
    expect(result).toEqual(mockResponse);
  });
  
  it('should handle API errors', async () => {
    global.fetch = createMock(() => Promise.resolve({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: () => Promise.resolve({ message: 'Memory not found' })
    }));
    
    try {
      await apiClient.get('/memories/nonexistent');
      expect(true).toBe(false); // Should not reach here
    } catch (error) {
      expect(error).toBeInstanceOf(APIError);
      expect(error.status).toBe(404);
      expect(error.message).toBe('Memory not found');
    }
  });
  
  it('should handle network errors', async () => {
    global.fetch = createMock(() => Promise.reject(new Error('Network error')));
    
    try {
      await apiClient.get('/memories');
      expect(true).toBe(false); // Should not reach here
    } catch (error) {
      expect(error).toBeInstanceOf(APIError);
      expect(error.status).toBe(0);
      expect(error.message).toBe('Network error');
    }
  });
  
  it('should cache GET requests', async () => {
    const mockResponse = { memories: [] };
    
    global.fetch = createMock(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(mockResponse),
      headers: { get: () => 'application/json' }
    }));
    
    // First request
    await apiClient.get('/memories');
    expect(global.fetch).toHaveBeenCalledTimes(1);
    
    // Second request should use cache
    await apiClient.get('/memories');
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
  
  it('should invalidate cache on mutations', async () => {
    const mockResponse = { memories: [] };
    
    global.fetch = createMock(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(mockResponse),
      headers: { get: () => 'application/json' }
    }));
    
    // Cache a GET request
    await apiClient.get('/memories');
    expect(apiClient.cache.size).toBeGreaterThan(0);
    
    // POST should invalidate cache
    await apiClient.post('/memories', { content: 'test' });
    expect(apiClient.cache.size).toBe(0);
  });
});

describe('Router', () => {
  let router;
  let originalHistory;
  
  beforeEach(() => {
    router = new Router();
    originalHistory = window.history;
    
    // Mock history API
    window.history = {
      pushState: createMock(),
      replaceState: createMock(),
      back: createMock(),
      forward: createMock()
    };
  });
  
  afterEach(() => {
    window.history = originalHistory;
    router.destroy();
  });
  
  it('should register routes', () => {
    const handler = createMock();
    router.register('/test', handler);
    
    expect(router.routes.has('/test')).toBeTruthy();
  });
  
  it('should register parameterized routes', () => {
    const handler = createMock();
    router.register('/memory/:id', handler);
    
    expect(router.routes.has('/memory/:id')).toBeTruthy();
  });
  
  it('should navigate to routes', () => {
    const handler = createMock();
    router.register('/test', handler);
    router.start();
    
    router.navigate('/test');
    
    expect(window.history.pushState).toHaveBeenCalledWith(
      null,
      '',
      '/test'
    );
    expect(handler).toHaveBeenCalled();
  });
  
  it('should extract route parameters', () => {
    const handler = createMock();
    router.register('/memory/:id', handler);
    router.start();
    
    router.navigate('/memory/123');
    
    expect(handler).toHaveBeenCalledWith({ id: '123' });
  });
  
  it('should handle complex route patterns', () => {
    const handler = createMock();
    router.register('/project/:projectId/memory/:memoryId', handler);
    router.start();
    
    router.navigate('/project/my-project/memory/456');
    
    expect(handler).toHaveBeenCalledWith({
      projectId: 'my-project',
      memoryId: '456'
    });
  });
  
  it('should handle 404 for unmatched routes', () => {
    const notFoundHandler = createMock();
    router.setNotFoundHandler(notFoundHandler);
    router.start();
    
    router.navigate('/nonexistent');
    
    expect(notFoundHandler).toHaveBeenCalled();
  });
  
  it('should handle browser back/forward', () => {
    const handler1 = createMock();
    const handler2 = createMock();
    
    router.register('/page1', handler1);
    router.register('/page2', handler2);
    router.start();
    
    // Simulate popstate event
    window.location.pathname = '/page1';
    const popstateEvent = new PopStateEvent('popstate');
    window.dispatchEvent(popstateEvent);
    
    expect(handler1).toHaveBeenCalled();
  });
});

describe('AppState', () => {
  let appState;
  
  beforeEach(() => {
    appState = new AppState();
    localStorage.clear();
  });
  
  afterEach(() => {
    localStorage.clear();
  });
  
  it('should initialize with default state', () => {
    expect(appState.getState()).toEqual({
      currentPage: null,
      searchQuery: '',
      filters: {},
      theme: 'light',
      user: null
    });
  });
  
  it('should update state', () => {
    appState.setState({ currentPage: 'dashboard' });
    
    expect(appState.getState().currentPage).toBe('dashboard');
  });
  
  it('should emit state change events', () => {
    let stateChangeEvent = null;
    
    appState.addEventListener('state-change', (event) => {
      stateChangeEvent = event;
    });
    
    appState.setState({ searchQuery: 'test' });
    
    expect(stateChangeEvent).toBeTruthy();
    expect(stateChangeEvent.detail.searchQuery).toBe('test');
  });
  
  it('should persist state to localStorage', () => {
    appState.setState({ theme: 'dark' });
    
    const stored = JSON.parse(localStorage.getItem('mem-mesh-state'));
    expect(stored.theme).toBe('dark');
  });
  
  it('should load state from localStorage', () => {
    localStorage.setItem('mem-mesh-state', JSON.stringify({
      currentPage: 'search',
      theme: 'dark'
    }));
    
    const newAppState = new AppState();
    const state = newAppState.getState();
    
    expect(state.currentPage).toBe('search');
    expect(state.theme).toBe('dark');
  });
  
  it('should handle invalid localStorage data', () => {
    localStorage.setItem('mem-mesh-state', 'invalid json');
    
    const newAppState = new AppState();
    const state = newAppState.getState();
    
    // Should fall back to default state
    expect(state.currentPage).toBe(null);
    expect(state.theme).toBe('light');
  });
  
  it('should provide convenience methods', () => {
    appState.setCurrentPage('analytics');
    expect(appState.getCurrentPage()).toBe('analytics');
    
    appState.setSearchQuery('test query');
    expect(appState.getSearchQuery()).toBe('test query');
    
    appState.setFilters({ category: 'bug' });
    expect(appState.getFilters()).toEqual({ category: 'bug' });
    
    appState.setTheme('dark');
    expect(appState.getTheme()).toBe('dark');
  });
});

describe('Service Integration', () => {
  let apiClient;
  let router;
  let appState;
  
  beforeEach(() => {
    apiClient = new APIClient('/api');
    router = new Router();
    appState = new AppState();
    
    global.fetch = createMock(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ memories: [] }),
      headers: { get: () => 'application/json' }
    }));
  });
  
  afterEach(() => {
    router.destroy();
    localStorage.clear();
  });
  
  it('should coordinate between services', async () => {
    // Setup route handler that uses API client and updates state
    router.register('/search', async () => {
      const results = await apiClient.searchMemories('test');
      appState.setState({ 
        currentPage: 'search',
        searchResults: results.memories 
      });
    });
    
    router.start();
    
    // Navigate to search
    router.navigate('/search');
    
    // Wait for async operations
    await new Promise(resolve => setTimeout(resolve, 0));
    
    expect(global.fetch).toHaveBeenCalled();
    expect(appState.getCurrentPage()).toBe('search');
  });
  
  it('should handle service errors gracefully', async () => {
    global.fetch = createMock(() => Promise.reject(new Error('Network error')));
    
    let errorCaught = false;
    
    router.register('/search', async () => {
      try {
        await apiClient.searchMemories('test');
      } catch (error) {
        errorCaught = true;
        appState.setState({ error: error.message });
      }
    });
    
    router.start();
    router.navigate('/search');
    
    await new Promise(resolve => setTimeout(resolve, 0));
    
    expect(errorCaught).toBeTruthy();
    expect(appState.getState().error).toBe('Network error');
  });
});