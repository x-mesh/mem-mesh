import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_node(script):
    subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_project_switch_discards_late_proposals_and_start_response():
    run_node("""
import assert from 'node:assert/strict';
globalThis.HTMLElement = class {};
globalThis.customElements = { define() {} };
const { CurationPage } = await import('./app/web/static/js/pages/curation.js');
const page = Object.create(CurationPage.prototype);
const selector = { value: 'old' };
const list = { innerHTML: '' };
const count = { textContent: '' };
page.querySelector = key => key === '.cur-reconciler-project' ? selector : key === '.cur-reconciler-list' ? list : count;
page._resolveReconcilerProposalStates = async (_, items) => items;
page._reconcilerRow = item => item.project_id;
let finish;
const wait = new Promise(resolve => finish = resolve);
globalThis.window = { app: { apiClient: { get: async () => { await wait; return { proposals: [{ project_id: 'old' }] }; } } } };
const pending = page.loadReconcilerProposals();
selector.value = 'new';
list.innerHTML = 'new project';
finish();
await pending;
assert.equal(list.innerHTML, 'new project');
selector.value = 'old';
let finishStart;
window.app.apiClient.post = () => new Promise(resolve => finishStart = resolve);
const button = {};
const form = { querySelector: key => key === '.cur-reconciler-project' ? selector : key === '.cur-reconciler-run-start' ? button : null };
page._setReconcilerRunMessage = () => {};
let rendered = false;
page._renderReconcilerRun = () => { rendered = true; };
page._startReconcilerPolling = () => {};
const start = page.startReconcilerRun(form);
selector.value = 'new';
finishStart({ id: 'old-run' });
await start;
assert.equal(rendered, false);
""")


def test_create_memory_protection_default_change_payload_and_reset():
    run_node("""
import assert from 'node:assert/strict';
globalThis.HTMLElement = class {};
globalThis.customElements = { define() {} };
globalThis.document = { createElement: () => ({}), head: { appendChild() {} } };
const { CreateMemoryPage } = await import('./app/web/static/js/pages/create-memory.js');
const page = new CreateMemoryPage();
assert.equal(page.formData.reconciler_protected, false);
let change;
const checkbox = { checked: false, addEventListener: (_, callback) => change = callback };
page.querySelector = key => key === '#reconciler_protected' ? checkbox : null;
page.markDirty = () => {};
page.setupEventListeners();
change({ target: { checked: true } });
assert.equal(page.formData.reconciler_protected, true);
page.validateForm = () => true;
page.setLoading = () => {};
let request;
globalThis.window = { app: { apiClient: { createMemory: async data => { request = data; return {}; } } } };
page.formData.content = 'Protected evidence';
await page.handleSubmit({ preventDefault() {} });
assert.equal(request.reconciler_protected, true);
page.populateForm = () => { checkbox.checked = page.formData.reconciler_protected; };
page.resetForm();
assert.equal(page.formData.reconciler_protected, false);
assert.equal(checkbox.checked, false);
""")


def test_curated_detail_loads_context_and_handles_missing_result():
    run_node("""
import assert from 'node:assert/strict';
globalThis.HTMLElement = class {};
globalThis.customElements = { define() {} };
globalThis.document = { createElement: () => ({}), head: { appendChild() {} } };
const { MemoryDetailPage } = await import('./app/web/static/js/pages/memory-detail.js');
const page = Object.create(MemoryDetailPage.prototype);
page.memoryId = 'cr_test';
page.render = () => {};
const memory = { id: page.memoryId, project_id: 'p', result_kind: 'curated', content: 'Summary' };
globalThis.window = { app: { apiClient: {
  getContext: async () => ({ primary_memory: memory, related_memories: [] }),
  get: async () => ({ sources: [], claims: [] })
} } };
await page.loadMemoryData();
assert.equal(page.memory, memory);
page.escapeHtml = value => String(value);
page.formatContent = value => value;
page.renderCurated();
assert.ok(page.innerHTML.includes('Source memories'));
assert.ok(page.innerHTML.includes('(0)'));
window.app.apiClient.get = async () => { throw { status: 404 }; };
await page.loadMemoryData();
assert.equal(page.memory, null);
assert.equal(page.isLoading, false);
let shownError = false;
window.app.errorHandler = { showError() { shownError = true; } };
window.app.apiClient.get = async () => ({ sources: {}, claims: [] });
await page.loadMemoryData();
assert.equal(page.memory, null);
assert.equal(shownError, true);
""")
