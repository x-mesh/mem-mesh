/**
 * Virtual Scroll Utility
 * Implements virtual scrolling for large lists to improve performance
 */

export class VirtualScroll {
  constructor(container, options = {}) {
    this.container = container;
    this.options = {
      itemHeight: options.itemHeight || 100,
      buffer: options.buffer || 5,
      renderItem: options.renderItem || this.defaultRenderItem,
      getItemHeight: options.getItemHeight || (() => this.options.itemHeight),
      ...options
    };
    
    this.items = [];
    this.visibleItems = [];
    this.scrollTop = 0;
    this.containerHeight = 0;
    this.totalHeight = 0;
    this.startIndex = 0;
    this.endIndex = 0;
    
    this.init();
  }
  
  /**
   * Initialize virtual scroll
   */
  init() {
    this.container.style.position = 'relative';
    this.container.style.overflow = 'auto';
    
    // Create viewport
    this.viewport = document.createElement('div');
    this.viewport.style.position = 'absolute';
    this.viewport.style.top = '0';
    this.viewport.style.left = '0';
    this.viewport.style.right = '0';
    this.container.appendChild(this.viewport);
    
    // Create spacer for total height
    this.spacer = document.createElement('div');
    this.spacer.style.position = 'absolute';
    this.spacer.style.top = '0';
    this.spacer.style.left = '0';
    this.spacer.style.right = '0';
    this.spacer.style.zIndex = '-1';
    this.container.appendChild(this.spacer);
    
    this.setupEventListeners();
    this.updateContainerHeight();
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    this.container.addEventListener('scroll', this.handleScroll.bind(this));
    
    // Handle resize
    if (window.ResizeObserver) {
      this.resizeObserver = new ResizeObserver(() => {
        this.updateContainerHeight();
        this.render();
      });
      this.resizeObserver.observe(this.container);
    } else {
      window.addEventListener('resize', () => {
        this.updateContainerHeight();
        this.render();
      });
    }
  }
  
  /**
   * Handle scroll event
   */
  handleScroll() {
    this.scrollTop = this.container.scrollTop;
    this.render();
  }
  
  /**
   * Update container height
   */
  updateContainerHeight() {
    this.containerHeight = this.container.clientHeight;
  }
  
  /**
   * Set items to display
   */
  setItems(items) {
    this.items = items;
    this.calculateTotalHeight();
    this.render();
  }
  
  /**
   * Calculate total height of all items
   */
  calculateTotalHeight() {
    if (typeof this.options.getItemHeight === 'function') {
      this.totalHeight = this.items.reduce((total, item, index) => {
        return total + this.options.getItemHeight(item, index);
      }, 0);
    } else {
      this.totalHeight = this.items.length * this.options.itemHeight;
    }
    
    this.spacer.style.height = `${this.totalHeight}px`;
  }
  
  /**
   * Calculate visible range
   */
  calculateVisibleRange() {
    const itemHeight = this.options.itemHeight;
    const buffer = this.options.buffer;
    
    // Simple calculation for fixed height items
    if (typeof this.options.getItemHeight !== 'function') {
      this.startIndex = Math.max(0, Math.floor(this.scrollTop / itemHeight) - buffer);
      this.endIndex = Math.min(
        this.items.length - 1,
        Math.ceil((this.scrollTop + this.containerHeight) / itemHeight) + buffer
      );
      return;
    }
    
    // Complex calculation for variable height items
    let currentHeight = 0;
    this.startIndex = 0;
    this.endIndex = 0;
    
    // Find start index
    for (let i = 0; i < this.items.length; i++) {
      const height = this.options.getItemHeight(this.items[i], i);
      if (currentHeight + height > this.scrollTop) {
        this.startIndex = Math.max(0, i - buffer);
        break;
      }
      currentHeight += height;
    }
    
    // Find end index
    const visibleBottom = this.scrollTop + this.containerHeight;
    currentHeight = this.getOffsetTop(this.startIndex);
    
    for (let i = this.startIndex; i < this.items.length; i++) {
      const height = this.options.getItemHeight(this.items[i], i);
      if (currentHeight > visibleBottom) {
        this.endIndex = Math.min(this.items.length - 1, i + buffer);
        break;
      }
      currentHeight += height;
      this.endIndex = i;
    }
  }
  
