"""Regression tests for project-detail data scoping."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DETAIL = ROOT / "app/web/static/js/pages/project-detail-v2.js"
MEMORY_DETAIL = ROOT / "app/web/static/js/pages/memory-detail.js"
PROJECTS = ROOT / "app/web/static/js/pages/projects.js"
MAIN_JS = ROOT / "app/web/static/js/main.js"


def test_project_detail_search_is_scoped_on_the_server() -> None:
    source = PROJECT_DETAIL.read_text(encoding="utf-8")

    assert "project_id: this.projectId" in source
    assert "searchMemories('', { limit: 1000 })" not in source


def test_project_cache_is_invalidated_after_memory_changes() -> None:
    source = MAIN_JS.read_text(encoding="utf-8")

    assert "this.apiClient.invalidateCache('/memories')" in source
    assert "this.apiClient.invalidateCache('/projects')" in source


def test_memory_project_link_scopes_projects_page() -> None:
    memory_detail = MEMORY_DETAIL.read_text(encoding="utf-8")
    projects = PROJECTS.read_text(encoding="utf-8")

    assert 'href="/projects?project_id=${encodeURIComponent(this.memory.project_id)}"' in memory_detail
    assert "new URLSearchParams(window.location.search).get('project_id')" in projects
    assert "project.id === this.projectFilter" in projects
    assert 'class="project-filter-banner"' in projects
