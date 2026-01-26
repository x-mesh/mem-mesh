/**
 * Context Timeline Web Component
 * Visualizes memory relationships in a timeline format
 */

class ContextTimeline extends HTMLElement {
  static get observedAttributes() {
    return ['memory-id', 'context-data', 'depth'];
  }
  
  constructor() {
    super();
    this.memoryId = null;
    this.contextData = [];
    this.depth = 2;
    this.svgWidth = 800;
    this.svgHeight = 400;
    this.nodeRadius = 8;
    this.levelHeight = 80;
  }
  
  connectedCallback() {
    this.render();
    this.setupEventListeners();
  }
  
  disconnectedCallback() {
    this.removeEventListeners();
  }
  
  attributeChangedCallback(name, oldValue, newValue) {
    if (oldValue !== newValue) {
      switch (name) {
        case 'memory-id':
          this.memoryId = newValue;
          break;
        case 'context-data':
          try {
            this.contextData = JSON.parse(newValue);
          } catch {
            this.contextData = [];
          }
          break;
        case 'depth':
          this.depth = parseInt(newValue) || 2;
          break;
      }
      this.render();
    }
  }
  
  /**
   * Setup event listeners
   */
  setupEventListeners() {
    this.addEventListener('click', this.handleClick.bind(this));
    
    // Add resize observer for responsive behavior
    if (window.ResizeObserver) {
      this.resizeObserver = new ResizeObserver(() => {
        this.updateDimensions();
        this.render();
      });
      this.resizeObserver.observe(this);
    }
  }
  
