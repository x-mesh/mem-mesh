/**
 * Hero Section Component - Chroma Style
 * Landing page hero section with gradient text and floating animations
 */

class HeroSection extends HTMLElement {
  constructor() {
    super();
    this.isInitialized = false;
  }
  
  connectedCallback() {
    if (this.isInitialized) return;
    this.isInitialized = true;
    
    this.render();
    this.setupEventListeners();
    this.startAnimations();
    this.addMicroInteractions();
  }
  
  disconnectedCallback() {
    this.removeEventListeners();
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    // Primary action button
    const primaryBtn = this.querySelector('.btn-hero-primary');
    if (primaryBtn) {
      primaryBtn.addEventListener('click', this.handlePrimaryAction.bind(this));
    }
    
    // Secondary action button
    const secondaryBtn = this.querySelector('.btn-hero-secondary');
    if (secondaryBtn) {
      secondaryBtn.addEventListener('click', this.handleSecondaryAction.bind(this));
    }
    
    // Floating cards interaction
    const floatingCards = this.querySelectorAll('.floating-card');
    floatingCards.forEach(card => {
      card.addEventListener('mouseenter', this.handleCardHover.bind(this));
      card.addEventListener('mouseleave', this.handleCardLeave.bind(this));
    });
  }
  
  /**
   * Remove event listeners
   */
  removeEventListeners() {
    const primaryBtn = this.querySelector('.btn-hero-primary');
    const secondaryBtn = this.querySelector('.btn-hero-secondary');
    
    if (primaryBtn) {
      primaryBtn.removeEventListener('click', this.handlePrimaryAction);
    }
    
    if (secondaryBtn) {
      secondaryBtn.removeEventListener('click', this.handleSecondaryAction);
    }
  }
  
  /**
   * Handle primary action (Get Started)
   */
  handlePrimaryAction(event) {
    event.preventDefault();
    
    // Navigate to dashboard or create memory
    if (window.app && window.app.router) {
      window.app.router.navigate('/create');
    }
    
    // Show toast notification
    if (window.app && window.app.toastNotifications) {
      window.app.toastNotifications.show('Welcome to mem-mesh!', 'Start creating your first memory.', 'success');
    }
  }
  
  /**
   * Handle secondary action (View Demo)
   */
  handleSecondaryAction(event) {
    event.preventDefault();
    
    // Navigate to search page with demo query
    if (window.app && window.app.router) {
      window.app.router.navigate('/search?demo=true');
    }
  }
  
  /**
   * Handle floating card hover
   */
  handleCardHover(event) {
    const card = event.currentTarget;
    card.style.transform = 'translateY(-10px) scale(1.05)';
    card.style.opacity = '1';
  }
  
  /**
   * Handle floating card leave
   */
  handleCardLeave(event) {
    const card = event.currentTarget;
    card.style.transform = '';
    card.style.opacity = '0.8';
  }
  
  /**
   * Start floating animations and particle effects
   */
  startAnimations() {
    const cards = this.querySelectorAll('.floating-card');
    
    cards.forEach((card, index) => {
      // Add staggered animation delays
      card.style.animationDelay = `${index * 2}s`;
      
      // Add subtle parallax effect on scroll
      window.addEventListener('scroll', () => {
        const scrolled = window.pageYOffset;
        const rate = scrolled * -0.2;
        card.style.transform = `translateY(${rate}px)`;
      });
    });
    
    // Create particle animation
    this.createParticles();
    
    // Add intersection observer for animations
    this.setupIntersectionObserver();
  }
  
  /**
   * Create floating particles
   */
  createParticles() {
    const particlesContainer = this.querySelector('.hero-particles');
    if (!particlesContainer) return;
    
    // Clear existing particles
    particlesContainer.innerHTML = '';
    
    // Create 15 particles for better coverage
    for (let i = 0; i < 15; i++) {
      const particle = document.createElement('div');
      particle.className = 'particle';
      
      // Random properties for variety
      const size = Math.random() * 6 + 3; // 3-9px
      const opacity = Math.random() * 0.4 + 0.2; // 0.2-0.6
      const duration = Math.random() * 15 + 10; // 10-25s
      const left = Math.random() * 100; // 0-100%
      const delay = Math.random() * 10; // 0-10s
      
      particle.style.cssText = `
        position: absolute;
        width: ${size}px;
        height: ${size}px;
        background: var(--primary-500);
        border-radius: 50%;
        opacity: ${opacity};
        left: ${left}%;
        bottom: -20px;
        animation: particleFloat ${duration}s linear infinite;
        animation-delay: ${delay}s;
      `;
      
      particlesContainer.appendChild(particle);
    }
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
    
    // Observe hero elements
    const heroTitle = this.querySelector('.hero-title');
    const heroDescription = this.querySelector('.hero-description');
    const heroActions = this.querySelector('.hero-actions');
    const heroVisual = this.querySelector('.hero-visual');
    
    [heroTitle, heroDescription, heroActions, heroVisual].forEach(el => {
      if (el) observer.observe(el);
    });
  }
  
