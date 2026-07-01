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
      if (value === null || value === undefined) return;
      // Arrays → repeated params (e.g. categories=bug&categories=incident) so
      // FastAPI List[str] query params bind correctly.
      if (Array.isArray(value)) {
        value.forEach((v) => {
          if (v !== null && v !== undefined && v !== '') url.searchParams.append(key, v);
        });
        return;
      }
      // query 파라미터는 빈 문자열도 허용
      if (key === 'query' || value !== '') {
        url.searchParams.append(key, value);
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
   * Drop cached GET responses whose key contains a path fragment.
   * The generic request() never invalidates the cache, so mutations must call
   * this explicitly (e.g. after updating a memory) or later reads stay stale.
   */
  invalidateCache(pathFragment) {
    for (const key of this.cache.keys()) {
      if (key.includes(pathFragment)) {
        this.cache.delete(key);
      }
    }
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

  async getProjects() {
    return this.get('/projects');
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
    // 직접 메모리 ID로 조회
    return this.get(`/memories/${memoryId}`);
  }
  
  async createMemory(memoryData) {
    const result = await this.post('/memories', memoryData);
    this.invalidateCache('/memories');
    return result;
  }

  async updateMemory(memoryId, updates) {
    const result = await this.put(`/memories/${memoryId}`, updates);
    this.invalidateCache('/memories');
    return result;
  }

  async deleteMemory(memoryId) {
    const result = await this.delete(`/memories/${memoryId}`);
    this.invalidateCache('/memories');
    return result;
  }

  /**
   * Relay API methods
   */

  async getRelayOverview(limit = 10) {
    return this.get('/relay/v1/admin/overview', { limit, _ts: Date.now() });
  }

  async materializeRelayMemories(limit = 1000) {
    return this.post('/relay/v1/admin/materialize', null, { limit });
  }

  async purgeRelayCurrentMemories(limit = 10000) {
    return this.post('/relay/v1/admin/purge-current', null, { limit });
  }

  async retryRelayDeadLetters(payload = {}) {
    return this.post('/relay/v1/admin/retry-dead-letters', {
      queue: payload.queue || 'all',
      id: payload.id || null,
      limit: payload.limit || 1000,
    });
  }

  async getRelaySettings() {
    return this.get('/relay/v1/admin/settings');
  }

  async updateRelaySettings(payload) {
    return this.put('/relay/v1/admin/settings', payload);
  }

  async checkRelayHub(payload) {
    return this.post('/relay/v1/admin/hub/check', payload);
  }

  async createRelayIdentity(payload) {
    return this.post('/relay/v1/admin/identities', payload);
  }

  async updateRelayIdentity(tokenHashPrefix, payload) {
    return this.put(`/relay/v1/admin/identities/${encodeURIComponent(tokenHashPrefix)}`, payload);
  }

  async deleteRelayIdentity(tokenHashPrefix) {
    return this.delete(`/relay/v1/admin/identities/${encodeURIComponent(tokenHashPrefix)}`);
  }

  async rotateRelayIdentity(tokenHashPrefix, payload = {}) {
    return this.post(`/relay/v1/admin/identities/${encodeURIComponent(tokenHashPrefix)}/rotate`, payload);
  }

  async shareRelayMemory(memoryId, payload) {
    return this.post(`/relay/v1/outbox/share/${encodeURIComponent(memoryId)}`, payload);
  }

  async shareRelayProject(projectId, payload) {
    return this.post(`/relay/v1/outbox/share-project/${encodeURIComponent(projectId)}`, payload);
  }

  async getRelayAutoShare() {
    return this.get('/relay/v1/admin/auto-share');
  }

  async setRelayAutoShare(projectId, payload) {
    return this.put(`/relay/v1/admin/auto-share/${encodeURIComponent(projectId)}`, payload);
  }

  /**
   * Analytics API methods (server-side aggregation)
   */

  async getDailyCounts(filters = {}) {
    return this.get('/memories/daily-counts', filters);
  }

  async getProductivityAnalytics(filters = {}) {
    return this.get('/analytics/productivity', filters);
  }

  async getTokenEconomics(filters = {}) {
    return this.get('/analytics/token-economics', filters);
  }

  async getKbHealth(filters = {}) {
    return this.get('/analytics/kb-health', filters);
  }

  async getRecallAnalytics(filters = {}) {
    return this.get('/analytics/recall', filters);
  }

  async getActivityTrend(filters = {}) {
    return this.get('/analytics/activity-trend', filters);
  }

  /**
   * Reconcile curation (SSOT #3 F4)
   */
  async getCurationQueue(projectId = null, limit = 50) {
    const params = { limit };
    if (projectId) params.project_id = projectId;
    return this.get('/curation/queue', params);
  }

  async approveCurationSupersede(relationId) {
    return this.post(
      `/curation/supersede/${encodeURIComponent(relationId)}/approve`,
      {}
    );
  }

  async rejectCurationNew(memoryId) {
    return this.post(`/curation/reject-new/${encodeURIComponent(memoryId)}`, {});
  }

  async approveCurationMerge(relationId, mergedText = null) {
    return this.post(
      `/curation/merge/${encodeURIComponent(relationId)}/approve`,
      { merged_text: mergedText }
    );
  }

  async dismissCuration(relationId) {
    return this.post(`/curation/dismiss/${encodeURIComponent(relationId)}`, {});
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
