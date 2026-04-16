/**
 * Toast Notifications System
 * Provides user-friendly notifications for success, error, warning, and info messages
 */

// Global toast instance for convenience
let globalToastInstance = null;

/**
 * Get or create global toast instance
 */
function getToastInstance() {
  if (!globalToastInstance) {
    globalToastInstance = new ToastNotifications();
  }
  return globalToastInstance;
}

/**
 * Convenience function to show toast
 */
export function showToast(message, type = 'info') {
  const toast = getToastInstance();
  switch (type) {
    case 'success':
      return toast.success(message);
    case 'error':
      return toast.error(message);
    case 'warning':
      return toast.warning(message);
    default:
      return toast.info(message);
  }
}

export class ToastNotifications {
  constructor() {
    this.container = null;
    this.toasts = new Map();
    this.defaultDuration = 5000;
    this.maxToasts = 5;
    
    this.init();
  }
  
  /**
   * Initialize toast system
   */
  init() {
    this.createContainer();
    this.addStyles();
  }
  
  /**
   * Create toast container
   */
  createContainer() {
    this.container = document.createElement('div');
    this.container.id = 'toast-container';
    this.container.className = 'toast-container';
    document.body.appendChild(this.container);
  }
  
  /**
   * Add toast styles
   */
  addStyles() {
    if (document.getElementById('toast-styles')) return;
    
    const style = document.createElement('style');
    style.id = 'toast-styles';
    style.textContent = `
      .toast-container {
        position: fixed;
        top: 1rem;
        right: 1rem;
        z-index: 10000;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
        pointer-events: none;
      }
      
      .toast {
        background: var(--bg-primary);
        border: 1px solid var(--border-color);
        border-radius: var(--border-radius);
        padding: 1rem 1.5rem;
        min-width: 300px;
        max-width: 500px;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        pointer-events: auto;
        transform: translateX(100%);
        opacity: 0;
        transition: all 0.3s ease-in-out;
        position: relative;
        overflow: hidden;
      }
      
      .toast.show {
        transform: translateX(0);
        opacity: 1;
      }
      
      .toast.hide {
        transform: translateX(100%);
        opacity: 0;
      }
      
      .toast::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        width: 4px;
        height: 100%;
        background: var(--toast-accent, var(--primary-color));
      }
      
      .toast-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 0.5rem;
      }
      
      .toast-title {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-weight: 600;
        color: var(--text-primary);
        margin: 0;
      }
      
      .toast-icon {
        font-size: 1.25rem;
        line-height: 1;
      }
      
      .toast-close {
        background: none;
        border: none;
        color: var(--text-secondary);
        cursor: pointer;
        padding: 0.25rem;
        border-radius: var(--border-radius-sm);
        font-size: 1.25rem;
        line-height: 1;
        transition: var(--transition);
      }
      
      .toast-close:hover {
        background: var(--bg-secondary);
        color: var(--text-primary);
      }
      
      .toast-message {
        color: var(--text-secondary);
        line-height: 1.5;
        margin: 0;
      }
      
      .toast-actions {
        display: flex;
        gap: 0.5rem;
        margin-top: 1rem;
      }
      
      .toast-action {
        background: var(--primary-color);
        color: white;
        border: none;
        padding: 0.5rem 1rem;
        border-radius: var(--border-radius-sm);
        cursor: pointer;
        font-size: 0.875rem;
        font-weight: 500;
        transition: var(--transition);
      }
      
      .toast-action:hover {
        background: var(--primary-hover);
      }
      
      .toast-action.secondary {
        background: var(--bg-secondary);
        color: var(--text-primary);
        border: 1px solid var(--border-color);
      }
      
      .toast-action.secondary:hover {
        background: var(--bg-tertiary);
      }
      
      .toast-progress {
        position: absolute;
        bottom: 0;
        left: 0;
        height: 3px;
        background: var(--toast-accent, var(--primary-color));
        transition: width linear;
        opacity: 0.7;
      }
      
      /* Toast types */
      .toast.success {
        --toast-accent: var(--success-color);
        border-color: var(--success-color);
      }
      
      .toast.error {
        --toast-accent: var(--error-color);
        border-color: var(--error-color);
      }
      
      .toast.warning {
        --toast-accent: var(--warning-color);
        border-color: var(--warning-color);
      }
      
      .toast.info {
        --toast-accent: var(--info-color);
        border-color: var(--info-color);
      }
      
      /* Responsive design */
      @media (max-width: 768px) {
        .toast-container {
          top: 1rem;
          right: 1rem;
          left: 1rem;
        }
        
        .toast {
          min-width: auto;
          max-width: none;
        }
      }
    `;
    
    document.head.appendChild(style);
  }
  
  /**
   * Show a toast notification
   */
  show(message, options = {}) {
    const config = {
      type: 'info',
      title: '',
      duration: this.defaultDuration,
      persistent: false,
      actions: [],
      ...options
    };
    
    // Remove oldest toast if at max capacity
    if (this.toasts.size >= this.maxToasts) {
      const oldestId = this.toasts.keys().next().value;
      this.hide(oldestId);
    }
    
    const toastId = this.generateId();
    const toast = this.createToast(toastId, message, config);
    
    this.container.appendChild(toast);
    this.toasts.set(toastId, { element: toast, config });
    
    // Trigger show animation
    requestAnimationFrame(() => {
      toast.classList.add('show');
    });
    
    // Auto-hide if not persistent
    if (!config.persistent && config.duration > 0) {
      this.scheduleHide(toastId, config.duration);
    }
    
    return toastId;
  }
  
