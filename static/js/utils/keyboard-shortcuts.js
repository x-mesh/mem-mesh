/**
 * Keyboard Shortcuts Manager
 * Handles global keyboard shortcuts for the application
 */

export class KeyboardShortcuts {
  constructor() {
    this.shortcuts = new Map();
    this.isEnabled = true;
    this.modifierKeys = {
      ctrl: false,
      alt: false,
      shift: false,
      meta: false
    };
    
    this.init();
  }
  
  /**
   * Initialize keyboard shortcuts
   */
  init() {
    this.setupEventListeners();
    this.registerDefaultShortcuts();
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    document.addEventListener('keydown', this.handleKeyDown.bind(this));
    document.addEventListener('keyup', this.handleKeyUp.bind(this));
    
    // Disable shortcuts when typing in input fields
    document.addEventListener('focusin', this.handleFocusIn.bind(this));
    document.addEventListener('focusout', this.handleFocusOut.bind(this));
  }
  
  /**
   * Handle key down event
   */
  handleKeyDown(event) {
    // Update modifier keys state
    this.updateModifierKeys(event);
    
    // Generate shortcut key
    const shortcutKey = this.generateShortcutKey(event);
    
    // Find matching shortcut
    const shortcut = this.shortcuts.get(shortcutKey);
    if (!shortcut) return;
    
    // Allow global shortcuts (Ctrl+K) even when typing in inputs
    const isGlobal = shortcut.global === true;
    
    if (!isGlobal && !this.isEnabled) return;
    if (!isGlobal && this.isTypingInInput(event.target)) return;
    
    event.preventDefault();
    event.stopPropagation();
    
    try {
      shortcut.callback(event);
    } catch {
      // Shortcut execution failed silently
    }
  }
  
  /**
   * Handle key up event
   */
  handleKeyUp(event) {
    this.updateModifierKeys(event);
  }
  
  /**
   * Handle focus in event
   */
  handleFocusIn(event) {
    if (this.isTypingInInput(event.target)) {
      this.isEnabled = false;
    }
  }
  
  /**
   * Handle focus out event
   */
  handleFocusOut(event) {
    if (this.isTypingInInput(event.target)) {
      this.isEnabled = true;
    }
  }
  
  /**
   * Update modifier keys state
   */
  updateModifierKeys(event) {
    this.modifierKeys.ctrl = event.ctrlKey;
    this.modifierKeys.alt = event.altKey;
    this.modifierKeys.shift = event.shiftKey;
    this.modifierKeys.meta = event.metaKey;
  }
  
  /**
   * Check if user is typing in an input field
   */
  isTypingInInput(element) {
    if (!element) return false;
    
    const tagName = element.tagName.toLowerCase();
    const inputTypes = ['input', 'textarea', 'select'];
    const contentEditable = element.contentEditable === 'true';
    
    return inputTypes.includes(tagName) || contentEditable;
  }
  
  /**
   * Generate shortcut key string
   */
  generateShortcutKey(event) {
    const parts = [];
    
    if (event.ctrlKey || event.metaKey) parts.push('ctrl');
    if (event.altKey) parts.push('alt');
    if (event.shiftKey) parts.push('shift');
    
    // Add the main key
    const key = event.key.toLowerCase();
    if (key !== 'control' && key !== 'alt' && key !== 'shift' && key !== 'meta') {
      parts.push(key);
    }
    
    return parts.join('+');
  }
  
  /**
   * Register a keyboard shortcut
   */
  register(shortcut, callback, description = '', options = {}) {
    const normalizedShortcut = this.normalizeShortcut(shortcut);
    
    this.shortcuts.set(normalizedShortcut, {
      shortcut: normalizedShortcut,
      originalShortcut: shortcut,
      callback,
      description,
      global: options.global || false
    });
  }
  
  /**
   * Unregister a keyboard shortcut
   */
  unregister(shortcut) {
    const normalizedShortcut = this.normalizeShortcut(shortcut);
    return this.shortcuts.delete(normalizedShortcut);
  }
  
