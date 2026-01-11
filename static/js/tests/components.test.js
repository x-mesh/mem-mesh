/**
 * Web Components Tests
 * Tests for memory card, search bar, and other core components
 */

import { describe, it, expect, beforeEach, afterEach, createMock, DOMTestUtils } from './test-runner.js';

// Mock window.app for testing
const mockApp = {
  apiClient: {
    searchMemories: createMock(),
    getMemory: createMock(),
    createMemory: createMock(),
    updateMemory: createMock(),
    deleteMemory: createMock()
  },
  router: {
    navigate: createMock()
  }
};

describe('MemoryCard Component', () => {
  let memoryCard;
  
  beforeEach(async () => {
    window.app = mockApp;
    memoryCard = await DOMTestUtils.createComponent('memory-card');
  });
  
  afterEach(() => {
    DOMTestUtils.cleanup();
    delete window.app;
  });
  
  it('should render with default content', () => {
    expect(memoryCard).toBeTruthy();
    expect(memoryCard.tagName.toLowerCase()).toBe('memory-card');
  });
  
  it('should display memory data when set', () => {
    const testMemory = {
      id: 'test-123',
      content: 'Test memory content',
      category: 'task',
      created_at: '2024-01-01T00:00:00Z',
      tags: ['test', 'example']
    };
    
    memoryCard.setAttribute('memory-data', JSON.stringify(testMemory));
    
    const content = memoryCard.querySelector('.memory-content');
    expect(content).toBeTruthy();
    expect(content.textContent).toContain('Test memory content');
  });
  
  it('should handle click events', () => {
    const testMemory = {
      id: 'test-123',
      content: 'Test memory content'
    };
    
    memoryCard.setAttribute('memory-data', JSON.stringify(testMemory));
    
    DOMTestUtils.fireEvent(memoryCard, 'click');
    
    expect(mockApp.router.navigate).toHaveBeenCalledWith('/memory/test-123');
  });
  
  it('should display category badge', () => {
    const testMemory = {
      id: 'test-123',
      content: 'Test memory content',
      category: 'bug'
    };
    
    memoryCard.setAttribute('memory-data', JSON.stringify(testMemory));
    
    const categoryBadge = memoryCard.querySelector('.category-badge');
    expect(categoryBadge).toBeTruthy();
    expect(categoryBadge.textContent).toBe('bug');
  });
  
  it('should display tags', () => {
    const testMemory = {
      id: 'test-123',
      content: 'Test memory content',
      tags: ['urgent', 'frontend']
    };
    
    memoryCard.setAttribute('memory-data', JSON.stringify(testMemory));
    
    const tags = memoryCard.querySelectorAll('.tag');
    expect(tags).toHaveLength(2);
    expect(tags[0].textContent).toBe('urgent');
    expect(tags[1].textContent).toBe('frontend');
  });
});

describe('SearchBar Component', () => {
  let searchBar;
  
  beforeEach(async () => {
    window.app = mockApp;
    searchBar = await DOMTestUtils.createComponent('search-bar');
  });
  
  afterEach(() => {
    DOMTestUtils.cleanup();
    delete window.app;
  });
  
  it('should render search input', () => {
    const input = searchBar.querySelector('input[type="search"]');
    expect(input).toBeTruthy();
    expect(input.placeholder).toContain('Search');
  });
  
  it('should handle input events with debouncing', async () => {
    const input = searchBar.querySelector('input[type="search"]');
    
    input.value = 'test query';
    DOMTestUtils.fireEvent(input, 'input');
    
    // Should not search immediately (debounced)
    expect(mockApp.apiClient.searchMemories).not.toHaveBeenCalled();
    
    // Wait for debounce
    await new Promise(resolve => setTimeout(resolve, 350));
    
    expect(mockApp.apiClient.searchMemories).toHaveBeenCalledWith('test query', expect.any(Object));
  });
  
  it('should handle keyboard shortcuts', () => {
    const input = searchBar.querySelector('input[type="search"]');
    
    // Simulate Ctrl+K
    const event = new KeyboardEvent('keydown', {
      key: 'k',
      ctrlKey: true,
      bubbles: true
    });
    
    document.dispatchEvent(event);
    
    expect(document.activeElement).toBe(input);
  });
  
  it('should show search suggestions', async () => {
    mockApp.apiClient.searchMemories.mockResolvedValue({
      memories: [
        { id: '1', content: 'First result' },
        { id: '2', content: 'Second result' }
      ]
    });
    
    const input = searchBar.querySelector('input[type="search"]');
    input.value = 'test';
    DOMTestUtils.fireEvent(input, 'input');
    
    await new Promise(resolve => setTimeout(resolve, 350));
    
    const suggestions = searchBar.querySelector('.search-suggestions');
    expect(suggestions).toBeTruthy();
    expect(suggestions.style.display).not.toBe('none');
  });
});

