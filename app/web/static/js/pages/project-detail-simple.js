/**
 * Simple Project Detail Page for testing
 */

class ProjectDetailPage extends HTMLElement {
  constructor() {
    super();
    console.log('ProjectDetailPage constructor called');
  }
  
  connectedCallback() {
    console.log('ProjectDetailPage connected');
    this.render();
  }
  
  render() {
    this.innerHTML = `
      <div style="padding: 2rem;">
        <h1>Project Detail Page</h1>
        <p>This is a test page to verify routing works.</p>
        <button onclick="history.back()">Go Back</button>
      </div>
    `;
  }
}

// Define the custom element
customElements.define('project-detail-page', ProjectDetailPage);

export { ProjectDetailPage };