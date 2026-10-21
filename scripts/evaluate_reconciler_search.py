"""Compare raw and effective search results for fixed project queries."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.schemas.responses import ContextResponse, SearchResponse


class QueryCase(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    expected_source_ids: list[str] = Field(default_factory=list)
    expected_source_groups: list[list[str]] = Field(default_factory=list)


class QuerySuite(BaseModel):
    project_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=100)
    cases: list[QueryCase] = Field(min_length=1, max_length=100)


def _measure(
    results: SearchResponse, expected: set[str], groups: list[set[str]]
) -> dict[str, Any]:
    source_ids: set[str] = set()
    result_sources: list[set[str]] = []
    curated_count = 0
    estimated_tokens = 0
    for item in results.results:
        estimated_tokens += max(1, len(item.content) // 4)
        if item.result_kind == "curated":
            curated_count += 1
            item_sources = {
                str(source["memory_id"])
                for source in item.citations
                if source.get("memory_id")
            }
        else:
            item_sources = {item.id}
        result_sources.append(item_sources)
        source_ids.update(item_sources)
    duplicate_count = sum(
        max(0, sum(bool(group & sources) for sources in result_sources) - 1)
        for group in groups
    )
    cross_group_count = sum(
        sum(bool(group & sources) for group in groups) > 1 for sources in result_sources
    )
    return {
        "result_count": len(results.results),
        "curated_count": curated_count,
        "estimated_text_tokens": estimated_tokens,
        "expected_source_coverage": (
            len(expected & source_ids) / len(expected) if expected else None
        ),
        "duplicate_result_count": duplicate_count if groups else None,
        "duplicate_result_rate": (
            duplicate_count / len(results.results)
            if groups and results.results
            else None
        ),
        "cross_group_result_count": cross_group_count if len(groups) > 1 else None,
    }


async def evaluate_suite(
    client: httpx.AsyncClient, suite: QuerySuite, limit: int = 5
) -> dict[str, Any]:
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    cases = []
    for case in suite.cases:
        result: dict[str, Any] = {"query": case.query}
        groups = [set(group) for group in case.expected_source_groups if group]
        expected = set(case.expected_source_ids).union(*groups)
        for view in ("raw", "effective"):
            response = await client.get(
                "/api/memories/search",
                params={
                    "query": case.query,
                    "project_id": suite.project_id,
                    "search_mode": "semantic",
                    "read_view": view,
                    "limit": limit,
                },
            )
            response.raise_for_status()
            search = SearchResponse.model_validate(response.json())
            result[view] = _measure(search, expected, groups)
            result[view]["estimated_context_tokens"] = None
            if search.results:
                primary_id = search.results[0].id
                context_response = await client.get(
                    f"/api/memories/{primary_id}/context",
                    params={
                        "project_id": suite.project_id,
                        "read_view": view,
                        "depth": 1,
                    },
                )
                context_response.raise_for_status()
                context = ContextResponse.model_validate(context_response.json())
                contents = [context.primary_memory.content] + [
                    item.content for item in context.related_memories
                ]
                result[view]["estimated_context_tokens"] = sum(
                    max(1, len(content) // 4) for content in contents
                )
        cases.append(result)
    labeled = [
        case
        for case in cases
        if case["raw"]["expected_source_coverage"] is not None
        and case["effective"]["expected_source_coverage"] is not None
    ]
    grouped = [
        case for case in cases if case["raw"]["duplicate_result_count"] is not None
    ]
    context_cases = [
        case
        for case in cases
        if case["raw"]["estimated_context_tokens"] is not None
        and case["effective"]["estimated_context_tokens"] is not None
    ]
    raw_text_tokens = sum(case["raw"]["estimated_text_tokens"] for case in cases)
    effective_text_tokens = sum(
        case["effective"]["estimated_text_tokens"] for case in cases
    )
    raw_context_tokens = sum(
        case["raw"]["estimated_context_tokens"] for case in context_cases
    )
    effective_context_tokens = sum(
        case["effective"]["estimated_context_tokens"] for case in context_cases
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            suite.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    return {
        "project_id": suite.project_id,
        "limit": limit,
        "suite_sha256": fingerprint,
        "cases": cases,
        "summary": {
            "query_count": len(cases),
            "labeled_query_count": len(labeled),
            "coverage_regression_count": sum(
                case["effective"]["expected_source_coverage"]
                < case["raw"]["expected_source_coverage"]
                for case in labeled
            ),
            "mean_expected_source_coverage": {
                view: (
                    sum(case[view]["expected_source_coverage"] for case in labeled)
                    / len(labeled)
                    if labeled
                    else None
                )
                for view in ("raw", "effective")
            },
            "duplicate_group_query_count": len(grouped),
            "duplicate_result_count": {
                view: sum(case[view]["duplicate_result_count"] for case in grouped)
                for view in ("raw", "effective")
            },
            "estimated_text_tokens_saved": raw_text_tokens - effective_text_tokens,
            "estimated_text_token_savings_rate": (
                (raw_text_tokens - effective_text_tokens) / raw_text_tokens
                if raw_text_tokens
                else None
            ),
            "context_query_count": len(context_cases),
            "estimated_context_tokens_saved": raw_context_tokens
            - effective_context_tokens,
            "estimated_context_token_savings_rate": (
                (raw_context_tokens - effective_context_tokens) / raw_context_tokens
                if raw_context_tokens
                else None
            ),
        },
    }


async def _main(base_url: str, suite: QuerySuite, limit: int) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        return await evaluate_suite(client, suite, limit)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--cases", required=True, help="JSON file or - for stdin")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    content = sys.stdin.read() if args.cases == "-" else Path(args.cases).read_text()
    suite = QuerySuite.model_validate_json(content)
    print(
        json.dumps(
            asyncio.run(_main(args.base_url, suite, args.limit)), ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
