"""MCP search response compression now leverages enrichment (abstract + topic
tags) so compact scans are denser and raw content is a drill-down (context/get)."""

import pytest

from app.core.schemas.responses import (
    ContextResponse,
    RelatedMemory,
    SearchResponse,
    SearchResult,
)
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


@pytest.mark.parametrize("format", ["minimal", "compact", "standard"])
def test_curated_search_compression_preserves_lookup_id_and_evidence(format):
    memory = _sr(
        id="cr_" + "a" * 32,
        result_kind="curated",
        representative_memory_id="original-1",
        citations=[{"memory_id": "original-1", "input_hash": "h1"}],
    )
    out = _tools()._compress_search_response(
        SearchResponse(results=[memory], total=1), format, {}
    )
    item = out["results"][0]
    assert item["id"] == memory.id
    assert item["result_kind"] == "curated"
    assert item["project_id"] == "p"
    assert item["representative_memory_id"] == "original-1"
    assert item["citations"] == memory.citations


def test_compact_context_preserves_curated_primary_and_related_evidence():
    primary = _sr(
        id="cr_" + "a" * 32,
        result_kind="curated",
        citations=[{"memory_id": "original-1", "input_hash": "h1"}],
    )
    related = RelatedMemory(
        id="cr_" + "b" * 32,
        content="Related fact",
        similarity_score=0.8,
        relationship="similar",
        created_at=primary.created_at,
        project_id="p",
        result_kind="curated",
        citations=[{"memory_id": "original-2", "input_hash": "h2"}],
    )
    out = _tools()._compress_context_response(
        ContextResponse(
            primary_memory=primary,
            related_memories=[related],
            timeline=[primary.id, related.id],
        )
    )
    assert out["primary"]["id"] == primary.id
    assert out["primary"]["summary"]
    assert out["primary"]["citations"] == primary.citations
    assert out["primary"]["result_kind"] == "curated"
    assert out["related"][0]["id"] == related.id
    assert out["related"][0]["citations"][0]["memory_id"] == "original-2"


def test_compact_context_populates_canonical_primary():
    primary = _sr(id="canonical-memory-id")
    out = _tools()._compress_context_response(
        ContextResponse(
            primary_memory=primary, related_memories=[], timeline=[primary.id]
        )
    )
    assert out["primary"]["id"] == "canonica"
    assert out["primary"]["category"] == "decision"
    assert out["primary"]["summary"]


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
