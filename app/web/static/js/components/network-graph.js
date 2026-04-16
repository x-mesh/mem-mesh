/**
 * Network Graph Web Component
 * Visualizes memory relationships as an interactive network graph
 */

class NetworkGraph extends HTMLElement {
  static get observedAttributes() {
    return ['memory-id', 'context-data', 'depth'];
  }
  
  constructor() {
    super();
    this.memoryId = null;
    this.contextData = [];
    this.depth = 2;
    this.svgWidth = 800;
    this.svgHeight = 600;
    this.nodes = [];
    this.links = [];
    this.simulation = null;
    this.zoom = null;
    this.isDragging = false;
  }
  
  connectedCallback() {
    this.render();
    this.setupEventListeners();
  }
  
  disconnectedCallback() {
    this.removeEventListeners();
    if (this.simulation) {
      this.simulation.stop();
    }
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
      this.updateGraph();
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
        this.updateGraph();
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
    
    if (target.classList.contains('graph-node')) {
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
    this.svgWidth = Math.max(400, rect.width - 32);
    this.svgHeight = Math.max(300, rect.height - 100);
  }
  
  /**
   * Prepare graph data from context
   */
  prepareGraphData() {
    if (!this.contextData.length) {
      return { nodes: [], links: [] };
    }
    
    const nodes = [];
    const links = [];
    const nodeMap = new Map();
    
    // Add current memory as central node
    if (this.memoryId) {
      const currentMemory = this.contextData.find(m => m.id === this.memoryId) || {
        id: this.memoryId,
        content: 'Current Memory',
        category: 'task',
        created_at: new Date().toISOString()
      };
      
      nodes.push({
        id: currentMemory.id,
        content: currentMemory.content,
        category: currentMemory.category,
        created_at: currentMemory.created_at,
        isCurrent: true,
        x: this.svgWidth / 2,
        y: this.svgHeight / 2
      });
      nodeMap.set(currentMemory.id, 0);
    }
    
    // Add context memories as nodes
    this.contextData.forEach((memory, index) => {
      if (memory.id !== this.memoryId) {
        nodes.push({
          id: memory.id,
          content: memory.content,
          category: memory.category,
          created_at: memory.created_at,
          similarity_score: memory.similarity_score,
          isCurrent: false
        });
        nodeMap.set(memory.id, nodes.length - 1);
      }
    });
    
    // Create links based on relationships
    this.contextData.forEach(memory => {
      if (memory.relationships) {
        memory.relationships.forEach(rel => {
          const sourceIndex = nodeMap.get(memory.id);
          const targetIndex = nodeMap.get(rel.target_id);
          
          if (sourceIndex !== undefined && targetIndex !== undefined) {
            links.push({
              source: sourceIndex,
              target: targetIndex,
              type: rel.type,
              strength: rel.strength || 0.5
            });
          }
        });
      } else if (memory.id !== this.memoryId) {
        // Create default link to current memory
        const sourceIndex = nodeMap.get(this.memoryId);
        const targetIndex = nodeMap.get(memory.id);
        
        if (sourceIndex !== undefined && targetIndex !== undefined) {
          links.push({
            source: sourceIndex,
            target: targetIndex,
            type: 'related',
            strength: memory.similarity_score || 0.5
          });
        }
      }
    });
    
    return { nodes, links };
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
  getRelationshipColor(type) {
    const colors = {
      before: '#10b981',
      after: '#f59e0b',
      similar: '#2563eb',
      related: '#64748b'
    };
    return colors[type] || '#64748b';
  }
  
  /**
   * Create force simulation
   */
  createSimulation(nodes, links) {
    // Stop existing simulation
    if (this.simulation) {
      this.simulation.stop();
    }
    
    // Create new simulation
    this.simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links)
        .id(d => d.id)
        .distance(d => 100 + (1 - d.strength) * 100)
        .strength(d => d.strength * 0.5)
      )
      .force('charge', d3.forceManyBody()
        .strength(-300)
        .distanceMax(300)
      )
      .force('center', d3.forceCenter(this.svgWidth / 2, this.svgHeight / 2))
      .force('collision', d3.forceCollide()
        .radius(d => d.isCurrent ? 40 : 30)
        .strength(0.7)
      );
    
    return this.simulation;
  }
  
