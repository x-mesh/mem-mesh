"""Regression tests for project-detail data scoping."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DETAIL = ROOT / "app/web/static/js/pages/project-detail-v2.js"
MAIN_JS = ROOT / "app/web/static/js/main.js"


def test_project_detail_search_is_scoped_on_the_server() -> None:
    source = PROJECT_DETAIL.read_text(encoding="utf-8")

    assert "project_id: this.projectId" in source
    assert "searchMemories('', { limit: 1000 })" not in source


def test_project_cache_is_invalidated_after_memory_changes() -> None:
    source = MAIN_JS.read_text(encoding="utf-8")

    assert "this.apiClient.invalidateCache('/memories')" in source
    assert "this.apiClient.invalidateCache('/projects')" in source
