"""Execute Reconciler card rendering without a browser or external packages."""

import subprocess
from pathlib import Path

import pytest


def test_reconciler_card_shows_uncited_inputs_and_escapes_explanation():
    source = Path(__file__).resolve().parents[1] / "app/web/static/js/pages/curation.js"
    script = """
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
globalThis.HTMLElement = class {};
globalThis.customElements = { define() {} };
const { CurationPage } = await import(pathToFileURL(process.argv[1]));
const page = Object.create(CurationPage.prototype);
const html = page._reconcilerRow({
  id: 'proposal', project_id: 'project', action: 'merge', status: 'preview',
  expected_revision: 0, representative_memory_id: 'm1', body: 'Derived body',
  input_sources_json: JSON.stringify([
    { memory_id: 'm1', input_hash: 'hash-one' },
    { memory_id: 'm2', input_hash: 'hash-two' },
  ]),
  claims_json: JSON.stringify([{ text: 'Claim', source_refs: [{ memory_id: 'm1', input_hash: 'hash-one' }] }]),
  proposal_json: JSON.stringify({
    preserved_conditions: ['Stable releases only'],
    removed_repetition: ['<img src=x onerror=alert(1)>'],
    uncertainties: ['Nightly status is unknown'],
  }),
});
assert.ok(html.includes('/memory/m2'));
assert.ok(html.includes('hash-two'));
assert.ok(html.includes('2 inputs (1 cited)'));
assert.ok(html.includes('Stable releases only'));
assert.ok(html.includes('Nightly status is unknown'));
assert.ok(html.includes('&lt;img'));
assert.ok(!html.includes('<img'));
assert.ok(!html.includes('cur-reconciler-approve'));
const active = page._reconcilerRow({ id: 'p', status: 'applied', action: 'merge',
  result_status: 'active', result_id: 'result', result_revision: 3 });
assert.ok(active.includes('cur-reconciler-result-deactivate'));
assert.ok(active.includes('data-revision="3"'));
const cancelled = page._reconcilerRow({ id: 'p', status: 'applied', action: 'merge',
  result_status: 'cancelled', result_id: 'result', result_revision: 4 });
assert.ok(!cancelled.includes('cur-reconciler-result-deactivate'));
const held = page._reconcilerRow({ id: 'p', status: 'needs_review',
  proposal_json: JSON.stringify({ review_reason: 'scope_mismatch' }) });
assert.ok(held.includes('Review reason: Project or scope mismatch'));
const unclassified = page._reconcilerRow({ id: 'p', status: 'needs_review' });
assert.ok(unclassified.includes('Review reason: Unclassified'));
const blocked = page._reconcilerRow({ id: 'p', status: 'needs_review', action: 'merge',
  error: 'activation budget exceeded <script>',
  proposal_json: JSON.stringify({ rationale: 'The evidence supports consolidation.' }) });
assert.ok(blocked.includes('The evidence supports consolidation.'));
assert.ok(blocked.includes('Processing issue:'));
assert.ok(blocked.includes('activation budget exceeded &lt;script&gt;'));
assert.ok(!blocked.includes('cur-reconciler-approve'));
"""
    subprocess.run(
        ["node", "--input-type=module", "-e", script, str(source)],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("curated_count", [0, 1])
def test_overview_generation_requires_active_derived_inputs(curated_count):
    source = Path(__file__).resolve().parents[1] / "app/web/static/js/pages/projects.js"
    script = """
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
class Element {
  constructor() { this.disabled = false; this.hidden = false; this.nodes = {}; }
  querySelector(selector) { return this.nodes[selector] ||= new Element(); }
  addEventListener() {}
  remove() {}
}
const overlays = [];
globalThis.HTMLElement = class {};
globalThis.customElements = { define() {} };
globalThis.document = { querySelector: () => null, createElement: () => new Element(),
  head: { appendChild() {} }, body: { appendChild: node => overlays.push(node) } };
const curated = Number(process.argv[2]);
globalThis.window = { app: { apiClient: { get: async () => ({ overview: null,
  coverage: { canonical_total: 10, covered_canonical: curated ? 2 : 0, curated_results: curated } }) } } };
const { ProjectsPage } = await import(pathToFileURL(process.argv[1]));
const page = Object.create(ProjectsPage.prototype);
await page.openOverviewModal('project');
const overlay = overlays[0];
assert.equal(overlay.querySelector('.overview-generate').disabled, curated === 0);
assert.equal(overlay.querySelector('.overview-generate').hidden, false);
assert.ok(overlay.querySelector('.overview-body').innerHTML.includes('overview-state-unavailable'));
if (curated === 0) {
  assert.ok(overlay.querySelector('.overview-body').innerHTML.includes('Open Memory Reconciler'));
}
"""
    subprocess.run(
        ["node", "--input-type=module", "-e", script, str(source), str(curated_count)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_reconciler_policy_roundtrip_preserves_processing_flags():
    source = Path(__file__).resolve().parents[1] / "app/web/static/js/pages/curation.js"
    script = """
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
globalThis.HTMLElement = class {};
globalThis.customElements = { define() {} };
const { CurationPage } = await import(pathToFileURL(process.argv[1]));
const page = Object.create(CurationPage.prototype);
const fields = {
  '.cur-reconciler-project': { value: 'project' },
  '.cur-reconciler-retain-evidence': {},
  '.cur-reconciler-policy-save': {},
  '.cur-reconciler-alerts': {},
};
page.querySelector = selector => fields[selector];
page._setReconcilerRunMessage = () => {};
let submitted;
globalThis.window = { app: { apiClient: {
  get: async () => ({ auto_noise_suppression: true, auto_derived_relations: true,
    retain_evidence_content: false }),
  put: async (path, body) => { submitted = body; return body; },
} } };
await page.loadReconcilerPolicy();
assert.equal(fields['.cur-reconciler-retain-evidence'].checked, false);
assert.equal(fields['.cur-reconciler-retain-evidence'].disabled, false);
fields['.cur-reconciler-retain-evidence'].checked = true;
await page.saveReconcilerPolicy();
assert.deepEqual(submitted, { auto_noise_suppression: true,
  auto_derived_relations: true, retain_evidence_content: true });
assert.equal(fields['.cur-reconciler-policy-save'].disabled, false);
let refreshed = 0;
let request;
page.loadReconcilerProposals = async () => { refreshed++; };
window.app.apiClient.post = async (path, body) => { request = { path, body }; };
const button = { dataset: { result: 'result/id', revision: '3' }, disabled: false };
await page.deactivateReconcilerResult(button);
assert.deepEqual(request, { path: '/curation/reconciler/results/result%2Fid/cancel',
  body: { expected_revision: 3 } });
assert.equal(refreshed, 1);
window.app.apiClient.get = async () => ({ alerts: [
  { kind: 'replay_non_idempotency', count: 2 },
  { kind: 'stale_anchor', count: 1 },
] });
await page.loadReconcilerAlerts();
assert.equal(fields['.cur-reconciler-alerts'].hidden, false);
assert.equal(fields['.cur-reconciler-alerts'].textContent,
  '2 input groups with duplicate results or activations · 1 open stale anchor episodes');
window.app.apiClient.get = async () => ({ alerts: [
  { kind: 'judge_failure_increase', count: 2 },
], run_trends: { previous: { judge_failure_rate: 0.1 }, recent: { judge_failure_rate: 0.2 } } });
await page.loadReconcilerAlerts();
assert.equal(fields['.cur-reconciler-alerts'].textContent, 'Judge failure rate: 10.0% → 20.0%');
window.app.apiClient.get = async () => ({ alerts: [], run_trends: { ready: false } });
await page.loadReconcilerAlerts();
assert.equal(fields['.cur-reconciler-alerts'].hidden, false);
assert.ok(fields['.cur-reconciler-alerts'].textContent.includes('Trend rates unavailable'));
window.app.apiClient.post = async () => { throw new Error('Revision conflict'); };
page._errText = error => error.message;
await page.deactivateReconcilerResult(button);
assert.equal(button.disabled, false);
assert.equal(refreshed, 1);
"""
    subprocess.run(
        ["node", "--input-type=module", "-e", script, str(source)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_project_combobox_preserves_selection_and_rejects_uncommitted_search():
    source = Path(__file__).resolve().parents[1] / "app/web/static/js/pages/curation.js"
    script = """
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
globalThis.HTMLElement = class {};
globalThis.customElements = { define() {} };
const { CurationPage } = await import(pathToFileURL(process.argv[1]));
const page = Object.create(CurationPage.prototype);
const input = { value: '', setAttribute() {} };
const toggle = {};
const picker = { options: [], searchQuery: '', close() {},
  querySelector: () => input, querySelectorAll: () => [input, toggle],
  setOptions(options) { this.options = options; },
  setValue(value) { this.selectedText = this.options.find(option => option.value === value)?.text || ''; input.value = this.selectedText; },
};
const select = { value: 'landing-maker', set innerHTML(html) {
  this.html = html;
  this.value = /value="([^"]+)" selected/.exec(html)?.[1] || '';
} };
page.querySelector = selector => selector === '.cur-reconciler-project' ? select : picker;
let latest = 0;
page.loadLatestReconcilerRun = async () => { latest++; };
page.loadReconcilerPolicy = async () => {};
page.loadReconcilerProposals = async () => {};
let message;
page._setReconcilerRunMessage = value => { message = value; };
page._errText = error => error.message;
globalThis.window = { app: { apiClient: { get: async () => ({ projects: [
  { id: 'landing-maker', name: 'Landing Maker', memory_count: 7 },
  { id: 'other', memory_count: 2 },
] }) } } };
await page.loadReconcilerProjects();
assert.equal(select.value, 'landing-maker');
assert.equal(input.value, 'Landing Maker · 7 memories');
assert.equal(input.disabled, false);
assert.equal(picker.options.length, 3);
page._onReconcilerProjectChange({ target: input });
assert.equal(latest, 1);
page._onReconcilerProjectChange({ target: picker, detail: { value: 'other' } });
assert.equal(select.value, 'other');
assert.equal(latest, 2);
input.value = 'unselected search';
const form = { querySelector: selector => selector === '.cur-reconciler-project' ? select : picker };
await page.startReconcilerRun(form);
assert.equal(message, 'Select a project from the search results first.');
window.app.apiClient.get = async () => ({ projects: [] });
await page.loadReconcilerProjects();
assert.equal(input.disabled, true);
assert.equal(input.placeholder, 'No projects found');
window.app.apiClient.get = async () => { throw new Error('network failed'); };
await page.loadReconcilerProjects();
assert.equal(input.disabled, true);
assert.equal(input.placeholder, 'Failed to load projects');
assert.equal(message, 'network failed');
"""
    subprocess.run(
        ["node", "--input-type=module", "-e", script, str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
