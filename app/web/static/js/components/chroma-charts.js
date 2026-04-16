/**
 * Chroma-Style Chart Components
 * Professional data visualizations with Chroma color palette
 * Requirements: 7.1, 7.2, 7.3
 */

class ChromaCharts {
  constructor() {
    this.colors = {
      primary: '#64748b',
      secondary: '#94a3b8',
      accent: '#475569',
      success: '#22c55e',
      warning: '#f59e0b',
      error: '#ef4444',
      info: '#3b82f6',
      muted: '#a3a3a3'
    };
    
    this.darkColors = {
      primary: '#94a3b8',
      secondary: '#64748b',
      accent: '#cbd5e1',
      success: '#4ade80',
      warning: '#fbbf24',
      error: '#f87171',
      info: '#60a5fa',
      muted: '#6b7280'
    };
  }

  /**
   * Get current color palette based on theme
   */
  getColors() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    return isDark ? this.darkColors : this.colors;
  }

  /**
   * Create category distribution donut chart
   */
  createCategoryDonutChart(data, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const colors = this.getColors();
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    
    // Monochrome color palette for category chart
    const categoryColors = isDark ? {
      task: '#f9fafb',        // Very light gray (dark theme)
      bug: '#e5e7eb',         // Light gray
      idea: '#d1d5db',        // Medium light gray
      decision: '#9ca3af',    // Medium gray
      code_snippet: '#6b7280', // Dark medium gray
      incident: '#4b5563'     // Dark gray
    } : {
      task: '#1f2937',        // Dark gray (light theme)
      bug: '#374151',         // Medium dark gray
      idea: '#4b5563',        // Medium gray
      decision: '#6b7280',    // Light medium gray
      code_snippet: '#9ca3af', // Light gray
      incident: '#d1d5db'     // Very light gray
    };

    const total = Object.values(data).reduce((sum, count) => sum + count, 0);
    if (total === 0) {
      container.innerHTML = '<div class="no-data">No data available</div>';
      return;
    }

    // Calculate percentages and create segments
    let currentAngle = 0;
    const segments = Object.entries(data).map(([category, count]) => {
      const percentage = (count / total) * 100;
      const angle = (count / total) * 360;
      const segment = {
        category,
        count,
        percentage,
        startAngle: currentAngle,
        endAngle: currentAngle + angle,
        color: categoryColors[category] || colors.muted
      };
      currentAngle += angle;
      return segment;
    });

    container.innerHTML = `
      <div class="chroma-donut-chart">
        <div class="donut-container">
          <svg class="donut-svg" viewBox="0 0 180 180">
            <defs>
              <filter id="donut-shadow">
                <feDropShadow dx="0" dy="2" stdDeviation="4" flood-opacity="0.1"/>
              </filter>
            </defs>
            ${this.createDonutSegments(segments)}
            <circle cx="90" cy="90" r="30" fill="var(--bg-primary)" stroke="var(--border-color)" stroke-width="1"/>
            <text x="90" y="85" text-anchor="middle" class="donut-total-label">Total</text>
            <text x="90" y="100" text-anchor="middle" class="donut-total-value">${total}</text>
          </svg>
          <div class="donut-tooltip" id="donut-tooltip-${containerId}"></div>
        </div>
        <div class="donut-legend">
          ${segments.map(segment => `
            <div class="legend-item" data-category="${segment.category}">
              <div class="legend-color" style="background: ${segment.color}"></div>
              <div class="legend-content">
                <div class="legend-label">${segment.category}</div>
                <div class="legend-value">${segment.count} (${segment.percentage.toFixed(1)}%)</div>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;

    this.setupDonutInteractions(container, segments, containerId);
  }

  /**
   * Create donut chart segments
   */
  createDonutSegments(segments) {
    const centerX = 90;
    const centerY = 90;
    const outerRadius = 70;
    const innerRadius = 40;

    return segments.map((segment, index) => {
      const startAngleRad = (segment.startAngle - 90) * (Math.PI / 180);
      const endAngleRad = (segment.endAngle - 90) * (Math.PI / 180);

      const x1 = centerX + outerRadius * Math.cos(startAngleRad);
      const y1 = centerY + outerRadius * Math.sin(startAngleRad);
      const x2 = centerX + outerRadius * Math.cos(endAngleRad);
      const y2 = centerY + outerRadius * Math.sin(endAngleRad);

      const x3 = centerX + innerRadius * Math.cos(endAngleRad);
      const y3 = centerY + innerRadius * Math.sin(endAngleRad);
      const x4 = centerX + innerRadius * Math.cos(startAngleRad);
      const y4 = centerY + innerRadius * Math.sin(startAngleRad);

      const largeArcFlag = segment.endAngle - segment.startAngle > 180 ? 1 : 0;

      const pathData = [
        `M ${x1} ${y1}`,
        `A ${outerRadius} ${outerRadius} 0 ${largeArcFlag} 1 ${x2} ${y2}`,
        `L ${x3} ${y3}`,
        `A ${innerRadius} ${innerRadius} 0 ${largeArcFlag} 0 ${x4} ${y4}`,
        'Z'
      ].join(' ');

      return `
        <path
          d="${pathData}"
          fill="${segment.color}"
          stroke="var(--bg-primary)"
          stroke-width="2"
          class="donut-segment"
          data-category="${segment.category}"
          data-count="${segment.count}"
          data-percentage="${segment.percentage.toFixed(1)}"
          filter="url(#donut-shadow)"
          style="transition: all 300ms ease; cursor: pointer;"
        />
      `;
    }).join('');
  }

  /**
   * Setup donut chart interactions
   */
  setupDonutInteractions(container, segments, containerId) {
    const tooltip = container.querySelector(`#donut-tooltip-${containerId}`);
    const legendItems = container.querySelectorAll('.legend-item');
    const donutSegments = container.querySelectorAll('.donut-segment');

    // Segment hover effects
    donutSegments.forEach(segment => {
      segment.addEventListener('mouseenter', (e) => {
        const category = e.target.getAttribute('data-category');
        const count = e.target.getAttribute('data-count');
        const percentage = e.target.getAttribute('data-percentage');

        // Highlight segment
        e.target.style.transform = 'scale(1.05)';
        e.target.style.transformOrigin = '90px 90px';
        e.target.style.filter = 'url(#donut-shadow) brightness(1.1)';

        // Show tooltip
        tooltip.innerHTML = `
          <div class="tooltip-content">
            <div class="tooltip-category">${category}</div>
            <div class="tooltip-value">${count} items (${percentage}%)</div>
          </div>
        `;
        tooltip.style.opacity = '1';
        tooltip.style.visibility = 'visible';

        // Highlight legend item
        const legendItem = container.querySelector(`.legend-item[data-category="${category}"]`);
        if (legendItem) {
          legendItem.classList.add('highlighted');
        }
      });

      segment.addEventListener('mouseleave', (e) => {
        const category = e.target.getAttribute('data-category');

        // Reset segment
        e.target.style.transform = '';
        e.target.style.filter = 'url(#donut-shadow)';

        // Hide tooltip
        tooltip.style.opacity = '0';
        tooltip.style.visibility = 'hidden';

        // Remove legend highlight
        const legendItem = container.querySelector(`.legend-item[data-category="${category}"]`);
        if (legendItem) {
          legendItem.classList.remove('highlighted');
        }
      });

      segment.addEventListener('mousemove', (e) => {
        const rect = container.getBoundingClientRect();
        tooltip.style.left = (e.clientX - rect.left + 10) + 'px';
        tooltip.style.top = (e.clientY - rect.top - 10) + 'px';
      });
    });

    // Legend hover effects
    legendItems.forEach(item => {
      item.addEventListener('mouseenter', (e) => {
        const category = e.currentTarget.getAttribute('data-category');
        const segment = container.querySelector(`.donut-segment[data-category="${category}"]`);
        
        if (segment) {
          segment.style.transform = 'scale(1.05)';
          segment.style.transformOrigin = '90px 90px';
          segment.style.filter = 'url(#donut-shadow) brightness(1.1)';
        }
        
        e.currentTarget.classList.add('highlighted');
      });

      item.addEventListener('mouseleave', (e) => {
        const category = e.currentTarget.getAttribute('data-category');
        const segment = container.querySelector(`.donut-segment[data-category="${category}"]`);
        
        if (segment) {
          segment.style.transform = '';
          segment.style.filter = 'url(#donut-shadow)';
        }
        
        e.currentTarget.classList.remove('highlighted');
      });
    });
  }

  /**
   * Create animated bar chart - Horizontal layout
   */
  createBarChart(data, containerId, options = {}) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const {
      title = 'Bar Chart',
      showValues = true,
      animate = true,
      height = 300
    } = options;

    const maxValue = Math.max(...Object.values(data));
    const entries = Object.entries(data);

    container.innerHTML = `
      <div class="chroma-bar-chart horizontal">
        <div class="chart-header">
          <h3 class="chart-title">${title}</h3>
        </div>
        <div class="chart-container-horizontal">
          ${entries.map(([label, value], index) => {
            const percentage = (value / maxValue) * 100;
            const color = this.getBarColor(index, entries.length);
            
            return `
              <div class="bar-row" data-label="${label}" data-value="${value}">
                <div class="bar-label-left" title="${label}">${label}</div>
                <div class="bar-track-horizontal">
                  <div 
                    class="bar-fill-horizontal" 
                    style="
                      width: ${animate ? 0 : percentage}%; 
                      background: ${color};
                      transition: width 800ms cubic-bezier(0.4, 0, 0.2, 1);
                      transition-delay: ${index * 100}ms;
                    "
                    data-target-width="${percentage}"
                  ></div>
                </div>
                ${showValues ? `<div class="bar-value-right">${value}</div>` : ''}
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;

    if (animate) {
      setTimeout(() => {
        const bars = container.querySelectorAll('.bar-fill-horizontal');
        bars.forEach(bar => {
          const targetWidth = bar.getAttribute('data-target-width');
          bar.style.width = targetWidth + '%';
        });
      }, 100);
    }

    this.setupBarChartInteractions(container);
  }

  /**
   * Get bar color based on index - Monochrome palette
   */
  getBarColor(index, total) {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    
    // Monochrome color palette for bar charts
    const monoColors = isDark ? [
      '#f9fafb',  // Very light gray (dark theme)
      '#e5e7eb',  // Light gray
      '#d1d5db',  // Medium light gray
      '#9ca3af',  // Medium gray
      '#6b7280',  // Dark medium gray
      '#4b5563'   // Dark gray
    ] : [
      '#1f2937',  // Dark gray (light theme)
      '#374151',  // Medium dark gray
      '#4b5563',  // Medium gray
      '#6b7280',  // Light medium gray
      '#9ca3af',  // Light gray
      '#d1d5db'   // Very light gray
    ];
    
    return monoColors[index % monoColors.length];
  }

  /**
   * Setup bar chart interactions
   */
  setupBarChartInteractions(container) {
    const barRows = container.querySelectorAll('.bar-row');

    barRows.forEach(row => {
      row.addEventListener('mouseenter', (e) => {
        const bar = e.currentTarget.querySelector('.bar-fill-horizontal');
        if (bar) {
          bar.style.filter = 'brightness(1.15)';
        }
        e.currentTarget.style.background = 'var(--bg-secondary)';
      });

      row.addEventListener('mouseleave', (e) => {
        const bar = e.currentTarget.querySelector('.bar-fill-horizontal');
        if (bar) {
          bar.style.filter = '';
        }
        e.currentTarget.style.background = '';
      });
    });
  }

  /**
   * Create line chart with smooth animations
   */
  createLineChart(data, containerId, options = {}) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const colors = this.getColors();
    const {
      title = 'Line Chart',
      labels = [],
      showPoints = true,
      showGrid = true,
      animate = true,
      height = 300,
      width = 500
    } = options;

    if (!data || data.length === 0) {
      container.innerHTML = '<div class="no-data">No data available</div>';
      return;
    }

    const maxValue = Math.max(...data);
    const minValue = Math.min(...data);
    const range = maxValue - minValue || 1;

    const pointCount = data.length;
    const points = data.map((value, index) => {
      const x = pointCount === 1
        ? (width - 60) / 2 + 30
        : (index / (pointCount - 1)) * (width - 60) + 30;
      const y = height - 40 - ((value - minValue) / range) * (height - 80);
      return { x, y, value };
    });

    const pathData = points.map((point, index) => 
      `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`
    ).join(' ');

    container.innerHTML = `
      <div class="chroma-line-chart">
        <div class="chart-header">
          <h3 class="chart-title">${title}</h3>
        </div>
        <div class="chart-container">
          <svg class="line-chart-svg" viewBox="0 0 ${width} ${height}">
            <defs>
              <linearGradient id="line-gradient-${containerId}" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" style="stop-color:${colors.primary};stop-opacity:0.3" />
                <stop offset="100%" style="stop-color:${colors.primary};stop-opacity:0" />
              </linearGradient>
              <filter id="line-shadow">
                <feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity="0.2"/>
              </filter>
            </defs>
            
            ${showGrid ? this.createGridLines(width, height) : ''}
            
            <!-- Area fill -->
            <path
              d="${pathData} L ${points[points.length - 1].x} ${height - 40} L ${points[0].x} ${height - 40} Z"
              fill="url(#line-gradient-${containerId})"
              class="line-area"
            />
            
            <!-- Main line -->
            <path
              d="${pathData}"
              fill="none"
              stroke="${colors.primary}"
              stroke-width="3"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="line-path"
              style="
                stroke-dasharray: ${animate ? '1000' : 'none'};
                stroke-dashoffset: ${animate ? '1000' : '0'};
                animation: ${animate ? 'drawLine 2s ease-out forwards' : 'none'};
              "
              filter="url(#line-shadow)"
            />
            
            ${showPoints ? points.map((point, index) => `
              <circle
                cx="${point.x}"
                cy="${point.y}"
                r="4"
                fill="${colors.primary}"
                stroke="var(--bg-primary)"
                stroke-width="2"
                class="line-point"
                data-value="${point.value}"
                data-index="${index}"
                style="
                  opacity: ${animate ? '0' : '1'};
                  animation: ${animate ? `fadeInPoint 0.3s ease-out ${0.5 + index * 0.1}s forwards` : 'none'};
                  cursor: pointer;
                "
              />
            `).join('') : ''}
          </svg>
          <div class="line-tooltip" id="line-tooltip-${containerId}"></div>
        </div>
      </div>
    `;

    this.setupLineChartInteractions(container, points, containerId, labels);
  }

  /**
   * Create grid lines for line chart
   */
  createGridLines(width, height) {
    const gridLines = [];
    const gridColor = 'var(--border-color)';
    
    // Horizontal grid lines
    for (let i = 1; i < 5; i++) {
      const y = (height - 80) * (i / 5) + 40;
      gridLines.push(`
        <line
          x1="30"
          y1="${y}"
          x2="${width - 30}"
          y2="${y}"
          stroke="${gridColor}"
          stroke-width="1"
          opacity="0.3"
        />
      `);
    }
    
    // Vertical grid lines
    for (let i = 1; i < 5; i++) {
      const x = (width - 60) * (i / 5) + 30;
      gridLines.push(`
        <line
          x1="${x}"
          y1="40"
          x2="${x}"
          y2="${height - 40}"
          stroke="${gridColor}"
          stroke-width="1"
          opacity="0.3"
        />
      `);
    }
    
    return gridLines.join('');
  }

  /**
   * Setup line chart interactions
   */
  setupLineChartInteractions(container, points, containerId, labels = []) {
    const tooltip = container.querySelector(`#line-tooltip-${containerId}`);
    const pointElements = container.querySelectorAll('.line-point');

    pointElements.forEach((point, index) => {
      point.addEventListener('mouseenter', (e) => {
        const value = e.target.getAttribute('data-value');
        
        // Highlight point
        e.target.style.r = '6';
        e.target.style.filter = 'brightness(1.2)';

        // Format label: use date label if available
        let labelText = `Point ${index + 1}`;
        if (labels[index]) {
          const d = new Date(labels[index] + 'T00:00:00');
          if (!isNaN(d.getTime())) {
            const dayNames = ['일', '월', '화', '수', '목', '금', '토'];
            labelText = `${d.getMonth() + 1}/${d.getDate()} (${dayNames[d.getDay()]})`;
          } else {
            labelText = labels[index];
          }
        }
        
        // Show tooltip
        tooltip.innerHTML = `
          <div class="tooltip-content">
            <div class="tooltip-value">${value}</div>
            <div class="tooltip-index">${labelText}</div>
          </div>
        `;
        tooltip.style.opacity = '1';
        tooltip.style.visibility = 'visible';
      });

      point.addEventListener('mouseleave', (e) => {
        // Reset point
        e.target.style.r = '4';
        e.target.style.filter = '';
        
        // Hide tooltip
        tooltip.style.opacity = '0';
        tooltip.style.visibility = 'hidden';
      });

      point.addEventListener('mousemove', (e) => {
        const rect = container.getBoundingClientRect();
        tooltip.style.left = (e.clientX - rect.left + 10) + 'px';
        tooltip.style.top = (e.clientY - rect.top - 10) + 'px';
      });
    });
  }

  /**
   * Create progress ring chart
   */
  createProgressRing(percentage, containerId, options = {}) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const colors = this.getColors();
    const {
      size = 120,
      strokeWidth = 8,
      title = 'Progress',
      animate = true
    } = options;

    const radius = (size - strokeWidth) / 2;
    const circumference = radius * 2 * Math.PI;
    const offset = circumference - (percentage / 100) * circumference;

    container.innerHTML = `
      <div class="chroma-progress-ring">
        <div class="progress-container">
          <svg width="${size}" height="${size}" class="progress-svg">
            <circle
              cx="${size / 2}"
              cy="${size / 2}"
              r="${radius}"
              stroke="var(--bg-tertiary)"
              stroke-width="${strokeWidth}"
              fill="transparent"
            />
            <circle
              cx="${size / 2}"
              cy="${size / 2}"
              r="${radius}"
              stroke="${colors.primary}"
              stroke-width="${strokeWidth}"
              fill="transparent"
              stroke-linecap="round"
              class="progress-circle"
              style="
                stroke-dasharray: ${circumference};
                stroke-dashoffset: ${animate ? circumference : offset};
                transform: rotate(-90deg);
                transform-origin: ${size / 2}px ${size / 2}px;
                transition: stroke-dashoffset 1s ease-out;
              "
            />
          </svg>
          <div class="progress-content">
            <div class="progress-percentage">${percentage}%</div>
            <div class="progress-title">${title}</div>
          </div>
        </div>
      </div>
    `;

    if (animate) {
      setTimeout(() => {
        const circle = container.querySelector('.progress-circle');
        circle.style.strokeDashoffset = offset;
      }, 100);
    }
  }
}

// Export for use in other components
window.ChromaCharts = ChromaCharts;