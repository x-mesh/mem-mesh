/**
 * Features Section Component - Chroma Style
 * Landing page features section with feature cards grid
 */

// Import feature card component
import { FeatureCard } from './feature-card.js';

class FeaturesSection extends HTMLElement {
  constructor() {
    super();
    this.isInitialized = false;
    this.features = [
      {
        icon: 'vector-search',
        title: 'Vector Search',
        description: 'Find memories using AI-powered semantic search. Discover connections between ideas that traditional keyword search would miss. Our advanced vector embeddings understand context and meaning.',
        link: '/search',
        linkText: 'Try Search',
        highlight: true
      },
      {
        icon: 'organization',
        title: 'Memory Organization',
        description: 'Organize your thoughts by projects and categories. Keep your knowledge structured and easily accessible with smart tagging and automatic categorization.',
        link: '/projects',
        linkText: 'View Projects'
      },
      {
        icon: 'analytics',
        title: 'Analytics Dashboard',
        description: 'Track patterns and insights in your knowledge base. Understand how your thoughts and ideas evolve over time with beautiful visualizations and metrics.',
        link: '/analytics',
        linkText: 'View Analytics'
      },
      {
        icon: 'project-management',
        title: 'Project Management',
        description: 'Connect memories to projects and track progress. See how your ideas contribute to larger goals with integrated project workflows and collaboration tools.',
        link: '/projects',
        linkText: 'Manage Projects'
      }
    ];
  }
  
  connectedCallback() {
    if (this.isInitialized) return;
    this.isInitialized = true;
    
    this.render();
    this.setupEventListeners();
    this.setupIntersectionObserver();
    this.setupResponsiveLayout();
  }
  
  disconnectedCallback() {
    this.removeEventListeners();
    this.removeResizeListener();
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    // Listen for feature card events
    this.addEventListener('feature-card-click', this.handleFeatureCardClick.bind(this));
    this.addEventListener('feature-link-click', this.handleFeatureLinkClick.bind(this));
    
    // Footer button events
    const primaryBtn = this.querySelector('.btn-features-primary');
    const secondaryBtn = this.querySelector('.btn-features-secondary');
    
    if (primaryBtn) {
      primaryBtn.addEventListener('click', this.handlePrimaryButtonClick.bind(this));
    }
    
    if (secondaryBtn) {
      secondaryBtn.addEventListener('click', this.handleSecondaryButtonClick.bind(this));
    }
  }
  
  /**
   * Handle primary button click
   */
  handlePrimaryButtonClick(event) {
    event.preventDefault();
    
    if (window.app && window.app.router) {
      window.app.router.navigate('/create');
    }
    
    // Show toast notification
    if (window.app && window.app.toastNotifications) {
      window.app.toastNotifications.show(
        'Welcome to mem-mesh!',
        'Start creating your first memory.',
        'success'
      );
    }
  }
  
  /**
   * Handle secondary button click
   */
  handleSecondaryButtonClick(event) {
    event.preventDefault();
    
    if (window.app && window.app.router) {
      window.app.router.navigate('/search');
    }
  }
  
  /**
   * Remove event listeners
   */
  removeEventListeners() {
    this.removeEventListener('feature-card-click', this.handleFeatureCardClick);
    this.removeEventListener('feature-link-click', this.handleFeatureLinkClick);
  }
  