  /**
   * Normalize shortcut string
   */
  normalizeShortcut(shortcut) {
    return shortcut.toLowerCase()
      .replace(/\s+/g, '')
      .replace(/cmd|command|meta/g, 'ctrl') // Treat cmd as ctrl
      .split('+')
      .sort((a, b) => {
        const order = ['ctrl', 'alt', 'shift'];
        const aIndex = order.indexOf(a);
        const bIndex = order.indexOf(b);
        
        if (aIndex !== -1 && bIndex !== -1) {
          return aIndex - bIndex;
        }
        if (aIndex !== -1) return -1;
        if (bIndex !== -1) return 1;
        return a.localeCompare(b);
      })
      .join('+');
  }
  
  /**
   * Register default application shortcuts
   */
  registerDefaultShortcuts() {
    // Navigation shortcuts
    this.register('ctrl+k', () => {
      // If already on search/memories page, just focus the search input
      const existingSearchInput = document.querySelector('.search-input') 
        || document.querySelector('.chroma-search-input')
        || document.querySelector('chroma-search-bar .chroma-search-input');
      
      if (existingSearchInput && document.activeElement !== existingSearchInput) {
        existingSearchInput.focus();
        existingSearchInput.select();
        return;
      }
      
      // Navigate to memories search view
      if (window.app?.router) {
        window.app.router.navigate('/memories?view=search');
      } else {
        window.location.href = '/memories?view=search';
      }
      
      setTimeout(() => {
        const searchInput = document.querySelector('.search-input')
          || document.querySelector('.chroma-search-input');
        if (searchInput) {
          searchInput.focus();
          searchInput.select();
        }
      }, 200);
    }, 'Open search', { global: true });
    
    this.register('ctrl+n', () => {
      window.app?.router?.navigate('/create');
    }, 'Create new memory');
    
    this.register('ctrl+h', () => {
      window.app?.router?.navigate('/');
    }, 'Go to dashboard');
    
    this.register('ctrl+p', () => {
      window.app?.router?.navigate('/projects');
    }, 'View projects');
    
    this.register('ctrl+a', () => {
      window.app?.router?.navigate('/analytics');
    }, 'View analytics');
    
    // Application shortcuts
    this.register('ctrl+r', (event) => {
      event.preventDefault();
      window.location.reload();
    }, 'Refresh page');
    
    this.register('ctrl+t', () => {
      if (window.app?.themeManager) {
        window.app.themeManager.toggle();
      }
    }, 'Toggle theme');
    
    this.register('escape', () => {
      this.closeModalsAndOverlays();
    }, 'Close modals');
    
    this.register('ctrl+/', () => {
      this.showShortcutsHelp();
    }, 'Show keyboard shortcuts');
    
    // Memory editing shortcuts (context-sensitive)
    this.register('ctrl+s', (event) => {
      const form = document.querySelector('form[id*="memory"]');
      if (form) {
        event.preventDefault();
        const submitButton = form.querySelector('button[type="submit"]');
        if (submitButton && !submitButton.disabled) {
          submitButton.click();
        }
      }
    }, 'Save memory (in forms)');
    
    this.register('ctrl+enter', (event) => {
      const form = document.querySelector('form[id*="memory"]');
      if (form) {
        event.preventDefault();
        const submitButton = form.querySelector('button[type="submit"]');
        if (submitButton && !submitButton.disabled) {
          submitButton.click();
        }
      }
    }, 'Submit form');
    
    // List navigation shortcuts
    this.register('j', () => {
      this.navigateList('down');
    }, 'Navigate down in lists');
    
    this.register('k', () => {
      this.navigateList('up');
    }, 'Navigate up in lists');
    
    this.register('enter', () => {
      this.activateSelectedItem();
    }, 'Activate selected item');
    
    // Quick actions
    this.register('g h', () => {
      window.app?.router?.navigate('/');
    }, 'Go to home');
    
    this.register('g s', () => {
      window.app?.router?.navigate('/search');
    }, 'Go to search');
    
    this.register('g p', () => {
      window.app?.router?.navigate('/projects');
    }, 'Go to projects');
    
    this.register('g a', () => {
      window.app?.router?.navigate('/analytics');
    }, 'Go to analytics');
  }
  
