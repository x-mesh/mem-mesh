"""Read-only raw/effective search comparison tests."""

import httpx
import pytest
from pydantic import ValidationError

from scripts.evaluate_reconciler_search import QuerySuite, evaluate_suite


@pytest.mark.asyncio
async def test_quality_report_tracks_source_coverage_without_claiming_recall():
    requests = []

    def respond(request):
        requests.append(request)
        view = request.url.params["read_view"]
        item = {
            "id": "m1" if view == "raw" else "cr_1",
            "content": "A landing page theme with shared components.",
            "similarity_score": 0.9,
            "created_at": "2026-10-19T00:00:00+00:00",
            "project_id": "landing-maker",
            "category": "task",
            "source": "test",
            "result_kind": "canonical" if view == "raw" else "curated",
            "citations": (
                [] if view == "raw" else [{"memory_id": "m1"}, {"memory_id": "m2"}]
            ),
        }
        if request.url.path.endswith("/context"):
            return httpx.Response(
                200,
                json={
                    "primary_memory": item,
                    "related_memories": [],
                    "timeline": [item["id"]],
                },
            )
        return httpx.Response(200, json={"results": [item]})

    suite = QuerySuite(
        project_id="landing-maker",
        cases=[{"query": "landing theme", "expected_source_ids": ["m1", "m2"]}],
    )
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        report = await evaluate_suite(client, suite)

    case = report["cases"][0]
    assert case["raw"]["expected_source_coverage"] == 0.5
    assert case["effective"]["expected_source_coverage"] == 1.0
    assert case["effective"]["curated_count"] == 1
    assert case["raw"]["estimated_context_tokens"] is not None
    assert report["summary"]["labeled_query_count"] == 1
    assert report["summary"]["coverage_regression_count"] == 0
    assert report["summary"]["mean_expected_source_coverage"] == {
        "raw": 0.5,
        "effective": 1.0,
    }
    assert len(report["suite_sha256"]) == 64
    assert [request.url.params["read_view"] for request in requests] == [
        "raw",
        "raw",
        "effective",
        "effective",
    ]


@pytest.mark.asyncio
async def test_quality_report_counts_duplicate_slots_by_expected_group():
    def item(memory_id, *, curated=False):
        return {
            "id": memory_id,
            "content": "The same release fact.",
            "similarity_score": 0.9,
            "created_at": "2026-10-19T00:00:00+00:00",
            "project_id": "landing-maker",
            "category": "task",
            "source": "test",
            "result_kind": "curated" if curated else "canonical",
            "citations": (
                [{"memory_id": "m1"}, {"memory_id": "m2"}] if curated else []
            ),
        }

    def respond(request):
        view = request.url.params["read_view"]
        results = (
            [item("m1"), item("m2")] if view == "raw" else [item("cr_1", curated=True)]
        )
        if request.url.path.endswith("/context"):
            return httpx.Response(
                200,
                json={
                    "primary_memory": results[0],
                    "related_memories": [],
                    "timeline": [results[0]["id"]],
                },
            )
        return httpx.Response(200, json={"results": results})

    suite = QuerySuite(
        project_id="landing-maker",
        cases=[
            {
                "query": "release fact",
                "expected_source_groups": [["m1", "m2"]],
            }
        ],
    )
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        case = (await evaluate_suite(client, suite))["cases"][0]

    assert case["raw"]["duplicate_result_count"] == 1
    assert case["raw"]["duplicate_result_rate"] == 0.5
    assert case["effective"]["duplicate_result_count"] == 0
    assert case["effective"]["expected_source_coverage"] == 1.0


@pytest.mark.asyncio
async def test_quality_summary_exposes_coverage_and_token_regressions():
    def item(memory_id, content):
        return {
            "id": memory_id,
            "content": content,
            "similarity_score": 0.9,
            "created_at": "2026-10-19T00:00:00+00:00",
            "project_id": "landing-maker",
            "category": "task",
            "source": "test",
        }

    def respond(request):
        results = (
            [item("m1", "Short fact."), item("m2", "Other fact.")]
            if request.url.params["read_view"] == "raw"
            else [item("m1", "A much longer summary of only the first fact.")]
        )
        if request.url.path.endswith("/context"):
            return httpx.Response(
                200,
                json={
                    "primary_memory": results[0],
                    "related_memories": [],
                    "timeline": [results[0]["id"]],
                },
            )
        return httpx.Response(200, json={"results": results})

    suite = QuerySuite(
        project_id="landing-maker",
        cases=[{"query": "fact", "expected_source_ids": ["m1", "m2"]}],
    )
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        summary = (await evaluate_suite(client, suite))["summary"]

    assert summary["coverage_regression_count"] == 1
    assert summary["mean_expected_source_coverage"] == {
        "raw": 1.0,
        "effective": 0.5,
    }
    assert summary["estimated_text_tokens_saved"] < 0
    assert summary["estimated_context_tokens_saved"] < 0


def test_quality_suite_rejects_invalid_scope():
    with pytest.raises(ValidationError):
        QuerySuite(project_id="../other", cases=[{"query": "x"}])
