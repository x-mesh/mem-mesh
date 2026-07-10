"""MCP search response compression now leverages enrichment (abstract + topic
tags) so compact scans are denser and raw content is a drill-down (context/get)."""

from app.core.schemas.responses import SearchResponse, SearchResult
from app.mcp_common.tools import MCPToolHandlers


def _sr(**kw) -> SearchResult:
    base = dict(
        id="mem-0001",
        content="X" * 200,
        similarity_score=0.9,
        created_at="2026-01-01T00:00:00Z",
        project_id="p",
        category="decision",
        source="test",
    )
    base.update(kw)
    return SearchResult(**base)


def _tools() -> MCPToolHandlers:
    return MCPToolHandlers(storage=None, enable_compression=True)


def test_compact_uses_abstract_title_and_tags():
    result = SearchResponse(results=[_sr(id="mem-0001")], total=1)
    emap = {
        "mem-0001": {
            "title": "Auth fix",
            "abstract": "Short dense abstract.",
            "tags": ["auth", "jwt"],
            "display_kind": "decision",
        }
    }
    out = _tools()._compress_search_response(result, "compact", emap)
    item = out["results"][0]
    assert item["summary"] == "Short dense abstract."  # abstract, not content[:80]
    assert item["title"] == "Auth fix"
    assert item["tags"] == ["auth", "jwt"]  # enrichment topic tags
    assert "content" not in item  # raw dropped in compact (progressive disclosure)


def test_compact_falls_back_to_content_without_enrichment():
    result = SearchResponse(results=[_sr(id="mem-0002", content="C" * 200)], total=1)
    out = _tools()._compress_search_response(result, "compact", {})
    item = out["results"][0]
    assert item["summary"].endswith("...")  # content[:80] fallback preserved
    assert "title" not in item


def test_standard_is_abstract_first_for_enriched():
    """Enriched → title+abstract+tags, raw content dropped (context()/get() drill-down)."""
    result = SearchResponse(results=[_sr(id="mem-0003", content="Z" * 500)], total=1)
    emap = {"mem-0003": {"title": "T", "abstract": "A", "tags": ["t"]}}
    out = _tools()._compress_search_response(result, "standard", emap)
    item = out["results"][0]
    assert item["id"] == "mem-0003"  # full id preserved for drill-down
    assert item["title"] == "T" and item["abstract"] == "A"
    assert item["tags"] == ["t"]  # enrichment topic tags
    assert "content" not in item  # raw dropped once a summary exists


def test_standard_keeps_full_content_when_unenriched():
    """No enrichment → full content stays (no regression until coverage lands)."""
    result = SearchResponse(results=[_sr(id="mem-0004", content="C" * 500)], total=1)
    out = _tools()._compress_search_response(result, "standard", {})
    item = out["results"][0]
    assert item["content"] == "C" * 500  # untouched
    assert "abstract" not in item