  /**
   * Update graph visualization
   */
  updateGraph() {
    if (!this.contextData.length) {
      this.showEmptyState();
      return;
    }
    
    // Check if D3.js is available
    if (typeof d3 === 'undefined') {
      this.showD3LoadingState();
      return;
    }
    
    const { nodes, links } = this.prepareGraphData();
    this.nodes = nodes;
    this.links = links;
    
    // Create SVG if it doesn't exist
    let svg = this.querySelector('.network-svg');
    if (!svg) {
      this.createSVG();
      svg = this.querySelector('.network-svg');
    }
    
    // Update SVG dimensions
    svg.setAttribute('width', this.svgWidth);
    svg.setAttribute('height', this.svgHeight);
    
    // Clear existing content
    const container = d3.select(svg.querySelector('.graph-container'));
    container.selectAll('*').remove();
    
    // Create links
    const linkElements = container.selectAll('.graph-link')
      .data(links)
      .enter()
      .append('line')
      .attr('class', 'graph-link')
      .attr('stroke', d => this.getRelationshipColor(d.type))
      .attr('stroke-width', d => Math.max(1, d.strength * 3))
      .attr('stroke-opacity', 0.6);
    
    // Create nodes
    const nodeElements = container.selectAll('.graph-node')
      .data(nodes)
      .enter()
      .append('g')
      .attr('class', 'graph-node-group');
    
    // Add circles for nodes
    nodeElements.append('circle')
      .attr('class', 'graph-node')
      .attr('r', d => d.isCurrent ? 25 : 15)
      .attr('fill', d => this.getCategoryColor(d.category))
      .attr('stroke', d => d.isCurrent ? '#ffffff' : 'none')
      .attr('stroke-width', d => d.isCurrent ? 3 : 0)
      .attr('data-memory-id', d => d.id)
      .style('cursor', 'pointer');
    
    // Add labels
    nodeElements.append('text')
      .attr('class', 'node-label')
      .attr('text-anchor', 'middle')
      .attr('dy', d => d.isCurrent ? 40 : 25)
      .style('font-size', '12px')
      .style('fill', 'var(--text-primary)')
      .style('pointer-events', 'none')
      .text(d => this.truncateText(d.content, 20));
    
    // Setup drag behavior
    const drag = d3.drag()
      .on('start', (event, d) => {
        if (!event.active) this.simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
        this.isDragging = true;
      })
      .on('drag', (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event, d) => {
        if (!event.active) this.simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
        this.isDragging = false;
      });
    
    nodeElements.call(drag);
    
    // Setup zoom behavior
    this.zoom = d3.zoom()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        container.attr('transform', event.transform);
      });
    
    d3.select(svg).call(this.zoom);
    
    // Create simulation
    const simulation = this.createSimulation(nodes, links);
    
    // Update positions on tick
    simulation.on('tick', () => {
      linkElements
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y);
      
      nodeElements
        .attr('transform', d => `translate(${d.x},${d.y})`);
    });
  }
  
  /**
   * Create SVG element
   */
  createSVG() {
    const container = this.querySelector('.graph-container');
    container.innerHTML = `
      <svg class="network-svg" width="${this.svgWidth}" height="${this.svgHeight}">
        <defs>
          <marker id="arrowhead" markerWidth="10" markerHeight="7" 
                  refX="9" refY="3.5" orient="auto">
            <polygon points="0 0, 10 3.5, 0 7" fill="#64748b" />
          </marker>
        </defs>
        <g class="graph-container"></g>
      </svg>
    `;
  }
  
  /**
   * Show empty state
   */
  showEmptyState() {
    const container = this.querySelector('.graph-container');
    container.innerHTML = `
      <div class="empty-state">
        <p>No context data available</p>
        <button class="refresh-btn">Refresh Context</button>
      </div>
    `;
  }
  
  /**
   * Show D3.js loading state
   */
  showD3LoadingState() {
    const container = this.querySelector('.graph-container');
    container.innerHTML = `
      <div class="d3-loading-state">
        <p>Loading D3.js library...</p>
        <div class="loading-spinner"></div>
      </div>
    `;
    
    // Retry after a short delay
    setTimeout(() => {
      if (typeof d3 !== 'undefined') {
        this.updateGraph();
      }
    }, 1000);
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
        this.updateGraph();
      }
    } catch (error) {
      console.error('Failed to load context data:', error);
      this.contextData = [];
      this.updateGraph();
    }
  }
  
  /**
   * Reset zoom
   */
  resetZoom() {
    if (this.zoom) {
      const svg = this.querySelector('.network-svg');
      d3.select(svg).transition().duration(750).call(
        this.zoom.transform,
        d3.zoomIdentity
      );
    }
  }
  
  /**
   * Fit to view
   */
  fitToView() {
    if (!this.nodes.length) return;
    
    const svg = this.querySelector('.network-svg');
    const container = svg.querySelector('.graph-container');
    
    // Calculate bounds
    const bounds = container.getBBox();
    const fullWidth = this.svgWidth;
    const fullHeight = this.svgHeight;
    const width = bounds.width;
    const height = bounds.height;
    const midX = bounds.x + width / 2;
    const midY = bounds.y + height / 2;
    
    if (width === 0 || height === 0) return;
    
    // Calculate scale and translate
    const scale = Math.min(fullWidth / width, fullHeight / height) * 0.9;
    const translate = [fullWidth / 2 - scale * midX, fullHeight / 2 - scale * midY];
    
    // Apply transform
    d3.select(svg).transition().duration(750).call(
      this.zoom.transform,
      d3.zoomIdentity.translate(translate[0], translate[1]).scale(scale)
    );
  }
  
  /**
   * Render the component
   */
  render() {
    this.className = 'network-graph';
    
    this.innerHTML = `
      <div class="graph-header">
        <h3>Network Graph</h3>
        <div class="graph-controls">
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
          <button class="reset-zoom-btn" title="Reset zoom"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg></button>
          <button class="fit-view-btn" title="Fit to view"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15,3 21,3 21,9"/><polyline points="9,21 3,21 3,15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg></button>
          <button class="refresh-btn" title="Refresh context"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"/></svg></button>
        </div>
      </div>
      <div class="graph-container">
        ${this.contextData.length ? '' : '<div class="graph-loading">Loading network graph...</div>'}
      </div>
      <div class="graph-legend">
        <div class="legend-item">
          <div class="legend-node current"></div>
          <span>Current Memory</span>
        </div>
        <div class="legend-item">
          <div class="legend-node related"></div>
          <span>Related Memory</span>
        </div>
        <div class="legend-item">
          <div class="legend-line before"></div>
          <span>Before</span>
        </div>
        <div class="legend-item">
          <div class="legend-line after"></div>
          <span>After</span>
        </div>
        <div class="legend-item">
          <div class="legend-line similar"></div>
          <span>Similar</span>
        </div>
      </div>
    `;
    
    // Setup control event listeners
    const depthSelect = this.querySelector('.depth-select');
    const resetZoomBtn = this.querySelector('.reset-zoom-btn');
    const fitViewBtn = this.querySelector('.fit-view-btn');
    const refreshBtn = this.querySelector('.refresh-btn');
    
    if (depthSelect) {
      depthSelect.addEventListener('change', (event) => {
        this.depth = parseInt(event.target.value);
        this.setAttribute('depth', this.depth);
        this.loadContextData();
      });
    }
    
    if (resetZoomBtn) {
      resetZoomBtn.addEventListener('click', () => {
        this.resetZoom();
      });
    }
    
    if (fitViewBtn) {
      fitViewBtn.addEventListener('click', () => {
        this.fitToView();
      });
    }
    
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        this.loadContextData();
      });
    }
    
    // Load context data if memory ID is set
    if (this.memoryId && !this.contextData.length) {
      this.loadContextData();
    } else {
      this.updateGraph();
    }
  }
}

