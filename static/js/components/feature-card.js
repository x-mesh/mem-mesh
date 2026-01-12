/**
 * Feature Card Component - Chroma Style
 * Reusable feature card with icon, title, description and action link
 */

class FeatureCard extends HTMLElement {
  constructor() {
    super();
    this.isInitialized = false;
  }
  
  static get observedAttributes() {
    return ['icon', 'title', 'description', 'link', 'link-text', 'variant'];
  }
  
  connectedCallback() {
    if (this.isInitialized) return;
    this.isInitialized = true;
    
    this.render();
    this.setupEventListeners();
    this.setupIntersectionObserver();
  }
  
  disconnectedCallback() {
    this.removeEventListeners();
  }
  
  attributeChangedCallback(name, oldValue, newValue) {
    if (this.isInitialized && oldValue !== newValue) {
      this.render();
    }
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    // Card click handler
    this.addEventListener('click', this.handleCardClick.bind(this));
    
    // Link click handler
    const link = this.querySelector('.feature-link');
    if (link) {
      link.addEventListener('click', this.handleLinkClick.bind(this));
    }
    
    // Hover effects
    this.addEventListener('mouseenter', this.handleMouseEnter.bind(this));
    this.addEventListener('mouseleave', this.handleMouseLeave.bind(this));
  }
  
  /**
   * Remove event listeners
   */
  removeEventListeners() {
    this.removeEventListener('click', this.handleCardClick);
    this.removeEventListener('mouseenter', this.handleMouseEnter);
    this.removeEventListener('mouseleave', this.handleMouseLeave);
  }
  
