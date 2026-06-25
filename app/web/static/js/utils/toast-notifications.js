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
  if (window.app?.toastNotifications) {
    return window.app.toastNotifications;
  }
  if (!globalToastInstance) {
    globalToastInstance = new ToastNotifications();
  }
  return globalToastInstance;
}

/**
 * Convenience function to show toast
 */
export function showToast(message, type = 'info', options = {}) {
  const toast = getToastInstance();
  switch (type) {
    case 'success':
      return toast.success(message, options);
    case 'error':
      return toast.error(message, options);
    case 'warning':
      return toast.warning(message, options);
    default:
      return toast.info(message, options);
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
    this.container = document.getElementById('toast-container');
    if (!this.container) {
      this.container = document.createElement('div');
      this.container.id = 'toast-container';
      document.body.appendChild(this.container);
    }
    this.container.className = 'toast-container';
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
        top: 20px;
        right: 20px;
        z-index: 10001;
        display: flex;
        flex-direction: column;
        gap: 8px;
        align-items: flex-end;
        pointer-events: none;
      }
      
      .toast {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        max-width: min(420px, calc(100vw - 40px));
        min-height: 38px;
        padding: 10px 18px;
        border: 0;
        border-radius: 6px;
        color: white;
        font-size: 13px;
        font-weight: 500;
        line-height: 1.35;
        box-shadow: 0 8px 20px rgba(15, 23, 42, 0.18);
        pointer-events: auto;
        transform: translateY(-16px);
        opacity: 0;
        transition: opacity 0.25s ease, transform 0.25s ease;
        position: relative;
        overflow: visible;
      }
      
      .toast.show {
        transform: translateY(0);
        opacity: 1;
      }
      
      .toast.hide {
        transform: translateY(-16px);
        opacity: 0;
      }
      
      .toast-body {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
      }
      
      .toast-title {
        font-weight: 700;
      }
      
      .toast-icon {
        display: none;
      }
      
      .toast-close {
        width: 20px;
        height: 20px;
        margin: -2px -8px -2px 0;
        padding: 0;
        background: rgba(255, 255, 255, 0.16);
        border: none;
        border-radius: 999px;
        color: white;
        cursor: pointer;
        font-size: 16px;
        line-height: 1;
        flex: 0 0 auto;
        transition: background 0.15s ease;
      }
      
      .toast-close:hover {
        background: rgba(255, 255, 255, 0.28);
      }
      
      .toast-message {
        margin: 0;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      
      .toast-actions {
        display: flex;
        gap: 6px;
      }
      
      .toast-action {
        min-height: 26px;
        padding: 4px 10px;
        background: rgba(255, 255, 255, 0.18);
        border: none;
        border-radius: 5px;
        color: white;
        cursor: pointer;
        font-size: 12px;
        font-weight: 500;
        transition: background 0.15s ease;
      }
      
      .toast-action:hover {
        background: rgba(255, 255, 255, 0.28);
      }
      
      .toast-action.secondary {
        background: rgba(255, 255, 255, 0.1);
        color: white;
      }
      
      .toast-action.secondary:hover {
        background: rgba(255, 255, 255, 0.2);
      }
      
      /* Toast types */
      .toast.success {
        background: #10b981;
      }
      
      .toast.error {
        background: #ef4444;
      }
      
      .toast.warning {
        background: #f59e0b;
      }
      
      .toast.info {
        background: #3b82f6;
      }
      
      /* Responsive design */
      @media (max-width: 768px) {
        .toast-container {
          top: 16px;
          right: 16px;
          left: 16px;
          align-items: stretch;
        }
        
        .toast {
          max-width: none;
          width: 100%;
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
    toast.className = `toast ${config.type} toast-${config.type}`;
    toast.setAttribute('data-toast-id', id);
    
    const title = config.title ? `<span class="toast-title">${this.escapeHtml(config.title)}</span>` : '';
    const close = config.persistent || config.duration === 0
      ? `<button class="toast-close" onclick="window.app?.toastNotifications?.hide('${id}')" aria-label="Close toast">&times;</button>`
      : '';
    
    toast.innerHTML = `
      <div class="toast-body">
        ${title}
        <p class="toast-message">${this.escapeHtml(message)}</p>
      </div>
      ${config.actions.length > 0 ? this.createActions(config.actions, id) : ''}
      ${close}
    `;
    
    return toast;
  }
  
  /**
   * Create action buttons
   */
  createActions(actions, toastId) {
    const actionsHtml = actions.map((action, index) => {
      const className = action.primary ? 'toast-action' : 'toast-action secondary';
      return `<button class="${className}" onclick="window.app?.toastNotifications?.handleAction('${toastId}', ${index})">${this.escapeHtml(action.label)}</button>`;
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
    return this.show(message, {
      ...options,
      type: 'error',
      duration: options.duration ?? 0,
      persistent: options.persistent ?? options.duration == null,
    });
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

  escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
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
