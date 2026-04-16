/**
 * Error Handler
 * Centralized error handling and user notifications
 */

import { APIError } from '../services/api-client.js';

export class ErrorHandler {
  constructor() {
    this.toastContainer = null;
    this.toastId = 0;
    this.init();
  }
  
  /**
   * Initialize error handler
   */
  init() {
    this.toastContainer = document.getElementById('toast-container');
    
    if (!this.toastContainer) {
      console.warn('Toast container not found');
    }
  }
  
  /**
   * Handle API errors
   */
  handleAPIError(error, context = '') {
    console.error('API Error:', error);
    
    let title = 'Error';
    let message = 'An unexpected error occurred';
    let type = 'error';
    
    if (error instanceof APIError) {
      title = this.getAPIErrorTitle(error);
      message = this.getAPIErrorMessage(error);
      type = this.getAPIErrorType(error);
    } else if (error instanceof Error) {
      message = error.message;
    } else if (typeof error === 'string') {
      message = error;
    }
    
    // Add context if provided
    if (context) {
      message = `${context}: ${message}`;
    }
    
    this.showToast({ type, title, message, duration: 5000 });
    
    return {
      title,
      message,
      type,
      originalError: error
    };
  }
  
  /**
   * Get API error title
   */
  getAPIErrorTitle(error) {
    if (error.isNetworkError) {
      return 'Network Error';
    }
    
    if (error.status === 400) return 'Bad Request';
    if (error.status === 401) return 'Unauthorized';
    if (error.status === 403) return 'Forbidden';
    if (error.status === 404) return 'Not Found';
    if (error.status === 422) return 'Validation Error';
    if (error.status >= 500) return 'Server Error';
    
    return 'Error';
  }
  
  /**
   * Get API error message
   */
  getAPIErrorMessage(error) {
    if (error.isNetworkError) {
      return 'Unable to connect to the server. Please check your internet connection.';
    }
    
    // Use server-provided message if available
    if (error.message && error.message !== `HTTP ${error.status}`) {
      return error.message;
    }
    
    // Default messages based on status code
    const defaultMessages = {
      400: 'The request was invalid. Please check your input.',
      401: 'Authentication required. Please log in.',
      403: 'You do not have permission to perform this action.',
      404: 'The requested resource was not found.',
      422: 'The provided data is invalid. Please check your input.',
      429: 'Too many requests. Please try again later.',
      500: 'Internal server error. Please try again later.',
      502: 'Bad gateway. The server is temporarily unavailable.',
      503: 'Service unavailable. Please try again later.',
      504: 'Gateway timeout. The server took too long to respond.'
    };
    
    return defaultMessages[error.status] || 'An unexpected error occurred.';
  }
  
  /**
   * Get API error type for styling
   */
  getAPIErrorType(error) {
    if (error.isNetworkError) return 'error';
    if (error.status === 401 || error.status === 403) return 'warning';
    if (error.status === 404) return 'warning';
    if (error.status >= 500) return 'error';
    return 'error';
  }
  
  /**
   * Show success message
   */
  showSuccess(message, title = 'Success') {
    this.showToast({
      type: 'success',
      title,
      message,
      duration: 3000
    });
  }
  
  /**
   * Show warning message
   */
  showWarning(message, title = 'Warning') {
    this.showToast({
      type: 'warning',
      title,
      message,
      duration: 4000
    });
  }
  
  /**
   * Show error message
   */
  showError(title, message, duration = 5000) {
    this.showToast({
      type: 'error',
      title,
      message,
      duration
    });
  }
  
  /**
   * Show info message
   */
  showInfo(message, title = 'Info') {
    this.showToast({
      type: 'info',
      title,
      message,
      duration: 3000
    });
  }
  