  /**
   * Setup intersection observer for scroll animations
   */
  setupIntersectionObserver() {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('animate-in');
        }
      });
    }, {
      threshold: 0.1,
      rootMargin: '0px 0px -50px 0px'
    });
    
    observer.observe(this);
  }
  
  /**
   * Handle card click
   */
  handleCardClick(event) {
    // Don't trigger if clicking on the link
    if (event.target.closest('.feature-link')) {
      return;
    }
    
    const link = this.getAttribute('link');
    if (link) {
      // Emit custom event
      this.dispatchEvent(new CustomEvent('feature-card-click', {
        detail: { link, title: this.getAttribute('title') },
        bubbles: true
      }));
      
      // Navigate if it's an internal route
      if (link.startsWith('/') && window.app && window.app.router) {
        window.app.router.navigate(link);
      } else if (link.startsWith('http')) {
        window.open(link, '_blank');
      }
    }
  }
  
  /**
   * Handle link click
   */
  handleLinkClick(event) {
    event.preventDefault();
    event.stopPropagation();
    
    const link = this.getAttribute('link');
    if (link) {
      // Emit custom event
      this.dispatchEvent(new CustomEvent('feature-link-click', {
        detail: { link, title: this.getAttribute('title') },
        bubbles: true
      }));
      
      // Navigate
      if (link.startsWith('/') && window.app && window.app.router) {
        window.app.router.navigate(link);
      } else if (link.startsWith('http')) {
        window.open(link, '_blank');
      }
    }
  }
  
  /**
   * Handle mouse enter
   */
  handleMouseEnter() {
    const icon = this.querySelector('.feature-icon');
    const link = this.querySelector('.feature-link');
    
    if (icon) {
      icon.style.transform = 'scale(1.1) translateY(-2px)';
    }
    
    if (link) {
      link.style.transform = 'translateX(4px)';
    }
  }
  
  /**
   * Handle mouse leave
   */
  handleMouseLeave() {
    const icon = this.querySelector('.feature-icon');
    const link = this.querySelector('.feature-link');
    
    if (icon) {
      icon.style.transform = '';
    }
    
    if (link) {
      link.style.transform = '';
    }
  }
  
  /**
   * Get icon SVG based on icon name
   */
  getIconSVG(iconName) {
    const icons = {
      'vector-search': `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M21 16V8C20.9996 7.64928 20.9071 7.30481 20.7315 7.00116C20.556 6.69751 20.3037 6.44536 20 6.27L13 2.27C12.696 2.09446 12.3511 2.00205 12 2.00205C11.6489 2.00205 11.304 2.09446 11 2.27L4 6.27C3.69626 6.44536 3.44398 6.69751 3.26846 7.00116C3.09294 7.30481 3.00036 7.64928 3 8V16C3.00036 16.3507 3.09294 16.6952 3.26846 16.9988C3.44398 17.3025 3.69626 17.5546 4 17.73L11 21.73C11.304 21.9055 11.6489 21.9979 12 21.9979C12.3511 21.9979 12.696 21.9055 13 21.73L20 17.73C20.3037 17.5546 20.556 17.3025 20.7315 16.9988C20.9071 16.6952 20.9996 16.3507 21 16Z" stroke="currentColor" stroke-width="2"/>
          <circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2"/>
          <path d="M12 1V3M12 21V23M4.22 4.22L5.64 5.64M18.36 18.36L19.78 19.78M1 12H3M21 12H23M4.22 19.78L5.64 18.36M18.36 5.64L19.78 4.22" stroke="currentColor" stroke-width="1" opacity="0.5"/>
        </svg>
      `,
      'organization': `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M22 19C22 19.5304 21.7893 20.0391 21.4142 20.4142C21.0391 20.7893 20.5304 21 20 21H4C3.46957 21 2.96086 20.7893 2.58579 20.4142C2.21071 20.0391 2 19.5304 2 19V5C2 4.46957 2.21071 3.96086 2.58579 3.58579C2.96086 3.21071 3.46957 3 4 3H9L11 6H20C20.5304 6 21.0391 6.21071 21.4142 6.58579C21.7893 6.96086 22 7.46957 22 8V19Z" stroke="currentColor" stroke-width="2"/>
          <path d="M6 10H18M6 14H18M6 18H12" stroke="currentColor" stroke-width="1.5" opacity="0.6"/>
        </svg>
      `,
      'analytics': `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M3 3V21H21V3H3Z" stroke="currentColor" stroke-width="2"/>
          <path d="M7 12L12 7L17 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          <circle cx="7" cy="12" r="1" fill="currentColor"/>
          <circle cx="12" cy="7" r="1" fill="currentColor"/>
          <circle cx="17" cy="12" r="1" fill="currentColor"/>
          <path d="M7 16H17" stroke="currentColor" stroke-width="1" opacity="0.4"/>
          <path d="M7 18H14" stroke="currentColor" stroke-width="1" opacity="0.4"/>
        </svg>
      `,
      'project-management': `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M9 12L11 14L15 10M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" stroke-width="2"/>
          <path d="M12 6V8M12 16V18M6 12H8M16 12H18" stroke="currentColor" stroke-width="1" opacity="0.5"/>
        </svg>
      `,
      'search': `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="2"/>
          <path d="M21 21L16.65 16.65" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          <circle cx="11" cy="11" r="3" stroke="currentColor" stroke-width="1" opacity="0.4"/>
        </svg>
      `,
      'memory': `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M9 21H15M12 3C8.68629 3 6 5.68629 6 9C6 11.973 7.818 14.441 10.5 15.5V17C10.5 17.8284 11.1716 18.5 12 18.5C12.8284 18.5 13.5 17.8284 13.5 17V15.5C16.182 14.441 18 11.973 18 9C18 5.68629 15.3137 3 12 3Z" stroke="currentColor" stroke-width="2"/>
          <path d="M12 7V11" stroke="currentColor" stroke-width="1.5" opacity="0.6"/>
          <circle cx="12" cy="9" r="1" fill="currentColor" opacity="0.6"/>
        </svg>
      `,
      'ai': `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
          <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
          <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
          <circle cx="12" cy="7" r="1" fill="currentColor"/>
          <circle cx="12" cy="12" r="1" fill="currentColor"/>
          <circle cx="12" cy="17" r="1" fill="currentColor"/>
        </svg>
      `,
      'collaboration': `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M17 21V19C17 17.9391 16.5786 16.9217 15.8284 16.1716C15.0783 15.4214 14.0609 15 13 15H5C3.93913 15 2.92172 15.4214 2.17157 16.1716C1.42143 16.9217 1 17.9391 1 19V21" stroke="currentColor" stroke-width="2"/>
          <circle cx="9" cy="7" r="4" stroke="currentColor" stroke-width="2"/>
          <path d="M23 21V19C23 18.1645 22.7155 17.3541 22.2094 16.6977C21.7033 16.0414 20.9999 15.5759 20.2 15.3805" stroke="currentColor" stroke-width="2"/>
          <path d="M16 3.13C16.8003 3.32548 17.5037 3.79099 18.0098 4.44738C18.5159 5.10376 18.8004 5.91421 18.8004 6.75C18.8004 7.58579 18.5159 8.39624 18.0098 9.05262C17.5037 9.70901 16.8003 10.1745 16 10.37" stroke="currentColor" stroke-width="2"/>
        </svg>
      `
    };
    
    return icons[iconName] || icons['memory'];
  }
  
  /**
   * Render the component
   */
  render() {
    const icon = this.getAttribute('icon') || 'memory';
    const title = this.getAttribute('title') || 'Feature';
    const description = this.getAttribute('description') || 'Feature description';
    const link = this.getAttribute('link') || '#';
    const linkText = this.getAttribute('link-text') || 'Learn more';
    const variant = this.getAttribute('variant') || 'default';
    
    this.className = `feature-card ${variant}`;
    
    this.innerHTML = `
      <div class="feature-header">
        <div class="feature-icon">
          ${this.getIconSVG(icon)}
        </div>
        <h3 class="feature-title">${title}</h3>
      </div>
      
      <p class="feature-description">${description}</p>
      
      <a href="${link}" class="feature-link">
        ${linkText}
        <svg class="arrow-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M5 12H19M19 12L12 5M19 12L12 19" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </a>
    `;
  }
}

// Define the custom element
customElements.define('feature-card', FeatureCard);

export { FeatureCard };