  /**
   * Create toast element
   */
  createToast(id, message, config) {
    const toast = document.createElement('div');
    toast.className = `toast ${config.type}`;
    toast.setAttribute('data-toast-id', id);
    
    const icon = this.getIcon(config.type);
    const title = config.title || this.getDefaultTitle(config.type);
    
    toast.innerHTML = `
      <div class="toast-header">
        <h4 class="toast-title">
          <span class="toast-icon">${icon}</span>
          ${title}
        </h4>
        <button class="toast-close" onclick="window.app?.toastNotifications?.hide('${id}')">&times;</button>
      </div>
      <p class="toast-message">${message}</p>
      ${config.actions.length > 0 ? this.createActions(config.actions, id) : ''}
      ${!config.persistent && config.duration > 0 ? '<div class="toast-progress"></div>' : ''}
    `;
    
    return toast;
  }
  
  /**
   * Create action buttons
   */
  createActions(actions, toastId) {
    const actionsHtml = actions.map((action, index) => {
      const className = action.primary ? 'toast-action' : 'toast-action secondary';
      return `<button class="${className}" onclick="window.app?.toastNotifications?.handleAction('${toastId}', ${index})">${action.label}</button>`;
    }).join('');
    
    return `<div class="toast-actions">${actionsHtml}</div>`;
  }
  
  /**
   * Handle action button click
   */
  handleAction(toastId, actionIndex) {
    const toast = this.toasts.get(toastId);
    if (toast && toast.config.actions[actionIndex]) {
      const action = toast.config.actions[actionIndex];
      if (typeof action.callback === 'function') {
        action.callback();
      }
      
      if (action.closeOnClick !== false) {
        this.hide(toastId);
      }
    }
  }
  
  /**
   * Get icon for toast type
   */
  getIcon(type) {
    const icons = {
      success: '✅',
      error: '❌',
      warning: '⚠️',
      info: 'ℹ️'
    };
    return icons[type] || icons.info;
  }
  
  /**
   * Get default title for toast type
   */
  getDefaultTitle(type) {
    const titles = {
      success: 'Success',
      error: 'Error',
      warning: 'Warning',
      info: 'Information'
    };
    return titles[type] || titles.info;
  }
  
  /**
   * Schedule toast to hide
   */
  scheduleHide(toastId, duration) {
    const toast = this.toasts.get(toastId);
    if (!toast) return;
    
    const progressBar = toast.element.querySelector('.toast-progress');
    if (progressBar) {
      progressBar.style.width = '100%';
      progressBar.style.transitionDuration = `${duration}ms`;
      
      requestAnimationFrame(() => {
        progressBar.style.width = '0%';
      });
    }
    
    setTimeout(() => {
      this.hide(toastId);
    }, duration);
  }
  
  /**
   * Hide a toast
   */
  hide(toastId) {
    const toast = this.toasts.get(toastId);
    if (!toast) return;
    
    toast.element.classList.add('hide');
    
    setTimeout(() => {
      if (toast.element.parentNode) {
        toast.element.parentNode.removeChild(toast.element);
      }
      this.toasts.delete(toastId);
    }, 300);
  }
  
  /**
   * Hide all toasts
   */
  hideAll() {
    const toastIds = Array.from(this.toasts.keys());
    toastIds.forEach(id => this.hide(id));
  }
  
  /**
   * Show success toast
   */
  success(message, options = {}) {
    return this.show(message, { ...options, type: 'success' });
  }
  
  /**
   * Show error toast
   */
  error(message, options = {}) {
    return this.show(message, { ...options, type: 'error', duration: 0, persistent: true });
  }
  
  /**
   * Show warning toast
   */
  warning(message, options = {}) {
    return this.show(message, { ...options, type: 'warning' });
  }
  
  /**
   * Show info toast
   */
  info(message, options = {}) {
    return this.show(message, { ...options, type: 'info' });
  }
  
  /**
   * Show loading toast
   */
  loading(message, options = {}) {
    return this.show(message, {
      ...options,
      type: 'info',
      title: 'Loading...',
      persistent: true,
      duration: 0
    });
  }
  
  /**
   * Generate unique ID
   */
  generateId() {
    return `toast-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  }
  
  /**
   * Get active toasts count
   */
  getActiveCount() {
    return this.toasts.size;
  }
  
  /**
   * Check if toast exists
   */
  exists(toastId) {
    return this.toasts.has(toastId);
  }
  
  /**
   * Update toast message
   */
  update(toastId, message, options = {}) {
    const toast = this.toasts.get(toastId);
    if (!toast) return false;
    
    const messageEl = toast.element.querySelector('.toast-message');
    if (messageEl) {
      messageEl.textContent = message;
    }
    
    if (options.title) {
      const titleEl = toast.element.querySelector('.toast-title');
      if (titleEl) {
        const iconEl = titleEl.querySelector('.toast-icon');
        titleEl.textContent = options.title;
        if (iconEl) {
          titleEl.prepend(iconEl);
        }
      }
    }
    
    return true;
  }
  
  /**
   * Destroy toast system
   */
  destroy() {
    this.hideAll();
    
    if (this.container && this.container.parentNode) {
      this.container.parentNode.removeChild(this.container);
    }
    
    const styles = document.getElementById('toast-styles');
    if (styles) {
      styles.remove();
    }
    
    this.toasts.clear();
  }
}