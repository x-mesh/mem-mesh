"""Regression tests for project-detail data scoping."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_DETAIL = ROOT / "app/web/static/js/pages/project-detail-v2.js"


def test_project_detail_search_is_scoped_on_the_server() -> None:
    source = PROJECT_DETAIL.read_text(encoding="utf-8")

    assert "project_id: this.projectId" in source
    assert "searchMemories('', { limit: 1000 })" not in source