// Define the custom element
customElements.define('network-graph', NetworkGraph);

// Add component styles
const style = document.createElement('style');
style.textContent = `
  .network-graph {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    overflow: hidden;
    height: 600px;
    display: flex;
    flex-direction: column;
  }
  
  .graph-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
  }
  
  .graph-header h3 {
    margin: 0;
    font-size: 1.125rem;
    color: var(--text-primary);
  }
  
  .graph-controls {
    display: flex;
    align-items: center;
    gap: 1rem;
  }
  
  .graph-controls label {
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
  
  .reset-zoom-btn,
  .fit-view-btn,
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
  
  .reset-zoom-btn svg,
  .fit-view-btn svg,
  .refresh-btn svg {
    width: 16px;
    height: 16px;
    stroke: currentColor;
  }
  
  .reset-zoom-btn:hover,
  .fit-view-btn:hover,
  .refresh-btn:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }
  
  .graph-container {
    flex: 1;
    position: relative;
    overflow: hidden;
  }
  
  .network-svg {
    width: 100%;
    height: 100%;
    display: block;
  }
  
  .graph-node {
    cursor: pointer;
    transition: var(--transition);
  }
  
  .graph-node:hover {
    stroke-width: 2;
    filter: brightness(1.1);
  }
  
  .graph-link {
    transition: var(--transition);
  }
  
  .graph-link:hover {
    stroke-opacity: 1;
    stroke-width: 3;
  }
  
  .node-label {
    font-family: var(--font-sans);
    font-size: 12px;
    text-anchor: middle;
    pointer-events: none;
    user-select: none;
  }
  
  .graph-loading {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-muted);
    font-style: italic;
  }
  
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-muted);
    text-align: center;
  }
  
  .empty-state p {
    margin: 0 0 1rem 0;
    font-style: italic;
  }
  
  .empty-state .refresh-btn {
    background: var(--primary-color);
    color: white;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: var(--border-radius);
    cursor: pointer;
    font-size: 0.875rem;
    transition: var(--transition);
  }
  
  .empty-state .refresh-btn:hover {
    background: var(--primary-hover);
  }
  
  .d3-loading-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-muted);
    text-align: center;
  }
  
  .d3-loading-state p {
    margin: 0 0 1rem 0;
    font-style: italic;
  }
  
  .loading-spinner {
    width: 24px;
    height: 24px;
    border: 2px solid var(--border-color);
    border-top: 2px solid var(--primary-color);
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }
  
  @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }
  
  .graph-legend {
    display: flex;
    justify-content: center;
    gap: 1.5rem;
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
  
  .legend-node {
    width: 12px;
    height: 12px;
    border-radius: 50%;
  }
  
  .legend-node.current {
    background: var(--primary-color);
    border: 2px solid white;
  }
  
  .legend-node.related {
    background: var(--secondary-color);
  }
  
  .legend-line {
    width: 20px;
    height: 2px;
  }
  
  .legend-line.before {
    background: #10b981;
  }
  
  .legend-line.after {
    background: #f59e0b;
  }
  
  .legend-line.similar {
    background: #2563eb;
  }
  
  /* Responsive design */
  @media (max-width: 768px) {
    .network-graph {
      height: 400px;
    }
    
    .graph-header {
      flex-direction: column;
      gap: 1rem;
      align-items: flex-start;
    }
    
    .graph-controls {
      align-self: stretch;
      justify-content: space-between;
    }
    
    .graph-legend {
      gap: 1rem;
      padding: 0.75rem;
    }
    
    .legend-item {
      font-size: 0.625rem;
    }
  }
`;

document.head.appendChild(style);

// Note: This component requires D3.js for force simulation
// Add D3.js script if not already included
if (typeof d3 === 'undefined') {
  const script = document.createElement('script');
  script.src = 'https://d3js.org/d3.v7.min.js';
  script.onload = () => {
    console.log('D3.js loaded for NetworkGraph component');
    // Trigger update for any existing NetworkGraph components
    document.querySelectorAll('network-graph').forEach(graph => {
      if (graph.contextData && graph.contextData.length > 0) {
        graph.updateGraph();
      }
    });
  };
  script.onerror = () => {
    console.error('Failed to load D3.js library');
  };
  document.head.appendChild(script);
}

export { NetworkGraph };