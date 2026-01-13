/**
 * Router Service
 * Handles client-side routing for the SPA
 */

export class Router {
  constructor() {
    this.routes = new Map();
    this.currentRoute = null;
    this.currentParams = {};
    this.isStarted = false;
    
    // Bind methods
    this.handlePopState = this.handlePopState.bind(this);
    this.handleLinkClick = this.handleLinkClick.bind(this);
  }
  
  /**
   * Register a route
   */
  register(pattern, handler) {
    this.routes.set(pattern, handler);
  }
  
  /**
   * Start the router
   */
  start() {
    if (this.isStarted) return;
    
    // Listen for browser navigation
    window.addEventListener('popstate', this.handlePopState);
    
    // Listen for link clicks
    document.addEventListener('click', this.handleLinkClick);
    
    // Handle initial route with query parameters
    const initialPath = window.location.pathname + window.location.search;
    this.handleRoute(initialPath);
    
    this.isStarted = true;
  }
  
  /**
   * Stop the router
   */
  stop() {
    if (!this.isStarted) return;
    
    window.removeEventListener('popstate', this.handlePopState);
    document.removeEventListener('click', this.handleLinkClick);
    
    this.isStarted = false;
  }
  
  /**
   * Navigate to a route
   */
  navigate(path, data = {}, replace = false) {
    // Extract pathname from full URL (remove query parameters for comparison)
    const currentPathname = window.location.pathname;
    const targetPathname = path.split('?')[0];
    
    // Don't prevent navigation if query parameters are different
    if (path === window.location.pathname + window.location.search) {
      return; // Already on this exact route with same query params
    }
    
    if (replace) {
      history.replaceState(data, '', path);
    } else {
      history.pushState(data, '', path);
    }
    
    this.handleRoute(targetPathname, data);
  }
  
  /**
   * Replace current route
   */
  replace(path, data = {}) {
    this.navigate(path, data, true);
  }
  
  /**
   * Go back in history
   */
  back() {
    history.back();
  }
  
  /**
   * Go forward in history
   */
  forward() {
    history.forward();
  }
  
  /**
   * Handle popstate event
   */
  handlePopState(event) {
    const fullPath = window.location.pathname + window.location.search;
    this.handleRoute(fullPath, event.state || {});
  }
  
  /**
   * Handle link clicks
   */
  handleLinkClick(event) {
    // Only handle left clicks
    if (event.button !== 0) return;
    
    // Don't handle if modifier keys are pressed
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    
    const link = event.target.closest('a[href]');
    if (!link) return;
    
    const href = link.getAttribute('href');
    
    // Only handle internal links
    if (!href || href.startsWith('http') || href.startsWith('mailto:') || href.startsWith('tel:')) {
      return;
    }
    
    // Prevent default navigation
    event.preventDefault();
    
    // Navigate using router
    this.navigate(href);
  }
  
  /**
   * Handle route
   */
  handleRoute(path, data = {}) {
    // Extract pathname from full URL (remove query parameters)
    const pathname = path.split('?')[0];
    const route = this.findRoute(pathname);
    
    if (route) {
      this.currentRoute = pathname;
      this.currentParams = route.params;
      
      try {
        route.handler(route.params, data);
      } catch (error) {
        console.error('Route handler error:', error);
        this.handleNotFound(pathname);
      }
    } else {
      this.handleNotFound(pathname);
    }
  }
  
  /**
   * Find matching route
   */
  findRoute(path) {
    for (const [pattern, handler] of this.routes) {
      const match = this.matchRoute(pattern, path);
      if (match) {
        return { handler, params: match };
      }
    }
    return null;
  }
  
  /**
   * Match route pattern against path
   */
  matchRoute(pattern, path) {
    // Remove query parameters from path for matching
    const cleanPath = path.split('?')[0];
    
    // Exact match
    if (pattern === cleanPath) {
      return {};
    }
    
    // Parameter matching
    const patternParts = pattern.split('/');
    const pathParts = cleanPath.split('/');
    
    if (patternParts.length !== pathParts.length) {
      return null;
    }
    
    const params = {};
    
    for (let i = 0; i < patternParts.length; i++) {
      const patternPart = patternParts[i];
      const pathPart = pathParts[i];
      
      if (patternPart.startsWith(':')) {
        // Parameter
        const paramName = patternPart.slice(1);
        params[paramName] = decodeURIComponent(pathPart);
      } else if (patternPart !== pathPart) {
        // No match
        return null;
      }
    }
    
    return params;
  }
  
  /**
   * Handle 404 not found
   */
  handleNotFound(path) {
    console.warn(`Route not found: ${path}`);
    
    // Redirect to home page
    if (path !== '/') {
      this.replace('/');
    }
  }
  
  /**
   * Get current route info
   */
  getCurrentRoute() {
    return {
      path: this.currentRoute,
      params: this.currentParams
    };
  }
  
  /**
   * Build URL with parameters
   */
  buildURL(pattern, params = {}) {
    let url = pattern;
    
    Object.entries(params).forEach(([key, value]) => {
      url = url.replace(`:${key}`, encodeURIComponent(value));
    });
    
    return url;
  }
  
  /**
   * Add query parameters to current URL
   */
  updateQuery(params, replace = false) {
    const url = new URL(window.location);
    
    Object.entries(params).forEach(([key, value]) => {
      if (value === null || value === undefined || value === '') {
        url.searchParams.delete(key);
      } else {
        url.searchParams.set(key, value);
      }
    });
    
    const newPath = url.pathname + url.search;
    
    if (replace) {
      history.replaceState(history.state, '', newPath);
    } else {
      history.pushState(history.state, '', newPath);
    }
  }
  
  /**
   * Get query parameters
   */
  getQuery() {
    const params = {};
    const searchParams = new URLSearchParams(window.location.search);
    
    for (const [key, value] of searchParams) {
      params[key] = value;
    }
    
    return params;
  }
}