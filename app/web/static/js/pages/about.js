/**
 * About Page Component
 * Landing page with hero section and features overview
 */

import { HeroSection } from '../components/hero-section.js';
import { FeaturesSection } from '../components/features-section.js';

class AboutPage extends HTMLElement {
  constructor() {
    super();
    this.isInitialized = false;
  }
  
  connectedCallback() {
    if (this.isInitialized) {
      return;
    }
    
    this.isInitialized = true;
    this.render();
    this.setupEventListeners();
  }
  
  setupEventListeners() {
    // Handle CTA button clicks
    this.addEventListener('click', this.handleClick.bind(this));
  }
  
  handleClick(event) {
    const target = event.target;
    
    // Handle navigation from hero section
    if (target.classList.contains('btn-primary') || target.closest('.btn-primary')) {
      event.preventDefault();
      if (window.app && window.app.router) {
        window.app.router.navigate('/dashboard');
      }
    }
    
    // Handle secondary action (demo/search)
    if (target.classList.contains('btn-secondary') || target.closest('.btn-secondary')) {
      event.preventDefault();
      if (window.app && window.app.router) {
        window.app.router.navigate('/search');
      }
    }
    
    // Handle feature card clicks
    if (target.classList.contains('feature-link') || target.closest('.feature-link')) {
      event.preventDefault();
      const href = target.getAttribute('href') || target.closest('.feature-link').getAttribute('href');
      if (href && window.app && window.app.router) {
        window.app.router.navigate(href);
      }
    }
  }
  
  render() {
    this.className = 'about-page';
    
    this.innerHTML = `
      <!-- Hero Section -->
      <hero-section></hero-section>
      
      <!-- Features Section -->
      <features-section></features-section>
      
      <!-- Additional About Content -->
      <section class="about-content">
        <div class="container">
          <div class="about-grid">
            <div class="about-text">
              <h2>AI-Powered Memory Management</h2>
              <p>
                mem-mesh is a centralized memory server for developers and knowledge workers. 
                With advanced vector search and context retrieval, you can systematically 
                manage and connect scattered thoughts and ideas.
              </p>
              <div class="feature-highlights">
                <div class="highlight-item">
                  <svg class="highlight-icon" viewBox="0 0 24 24" fill="none">
                    <circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="2"/>
                    <path d="M21 21L16.65 16.65" stroke="currentColor" stroke-width="2"/>
                  </svg>
                  <div>
                    <h3>Semantic Search</h3>
                    <p>Find relevant information quickly with meaning-based search</p>
                  </div>
                </div>
                <div class="highlight-item">
                  <svg class="highlight-icon" viewBox="0 0 24 24" fill="none">
                    <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2"/>
                    <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2"/>
                    <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2"/>
                  </svg>
                  <div>
                    <h3>Context Awareness</h3>
                    <p>Automatically discover connections between related memories</p>
                  </div>
                </div>
                <div class="highlight-item">
                  <svg class="highlight-icon" viewBox="0 0 24 24" fill="none">
                    <path d="M18 20V10" stroke="currentColor" stroke-width="2"/>
                    <path d="M12 20V4" stroke="currentColor" stroke-width="2"/>
                    <path d="M6 20V14" stroke="currentColor" stroke-width="2"/>
                  </svg>
                  <div>
                    <h3>Analytics & Insights</h3>
                    <p>Analyze knowledge patterns through data visualization</p>
                  </div>
                </div>
              </div>
            </div>
            <div class="about-visual">
              <div class="visual-container">
                <div class="floating-elements">
                  <div class="memory-node" style="--delay: 0s">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M9 12L11 14L15 10" stroke="currentColor" stroke-width="2"/>
                      <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/>
                    </svg>
                  </div>
                  <div class="memory-node" style="--delay: 0.5s">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M9 21H15M12 3C8.68629 3 6 5.68629 6 9C6 11.973 7.818 14.441 10.5 15.5V17C10.5 17.8284 11.1716 18.5 12 18.5C12.8284 18.5 13.5 17.8284 13.5 17V15.5C16.182 14.441 18 11.973 18 9C18 5.68629 15.3137 3 12 3Z" stroke="currentColor" stroke-width="2"/>
                    </svg>
                  </div>
                  <div class="memory-node" style="--delay: 1s">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M16 18L22 12L16 6M8 6L2 12L8 18" stroke="currentColor" stroke-width="2"/>
                    </svg>
                  </div>
                  <div class="connection-line" style="--delay: 1.5s"></div>
                  <div class="connection-line" style="--delay: 2s"></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
      
      <!-- CTA Section -->
      <section class="cta-section">
        <div class="container">
          <div class="cta-content">
            <h2>Get Started Today</h2>
            <p>Manage your knowledge systematically with mem-mesh and discover new insights.</p>
            <div class="cta-actions">
              <button class="btn-primary">Go to Dashboard</button>
              <button class="btn-secondary">Try Search</button>
            </div>
          </div>
        </div>
      </section>
    `;
  }
}

// Define the custom element
customElements.define('about-page', AboutPage);

export { AboutPage };