describe('FilterPanel Component', () => {
  let filterPanel;
  
  beforeEach(async () => {
    filterPanel = await DOMTestUtils.createComponent('filter-panel');
  });
  
  afterEach(() => {
    DOMTestUtils.cleanup();
  });
  
  it('should render filter controls', () => {
    const categorySelect = filterPanel.querySelector('.category-filter');
    const projectInput = filterPanel.querySelector('.project-filter');
    const dateInputs = filterPanel.querySelectorAll('input[type="date"]');
    
    expect(categorySelect).toBeTruthy();
    expect(projectInput).toBeTruthy();
    expect(dateInputs).toHaveLength(2); // start and end date
  });
  
  it('should emit filter change events', () => {
    let filterChangeEvent = null;
    
    filterPanel.addEventListener('filter-change', (event) => {
      filterChangeEvent = event;
    });
    
    const categorySelect = filterPanel.querySelector('.category-filter');
    categorySelect.value = 'bug';
    DOMTestUtils.fireEvent(categorySelect, 'change');
    
    expect(filterChangeEvent).toBeTruthy();
    expect(filterChangeEvent.detail.category).toBe('bug');
  });
  
  it('should reset filters', () => {
    const categorySelect = filterPanel.querySelector('.category-filter');
    const projectInput = filterPanel.querySelector('.project-filter');
    
    categorySelect.value = 'bug';
    projectInput.value = 'test-project';
    
    const resetButton = filterPanel.querySelector('.reset-filters');
    DOMTestUtils.fireEvent(resetButton, 'click');
    
    expect(categorySelect.value).toBe('');
    expect(projectInput.value).toBe('');
  });
});

describe('ContextTimeline Component', () => {
  let timeline;
  
  beforeEach(async () => {
    timeline = await DOMTestUtils.createComponent('context-timeline');
  });
  
  afterEach(() => {
    DOMTestUtils.cleanup();
  });
  
  it('should render SVG timeline', () => {
    const svg = timeline.querySelector('svg');
    expect(svg).toBeTruthy();
    expect(svg.classList.contains('timeline-svg')).toBeTruthy();
  });
  
  it('should display context data', () => {
    const contextData = [
      {
        id: '1',
        content: 'First memory',
        created_at: '2024-01-01T00:00:00Z',
        relationship_type: 'before'
      },
      {
        id: '2',
        content: 'Second memory',
        created_at: '2024-01-02T00:00:00Z',
        relationship_type: 'after'
      }
    ];
    
    timeline.setAttribute('context-data', JSON.stringify(contextData));
    
    const nodes = timeline.querySelectorAll('.timeline-node');
    expect(nodes).toHaveLength(2);
  });
  
  it('should handle node clicks', () => {
    let memorySelectEvent = null;
    
    timeline.addEventListener('memory-select', (event) => {
      memorySelectEvent = event;
    });
    
    const contextData = [
      {
        id: 'test-123',
        content: 'Test memory',
        created_at: '2024-01-01T00:00:00Z'
      }
    ];
    
    timeline.setAttribute('context-data', JSON.stringify(contextData));
    
    const node = timeline.querySelector('.timeline-node');
    DOMTestUtils.fireEvent(node, 'click');
    
    expect(memorySelectEvent).toBeTruthy();
    expect(memorySelectEvent.detail.memoryId).toBe('test-123');
  });
});

