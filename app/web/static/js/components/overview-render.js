/**
 * Shared renderer for a project Overview payload — used by both the Projects
 * page modal and the memory-detail sidebar so they look identical.
 *
 * Input is the `/projects/{id}/overview` response: { overview, stale,
 * generated_at, ... } where overview = { summary, themes, recent_activity,
 * open_issues, key_decisions, source_memory_ids }.
 */

function _esc(s) {
  return (s == null ? '' : String(s))
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _memLink(id, text) {
  const href = `/memory/${encodeURIComponent(id)}`;
  return `<a class="ov-src" href="${href}" data-route="${href}" title="${_esc(id)}">${_esc(text)}</a>`;
}

// A memory id as the model leaves it inline in prose — a plain UUID. Module
// level is safe even with /g/: String#replace and #match both reset lastIndex
// on entry, so these are never carried between calls.
const _UUID_SRC = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const _UUID_RE = new RegExp(_UUID_SRC, 'gi');
// The model habitually trails a claim with a bracketed source list:
// "... 조사가 기록되었다. [uuid, uuid, uuid]" — that whole block collapses at
// once so the brackets and commas go away with the ids. A stray id loose in the
// prose is the second alternative. Both live in ONE pattern (bracket form
// first, so it wins) because a second replace pass would re-match the ids
// inside the hrefs the first pass just wrote.
const _CITE_RE = new RegExp(
  `\\[\\s*${_UUID_SRC}(?:\\s*,\\s*${_UUID_SRC})*\\s*\\]|${_UUID_SRC}`,
  'gi'
);

/**
 * Numbers cited memories in first-appearance order. One counter per rendered
 * overview, so the same memory keeps the same marker across every section.
 */
function _citations() {
  const seen = new Map();
  return (id) => {
    const key = String(id).toLowerCase();
    if (!seen.has(key)) seen.set(key, seen.size + 1);
    return seen.get(key);
  };
}

function _citeLink(id, numberOf) {
  const href = `/memory/${encodeURIComponent(id)}`;
  return `<a class="ov-cite" href="${href}" data-route="${href}" title="${_esc(id)}">${numberOf(id)}</a>`;
}

/**
 * Turn raw memory ids inside already-escaped text into compact footnote links.
 *
 * Display layer only — the stored overview keeps its ids verbatim, so a
 * regenerate/export still carries the full provenance. Escaping must come
 * first (this splices in HTML); uuids survive it untouched.
 */
function _linkifyCitations(escaped, numberOf) {
  if (!escaped) return '';
  return escaped.replace(_CITE_RE, (match) => {
    const ids = match.match(_UUID_RE) || [];
    return `<sup class="ov-cites">${ids.map((id) => _citeLink(id, numberOf)).join('')}</sup>`;
  });
}

function _list(items, cls) {
  return `<ul class="ov-list ${cls}">${items.map((x) => `<li>${x}</li>`).join('')}</ul>`;
}

window.ProjectOverviewRender = {
  html(res, opts = {}) {
    const ov = res && res.overview;
    if (!ov) {
      return '<div class="overview-empty">No overview yet.</div>';
    }
    const parts = [];
    const cite = _citations();

    if (res.stale) {
      parts.push('<div class="ov-stale">⚠ Memories changed since this was generated — refresh for the latest.</div>');
    }
    if (ov.summary) {
      parts.push(`<p class="ov-summary">${_linkifyCitations(_esc(ov.summary), cite)}</p>`);
    }
    const themes = Array.isArray(ov.themes) ? ov.themes.filter(Boolean) : [];
    if (themes.length) {
      parts.push(`<div class="ov-themes">${themes.map((t) => `<span class="ov-theme">${_esc(t)}</span>`).join('')}</div>`);
    }

    const issues = Array.isArray(ov.open_issues) ? ov.open_issues.filter(Boolean) : [];
    if (issues.length) {
      const rows = issues.map((i) => {
        const text = _linkifyCitations(_esc(i.text || i), cite);
        return i.memory_id ? `${_memLink(i.memory_id, '↗')} ${text}` : text;
      });
      parts.push(`<div class="ov-section ov-issues"><div class="ov-h">⚠ Open issues (${issues.length})</div>${_list(rows, 'ov-issue-list')}</div>`);
    }

    const decisions = Array.isArray(ov.key_decisions) ? ov.key_decisions.filter(Boolean) : [];
    if (decisions.length) {
      const rows = decisions.map((d) => {
        const text = _linkifyCitations(_esc(d.text || d), cite);
        return d.memory_id ? `${_memLink(d.memory_id, '↗')} ${text}` : text;
      });
      parts.push(`<div class="ov-section ov-decisions"><div class="ov-h">🔑 Decisions</div>${_list(rows, '')}</div>`);
    }

    const activity = Array.isArray(ov.recent_activity) ? ov.recent_activity.filter(Boolean) : [];
    if (activity.length) {
      const rows = activity.map((a) => _linkifyCitations(_esc(a), cite));
      parts.push(`<div class="ov-section ov-activity"><div class="ov-h">🕒 Recent activity</div>${_list(rows, '')}</div>`);
    }

    if (opts.showGeneratedAt && res.generated_at) {
      const n = res.item_count != null ? `${res.item_count} memories · ` : '';
      parts.push(`<div class="ov-foot">${n}generated ${_esc(res.generated_at.slice(0, 16).replace('T', ' '))}</div>`);
    }
    return parts.join('') || '<div class="overview-empty">Empty overview.</div>';
  },
};
