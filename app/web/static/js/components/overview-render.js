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

    if (res.stale) {
      parts.push('<div class="ov-stale">⚠ Memories changed since this was generated — refresh for the latest.</div>');
    }
    if (ov.summary) {
      parts.push(`<p class="ov-summary">${_esc(ov.summary)}</p>`);
    }
    const themes = Array.isArray(ov.themes) ? ov.themes.filter(Boolean) : [];
    if (themes.length) {
      parts.push(`<div class="ov-themes">${themes.map((t) => `<span class="ov-theme">${_esc(t)}</span>`).join('')}</div>`);
    }

    const issues = Array.isArray(ov.open_issues) ? ov.open_issues.filter(Boolean) : [];
    if (issues.length) {
      const rows = issues.map((i) => {
        const text = _esc(i.text || i);
        return i.memory_id ? `${_memLink(i.memory_id, '↗')} ${text}` : text;
      });
      parts.push(`<div class="ov-section ov-issues"><div class="ov-h">⚠ Open issues (${issues.length})</div>${_list(rows, 'ov-issue-list')}</div>`);
    }

    const decisions = Array.isArray(ov.key_decisions) ? ov.key_decisions.filter(Boolean) : [];
    if (decisions.length) {
      const rows = decisions.map((d) => {
        const text = _esc(d.text || d);
        return d.memory_id ? `${_memLink(d.memory_id, '↗')} ${text}` : text;
      });
      parts.push(`<div class="ov-section ov-decisions"><div class="ov-h">🔑 Decisions</div>${_list(rows, '')}</div>`);
    }

    const activity = Array.isArray(ov.recent_activity) ? ov.recent_activity.filter(Boolean) : [];
    if (activity.length) {
      parts.push(`<div class="ov-section ov-activity"><div class="ov-h">🕒 Recent activity</div>${_list(activity.map(_esc), '')}</div>`);
    }

    if (opts.showGeneratedAt && res.generated_at) {
      const n = res.item_count != null ? `${res.item_count} memories · ` : '';
      parts.push(`<div class="ov-foot">${n}generated ${_esc(res.generated_at.slice(0, 16).replace('T', ' '))}</div>`);
    }
    return parts.join('') || '<div class="overview-empty">Empty overview.</div>';
  },
};