  /**
   * Setup intersection observer for scroll animations
   */
  setupIntersectionObserver() {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('animate-in');
          
          // Stagger animation for feature cards
          const cards = entry.target.querySelectorAll('feature-card');
          cards.forEach((card, index) => {
            setTimeout(() => {
              card.classList.add('animate-in');
            }, index * 100);
          });
        }
      });
    }, {
      threshold: 0.1,
      rootMargin: '0px 0px -50px 0px'
    });
    
    observer.observe(this);
  }
  
  /**
   * Setup responsive layout behavior
   */
  setupResponsiveLayout() {
    this.handleResize = this.handleResize.bind(this);
    window.addEventListener('resize', this.handleResize);
    
    // Initial layout check
    this.handleResize();
  }
  
  /**
   * Remove resize listener
   */
  removeResizeListener() {
    if (this.handleResize) {
      window.removeEventListener('resize', this.handleResize);
    }
  }
  
  /**
   * Handle window resize
   */
  handleResize() {
    const grid = this.querySelector('.features-grid');
    if (!grid) return;
    
    const width = window.innerWidth;
    
    // Add responsive classes based on viewport width
    grid.classList.remove('grid-mobile', 'grid-tablet', 'grid-desktop', 'grid-large');
    
    if (width < 768) {
      grid.classList.add('grid-mobile');
      this.adjustForMobile();
    } else if (width < 1200) {
      grid.classList.add('grid-tablet');
      this.adjustForTablet();
    } else if (width < 1400) {
      grid.classList.add('grid-desktop');
      this.adjustForDesktop();
    } else {
      grid.classList.add('grid-large');
      this.adjustForLarge();
    }
  }
  
  /**
   * Adjust layout for mobile
   */
  adjustForMobile() {
    const cards = this.querySelectorAll('feature-card');
    cards.forEach((card, index) => {
      // Stagger animations for mobile
      card.style.animationDelay = `${index * 0.1}s`;
    });
  }
  
  /**
   * Adjust layout for tablet
   */
  adjustForTablet() {
    const cards = this.querySelectorAll('feature-card');
    cards.forEach((card, index) => {
      // Different stagger timing for tablet
      card.style.animationDelay = `${index * 0.15}s`;
    });
  }
  
  /**
   * Adjust layout for desktop
   */
  adjustForDesktop() {
    const cards = this.querySelectorAll('feature-card');
    cards.forEach((card, index) => {
      // Standard stagger timing
      card.style.animationDelay = `${index * 0.2}s`;
    });
  }
  
  /**
   * Adjust layout for large screens
   */
  adjustForLarge() {
    const cards = this.querySelectorAll('feature-card');
    cards.forEach((card, index) => {
      // Slower stagger for large screens
      card.style.animationDelay = `${index * 0.25}s`;
    });
  }
  handleFeatureCardClick(event) {
    const { link, title } = event.detail;
    
    // Show toast notification
    if (window.app && window.app.toastNotifications) {
      window.app.toastNotifications.show(
        `Navigating to ${title}`,
        'Exploring feature...',
        'info'
      );
    }
    
    // Analytics tracking (if available)
    if (window.gtag) {
      window.gtag('event', 'feature_card_click', {
        feature_name: title,
        link: link
      });
    }
  }
  
  /**
   * Handle feature link click
   */
  handleFeatureLinkClick(event) {
    const { link, title } = event.detail;
    
    // Analytics tracking (if available)
    if (window.gtag) {
      window.gtag('event', 'feature_link_click', {
        feature_name: title,
        link: link
      });
    }
  }
  
  /**
   * Create feature cards
   */
  createFeatureCards() {
    return this.features.map(feature => `
      <feature-card
        icon="${feature.icon}"
        title="${feature.title}"
        description="${feature.description}"
        link="${feature.link}"
        link-text="${feature.linkText}"
        variant="${feature.highlight ? 'highlighted' : 'default'}"
      ></feature-card>
    `).join('');
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'features-section';
    
    this.innerHTML = `
      <div class="features-content">
        <div class="features-header">
          <h2 class="features-title">Powerful Features for Knowledge Management</h2>
          <p class="features-subtitle">
            Everything you need to capture, organize, and discover your knowledge.
            Built with AI-powered search and intuitive organization tools.
          </p>
        </div>
        
        <div class="features-grid">
          ${this.createFeatureCards()}
        </div>
        
        <div class="features-footer">
          <p class="features-footer-text">
            Ready to transform how you manage knowledge?
          </p>
          <div class="features-footer-actions">
            <button class="btn-features-primary" data-route="/create">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 5V19M5 12H19" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              Start Building Your Memory Hub
            </button>
            <button class="btn-features-secondary" data-route="/search">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="2"/>
                <path d="M21 21L16.65 16.65" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              Explore Features
            </button>
          </div>
        </div>
      </div>
    `;
  }
}

// Define the custom element
customElements.define('features-section', FeaturesSection);

export { FeaturesSection };