  /**
   * Remove event listeners
   */
  removeEventListeners() {
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
    }
  }
  
  /**
   * Handle click events
   */
  handleClick(event) {
    const target = event.target;
    
    if (target.classList.contains('timeline-node')) {
      const memoryId = target.getAttribute('data-memory-id');
      if (memoryId) {
        this.dispatchEvent(new CustomEvent('memory-select', {
          detail: { memoryId },
          bubbles: true
        }));
      }
    } else if (target.classList.contains('expand-btn')) {
      const memoryId = target.getAttribute('data-memory-id');
      this.expandContext(memoryId);
    }
  }
  
  /**
   * Update dimensions based on container size
   */
  updateDimensions() {
    const rect = this.getBoundingClientRect();
    this.svgWidth = Math.max(400, rect.width - 32); // Account for padding
    this.svgHeight = Math.max(300, this.calculateRequiredHeight());
  }
  
  /**
   * Calculate required height based on context data
   */
  calculateRequiredHeight() {
    const levels = this.groupByTimeLevel(this.contextData);
    return Math.max(300, levels.length * this.levelHeight + 100);
  }
  
  /**
   * Group memories by time level for timeline layout
   */
  groupByTimeLevel(memories) {
    if (!memories.length) return [];
    
    // Sort by created_at
    const sorted = [...memories].sort((a, b) => 
      new Date(a.created_at) - new Date(b.created_at)
    );
    
    // Group by time periods (days, weeks, months depending on range)
    const groups = [];
    const timeRange = new Date(sorted[sorted.length - 1].created_at) - new Date(sorted[0].created_at);
    const groupingInterval = this.getGroupingInterval(timeRange);
    
    let currentGroup = null;
    let currentGroupTime = null;
    
    sorted.forEach(memory => {
      const memoryTime = new Date(memory.created_at);
      const groupTime = this.getGroupTime(memoryTime, groupingInterval);
      
      if (!currentGroup || groupTime !== currentGroupTime) {
        currentGroup = {
          time: groupTime,
          label: this.formatGroupLabel(groupTime, groupingInterval),
          memories: []
        };
        groups.push(currentGroup);
        currentGroupTime = groupTime;
      }
      
      currentGroup.memories.push(memory);
    });
    
    return groups;
  }
  
  /**
   * Get appropriate grouping interval based on time range
   */
  getGroupingInterval(timeRange) {
    const days = timeRange / (1000 * 60 * 60 * 24);
    
    if (days <= 7) return 'day';
    if (days <= 30) return 'week';
    if (days <= 365) return 'month';
    return 'year';
  }
  
  /**
   * Get group time based on interval
   */
  getGroupTime(date, interval) {
    switch (interval) {
      case 'day':
        return date.toDateString();
      case 'week':
        const weekStart = new Date(date);
        weekStart.setDate(date.getDate() - date.getDay());
        return weekStart.toDateString();
      case 'month':
        return `${date.getFullYear()}-${date.getMonth()}`;
      case 'year':
        return date.getFullYear().toString();
      default:
        return date.toDateString();
    }
  }
  
  /**
   * Format group label
   */
  formatGroupLabel(groupTime, interval) {
    switch (interval) {
      case 'day':
        return new Date(groupTime).toLocaleDateString();
      case 'week':
        const weekStart = new Date(groupTime);
        const weekEnd = new Date(weekStart);
        weekEnd.setDate(weekStart.getDate() + 6);
        return `${weekStart.toLocaleDateString()} - ${weekEnd.toLocaleDateString()}`;
      case 'month':
        const [year, month] = groupTime.split('-');
        return new Date(year, month).toLocaleDateString('en-US', { year: 'numeric', month: 'long' });
      case 'year':
        return groupTime;
      default:
        return groupTime;
    }
  }
  
  /**
   * Get category color
   */
  getCategoryColor(category) {
    const colors = {
      task: '#2563eb',
      bug: '#ef4444',
      idea: '#f59e0b',
      decision: '#8b5cf6',
      incident: '#ef4444',
      code_snippet: '#10b981'
    };
    return colors[category] || '#64748b';
  }
  
  /**
   * Get relationship color
   */
  getRelationshipColor(relationType) {
    const colors = {
      before: '#10b981',
      after: '#f59e0b',
      similar: '#2563eb',
      related: '#64748b'
    };
    return colors[relationType] || '#64748b';
  }
  
  /**
   * Create SVG timeline
   */
  createTimeline() {
    const levels = this.groupByTimeLevel(this.contextData);
    if (!levels.length) {
      return '<div class="no-context">No context data available</div>';
    }
    
    const centerX = this.svgWidth / 2;
    let currentY = 50;
    
    let svgContent = `
      <svg width="${this.svgWidth}" height="${this.svgHeight}" class="timeline-svg">
        <defs>
          <marker id="arrowhead" markerWidth="10" markerHeight="7" 
                  refX="9" refY="3.5" orient="auto">
            <polygon points="0 0, 10 3.5, 0 7" fill="#64748b" />
          </marker>
        </defs>
    `;
    
    // Draw timeline spine
    svgContent += `
      <line x1="${centerX}" y1="20" x2="${centerX}" y2="${this.svgHeight - 20}" 
            stroke="var(--border-color)" stroke-width="2" class="timeline-spine"/>
    `;
    
    levels.forEach((level, levelIndex) => {
      // Draw time label
      svgContent += `
        <text x="20" y="${currentY + 5}" class="time-label" fill="var(--text-secondary)">
          ${level.label}
        </text>
      `;
      
      // Draw memories in this level
      const memoriesPerRow = Math.min(level.memories.length, 5);
      const spacing = Math.min(120, (this.svgWidth - 200) / memoriesPerRow);
      const startX = centerX - (memoriesPerRow - 1) * spacing / 2;
      
      level.memories.forEach((memory, memoryIndex) => {
        const x = startX + (memoryIndex % memoriesPerRow) * spacing;
        const y = currentY + Math.floor(memoryIndex / memoriesPerRow) * 40;
        
        // Draw connection to timeline spine
        svgContent += `
          <line x1="${centerX}" y1="${y}" x2="${x}" y2="${y}" 
                stroke="var(--border-color)" stroke-width="1" stroke-dasharray="3,3"/>
        `;
        
        // Draw memory node
        const isCurrentMemory = memory.id === this.memoryId;
        const nodeColor = isCurrentMemory ? 'var(--primary-color)' : this.getCategoryColor(memory.category);
        const nodeSize = isCurrentMemory ? this.nodeRadius + 2 : this.nodeRadius;
        
        svgContent += `
          <circle cx="${x}" cy="${y}" r="${nodeSize}" 
                  fill="${nodeColor}" 
                  stroke="white" 
                  stroke-width="2"
                  class="timeline-node ${isCurrentMemory ? 'current' : ''}"
                  data-memory-id="${memory.id}"
                  title="${memory.content.substring(0, 100)}..."/>
        `;
        
        // Draw memory preview
        svgContent += `
          <foreignObject x="${x - 60}" y="${y + nodeSize + 5}" width="120" height="40">
            <div class="memory-preview" data-memory-id="${memory.id}">
              <div class="memory-title">${this.truncateText(memory.content, 20)}</div>
              <div class="memory-meta">${memory.category}</div>
            </div>
          </foreignObject>
        `;
      });
      
      currentY += this.levelHeight;
    });
    
    // Draw relationships
    this.drawRelationships(svgContent, levels);
    
    svgContent += '</svg>';
    return svgContent;
  }
  
  /**
   * Draw relationship connections
   */
  drawRelationships(svgContent, levels) {
    // This would draw curved lines between related memories
    // For now, we'll keep it simple and just show the basic timeline
    // In a full implementation, this would analyze the context relationships
    // and draw appropriate connecting lines
  }
  
  /**
   * Truncate text to specified length
   */
  truncateText(text, maxLength) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  }
  
  /**
   * Expand context for a specific memory
   */
  async expandContext(memoryId) {
    this.dispatchEvent(new CustomEvent('context-expand', {
      detail: { memoryId, depth: this.depth + 1 },
      bubbles: true
    }));
  }
  
  /**
   * Load context data
   */
  async loadContextData() {
    if (!this.memoryId) return;
    
    try {
      if (window.app && window.app.apiClient) {
        const contextData = await window.app.apiClient.getContext(this.memoryId, this.depth);
        this.contextData = contextData.memories || [];
        this.render();
      }
    } catch (error) {
      console.error('Failed to load context data:', error);
      this.contextData = [];
      this.render();
    }
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'context-timeline';
    
    if (!this.contextData.length && this.memoryId) {
      this.innerHTML = `
        <div class="timeline-header">
          <h3>Context Timeline</h3>
          <div class="timeline-controls">
            <label>
              Depth: 
              <select class="depth-select">
                <option value="1" ${this.depth === 1 ? 'selected' : ''}>1</option>
                <option value="2" ${this.depth === 2 ? 'selected' : ''}>2</option>
                <option value="3" ${this.depth === 3 ? 'selected' : ''}>3</option>
                <option value="4" ${this.depth === 4 ? 'selected' : ''}>4</option>
                <option value="5" ${this.depth === 5 ? 'selected' : ''}>5</option>
              </select>
            </label>
            <button class="refresh-btn" title="Refresh context"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"/></svg></button>
          </div>
        </div>
        <div class="timeline-loading">
          <div class="loading-spinner"></div>
          <p>Loading context...</p>
        </div>
      `;
      
      // Load context data
      this.loadContextData();
      return;
    }
    
    this.innerHTML = `
      <div class="timeline-header">
        <h3>Context Timeline</h3>
        <div class="timeline-controls">
          <label>
            Depth: 
            <select class="depth-select">
              <option value="1" ${this.depth === 1 ? 'selected' : ''}>1</option>
              <option value="2" ${this.depth === 2 ? 'selected' : ''}>2</option>
              <option value="3" ${this.depth === 3 ? 'selected' : ''}>3</option>
              <option value="4" ${this.depth === 4 ? 'selected' : ''}>4</option>
              <option value="5" ${this.depth === 5 ? 'selected' : ''}>5</option>
            </select>
          </label>
          <button class="refresh-btn" title="Refresh context"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"/></svg></button>
        </div>
      </div>
      <div class="timeline-container">
        ${this.createTimeline()}
      </div>
      <div class="timeline-legend">
        <div class="legend-item">
          <div class="legend-color" style="background: var(--primary-color)"></div>
          <span>Current Memory</span>
        </div>
        <div class="legend-item">
          <div class="legend-color" style="background: #10b981"></div>
          <span>Before</span>
        </div>
        <div class="legend-item">
          <div class="legend-color" style="background: #f59e0b"></div>
          <span>After</span>
        </div>
        <div class="legend-item">
          <div class="legend-color" style="background: #2563eb"></div>
          <span>Similar</span>
        </div>
      </div>
    `;
    
    // Setup control event listeners
    const depthSelect = this.querySelector('.depth-select');
    const refreshBtn = this.querySelector('.refresh-btn');
    
    if (depthSelect) {
      depthSelect.addEventListener('change', (event) => {
        this.depth = parseInt(event.target.value);
        this.setAttribute('depth', this.depth);
        this.loadContextData();
      });
    }
    
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        this.loadContextData();
      });
    }
  }
}