  /**
   * Add micro-interactions to buttons
   */
  addMicroInteractions() {
    const buttons = this.querySelectorAll('.btn-hero-primary, .btn-hero-secondary');
    
    buttons.forEach(button => {
      // Add ripple effect on click
      button.addEventListener('click', (e) => {
        const ripple = document.createElement('span');
        const rect = button.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const x = e.clientX - rect.left - size / 2;
        const y = e.clientY - rect.top - size / 2;
        
        ripple.style.width = ripple.style.height = size + 'px';
        ripple.style.left = x + 'px';
        ripple.style.top = y + 'px';
        ripple.classList.add('ripple');
        
        button.appendChild(ripple);
        
        setTimeout(() => {
          ripple.remove();
        }, 600);
      });
      
      // Add magnetic effect
      button.addEventListener('mousemove', (e) => {
        const rect = button.getBoundingClientRect();
        const x = e.clientX - rect.left - rect.width / 2;
        const y = e.clientY - rect.top - rect.height / 2;
        
        button.style.transform = `translate(${x * 0.1}px, ${y * 0.1}px)`;
      });
      
      button.addEventListener('mouseleave', () => {
        button.style.transform = '';
      });
    });
  }
  
  /**
   * Create floating memory cards
   */
  createFloatingCards() {
    return `
      <div class="floating-cards">
        <div class="floating-card">
          <div class="floating-card-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M21 16V8C20.9996 7.64928 20.9071 7.30481 20.7315 7.00116C20.556 6.69751 20.3037 6.44536 20 6.27L13 2.27C12.696 2.09446 12.3511 2.00205 12 2.00205C11.6489 2.00205 11.304 2.09446 11 2.27L4 6.27C3.69626 6.44536 3.44398 6.69751 3.26846 7.00116C3.09294 7.30481 3.00036 7.64928 3 8V16C3.00036 16.3507 3.09294 16.6952 3.26846 16.9988C3.44398 17.3025 3.69626 17.5546 4 17.73L11 21.73C11.304 21.9055 11.6489 21.9979 12 21.9979C12.3511 21.9979 12.696 21.9055 13 21.73L20 17.73C20.3037 17.5546 20.556 17.3025 20.7315 16.9988C20.9071 16.6952 20.9996 16.3507 21 16Z" stroke="currentColor" stroke-width="2"/>
              <path d="M7.5 4.21L12 6.81L16.5 4.21M12 22.08V12M12 6.81L3.27 2.04" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <div class="floating-card-title">Vector Search</div>
          <div class="floating-card-text">Find memories using AI-powered semantic search</div>
        </div>
        
        <div class="floating-card">
          <div class="floating-card-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M22 19C22 19.5304 21.7893 20.0391 21.4142 20.4142C21.0391 20.7893 20.5304 21 20 21H4C3.46957 21 2.96086 20.7893 2.58579 20.4142C2.21071 20.0391 2 19.5304 2 19V5C2 4.46957 2.21071 3.96086 2.58579 3.58579C2.96086 3.21071 3.46957 3 4 3H9L11 6H20C20.5304 6 21.0391 6.21071 21.4142 6.58579C21.7893 6.96086 22 7.46957 22 8V19Z" stroke="currentColor" stroke-width="2"/>
            </svg>
          </div>
          <div class="floating-card-title">Organization</div>
          <div class="floating-card-text">Organize memories by projects and categories</div>
        </div>
        
        <div class="floating-card">
          <div class="floating-card-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M3 3V21H21V3H3Z" stroke="currentColor" stroke-width="2"/>
              <path d="M9 9H15M9 13H15M9 17H15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            </svg>
          </div>
          <div class="floating-card-title">Analytics</div>
          <div class="floating-card-text">Track patterns and insights in your knowledge</div>
        </div>
      </div>
    `;
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'hero-section';
    
    this.innerHTML = `
      <!-- Animated background particles -->
      <div class="hero-particles"></div>
      
      <div class="hero-content">
        <h1 class="hero-title">
          Mem-Mesh:
          <span class="gradient-text">One Context. Any Tool.</span>
        </h1>
        
        <p class="hero-description">
          Store, search, and analyze your thoughts with advanced vector search.
          Transform scattered notes into organized knowledge that grows with you.
        </p>
        
        <div class="hero-actions">
          <button class="btn-hero-primary">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 5V19M5 12H19" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            Get Started
          </button>
          
          <button class="btn-hero-secondary">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M8 5V19L21 12L8 5Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
            </svg>
            View Demo
          </button>
        </div>
        
        <div class="hero-visual">
          ${this.createFloatingCards()}
        </div>
      </div>
    `;
  }
}

// Define the custom element
customElements.define('hero-section', HeroSection);

export { HeroSection };