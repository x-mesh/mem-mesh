from unittest.mock import AsyncMock

import pytest

from app.mcp_common.batch_tools import BatchOperationHandler


@pytest.mark.asyncio
async def test_batch_search_preserves_each_operations_scope():
    handler = object.__new__(BatchOperationHandler)

    async def search(**kwargs):
        return {
            "status": "success",
            "results": {
                query: {"results": {"results": [kwargs], "total": 1}}
                for query in kwargs["queries"]
            },
        }

    handler.batch_search = AsyncMock(side_effect=search)
    operations = [
        {"type": "search", "query": "same", "project_id": "a"},
        {"type": "search", "query": "same", "project_id": "b"},
        {"type": "search", "query": "same", "project_id": "a", "read_view": "raw"},
        {"type": "search", "query": "other", "project_id": "a"},
    ]
    response = await handler.batch_operations(operations)
    results = response["results"]
    assert [item["results"][0]["project_id"] for item in results] == [
        "a",
        "b",
        "a",
        "a",
    ]
    assert [item["results"][0]["read_view"] for item in results] == [
        "effective",
        "effective",
        "raw",
        "effective",
    ]
    assert handler.batch_search.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("category", "decision"),
        ("limit", 1),
        ("anchored_path", "/project/src"),
        ("starred_only", True),
    ],
)
async def test_batch_search_separates_all_filters(field, value):
    handler = object.__new__(BatchOperationHandler)
    handler.batch_search = AsyncMock(return_value={"status": "success", "results": {}})
    await handler.batch_operations(
        [
            {"type": "search", "query": "same"},
            {"type": "search", "query": "same", field: value},
        ]
    )
    assert handler.batch_search.await_count == 2
    assert handler.batch_search.await_args_list[1].kwargs[field] == value
