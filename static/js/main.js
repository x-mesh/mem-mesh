/**
 * mem-mesh Web UI Main Application
 * Entry point for the single-page application
 */

// Import core services and components
import { APIClient } from './services/api-client.js';
import { Router } from './services/router.js';
import { AppState } from './services/app-state.js';
import { ThemeManager } from './utils/theme-manager.js';
import { ErrorHandler } from './utils/error-handler.js';
import { KeyboardShortcuts } from './utils/keyboard-shortcuts.js';
import { ToastNotifications } from './utils/toast-notifications.js';

// Import components
import { MemoryCard } from './components/memory-card.js';
import { SearchBar } from './components/search-bar.js';
import { FilterPanel } from './components/filter-panel.js';
import { ContextTimeline } from './components/context-timeline.js';
import { NetworkGraph } from './components/network-graph.js';
import { HeroSection } from './components/hero-section.js';
import { FeaturesSection } from './components/features-section.js';
import { FeatureCard } from './components/feature-card.js';
import ChromaHeader from './components/chroma-header.js';
import { ChromaSearchBar } from './components/chroma-search-bar.js';
import { DashboardPreview } from './components/dashboard-preview.js';
import { SearchableCombobox } from './components/searchable-combobox.js';

// Import chart components
import './components/chroma-charts.js';

// Import pages
import { DashboardPage } from './pages/dashboard.js';
import { AboutPage } from './pages/about.js';
import { SearchPage } from './pages/search.js';
import { MemoryDetailPage } from './pages/memory-detail.js';
import { CreateMemoryPage } from './pages/create-memory.js';
import { EditMemoryPage } from './pages/edit-memory.js';
import { ProjectsPage } from './pages/projects.js';
import { ProjectDetailPage } from './pages/project-detail-v2.js';
import { MemoriesPage } from './pages/memories.js';
import { AnalyticsPage } from './pages/analytics.js';
import { SettingsPage } from './pages/settings-page.js';

/**
 * Main Application Class
 */
class App {
  constructor() {
    // 전역 앱 객체를 즉시 설정
    window.app = this;
    
    this.apiClient = new APIClient();
    this.appState = new AppState();
    this.router = new Router();
    this.themeManager = new ThemeManager();
    this.errorHandler = new ErrorHandler();
    this.keyboardShortcuts = new KeyboardShortcuts();
    this.toastNotifications = new ToastNotifications();
    
    this.pages = new Map();
    this.currentPage = null;
    
    this.init();
  }
  
  /**
   * Initialize the application
   */
  async init() {
    try {
      console.log('Initializing mem-mesh Web UI...');
      
      // Initialize theme
      this.themeManager.init();
      
      // Register pages
      this.registerPages();
      
      // Register routes
      this.registerRoutes();
      
      // Setup event listeners
      this.setupEventListeners();
      
      // Setup keyboard shortcuts
      this.setupKeyboardShortcuts();
      
      // Start router
      this.router.start();
      
      console.log('mem-mesh Web UI initialized successfully');
      
    } catch (error) {
      console.error('Failed to initialize application:', error);
      this.errorHandler.showError('Failed to initialize application', error.message);
    }
  }
  
  /**
   * Register all pages
   */
  registerPages() {
    // Only register pages that actually exist
    this.pages.set('about', AboutPage);
    this.pages.set('dashboard', DashboardPage);
    this.pages.set('search', SearchPage);
    this.pages.set('memory-detail', MemoryDetailPage);
    this.pages.set('create-memory', CreateMemoryPage);
    this.pages.set('edit-memory', EditMemoryPage);
    this.pages.set('projects', ProjectsPage);
    this.pages.set('project-detail', ProjectDetailPage);
    this.pages.set('memories', MemoriesPage);
    this.pages.set('analytics', AnalyticsPage);
    this.pages.set('settings', SettingsPage);
  }
  
  /**
   * Register all routes
   */
  registerRoutes() {
    this.router.register('/', () => this.renderPage('about'));
    this.router.register('/about', () => this.renderPage('about'));
    this.router.register('/dashboard', () => this.renderPage('dashboard'));
    this.router.register('/search', () => this.renderPage('search'));
    this.router.register('/memory/:id', (params) => this.renderPage('memory-detail', params));
    this.router.register('/create', () => this.renderPage('create-memory'));
    this.router.register('/edit/:id', (params) => this.renderPage('edit-memory', params));
    this.router.register('/projects', () => this.renderPage('projects'));
    this.router.register('/project/:id', (params) => this.renderPage('project-detail', params));
    this.router.register('/memories', () => this.renderPage('memories'));
    this.router.register('/analytics', () => this.renderPage('analytics'));
    this.router.register('/settings', () => this.renderPage('settings'));
  }
  
  /**
   * Setup global event listeners
   */
  setupEventListeners() {
    // Theme toggle
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
      themeToggle.addEventListener('click', () => {
        this.themeManager.toggle();
      });
    }
    
    // Create memory button
    const createButton = document.getElementById('create-memory');
    if (createButton) {
      createButton.addEventListener('click', () => {
        this.router.navigate('/create');
      });
    }
    
    // Navigation links
    document.addEventListener('click', (event) => {
      const link = event.target.closest('[data-route]');
      if (link) {
        event.preventDefault();
        const route = link.getAttribute('data-route');
        this.router.navigate(route);
      }
    });
    
    // Global error handling
    window.addEventListener('error', (event) => {
      console.error('Global error:', event.error);
      this.errorHandler.showError('Application Error', event.error?.message || 'An unexpected error occurred');
    });
    
