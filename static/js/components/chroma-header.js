/**
 * Chroma-style Header Component
 * Clean, modern header with navigation and user actions
 */
class ChromaHeader extends HTMLElement {
  constructor() {
    super();
    this.isScrolled = false;
    this.isMobileMenuOpen = false;
  }

  connectedCallback() {
    this.render();
    this.setupEventListeners();
    this.setupScrollBehavior();
  }

  render() {
    this.innerHTML = `
      <header class="chroma-header" id="chroma-header">
        <div class="header-container">
          <!-- Logo Section -->
          <div class="header-logo">
            <a href="/about" class="logo-link" data-route="/about">
              <svg class="logo-icon" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M16 4L4 10L16 16L28 10L16 4Z" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>
                <path d="M4 22L16 28L28 22" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>
                <path d="M4 16L16 22L28 16" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>
              </svg>
              <span class="logo-text">mem-mesh</span>
            </a>
          </div>

          <!-- Navigation Menu -->
          <nav class="header-nav" id="header-nav">
            <div class="nav-links">
              <a href="/dashboard" class="nav-link" data-route="/dashboard" data-nav="dashboard">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none">
                  <path d="M3 9L12 2L21 9V20C21 20.5304 20.7893 21.0391 20.4142 21.4142C20.0391 21.7893 19.5304 22 19 22H5C4.46957 22 3.96086 21.7893 3.58579 21.4142C3.21071 21.0391 3 20.5304 3 20V9Z" stroke="currentColor" stroke-width="2"/>
                  <path d="M9 22V12H15V22" stroke="currentColor" stroke-width="2"/>
                </svg>
                <span>Dashboard</span>
              </a>
              <a href="/search" class="nav-link" data-route="/search" data-nav="search">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none">
                  <circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="2"/>
                  <path d="M21 21L16.65 16.65" stroke="currentColor" stroke-width="2"/>
                </svg>
                <span>Search</span>
              </a>
              <a href="/projects" class="nav-link" data-route="/projects" data-nav="projects">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none">
                  <path d="M22 19C22 19.5304 21.7893 20.0391 21.4142 20.4142C21.0391 20.7893 20.5304 21 20 21H4C3.46957 21 2.96086 20.7893 2.58579 20.4142C2.21071 20.0391 2 19.5304 2 19V5C2 4.46957 2.21071 3.96086 2.58579 3.58579C2.96086 3.21071 3.46957 3 4 3H9L11 6H20C20.5304 6 21.0391 6.21071 21.4142 6.58579C21.7893 6.96086 22 7.46957 22 8V19Z" stroke="currentColor" stroke-width="2"/>
                </svg>
                <span>Projects</span>
              </a>
              <a href="/work" class="nav-link" data-route="/work" data-nav="work">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none">
                  <path d="M9 11L12 14L22 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  <path d="M21 12V19C21 19.5304 20.7893 20.0391 20.4142 20.4142C20.0391 20.7893 19.5304 21 19 21H5C4.46957 21 3.96086 20.7893 3.58579 20.4142C3.21071 20.0391 3 19.5304 3 19V5C3 4.46957 3.21071 3.96086 3.58579 3.58579C3.96086 3.21071 4.46957 3 5 3H16" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span>Work</span>
              </a>
              <a href="/analytics" class="nav-link" data-route="/analytics" data-nav="analytics">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none">
                  <path d="M18 20V10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                  <path d="M12 20V4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                  <path d="M6 20V14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                </svg>
                <span>Analytics</span>
              </a>
              <a href="/monitoring" class="nav-link" data-route="/monitoring" data-nav="monitoring">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none">
                  <path d="M3 3V21H21" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  <path d="M7 16L12 11L16 15L21 10" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span>Monitoring</span>
              </a>
              <a href="/settings" class="nav-link" data-route="/settings" data-nav="settings">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2"/>
                  <path d="M19.4 15C19.2669 15.3016 19.2272 15.6362 19.286 15.9606C19.3448 16.285 19.4995 16.5843 19.73 16.82L19.79 16.88C19.976 17.0657 20.1235 17.2863 20.2241 17.5291C20.3248 17.7719 20.3766 18.0322 20.3766 18.295C20.3766 18.5578 20.3248 18.8181 20.2241 19.0609C20.1235 19.3037 19.976 19.5243 19.79 19.71C19.6043 19.896 19.3837 20.0435 19.1409 20.1441C18.8981 20.2448 18.6378 20.2966 18.375 20.2966C18.1122 20.2966 17.8519 20.2448 17.6091 20.1441C17.3663 20.0435 17.1457 19.896 16.96 19.71L16.9 19.65C16.6643 19.4195 16.365 19.2648 16.0406 19.206C15.7162 19.1472 15.3816 19.1869 15.08 19.32C14.7842 19.4468 14.532 19.6572 14.3543 19.9255C14.1766 20.1938 14.0813 20.5082 14.08 20.83V21C14.08 21.5304 13.8693 22.0391 13.4942 22.4142C13.1191 22.7893 12.6104 23 12.08 23C11.5496 23 11.0409 22.7893 10.6658 22.4142C10.2907 22.0391 10.08 21.5304 10.08 21V20.91C10.0723 20.579 9.96512 20.2573 9.77251 19.9887C9.5799 19.7201 9.31074 19.5176 9 19.41C8.69838 19.2769 8.36381 19.2372 8.03941 19.296C7.71502 19.3548 7.41568 19.5095 7.18 19.74L7.12 19.8C6.93425 19.986 6.71368 20.1335 6.47088 20.2341C6.22808 20.3348 5.96783 20.3866 5.705 20.3866C5.44217 20.3866 5.18192 20.3348 4.93912 20.2341C4.69632 20.1335 4.47575 19.986 4.29 19.8C4.10405 19.6143 3.95653 19.3937 3.85588 19.1509C3.75523 18.9081 3.70343 18.6478 3.70343 18.385C3.70343 18.1222 3.75523 17.8619 3.85588 17.6191C3.95653 17.3763 4.10405 17.1557 4.29 16.97L4.35 16.91C4.58054 16.6743 4.73519 16.375 4.794 16.0506C4.85282 15.7262 4.81312 15.3916 4.68 15.09C4.55324 14.7942 4.34276 14.542 4.07447 14.3643C3.80618 14.1866 3.49179 14.0913 3.17 14.09H3C2.46957 14.09 1.96086 13.8793 1.58579 13.5042C1.21071 13.1291 1 12.6204 1 12.09C1 11.5596 1.21071 11.0509 1.58579 10.6758C1.96086 10.3007 2.46957 10.09 3 10.09H3.09C3.42099 10.0823 3.742 9.97512 4.01062 9.78251C4.27925 9.5899 4.48167 9.32074 4.59 9.01C4.72312 8.70838 4.76282 8.37381 4.704 8.04941C4.64519 7.72502 4.49054 7.42568 4.26 7.19L4.2 7.13C4.01405 6.94425 3.86653 6.72368 3.76588 6.48088C3.66523 6.23808 3.61343 5.97783 3.61343 5.715C3.61343 5.45217 3.66523 5.19192 3.76588 4.94912C3.86653 4.70632 4.01405 4.48575 4.2 4.3C4.38575 4.11405 4.60632 3.96653 4.84912 3.86588C5.09192 3.76523 5.35217 3.71343 5.615 3.71343C5.87783 3.71343 6.13808 3.76523 6.38088 3.86588C6.62368 3.96653 6.84425 4.11405 7.03 4.3L7.09 4.36C7.32568 4.59054 7.62502 4.74519 7.94941 4.804C8.27381 4.86282 8.60838 4.82312 8.91 4.69H9C9.29577 4.56324 9.54802 4.35276 9.72569 4.08447C9.90337 3.81618 9.99872 3.50179 10 3.18V3C10 2.46957 10.2107 1.96086 10.5858 1.58579C10.9609 1.21071 11.4696 1 12 1C12.5304 1 13.0391 1.21071 13.4142 1.58579C13.7893 1.96086 14 2.46957 14 3V3.09C14.0013 3.41179 14.0966 3.72618 14.2743 3.99447C14.452 4.26276 14.7042 4.47324 15 4.6C15.3016 4.73312 15.6362 4.77282 15.9606 4.714C16.285 4.65519 16.5843 4.50054 16.82 4.27L16.88 4.21C17.0657 4.02405 17.2863 3.87653 17.5291 3.77588C17.7719 3.67523 18.0322 3.62343 18.295 3.62343C18.5578 3.62343 18.8181 3.67523 19.0609 3.77588C19.3037 3.87653 19.5243 4.02405 19.71 4.21C19.896 4.39575 20.0435 4.61632 20.1441 4.85912C20.2448 5.10192 20.2966 5.36217 20.2966 5.625C20.2966 5.88783 20.2448 6.14808 20.1441 6.39088C20.0435 6.63368 19.896 6.85425 19.71 7.04L19.65 7.1C19.4195 7.33568 19.2648 7.63502 19.206 7.95941C19.1472 8.28381 19.1869 8.61838 19.32 8.92V9C19.4468 9.29577 19.6572 9.54802 19.9255 9.72569C20.1938 9.90337 20.5082 9.99872 20.83 10H21C21.5304 10 22.0391 10.2107 22.4142 10.5858C22.7893 10.9609 23 11.4696 23 12C23 12.5304 22.7893 13.0391 22.4142 13.4142C22.0391 13.7893 21.5304 14 21 14H20.91C20.5882 14.0013 20.2738 14.0966 20.0055 14.2743C19.7372 14.452 19.5268 14.7042 19.4 15Z" stroke="currentColor" stroke-width="2"/>
                </svg>
                <span>Settings</span>
              </a>
            </div>
          </nav>

          <!-- User Actions -->
          <div class="header-actions">
            <!-- Search Button (Mobile) -->
            <!--
            <button class="action-btn search-btn mobile-only" id="mobile-search-btn" title="Search">
              <svg viewBox="0 0 24 24" fill="none">
                <circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="2"/>
                <path d="M21 21L16.65 16.65" stroke="currentColor" stroke-width="2"/>
              </svg>
            </button>
            -->

            <!-- Theme Toggle -->
            <button class="action-btn theme-toggle" id="theme-toggle-btn" title="Toggle theme">
              <svg class="theme-icon sun-icon" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="5" stroke="currentColor" stroke-width="2"/>
                <path d="M12 1V3M12 21V23M4.22 4.22L5.64 5.64M18.36 18.36L19.78 19.78M1 12H3M21 12H23M4.22 19.78L5.64 18.36M18.36 5.64L19.78 4.22" stroke="currentColor" stroke-width="2"/>
              </svg>
              <svg class="theme-icon moon-icon" viewBox="0 0 24 24" fill="none">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" stroke="currentColor" stroke-width="2"/>
              </svg>
            </button>

            <!-- Profile/User Menu -->
            <!--
            <div class="user-menu" id="user-menu">
              <button class="action-btn user-btn" id="user-menu-btn" title="User menu">
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M20 21V19C20 17.9391 19.5786 16.9217 18.8284 16.1716C18.0783 15.4214 17.0609 15 16 15H8C6.93913 15 5.92172 15.4214 5.17157 16.1716C4.42143 16.9217 4 17.9391 4 19V21" stroke="currentColor" stroke-width="2"/>
                  <circle cx="12" cy="7" r="4" stroke="currentColor" stroke-width="2"/>
                </svg>
              </button>
              <div class="user-dropdown" id="user-dropdown">
                <div class="dropdown-header">
                  <div class="user-info">
                    <div class="user-avatar">
                      <svg viewBox="0 0 24 24" fill="none">
                        <circle cx="12" cy="7" r="4" stroke="currentColor" stroke-width="2"/>
                        <path d="M6 21V19C6 16.7909 7.79086 15 10 15H14C16.2091 15 18 16.7909 18 19V21" stroke="currentColor" stroke-width="2"/>
                      </svg>
                    </div>
                    <div class="user-details">
                      <div class="user-name">User</div>
                      <div class="user-email">user@example.com</div>
                    </div>
                  </div>
                </div>
                <div class="dropdown-divider"></div>
                <div class="dropdown-menu">
                  <a href="/profile" class="dropdown-item" data-route="/profile">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M20 21V19C20 17.9391 19.5786 16.9217 18.8284 16.1716C18.0783 15.4214 17.0609 15 16 15H8C6.93913 15 5.92172 15.4214 5.17157 16.1716C4.42143 16.9217 4 17.9391 4 19V21" stroke="currentColor" stroke-width="2"/>
                      <circle cx="12" cy="7" r="4" stroke="currentColor" stroke-width="2"/>
                    </svg>
                    Profile
                  </a>
                  <a href="/settings" class="dropdown-item" data-route="/settings">
                    <svg viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2"/>
                      <path d="M19.4 15C19.2669 15.3016 19.2272 15.6362 19.286 15.9606C19.3448 16.285 19.4995 16.5843 19.73 16.82L19.79 16.88C19.976 17.0657 20.1235 17.2863 20.2241 17.5291C20.3248 17.7719 20.3766 18.0322 20.3766 18.295C20.3766 18.5578 20.3248 18.8181 20.2241 19.0609C20.1235 19.3037 19.976 19.5243 19.79 19.71C19.6043 19.896 19.3837 20.0435 19.1409 20.1441C18.8981 20.2448 18.6378 20.2966 18.375 20.2966C18.1122 20.2966 17.8519 20.2448 17.6091 20.1441C17.3663 20.0435 17.1457 19.896 16.96 19.71L16.9 19.65C16.6643 19.4195 16.365 19.2648 16.0406 19.206C15.7162 19.1472 15.3816 19.1869 15.08 19.32C14.7842 19.4468 14.532 19.6572 14.3543 19.9255C14.1766 20.1938 14.0813 20.5082 14.08 20.83V21C14.08 21.5304 13.8693 22.0391 13.4942 22.4142C13.1191 22.7893 12.6104 23 12.08 23C11.5496 23 11.0409 22.7893 10.6658 22.4142C10.2907 22.0391 10.08 21.5304 10.08 21V20.91C10.0723 20.579 9.96512 20.2573 9.77251 19.9887C9.5799 19.7201 9.31074 19.5176 9 19.41C8.69838 19.2769 8.36381 19.2372 8.03941 19.296C7.71502 19.3548 7.41568 19.5095 7.18 19.74L7.12 19.8C6.93425 19.986 6.71368 20.1335 6.47088 20.2341C6.22808 20.3348 5.96783 20.3866 5.705 20.3866C5.44217 20.3866 5.18192 20.3348 4.93912 20.2341C4.69632 20.1335 4.47575 19.986 4.29 19.8C4.10405 19.6143 3.95653 19.3937 3.85588 19.1509C3.75523 18.9081 3.70343 18.6478 3.70343 18.385C3.70343 18.1222 3.75523 17.8619 3.85588 17.6191C3.95653 17.3763 4.10405 17.1557 4.29 16.97L4.35 16.91C4.58054 16.6743 4.73519 16.375 4.794 16.0506C4.85282 15.7262 4.81312 15.3916 4.68 15.09C4.55324 14.7942 4.34276 14.542 4.07447 14.3643C3.80618 14.1866 3.49179 14.0913 3.17 14.09H3C2.46957 14.09 1.96086 13.8793 1.58579 13.5042C1.21071 13.1291 1 12.6204 1 12.09C1 11.5596 1.21071 11.0509 1.58579 10.6758C1.96086 10.3007 2.46957 10.09 3 10.09H3.09C3.42099 10.0823 3.742 9.97512 4.01062 9.78251C4.27925 9.5899 4.48167 9.32074 4.59 9.01C4.72312 8.70838 4.76282 8.37381 4.704 8.04941C4.64519 7.72502 4.49054 7.42568 4.26 7.19L4.2 7.13C4.01405 6.94425 3.86653 6.72368 3.76588 6.48088C3.66523 6.23808 3.61343 5.97783 3.61343 5.715C3.61343 5.45217 3.66523 5.19192 3.76588 4.94912C3.86653 4.70632 4.01405 4.48575 4.2 4.3C4.38575 4.11405 4.60632 3.96653 4.84912 3.86588C5.09192 3.76523 5.35217 3.71343 5.615 3.71343C5.87783 3.71343 6.13808 3.76523 6.38088 3.86588C6.62368 3.96653 6.84425 4.11405 7.03 4.3L7.09 4.36C7.32568 4.59054 7.62502 4.74519 7.94941 4.804C8.27381 4.86282 8.60838 4.82312 8.91 4.69H9C9.29577 4.56324 9.54802 4.35276 9.72569 4.08447C9.90337 3.81618 9.99872 3.50179 10 3.18V3C10 2.46957 10.2107 1.96086 10.5858 1.58579C10.9609 1.21071 11.4696 1 12 1C12.5304 1 13.0391 1.21071 13.4142 1.58579C13.7893 1.96086 14 2.46957 14 3V3.09C14.0013 3.41179 14.0966 3.72618 14.2743 3.99447C14.452 4.26276 14.7042 4.47324 15 4.6C15.3016 4.73312 15.6362 4.77282 15.9606 4.714C16.285 4.65519 16.5843 4.50054 16.82 4.27L16.88 4.21C17.0657 4.02405 17.2863 3.87653 17.5291 3.77588C17.7719 3.67523 18.0322 3.62343 18.295 3.62343C18.5578 3.62343 18.8181 3.67523 19.0609 3.77588C19.3037 3.87653 19.5243 4.02405 19.71 4.21C19.896 4.39575 20.0435 4.61632 20.1441 4.85912C20.2448 5.10192 20.2966 5.36217 20.2966 5.625C20.2966 5.88783 20.2448 6.14808 20.1441 6.39088C20.0435 6.63368 19.896 6.85425 19.71 7.04L19.65 7.1C19.4195 7.33568 19.2648 7.63502 19.206 7.95941C19.1472 8.28381 19.1869 8.61838 19.32 8.92V9C19.4468 9.29577 19.6572 9.54802 19.9255 9.72569C20.1938 9.90337 20.5082 9.99872 20.83 10H21C21.5304 10 22.0391 10.2107 22.4142 10.5858C22.7893 10.9609 23 11.4696 23 12C23 12.5304 22.7893 13.0391 22.4142 13.4142C22.0391 13.7893 21.5304 14 21 14H20.91C20.5882 14.0013 20.2738 14.0966 20.0055 14.2743C19.7372 14.452 19.5268 14.7042 19.4 15Z" stroke="currentColor" stroke-width="2"/>
                    </svg>
                    Settings
                  </a>
                  <div class="dropdown-divider"></div>
                  <button class="dropdown-item logout-btn" id="logout-btn">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M9 21H5C4.46957 21 3.96086 20.7893 3.58579 20.4142C3.21071 20.0391 3 19.5304 3 19V5C3 4.46957 3.21071 3.96086 3.58579 3.58579C3.96086 3.21071 4.46957 3 5 3H9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                      <path d="M16 17L21 12L16 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                      <path d="M21 12H9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    Sign out
                  </button>
                </div>
              </div>
            </div>
            -->

            <!-- Mobile Menu Toggle -->
            <button class="action-btn mobile-menu-toggle mobile-only" id="mobile-menu-toggle" title="Menu">
              <svg class="hamburger-icon" viewBox="0 0 24 24" fill="none">
                <path d="M3 12H21M3 6H21M3 18H21" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
              <svg class="close-icon" viewBox="0 0 24 24" fill="none">
                <path d="M18 6L6 18M6 6L18 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>

            <!-- Create Memory Button -->
            <button class="btn-primary create-memory-btn" id="create-memory-btn" data-route="/create">
              <svg viewBox="0 0 24 24" fill="none">
                <path d="M12 5V19M5 12H19" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <span class="btn-text">New Memory</span>
            </button>
          </div>
        </div>

        <!-- Mobile Navigation Overlay -->
        <div class="mobile-nav-overlay" id="mobile-nav-overlay">
          <nav class="mobile-nav" id="mobile-nav">
            <div class="mobile-nav-links">
              <a href="/dashboard" class="mobile-nav-link" data-route="/dashboard" data-nav="dashboard">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none">
                  <path d="M3 9L12 2L21 9V20C21 20.5304 20.7893 21.0391 20.4142 21.4142C20.0391 21.7893 19.5304 22 19 22H5C4.46957 22 3.96086 21.7893 3.58579 21.4142C3.21071 21.0391 3 20.5304 3 20V9Z" stroke="currentColor" stroke-width="2"/>
                  <path d="M9 22V12H15V22" stroke="currentColor" stroke-width="2"/>
                </svg>
                <span>Dashboard</span>
              </a>
              <a href="/search" class="mobile-nav-link" data-route="/search" data-nav="search">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none">
                  <circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="2"/>
                  <path d="M21 21L16.65 16.65" stroke="currentColor" stroke-width="2"/>
                </svg>
                <span>Search</span>
              </a>
              <a href="/projects" class="mobile-nav-link" data-route="/projects" data-nav="projects">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none">
                  <path d="M22 19C22 19.5304 21.7893 20.0391 21.4142 20.4142C21.0391 20.7893 20.5304 21 20 21H4C3.46957 21 2.96086 20.7893 2.58579 20.4142C2.21071 20.0391 2 19.5304 2 19V5C2 4.46957 2.21071 3.96086 2.58579 3.58579C2.96086 3.21071 3.46957 3 4 3H9L11 6H20C20.5304 6 21.0391 6.21071 21.4142 6.58579C21.7893 6.96086 22 7.46957 22 8V19Z" stroke="currentColor" stroke-width="2"/>
                </svg>
                <span>Projects</span>
              </a>
              <a href="/analytics" class="mobile-nav-link" data-route="/analytics" data-nav="analytics">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none">
                  <path d="M18 20V10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                  <path d="M12 20V4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                  <path d="M6 20V14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                </svg>
                <span>Analytics</span>
              </a>
              <a href="/settings" class="mobile-nav-link" data-route="/settings" data-nav="settings">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2"/>
                  <path d="M19.4 15C19.2669 15.3016 19.2272 15.6362 19.286 15.9606C19.3448 16.285 19.4995 16.5843 19.73 16.82L19.79 16.88C19.976 17.0657 20.1235 17.2863 20.2241 17.5291C20.3248 17.7719 20.3766 18.0322 20.3766 18.295C20.3766 18.5578 20.3248 18.8181 20.2241 19.0609C20.1235 19.3037 19.976 19.5243 19.79 19.71C19.6043 19.896 19.3837 20.0435 19.1409 20.1441C18.8981 20.2448 18.6378 20.2966 18.375 20.2966C18.1122 20.2966 17.8519 20.2448 17.6091 20.1441C17.3663 20.0435 17.1457 19.896 16.96 19.71L16.9 19.65C16.6643 19.4195 16.365 19.2648 16.0406 19.206C15.7162 19.1472 15.3816 19.1869 15.08 19.32C14.7842 19.4468 14.532 19.6572 14.3543 19.9255C14.1766 20.1938 14.0813 20.5082 14.08 20.83V21C14.08 21.5304 13.8693 22.0391 13.4942 22.4142C13.1191 22.7893 12.6104 23 12.08 23C11.5496 23 11.0409 22.7893 10.6658 22.4142C10.2907 22.0391 10.08 21.5304 10.08 21V20.91C10.0723 20.579 9.96512 20.2573 9.77251 19.9887C9.5799 19.7201 9.31074 19.5176 9 19.41C8.69838 19.2769 8.36381 19.2372 8.03941 19.296C7.71502 19.3548 7.41568 19.5095 7.18 19.74L7.12 19.8C6.93425 19.986 6.71368 20.1335 6.47088 20.2341C6.22808 20.3348 5.96783 20.3866 5.705 20.3866C5.44217 20.3866 5.18192 20.3348 4.93912 20.2341C4.69632 20.1335 4.47575 19.986 4.29 19.8C4.10405 19.6143 3.95653 19.3937 3.85588 19.1509C3.75523 18.9081 3.70343 18.6478 3.70343 18.385C3.70343 18.1222 3.75523 17.8619 3.85588 17.6191C3.95653 17.3763 4.10405 17.1557 4.29 16.97L4.35 16.91C4.58054 16.6743 4.73519 16.375 4.794 16.0506C4.85282 15.7262 4.81312 15.3916 4.68 15.09C4.55324 14.7942 4.34276 14.542 4.07447 14.3643C3.80618 14.1866 3.49179 14.0913 3.17 14.09H3C2.46957 14.09 1.96086 13.8793 1.58579 13.5042C1.21071 13.1291 1 12.6204 1 12.09C1 11.5596 1.21071 11.0509 1.58579 10.6758C1.96086 10.3007 2.46957 10.09 3 10.09H3.09C3.42099 10.0823 3.742 9.97512 4.01062 9.78251C4.27925 9.5899 4.48167 9.32074 4.59 9.01C4.72312 8.70838 4.76282 8.37381 4.704 8.04941C4.64519 7.72502 4.49054 7.42568 4.26 7.19L4.2 7.13C4.01405 6.94425 3.86653 6.72368 3.76588 6.48088C3.66523 6.23808 3.61343 5.97783 3.61343 5.715C3.61343 5.45217 3.66523 5.19192 3.76588 4.94912C3.86653 4.70632 4.01405 4.48575 4.2 4.3C4.38575 4.11405 4.60632 3.96653 4.84912 3.86588C5.09192 3.76523 5.35217 3.71343 5.615 3.71343C5.87783 3.71343 6.13808 3.76523 6.38088 3.86588C6.62368 3.96653 6.84425 4.11405 7.03 4.3L7.09 4.36C7.32568 4.59054 7.62502 4.74519 7.94941 4.804C8.27381 4.86282 8.60838 4.82312 8.91 4.69H9C9.29577 4.56324 9.54802 4.35276 9.72569 4.08447C9.90337 3.81618 9.99872 3.50179 10 3.18V3C10 2.46957 10.2107 1.96086 10.5858 1.58579C10.9609 1.21071 11.4696 1 12 1C12.5304 1 13.0391 1.21071 13.4142 1.58579C13.7893 1.96086 14 2.46957 14 3V3.09C14.0013 3.41179 14.0966 3.72618 14.2743 3.99447C14.452 4.26276 14.7042 4.47324 15 4.6C15.3016 4.73312 15.6362 4.77282 15.9606 4.714C16.285 4.65519 16.5843 4.50054 16.82 4.27L16.88 4.21C17.0657 4.02405 17.2863 3.87653 17.5291 3.77588C17.7719 3.67523 18.0322 3.62343 18.295 3.62343C18.5578 3.62343 18.8181 3.67523 19.0609 3.77588C19.3037 3.87653 19.5243 4.02405 19.71 4.21C19.896 4.39575 20.0435 4.61632 20.1441 4.85912C20.2448 5.10192 20.2966 5.36217 20.2966 5.625C20.2966 5.88783 20.2448 6.14808 20.1441 6.39088C20.0435 6.63368 19.896 6.85425 19.71 7.04L19.65 7.1C19.4195 7.33568 19.2648 7.63502 19.206 7.95941C19.1472 8.28381 19.1869 8.61838 19.32 8.92V9C19.4468 9.29577 19.6572 9.54802 19.9255 9.72569C20.1938 9.90337 20.5082 9.99872 20.83 10H21C21.5304 10 22.0391 10.2107 22.4142 10.5858C22.7893 10.9609 23 11.4696 23 12C23 12.5304 22.7893 13.0391 22.4142 13.4142C22.0391 13.7893 21.5304 14 21 14H20.91C20.5882 14.0013 20.2738 14.0966 20.0055 14.2743C19.7372 14.452 19.5268 14.7042 19.4 15Z" stroke="currentColor" stroke-width="2"/>
                </svg>
                <span>Settings</span>
              </a>
            </div>
            <div class="mobile-nav-actions">
              <button class="btn-primary mobile-create-btn" data-route="/create">
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M12 5V19M5 12H19" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                New Memory
              </button>
            </div>
          </nav>
        </div>
      </header>
    `;
  }