describe('NetworkGraph Component', () => {
  let networkGraph;
  
  beforeEach(async () => {
    // Mock D3.js for testing
    window.d3 = {
      forceSimulation: createMock(() => ({
        force: createMock(() => ({ force: createMock() })),
        on: createMock(),
        stop: createMock()
      })),
      forceLink: createMock(),
      forceManyBody: createMock(),
      forceCenter: createMock(),
      forceCollide: createMock(),
      select: createMock(() => ({
        selectAll: createMock(() => ({
          data: createMock(() => ({
            enter: createMock(() => ({
              append: createMock(() => ({
                attr: createMock(() => ({ attr: createMock() })),
                style: createMock(() => ({ style: createMock() })),
                text: createMock()
              }))
            }))
          }))
        })),
        call: createMock(),
        transition: createMock(() => ({
          duration: createMock(() => ({
            call: createMock()
          }))
        }))
      })),
      drag: createMock(() => ({
        on: createMock(() => ({ on: createMock() }))
      })),
      zoom: createMock(() => ({
        scaleExtent: createMock(() => ({
          on: createMock()
        }))
      })),
      zoomIdentity: {
        translate: createMock(() => ({
          scale: createMock()
        }))
      }
    };
    
    networkGraph = await DOMTestUtils.createComponent('network-graph');
  });
  
  afterEach(() => {
    DOMTestUtils.cleanup();
    delete window.d3;
  });
  
  it('should render graph container', () => {
    const container = networkGraph.querySelector('.graph-container');
    expect(container).toBeTruthy();
  });
  
  it('should handle context data', () => {
    const contextData = [
      {
        id: '1',
        content: 'Node 1',
        relationships: [{ target_id: '2', type: 'related' }]
      },
      {
        id: '2',
        content: 'Node 2'
      }
    ];
    
    networkGraph.setAttribute('context-data', JSON.stringify(contextData));
    networkGraph.setAttribute('memory-id', '1');
    
    // Should process the data and attempt to create graph
    expect(networkGraph.contextData).toEqual(contextData);
    expect(networkGraph.memoryId).toBe('1');
  });
  
  it('should show empty state when no data', () => {
    networkGraph.setAttribute('context-data', JSON.stringify([]));
    
    const emptyState = networkGraph.querySelector('.empty-state');
    expect(emptyState).toBeTruthy();
  });
});

describe('Component Integration', () => {
  beforeEach(() => {
    window.app = mockApp;
  });
  
  afterEach(() => {
    DOMTestUtils.cleanup();
    delete window.app;
  });
  
  it('should handle component communication', async () => {
    const searchBar = await DOMTestUtils.createComponent('search-bar');
    const filterPanel = await DOMTestUtils.createComponent('filter-panel');
    
    let searchEvent = null;
    let filterEvent = null;
    
    document.addEventListener('search-query', (event) => {
      searchEvent = event;
    });
    
    document.addEventListener('filter-change', (event) => {
      filterEvent = event;
    });
    
    // Trigger search
    const searchInput = searchBar.querySelector('input[type="search"]');
    searchInput.value = 'test query';
    DOMTestUtils.fireEvent(searchInput, 'input');
    
    // Trigger filter change
    const categorySelect = filterPanel.querySelector('.category-filter');
    categorySelect.value = 'task';
    DOMTestUtils.fireEvent(categorySelect, 'change');
    
    await new Promise(resolve => setTimeout(resolve, 350));
    
    expect(searchEvent).toBeTruthy();
    expect(filterEvent).toBeTruthy();
  });
  
  it('should handle error states gracefully', async () => {
    mockApp.apiClient.searchMemories.mockRejectedValue(new Error('API Error'));
    
    const searchBar = await DOMTestUtils.createComponent('search-bar');
    const input = searchBar.querySelector('input[type="search"]');
    
    input.value = 'test query';
    DOMTestUtils.fireEvent(input, 'input');
    
    await new Promise(resolve => setTimeout(resolve, 350));
    
    // Should handle error gracefully without crashing
    expect(searchBar.querySelector('.error-message')).toBeTruthy();
  });
});