// Define the custom element
customElements.define('context-timeline', ContextTimeline);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .context-timeline {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    overflow: hidden;
  }
  
  .timeline-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
  }
  
  .timeline-header h3 {
    margin: 0;
    font-size: 1.125rem;
    color: var(--text-primary);
  }
  
  .timeline-controls {
    display: flex;
    align-items: center;
    gap: 1rem;
  }
  
  .timeline-controls label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
    color: var(--text-secondary);
  }
  
  .depth-select {
    padding: 0.25rem 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.875rem;
  }
  
  .refresh-btn {
    background: none;
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    padding: 0.25rem 0.5rem;
    border-radius: var(--border-radius-sm);
    cursor: pointer;
    font-size: 1rem;
    transition: var(--transition);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .refresh-btn svg {
    width: 16px;
    height: 16px;
    stroke: currentColor;
  }
  
  .refresh-btn:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }
  
  .timeline-container {
    padding: 1rem;
    overflow-x: auto;
  }
  
  .timeline-svg {
    display: block;
    margin: 0 auto;
  }
  
  .timeline-node {
    cursor: pointer;
    transition: var(--transition);
  }
  
  .timeline-node:hover {
    stroke-width: 3;
    filter: brightness(1.1);
  }
  
  .timeline-node.current {
    filter: drop-shadow(0 0 8px var(--primary-color));
  }
  
  .time-label {
    font-size: 0.75rem;
    font-weight: 500;
  }
  
  .memory-preview {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm);
    padding: 0.5rem;
    font-size: 0.75rem;
    text-align: center;
    box-shadow: var(--shadow-sm);
    cursor: pointer;
    transition: var(--transition);
  }
  
  .memory-preview:hover {
    box-shadow: var(--shadow-md);
    transform: translateY(-1px);
  }
  
  .memory-title {
    font-weight: 500;
    color: var(--text-primary);
    margin-bottom: 0.25rem;
    line-height: 1.2;
  }
  
  .memory-meta {
    color: var(--text-muted);
    font-size: 0.625rem;
  }
  
  .timeline-legend {
    display: flex;
    justify-content: center;
    gap: 1rem;
    padding: 1rem;
    background: var(--bg-secondary);
    border-top: 1px solid var(--border-color);
    flex-wrap: wrap;
  }
  
  .legend-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.75rem;
    color: var(--text-secondary);
  }
  
  .legend-color {
    width: 0.75rem;
    height: 0.75rem;
    border-radius: 50%;
  }
  
  .timeline-loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 3rem;
    color: var(--text-muted);
  }
  
  .loading-spinner {
    width: 2rem;
    height: 2rem;
    border: 2px solid var(--border-color);
    border-top: 2px solid var(--primary-color);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-bottom: 1rem;
  }
  
  @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }
  
  .no-context {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 3rem;
    color: var(--text-muted);
    font-style: italic;
  }
  
  /* Responsive design */
  @media (max-width: 768px) {
    .timeline-header {
      flex-direction: column;
      gap: 1rem;
      align-items: flex-start;
    }
    
    .timeline-controls {
      align-self: stretch;
      justify-content: space-between;
    }
    
    .timeline-container {
      padding: 0.5rem;
    }
    
    .timeline-legend {
      gap: 0.5rem;
      padding: 0.75rem;
    }
    
    .legend-item {
      font-size: 0.625rem;
    }
  }
`;

document.head.appendChild(style);

export { ContextTimeline };