  setupEventListeners() {
    // Theme toggle
    const themeToggle = this.querySelector('#theme-toggle-btn');
    themeToggle?.addEventListener('click', this.toggleTheme.bind(this));

    // User menu toggle
    const userMenuBtn = this.querySelector('#user-menu-btn');
    const userDropdown = this.querySelector('#user-dropdown');
    userMenuBtn?.addEventListener('click', (e) => {
      e.stopPropagation();
      userDropdown?.classList.toggle('open');
    });

    // Close user menu when clicking outside
    document.addEventListener('click', (e) => {
      if (!this.querySelector('#user-menu')?.contains(e.target)) {
        userDropdown?.classList.remove('open');
      }
    });

    // Mobile menu toggle
    const mobileMenuToggle = this.querySelector('#mobile-menu-toggle');
    const mobileNavOverlay = this.querySelector('#mobile-nav-overlay');
    mobileMenuToggle?.addEventListener('click', () => {
      this.toggleMobileMenu();
    });

    // Close mobile menu when clicking overlay
    mobileNavOverlay?.addEventListener('click', (e) => {
      if (e.target === mobileNavOverlay) {
        this.closeMobileMenu();
      }
    });

    // Touch gestures for mobile menu
    this.setupTouchGestures();

    // Navigation link handling
    this.querySelectorAll('[data-route]').forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        const route = link.getAttribute('data-route');
        this.handleNavigation(route);
        this.closeMobileMenu();
      });
    });

    // Set active navigation state
    this.updateActiveNavigation();

    // Handle escape key to close mobile menu
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.isMobileMenuOpen) {
        this.closeMobileMenu();
      }
    });
  }

  setupTouchGestures() {
    const mobileNav = this.querySelector('.mobile-nav');
    if (!mobileNav) return;

    let startX = 0;
    let currentX = 0;
    let isDragging = false;

    const handleTouchStart = (e) => {
      startX = e.touches[0].clientX;
      isDragging = true;
      mobileNav.style.transition = 'none';
    };

    const handleTouchMove = (e) => {
      if (!isDragging) return;
      
      currentX = e.touches[0].clientX;
      const deltaX = currentX - startX;
      
      // Only allow swiping to the right (closing)
      if (deltaX > 0) {
        const translateX = Math.min(deltaX, mobileNav.offsetWidth);
        mobileNav.style.transform = `translateX(${translateX}px)`;
      }
    };

    const handleTouchEnd = () => {
      if (!isDragging) return;
      
      isDragging = false;
      mobileNav.style.transition = '';
      
      const deltaX = currentX - startX;
      
      // Close menu if swiped more than 30% of its width
      if (deltaX > mobileNav.offsetWidth * 0.3) {
        this.closeMobileMenu();
      } else {
        // Snap back to open position
        mobileNav.style.transform = 'translateX(0)';
      }
    };

    mobileNav.addEventListener('touchstart', handleTouchStart, { passive: true });
    mobileNav.addEventListener('touchmove', handleTouchMove, { passive: true });
    mobileNav.addEventListener('touchend', handleTouchEnd, { passive: true });
  }

  toggleMobileMenu() {
    this.isMobileMenuOpen = !this.isMobileMenuOpen;
    const mobileNavOverlay = this.querySelector('#mobile-nav-overlay');
    const mobileMenuToggle = this.querySelector('#mobile-menu-toggle');
    
    mobileNavOverlay?.classList.toggle('open', this.isMobileMenuOpen);
    mobileMenuToggle?.classList.toggle('open', this.isMobileMenuOpen);
    document.body.classList.toggle('mobile-menu-open', this.isMobileMenuOpen);

    // Add haptic feedback on supported devices
    if ('vibrate' in navigator && this.isMobileMenuOpen) {
      navigator.vibrate(50);
    }
  }

  setupScrollBehavior() {
    let ticking = false;
    let lastScrollY = 0;
    let scrollDirection = 'up';
    
    const updateHeaderOnScroll = () => {
      const scrollY = window.scrollY;
      const header = this.querySelector('.chroma-header');
      
      // Determine scroll direction
      if (scrollY > lastScrollY && scrollY > 100) {
        scrollDirection = 'down';
      } else {
        scrollDirection = 'up';
      }
      lastScrollY = scrollY;
      
      // Add scrolled class for backdrop blur and shadow
      if (scrollY > 10 && !this.isScrolled) {
        this.isScrolled = true;
        header?.classList.add('scrolled');
      } else if (scrollY <= 10 && this.isScrolled) {
        this.isScrolled = false;
        header?.classList.remove('scrolled');
      }
      
      // Hide/show header based on scroll direction (only on mobile)
      if (window.innerWidth <= 768) {
        if (scrollDirection === 'down' && scrollY > 200) {
          header?.classList.add('hidden');
        } else if (scrollDirection === 'up') {
          header?.classList.remove('hidden');
        }
      }
      
      // Add parallax effect to logo on scroll
      const logoIcon = this.querySelector('.logo-icon');
      if (logoIcon && scrollY < 500) {
        const rotation = scrollY * 0.2;
        logoIcon.style.transform = `rotate(${rotation}deg)`;
      }
      
      ticking = false;
    };

    // Throttled scroll handler
    const handleScroll = () => {
      if (!ticking) {
        requestAnimationFrame(updateHeaderOnScroll);
        ticking = true;
      }
    };

    // Smooth scroll to top when clicking logo on about page
    const logoLink = this.querySelector('.logo-link');
    logoLink?.addEventListener('click', (e) => {
      if (window.location.pathname === '/about') {
        e.preventDefault();
        window.scrollTo({
          top: 0,
          behavior: 'smooth'
        });
      }
    });

    // Add scroll event listener
    window.addEventListener('scroll', handleScroll, { passive: true });
    
    // Handle resize to reset mobile header behavior
    window.addEventListener('resize', () => {
      const header = this.querySelector('.chroma-header');
      if (window.innerWidth > 768) {
        header?.classList.remove('hidden');
      }
    });

    // Initial call to set correct state
    updateHeaderOnScroll();
  }

  toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    
    // Update theme icon
    const header = this.querySelector('.chroma-header');
    header?.classList.toggle('dark-theme', newTheme === 'dark');
  }

  closeMobileMenu() {
    this.isMobileMenuOpen = false;
    const mobileNavOverlay = this.querySelector('#mobile-nav-overlay');
    const mobileMenuToggle = this.querySelector('#mobile-menu-toggle');
    
    mobileNavOverlay?.classList.remove('open');
    mobileMenuToggle?.classList.remove('open');
    document.body.classList.remove('mobile-menu-open');
  }

  handleNavigation(route) {
    // Update active state
    this.querySelectorAll('.nav-link, .mobile-nav-link').forEach(link => {
      link.classList.remove('active');
    });
    
    this.querySelectorAll(`[data-route="${route}"]`).forEach(link => {
      link.classList.add('active');
    });

    // Dispatch navigation event
    window.dispatchEvent(new CustomEvent('navigate', { detail: { route } }));
  }

  updateActiveNavigation() {
    const currentPath = window.location.pathname;
    this.querySelectorAll('.nav-link, .mobile-nav-link').forEach(link => {
      const route = link.getAttribute('data-route');
      link.classList.toggle('active', route === currentPath);
    });
  }
}

// Register the component
customElements.define('chroma-header', ChromaHeader);

export default ChromaHeader;