  /**
   * Get offset top for an item index
   */
  getOffsetTop(index) {
    if (typeof this.options.getItemHeight !== 'function') {
      return index * this.options.itemHeight;
    }
    
    let offset = 0;
    for (let i = 0; i < index; i++) {
      offset += this.options.getItemHeight(this.items[i], i);
    }
    return offset;
  }
  
  /**
   * Render visible items
   */
  render() {
    if (!this.items.length) {
      this.viewport.innerHTML = '';
      return;
    }
    
    this.calculateVisibleRange();
    
    // Clear viewport
    this.viewport.innerHTML = '';
    
    // Render visible items
    const fragment = document.createDocumentFragment();
    let currentTop = this.getOffsetTop(this.startIndex);
    
    for (let i = this.startIndex; i <= this.endIndex; i++) {
      const item = this.items[i];
      const element = this.options.renderItem(item, i);
      
      // Position element
      element.style.position = 'absolute';
      element.style.top = `${currentTop}px`;
      element.style.left = '0';
      element.style.right = '0';
      
      // Set height if specified
      const height = this.options.getItemHeight(item, i);
      if (height) {
        element.style.height = `${height}px`;
      }
      
      fragment.appendChild(element);
      currentTop += height;
    }
    
    this.viewport.appendChild(fragment);
    this.visibleItems = this.items.slice(this.startIndex, this.endIndex + 1);
  }
  
  /**
   * Default render item function
   */
  defaultRenderItem(item, index) {
    const element = document.createElement('div');
    element.textContent = typeof item === 'string' ? item : JSON.stringify(item);
    element.style.padding = '1rem';
    element.style.borderBottom = '1px solid #e5e7eb';
    return element;
  }
  
  /**
   * Scroll to specific item
   */
  scrollToItem(index) {
    if (index < 0 || index >= this.items.length) return;
    
    const offset = this.getOffsetTop(index);
    this.container.scrollTop = offset;
  }
  
  /**
   * Scroll to top
   */
  scrollToTop() {
    this.container.scrollTop = 0;
  }
  
  /**
   * Scroll to bottom
   */
  scrollToBottom() {
    this.container.scrollTop = this.totalHeight;
  }
  
  /**
   * Get visible items
   */
  getVisibleItems() {
    return this.visibleItems;
  }
  
  /**
   * Get visible range
   */
  getVisibleRange() {
    return {
      start: this.startIndex,
      end: this.endIndex
    };
  }
  
  /**
   * Update item at index
   */
  updateItem(index, newItem) {
    if (index >= 0 && index < this.items.length) {
      this.items[index] = newItem;
      
      // Re-calculate height if necessary
      if (typeof this.options.getItemHeight === 'function') {
        this.calculateTotalHeight();
      }
      
      // Re-render if item is visible
      if (index >= this.startIndex && index <= this.endIndex) {
        this.render();
      }
    }
  }
  
  /**
   * Add item
   */
  addItem(item, index = -1) {
    if (index === -1 || index >= this.items.length) {
      this.items.push(item);
    } else {
      this.items.splice(index, 0, item);
    }
    
    this.calculateTotalHeight();
    this.render();
  }
  
  /**
   * Remove item
   */
  removeItem(index) {
    if (index >= 0 && index < this.items.length) {
      this.items.splice(index, 1);
      this.calculateTotalHeight();
      this.render();
    }
  }
  
  /**
   * Destroy virtual scroll
   */
  destroy() {
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
    }
    
    this.container.removeEventListener('scroll', this.handleScroll.bind(this));
    
    if (this.viewport && this.viewport.parentNode) {
      this.viewport.parentNode.removeChild(this.viewport);
    }
    
    if (this.spacer && this.spacer.parentNode) {
      this.spacer.parentNode.removeChild(this.spacer);
    }
  }
}