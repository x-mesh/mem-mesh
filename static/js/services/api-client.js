/**
 * API Client Service
 * Handles all HTTP requests to the mem-mesh API
 */

export class APIClient {
  constructor(baseURL = '/api') {
    this.baseURL = baseURL;
    this.cache = new Map();
    this.requestQueue = new Map();
  }
  
  /**
   * Build URL with query parameters
   */
  buildURL(endpoint, params = {}) {
    const url = new URL(`${this.baseURL}${endpoint}`, window.location.origin);
    
    Object.entries(params).forEach(([key, value]) => {
      if (value !== null && value !== undefined) {
        // query 파라미터는 빈 문자열도 허용
        if (key === 'query' || value !== '') {
          url.searchParams.append(key, value);
        }
      }
    });
    
    return url;
  }
  
  /**
   * Generate cache key
   */
  getCacheKey(method, url, data = null) {
    const key = `${method}:${url.toString()}`;
    return data ? `${key}:${JSON.stringify(data)}` : key;
  }
  
  /**
   * Check if request should be cached
   */
  shouldCache(method) {
    return method === 'GET';
  }
  
  /**
   * Generic HTTP request method
   */
  async request(method, endpoint, data = null, params = {}) {
    const url = this.buildURL(endpoint, params);
    const cacheKey = this.getCacheKey(method, url, data);
    
    // Check cache for GET requests
    if (this.shouldCache(method) && this.cache.has(cacheKey)) {
      return this.cache.get(cacheKey);
    }
    
    // Prevent duplicate requests
    if (this.requestQueue.has(cacheKey)) {
      return this.requestQueue.get(cacheKey);
    }
    
    const requestOptions = {
      method,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      }
    };
    
    if (data && (method === 'POST' || method === 'PUT' || method === 'PATCH')) {
      requestOptions.body = JSON.stringify(data);
    }
    
    // Create request promise
    const requestPromise = this.executeRequest(url, requestOptions, cacheKey);
    
    // Add to queue
    this.requestQueue.set(cacheKey, requestPromise);
    
    try {
      const result = await requestPromise;
      
      // Cache GET requests
      if (this.shouldCache(method)) {
        this.cache.set(cacheKey, result);
      }
      
      return result;
      
    } finally {
      // Remove from queue
      this.requestQueue.delete(cacheKey);
    }
  }
  
  /**
   * Execute HTTP request
   */
  async executeRequest(url, options, cacheKey) {
    try {
      const response = await fetch(url, options);
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new APIError(
          response.status,
          errorData.message || `HTTP ${response.status}: ${response.statusText}`,
          errorData
        );
      }
      
      const contentType = response.headers.get('content-type');
      if (contentType && contentType.includes('application/json')) {
        return await response.json();
      }
      
      return await response.text();
      
    } catch (error) {
      if (error instanceof APIError) {
        throw error;
      }
      
      // Network or other errors
      throw new APIError(0, error.message || 'Network error', { originalError: error });
    }
  }
  
  /**
   * GET request
   */
  async get(endpoint, params = {}) {
    return this.request('GET', endpoint, null, params);
  }
  
  /**
   * POST request
   */
  async post(endpoint, data, params = {}) {
    this.invalidateCache();
    return this.request('POST', endpoint, data, params);
  }
  
  /**
   * PUT request
   */
  async put(endpoint, data, params = {}) {
    this.invalidateCache();
    return this.request('PUT', endpoint, data, params);
  }
  
  /**
   * DELETE request
   */
  async delete(endpoint, params = {}) {
    this.invalidateCache();
    return this.request('DELETE', endpoint, null, params);
  }
  
  /**
   * PATCH request
   */
  async patch(endpoint, data, params = {}) {
    this.invalidateCache();
    return this.request('PATCH', endpoint, data, params);
  }
  
  /**
   * Invalidate cache
   */
  invalidateCache(pattern = null) {
    if (pattern) {
      // Invalidate specific pattern
      for (const key of this.cache.keys()) {
        if (key.includes(pattern)) {
          this.cache.delete(key);
        }
      }
    } else {
      // Clear all cache
      this.cache.clear();
    }
  }
  
  /**
   * Memory-specific API methods
   */
  
  async getStats(filters = {}) {
    return this.get('/memories/stats', filters);
  }
  
  async searchMemories(query, filters = {}) {
    return this.get('/memories/search', { query, ...filters });
  }
  
  async getContext(memoryId, depth = 2, projectId = null) {
    const params = { depth };
    if (projectId) params.project_id = projectId;
    return this.get(`/memories/${memoryId}/context`, params);
  }
  
  async getMemory(memoryId) {
    // 단일 메모리 조회는 현재 API에 없으므로 검색으로 대체
    // 모든 메모리를 검색해서 해당 ID를 찾음
    const result = await this.searchMemories(' ', { limit: 100 });
    const memory = result.results?.find(m => m.id === memoryId);
    if (!memory) {
      const error = new APIError(404, 'Memory not found');
      throw error;
    }
    return memory;
  }
  
  async createMemory(memoryData) {
    return this.post('/memories', memoryData);
  }
  
  async updateMemory(memoryId, updates) {
    return this.put(`/memories/${memoryId}`, updates);
  }
  
  async deleteMemory(memoryId) {
    return this.delete(`/memories/${memoryId}`);
  }
  
  /**
   * Health check
   */
  async healthCheck() {
    return this.get('/health');
  }
}

/**
 * API Error class
 */
export class APIError extends Error {
  constructor(status, message, data = {}) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.data = data;
  }
  
  get isNetworkError() {
    return this.status === 0;
  }
  
  get isClientError() {
    return this.status >= 400 && this.status < 500;
  }
  
  get isServerError() {
    return this.status >= 500;
  }
}