  /**
   * Close modals and overlays
   */
  closeModalsAndOverlays() {
    // Close any open modals
    const modals = document.querySelectorAll('.modal, .overlay, .dropdown');
    modals.forEach(modal => {
      if (modal.style.display !== 'none') {
        modal.style.display = 'none';
      }
    });
    
    // Close help dialog
    const helpDialog = document.getElementById('shortcuts-help');
    if (helpDialog) {
      helpDialog.style.display = 'none';
    }
    
    // Clear focus from search inputs
    const searchInputs = document.querySelectorAll('input[type="search"], .search-input');
    searchInputs.forEach(input => {
      if (document.activeElement === input) {
        input.blur();
      }
    });
  }
  
  /**
   * Navigate in lists (for keyboard navigation)
   */
  navigateList(direction) {
    const lists = document.querySelectorAll('.memory-list, .project-list, .search-results');
    const activeList = Array.from(lists).find(list => 
      list.getBoundingClientRect().top >= 0 && 
      list.getBoundingClientRect().bottom <= window.innerHeight
    );
    
    if (!activeList) return;
    
    const items = activeList.querySelectorAll('.memory-card, .project-card, .search-result-item');
    if (items.length === 0) return;
    
    let currentIndex = Array.from(items).findIndex(item => 
      item.classList.contains('keyboard-selected')
    );
    
    // Remove current selection
    items.forEach(item => item.classList.remove('keyboard-selected'));
    
    // Calculate new index
    if (direction === 'down') {
      currentIndex = currentIndex < items.length - 1 ? currentIndex + 1 : 0;
    } else {
      currentIndex = currentIndex > 0 ? currentIndex - 1 : items.length - 1;
    }
    
    // Apply new selection
    const selectedItem = items[currentIndex];
    selectedItem.classList.add('keyboard-selected');
    selectedItem.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  
  /**
   * Activate selected item
   */
  activateSelectedItem() {
    const selectedItem = document.querySelector('.keyboard-selected');
    if (selectedItem) {
      // Try to find a clickable element
      const clickable = selectedItem.querySelector('a, button, [data-route]') || selectedItem;
      if (clickable) {
        clickable.click();
      }
    }
  }
  
  /**
   * Show shortcuts help dialog
   */
  showShortcutsHelp() {
    let helpDialog = document.getElementById('shortcuts-help');
    
    if (!helpDialog) {
      helpDialog = this.createShortcutsHelpDialog();
      document.body.appendChild(helpDialog);
    }
    
    helpDialog.style.display = 'flex';
  }
  
  /**
   * Create shortcuts help dialog
   */
  createShortcutsHelpDialog() {
    const dialog = document.createElement('div');
    dialog.id = 'shortcuts-help';
    dialog.className = 'shortcuts-help-dialog';
    
    const shortcuts = Array.from(this.shortcuts.values())
      .filter(shortcut => shortcut.description)
      .sort((a, b) => a.description.localeCompare(b.description));
    
    dialog.innerHTML = `
      <div class="shortcuts-help-overlay"></div>
      <div class="shortcuts-help-content">
        <div class="shortcuts-help-header">
          <h2>Keyboard Shortcuts</h2>
          <button class="close-btn" data-action="close-shortcuts-help">×</button>
        </div>
        <div class="shortcuts-help-body">
          <div class="shortcuts-grid">
            ${shortcuts.map(shortcut => `
              <div class="shortcut-item">
                <div class="shortcut-keys">
                  ${this.formatShortcutDisplay(shortcut.originalShortcut)}
                </div>
                <div class="shortcut-description">${shortcut.description}</div>
              </div>
            `).join('')}
          </div>
        </div>
        <div class="shortcuts-help-footer">
          <p>Press <kbd>Escape</kbd> or <kbd>Ctrl+/</kbd> to close this dialog</p>
        </div>
      </div>
    `;
    
    // Add styles
    const style = document.createElement('style');
    style.textContent = `
      .shortcuts-help-dialog {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: 10000;
        display: none;
        align-items: center;
        justify-content: center;
      }
      
      .shortcuts-help-overlay {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
      }
      
      .shortcuts-help-content {
        position: relative;
        background: var(--bg-primary);
        border: 1px solid var(--border-color);
        border-radius: var(--border-radius);
        max-width: 600px;
        max-height: 80vh;
        width: 90%;
        display: flex;
        flex-direction: column;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
      }
      
      .shortcuts-help-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1.5rem;
        border-bottom: 1px solid var(--border-color);
      }
      
      .shortcuts-help-header h2 {
        margin: 0;
        color: var(--text-primary);
      }
      
      .close-btn {
        background: none;
        border: none;
        font-size: 1.5rem;
        color: var(--text-secondary);
        cursor: pointer;
        padding: 0.25rem;
        line-height: 1;
      }
      
      .close-btn:hover {
        color: var(--text-primary);
      }
      
      .shortcuts-help-body {
        flex: 1;
        overflow-y: auto;
        padding: 1.5rem;
      }
      
      .shortcuts-grid {
        display: grid;
        gap: 1rem;
      }
      
      .shortcut-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.75rem;
        background: var(--bg-secondary);
        border-radius: var(--border-radius);
      }
      
      .shortcut-keys {
        font-family: var(--font-mono);
        font-weight: 500;
        color: var(--primary-color);
      }
      
      .shortcut-keys kbd {
        background: var(--bg-tertiary);
        border: 1px solid var(--border-color);
        border-radius: 3px;
        padding: 0.125rem 0.375rem;
        font-size: 0.875rem;
        margin: 0 0.125rem;
      }
      
      .shortcut-description {
        color: var(--text-secondary);
        text-align: right;
      }
      
      .shortcuts-help-footer {
        padding: 1rem 1.5rem;
        border-top: 1px solid var(--border-color);
        text-align: center;
      }
      
      .shortcuts-help-footer p {
        margin: 0;
        color: var(--text-muted);
        font-size: 0.875rem;
      }
      
      .keyboard-selected {
        outline: 2px solid var(--primary-color);
        outline-offset: 2px;
      }
    `;
    
    if (!document.getElementById('shortcuts-help-styles')) {
      style.id = 'shortcuts-help-styles';
      document.head.appendChild(style);
    }
    
    // Close button event
    dialog.addEventListener('click', (e) => {
      if (e.target.closest('[data-action="close-shortcuts-help"]') || e.target.closest('.shortcuts-help-overlay')) {
        dialog.style.display = 'none';
      }
    });
    
    return dialog;
  }
  
  /**
   * Format shortcut for display
   */
  formatShortcutDisplay(shortcut) {
    return shortcut
      .split('+')
      .map(key => {
        const keyMap = {
          'ctrl': '⌃',
          'cmd': '⌘',
          'alt': '⌥',
          'shift': '⇧',
          'enter': '↵',
          'escape': 'Esc',
          'space': 'Space'
        };
        
        const displayKey = keyMap[key.toLowerCase()] || key.toUpperCase();
        return `<kbd>${displayKey}</kbd>`;
      })
      .join(' + ');
  }
  
  /**
   * Get all registered shortcuts
   */
  getShortcuts() {
    return Array.from(this.shortcuts.values());
  }
  
  /**
   * Enable shortcuts
   */
  enable() {
    this.isEnabled = true;
  }
  
  /**
   * Disable shortcuts
   */
  disable() {
    this.isEnabled = false;
  }
  
  /**
   * Check if shortcuts are enabled
   */
  isShortcutsEnabled() {
    return this.isEnabled;
  }
  
  /**
   * Destroy keyboard shortcuts manager
   */
  destroy() {
    document.removeEventListener('keydown', this.handleKeyDown.bind(this));
    document.removeEventListener('keyup', this.handleKeyUp.bind(this));
    document.removeEventListener('focusin', this.handleFocusIn.bind(this));
    document.removeEventListener('focusout', this.handleFocusOut.bind(this));
    
    const helpDialog = document.getElementById('shortcuts-help');
    if (helpDialog) {
      helpDialog.remove();
    }
    
    const styles = document.getElementById('shortcuts-help-styles');
    if (styles) {
      styles.remove();
    }
    
    this.shortcuts.clear();
  }
}