    window.addEventListener('unhandledrejection', (event) => {
      console.error('Unhandled promise rejection:', event.reason);
      this.errorHandler.showError('Promise Error', event.reason?.message || 'An unexpected error occurred');
    });
  }
  
  /**
   * Setup keyboard shortcuts
   */
  setupKeyboardShortcuts() {
    document.addEventListener('keydown', (event) => {
      // Ctrl+K or Cmd+K for search
      if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
        event.preventDefault();
        this.router.navigate('/search');
        // Focus search input after navigation
        setTimeout(() => {
          const searchInput = document.querySelector('search-bar input');
          if (searchInput) {
            searchInput.focus();
          }
        }, 100);
      }
      
      // Ctrl+N or Cmd+N for new memory
      if ((event.ctrlKey || event.metaKey) && event.key === 'n') {
        event.preventDefault();
        this.router.navigate('/create');
      }
      
      // Escape to close modals/overlays
      if (event.key === 'Escape') {
        this.closeModals();
      }
    });
  }
  
  /**
   * Render a page
   */
  async renderPage(pageName, params = {}) {
    try {
      // Show loading state
      this.showLoading();
      
      // Update navigation
      this.updateNavigation(pageName);
      
      // Get page class
      const PageClass = this.pages.get(pageName);
      if (!PageClass) {
        throw new Error(`Page not found: ${pageName}`);
      }
      
      // Get or create page container
      const pageContent = document.getElementById('page-content');
      if (!pageContent) {
        throw new Error('Page content container not found');
      }
      
      // Clear existing content
      pageContent.innerHTML = '';
      
      // Create and append page element
      let pageElement;
      switch (pageName) {
        case 'about':
          pageElement = document.createElement('about-page');
          break;
        case 'dashboard':
          pageElement = document.createElement('dashboard-page');
          break;
        case 'search':
          pageElement = document.createElement('search-page');
          break;
        case 'memory-detail':
          pageElement = document.createElement('memory-detail-page');
          if (params.id) {
            pageElement.setAttribute('memory-id', params.id);
          }
          break;
        case 'create-memory':
          pageElement = document.createElement('create-memory-page');
          break;
        case 'edit-memory':
          pageElement = document.createElement('edit-memory-page');
          if (params.id) {
            pageElement.setAttribute('memory-id', params.id);
          }
          break;
        case 'projects':
          pageElement = document.createElement('projects-page');
          break;
        case 'project-detail':
          pageElement = document.createElement('project-detail-page');
          if (params.id) {
            pageElement.setAttribute('project-id', params.id);
          }
          break;
        case 'memories':
          pageElement = document.createElement('memories-page');
          break;
        case 'analytics':
          pageElement = document.createElement('analytics-page');
          break;
        case 'settings':
          pageElement = document.createElement('settings-page');
          break;
        default:
          throw new Error(`Unknown page: ${pageName}`);
      }
      
      pageContent.appendChild(pageElement);
      pageContent.classList.remove('hidden');
      
      // Hide loading state
      this.hideLoading();
      
      // Update current page
      this.currentPage = pageName;
      
      // Update app state
      this.appState.setCurrentPage(pageName);
      
    } catch (error) {
      console.error('Failed to render page:', error);
      this.hideLoading();
      this.showErrorPage(error);
    }
  }
  
  /**
   * Update navigation active state
   */
  updateNavigation(pageName) {
    const navLinks = document.querySelectorAll('.nav-link, .mobile-nav-link');
    navLinks.forEach(link => {
      link.classList.remove('active');
      const route = link.getAttribute('data-route');
      if (
        (route === '/' && pageName === 'about') ||
        (route === '/about' && pageName === 'about') ||
        (route === '/dashboard' && pageName === 'dashboard') ||
        (route === '/search' && pageName === 'search') ||
        (route === '/projects' && pageName === 'projects') ||
        (route === '/memories' && pageName === 'memories') ||
        (route === '/analytics' && pageName === 'analytics') ||
        (route === '/settings' && pageName === 'settings')
      ) {
        link.classList.add('active');
      }
    });
  }
  
  /**
   * Show loading state
   */
  showLoading() {
    const loadingState = document.getElementById('loading-state');
    const pageContent = document.getElementById('page-content');
    
    if (loadingState) loadingState.classList.remove('hidden');
    if (pageContent) pageContent.classList.add('hidden');
  }
  
  /**
   * Hide loading state
   */
  hideLoading() {
    const loadingState = document.getElementById('loading-state');
    if (loadingState) loadingState.classList.add('hidden');
  }
  
  /**
   * Show error page
   */
  showErrorPage(error) {
    const pageContent = document.getElementById('page-content');
    if (pageContent) {
      pageContent.innerHTML = `
        <div class="error-page">
          <div class="error-content">
            <h2>Something went wrong</h2>
            <p>${error.message || 'An unexpected error occurred'}</p>
            <div class="error-actions">
              <button class="primary-button" onclick="location.reload()">
                Refresh Page
              </button>
              <button class="secondary-button" onclick="history.back()">
                Go Back
              </button>
            </div>
          </div>
        </div>
      `;
      pageContent.classList.remove('hidden');
    }
  }
  
  /**
   * Close all modals and overlays
   */
  closeModals() {
    const modalContainer = document.getElementById('modal-container');
    const loadingOverlay = document.getElementById('loading-overlay');
    
    if (modalContainer) modalContainer.classList.add('hidden');
    if (loadingOverlay) loadingOverlay.classList.add('hidden');
  }
}

// Initialize application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  new App(); // window.app은 생성자에서 설정됨
});

// Export for debugging
export { App };