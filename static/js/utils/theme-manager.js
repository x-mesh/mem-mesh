/**
 * Theme Manager
 * Handles theme switching and persistence
 */

export class ThemeManager {
  constructor() {
    this.currentTheme = this.getStoredTheme();
    this.mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
  }
  
  /**
   * Initialize theme manager
   */
  init() {
    // Apply initial theme
    this.applyTheme(this.currentTheme);
    
    // Listen for system theme changes
    this.mediaQuery.addEventListener('change', this.handleSystemThemeChange.bind(this));
    
    // Listen for storage changes (multi-tab sync)
    window.addEventListener('storage', this.handleStorageChange.bind(this));
  }
  
  /**
   * Get stored theme or detect system preference
   */
  getStoredTheme() {
    const stored = localStorage.getItem('mem-mesh-theme');
    if (stored && ['light', 'dark', 'auto'].includes(stored)) {
      return stored;
    }
    
    return 'auto';
  }
  
  /**
   * Get effective theme (resolves 'auto' to actual theme)
   */
  getEffectiveTheme() {
    if (this.currentTheme === 'auto') {
      return this.mediaQuery.matches ? 'dark' : 'light';
    }
    return this.currentTheme;
  }
  
  /**
   * Set theme
   */
  setTheme(theme) {
    if (!['light', 'dark', 'auto'].includes(theme)) {
      console.warn(`Invalid theme: ${theme}`);
      return;
    }
    
    this.currentTheme = theme;
    this.applyTheme(theme);
    this.storeTheme(theme);
    this.emitThemeChange(theme);
  }
  
  /**
   * Toggle between light and dark themes
   */
  toggle() {
    const effectiveTheme = this.getEffectiveTheme();
    const newTheme = effectiveTheme === 'light' ? 'dark' : 'light';
    this.setTheme(newTheme);
  }
  
  /**
   * Apply theme to document
   */
  applyTheme(theme) {
    const effectiveTheme = theme === 'auto' 
      ? (this.mediaQuery.matches ? 'dark' : 'light')
      : theme;
    
    // Update document attribute
    document.documentElement.setAttribute('data-theme', effectiveTheme);
    
    // Update theme toggle button
    this.updateThemeToggle(effectiveTheme);
    
    // Update meta theme-color for mobile browsers
    this.updateMetaThemeColor(effectiveTheme);
  }
  
  /**
   * Update theme toggle button
   */
  updateThemeToggle(effectiveTheme) {
    const themeToggle = document.getElementById('theme-toggle');
    const themeIcon = themeToggle?.querySelector('.theme-icon');
    
    if (themeIcon) {
      themeIcon.textContent = effectiveTheme === 'light' ? '🌙' : '☀️';
      themeToggle.setAttribute('aria-label', 
        `Switch to ${effectiveTheme === 'light' ? 'dark' : 'light'} theme`
      );
    }
  }
  
  /**
   * Update meta theme-color for mobile browsers
   */
  updateMetaThemeColor(effectiveTheme) {
    let metaThemeColor = document.querySelector('meta[name="theme-color"]');
    
    if (!metaThemeColor) {
      metaThemeColor = document.createElement('meta');
      metaThemeColor.name = 'theme-color';
      document.head.appendChild(metaThemeColor);
    }
    
    // Set theme color based on CSS custom properties
    const color = effectiveTheme === 'light' ? '#ffffff' : '#0f172a';
    metaThemeColor.content = color;
  }
  
  /**
   * Store theme preference
   */
  storeTheme(theme) {
    try {
      localStorage.setItem('mem-mesh-theme', theme);
    } catch (error) {
      console.warn('Failed to store theme preference:', error);
    }
  }
  
  /**
   * Handle system theme changes
   */
  handleSystemThemeChange(event) {
    if (this.currentTheme === 'auto') {
      this.applyTheme('auto');
      this.emitThemeChange('auto');
    }
  }
  
  /**
   * Handle storage changes (multi-tab sync)
   */
  handleStorageChange(event) {
    if (event.key === 'mem-mesh-theme' && event.newValue !== this.currentTheme) {
      this.currentTheme = event.newValue || 'auto';
      this.applyTheme(this.currentTheme);
      this.emitThemeChange(this.currentTheme);
    }
  }
  
  /**
   * Emit theme change event
   */
  emitThemeChange(theme) {
    const event = new CustomEvent('themechange', {
      detail: {
        theme,
        effectiveTheme: this.getEffectiveTheme()
      }
    });
    
    document.dispatchEvent(event);
  }
  
  /**
   * Get current theme info
   */
  getThemeInfo() {
    return {
      current: this.currentTheme,
      effective: this.getEffectiveTheme(),
      systemPreference: this.mediaQuery.matches ? 'dark' : 'light'
    };
  }
  
  /**
   * Check if dark theme is active
   */
  isDark() {
    return this.getEffectiveTheme() === 'dark';
  }
  
  /**
   * Check if light theme is active
   */
  isLight() {
    return this.getEffectiveTheme() === 'light';
  }
}