  /**
   * Show toast notification
   */
  showToast({ type, title, message, duration = 3000, actions = [] }) {
    if (!this.toastContainer) {
      console.warn('Toast container not available');
      return;
    }
    
    const toastId = ++this.toastId;
    const toast = this.createToastElement(toastId, type, title, message, actions);
    
    // Add to container
    this.toastContainer.appendChild(toast);
    
    // Auto-remove after duration
    if (duration > 0) {
      setTimeout(() => {
        this.removeToast(toastId);
      }, duration);
    }
    
    return toastId;
  }
  
  /**
   * Create toast element
   */
  createToastElement(id, type, title, message, actions) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.setAttribute('data-toast-id', id);
    
    const content = document.createElement('div');
    content.className = 'toast-content';
    
    if (title) {
      const titleElement = document.createElement('strong');
      titleElement.textContent = title;
      content.appendChild(titleElement);
    }
    
    if (message) {
      const messageElement = document.createElement('p');
      messageElement.textContent = message;
      content.appendChild(messageElement);
    }
    
    // Add actions if provided
    if (actions.length > 0) {
      const actionsContainer = document.createElement('div');
      actionsContainer.className = 'toast-actions';
      
      actions.forEach(action => {
        const button = document.createElement('button');
        button.className = `btn ${action.type || 'secondary'}`;
        button.textContent = action.label;
        button.addEventListener('click', () => {
          if (action.handler) action.handler();
          this.removeToast(id);
        });
        actionsContainer.appendChild(button);
      });
      
      content.appendChild(actionsContainer);
    }
    
    toast.appendChild(content);
    
    // Close button
    const closeButton = document.createElement('button');
    closeButton.className = 'toast-close';
    closeButton.innerHTML = '&times;';
    closeButton.setAttribute('aria-label', 'Close notification');
    closeButton.addEventListener('click', () => this.removeToast(id));
    
    toast.appendChild(closeButton);
    
    return toast;
  }
  
  /**
   * Remove toast by ID
   */
  removeToast(id) {
    const toast = this.toastContainer?.querySelector(`[data-toast-id="${id}"]`);
    if (toast) {
      toast.style.animation = 'slideOut 0.3s ease-in forwards';
      setTimeout(() => {
        if (toast.parentNode) {
          toast.parentNode.removeChild(toast);
        }
      }, 300);
    }
  }
  
  /**
   * Clear all toasts
   */
  clearAllToasts() {
    if (this.toastContainer) {
      this.toastContainer.innerHTML = '';
    }
  }
  
  /**
   * Handle validation errors
   */
  handleValidationError(errors) {
    if (Array.isArray(errors)) {
      errors.forEach(error => {
        this.showError('Validation Error', error.message || error);
      });
    } else if (typeof errors === 'object') {
      Object.entries(errors).forEach(([field, messages]) => {
        const messageList = Array.isArray(messages) ? messages : [messages];
        messageList.forEach(message => {
          this.showError('Validation Error', `${field}: ${message}`);
        });
      });
    } else {
      this.showError('Validation Error', errors);
    }
  }
  
  /**
   * Show confirmation dialog
   */
  showConfirmation(message, title = 'Confirm') {
    return new Promise((resolve) => {
      const actions = [
        {
          label: 'Cancel',
          type: 'secondary',
          handler: () => resolve(false)
        },
        {
          label: 'Confirm',
          type: 'primary',
          handler: () => resolve(true)
        }
      ];
      
      this.showToast({
        type: 'warning',
        title,
        message,
        duration: 0, // Don't auto-close
        actions
      });
    });
  }
}

// Add CSS for toast animations
const style = document.createElement('style');
style.textContent = `
  @keyframes slideOut {
    from {
      transform: translateX(0);
      opacity: 1;
    }
    to {
      transform: translateX(100%);
      opacity: 0;
    }
  }
  
  .toast-actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.75rem;
  }
  
  .toast-actions .btn {
    padding: 0.25rem 0.75rem;
    font-size: 0.8rem;
  }
`;
document.head.appendChild(style);