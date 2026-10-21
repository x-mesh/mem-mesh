"""Read-view protocol forwarding tests."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.core.schemas.requests import ContextParams, SearchParams
from app.core.services.memory_reconciler import MemoryReconcilerService
from app.core.storage.api import APIStorageBackend
from app.core.storage.direct import DirectStorageBackend
from app.mcp_common.batch_tools import BatchOperationHandler
from app.mcp_common.dispatcher import MCPDispatcher
from app.mcp_common.schemas import get_all_tool_schemas, get_tool_schemas
from app.mcp_common.tools import MCPToolHandlers


def test_read_view_is_in_search_and_context_schemas():
    schemas = {item["name"]: item for item in get_tool_schemas()}
    assert schemas["search"]["inputSchema"]["properties"]["read_view"]["enum"] == [
        "effective",
        "raw",
    ]
    assert (
        schemas["context"]["inputSchema"]["properties"]["read_view"]["default"]
        == "effective"
    )
    assert SearchParams(query="q", read_view="raw").read_view == "raw"
    assert ContextParams(memory_id="m", read_view="raw").read_view == "raw"


@pytest.mark.asyncio
async def test_dispatcher_forwards_raw_read_view():
    handlers = MagicMock()
    handlers.search = AsyncMock(return_value={"results": []})
    handlers.context = AsyncMock(return_value={"primary_memory": {}})
    dispatcher = MCPDispatcher(handlers)

    await dispatcher.dispatch("search", {"query": "q", "read_view": "raw"})
    await dispatcher.dispatch("context", {"memory_id": "m", "read_view": "raw"})

    assert handlers.search.await_args.kwargs["read_view"] == "raw"
    assert handlers.context.await_args.kwargs["read_view"] == "raw"


def test_reconciler_read_tools_have_project_scoped_schemas():
    schemas = {item["name"]: item for item in get_all_tool_schemas()}

    assert schemas["reconciler_run"]["inputSchema"]["required"] == [
        "project_id",
        "run_id",
    ]
    assert schemas["reconciler_proposals"]["inputSchema"]["required"] == ["project_id"]
    assert schemas["reconciler_candidates"]["inputSchema"]["required"] == [
        "project_id",
        "run_id",
    ]
    assert schemas["reconciler_candidate"]["inputSchema"]["required"] == [
        "project_id",
        "candidate_id",
    ]
    assert schemas["reconciler_result"]["inputSchema"]["required"] == [
        "project_id",
        "result_id",
    ]
    assert schemas["reconciler_start"]["inputSchema"]["required"] == ["project_id"]
    assert (
        schemas["reconciler_start"]["inputSchema"]["properties"]["dry_run"]["default"]
        is True
    )
    assert schemas["reconciler_cancel"]["inputSchema"]["required"] == [
        "project_id",
        "run_id",
    ]


@pytest.mark.asyncio
async def test_dispatcher_routes_reconciler_read_tools():
    handlers = MagicMock()
    handlers.reconciler_run = AsyncMock(return_value={"id": "rr_123"})
    handlers.reconciler_proposals = AsyncMock(return_value={"proposals": []})
    handlers.reconciler_candidates = AsyncMock(return_value={"candidates": []})
    handlers.reconciler_candidate = AsyncMock(return_value={"id": "rc_123"})
    handlers.reconciler_result = AsyncMock(return_value={"id": "cr_123"})
    handlers.reconciler_start = AsyncMock(return_value={"id": "rr_456"})
    handlers.reconciler_cancel = AsyncMock(return_value={"status": "cancelled"})
    dispatcher = MCPDispatcher(handlers)

    await dispatcher.dispatch(
        "reconciler_run", {"project_id": "landing-maker", "run_id": "rr_123"}
    )
    await dispatcher.dispatch(
        "reconciler_proposals", {"project_id": "landing-maker", "limit": 5}
    )
    await dispatcher.dispatch(
        "reconciler_candidates",
        {"project_id": "landing-maker", "run_id": "rr_123", "limit": 5},
    )
    await dispatcher.dispatch(
        "reconciler_candidate",
        {"project_id": "landing-maker", "candidate_id": "rc_123"},
    )
    await dispatcher.dispatch(
        "reconciler_result",
        {"project_id": "landing-maker", "result_id": "cr_123"},
    )
    await dispatcher.dispatch("reconciler_start", {"project_id": "landing-maker"})
    await dispatcher.dispatch(
        "reconciler_cancel", {"project_id": "landing-maker", "run_id": "rr_123"}
    )

    handlers.reconciler_run.assert_awaited_once_with(
        project_id="landing-maker", run_id="rr_123"
    )
    handlers.reconciler_proposals.assert_awaited_once_with(
        project_id="landing-maker", status=None, limit=5
    )
    handlers.reconciler_candidates.assert_awaited_once_with(
        project_id="landing-maker", run_id="rr_123", limit=5, offset=0
    )
    handlers.reconciler_candidate.assert_awaited_once_with(
        project_id="landing-maker", candidate_id="rc_123"
    )
    handlers.reconciler_result.assert_awaited_once_with(
        project_id="landing-maker", result_id="cr_123"
    )
    handlers.reconciler_start.assert_awaited_once_with(
        project_id="landing-maker",
        dry_run=True,
        anchored_path=None,
        created_after=None,
        created_before=None,
    )
    handlers.reconciler_cancel.assert_awaited_once_with(
        project_id="landing-maker", run_id="rr_123"
    )


@pytest.mark.asyncio
async def test_direct_reconciler_read_stays_in_project(temp_db):
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("landing-maker")
    storage = DirectStorageBackend(temp_db.db_path)
    storage.db = temp_db

    found = await storage.get_reconciler_run("landing-maker", run["id"])
    proposals = await storage.list_reconciler_proposals("landing-maker", None, 5)
    candidates = await storage.list_reconciler_candidates(
        "landing-maker", run["id"], 5, 0
    )

    assert found["id"] == run["id"]
    assert proposals == {"proposals": [], "count": 0}
    assert candidates["project_id"] == "landing-maker"
    assert candidates["candidates"] == []
    with pytest.raises(ValueError, match="not found"):
        await storage.get_reconciler_run("another-project", run["id"])
    with pytest.raises(ValueError, match="not found"):
        await storage.list_reconciler_candidates("another-project", run["id"], 5, 0)
    with pytest.raises(ValueError, match="not found"):
        await storage.get_reconciler_candidate("another-project", "rc_" + "a" * 32)


@pytest.mark.asyncio
async def test_direct_reconciler_candidate_audit_uses_real_candidate_id(temp_db):
    for memory_id in ("m1", "m2"):
        await temp_db.add_memory(
            {
                "id": memory_id,
                "content": "The same project task is recorded in both memories.",
                "content_hash": f"hash-{memory_id}",
                "project_id": "landing-maker",
                "category": "task",
                "status": "canonical",
                "source": "session",
                "client": "test",
                "embedding": b"\x00" * 16,
                "tags": json.dumps([]),
                "anchors": json.dumps({"file_paths": ["app/page.tsx"]}),
                "created_at": "2026-10-19T10:00:00+00:00",
                "updated_at": "2026-10-19T10:00:00+00:00",
            }
        )
    run = await MemoryReconcilerService(temp_db).create_run("landing-maker")
    storage = DirectStorageBackend(temp_db.db_path)
    storage.db = temp_db

    page = await storage.list_reconciler_candidates("landing-maker", run["id"], 5, 0)
    assert page["total"] == 1
    candidate_id = page["candidates"][0]["id"]
    assert candidate_id.startswith("rc_")
    detail = await storage.get_reconciler_candidate("landing-maker", candidate_id)
    assert detail["candidate"]["id"] == candidate_id
    assert {item["memory_id"] for item in detail["inputs"]} == {"m1", "m2"}
    with pytest.raises(ValueError, match="not found"):
        await storage.get_reconciler_candidate("other-project", candidate_id)


@pytest.mark.asyncio
async def test_api_reconciler_read_uses_existing_routes():
    storage = APIStorageBackend("http://test")
    storage.client = MagicMock()
    run_id = "rr_" + "a" * 32
    storage._make_request_with_retry = AsyncMock(
        return_value={"id": run_id, "project_id": "landing-maker"}
    )

    await storage.get_reconciler_run("landing-maker", run_id)

    storage._make_request_with_retry.assert_awaited_with(
        method="GET", url=f"/api/curation/reconciler/runs/{run_id}"
    )
    with pytest.raises(ValueError, match="not found"):
        await storage.get_reconciler_run("another-project", run_id)
    storage._make_request_with_retry.return_value = {"proposals": [], "count": 0}
    await storage.list_reconciler_proposals("landing-maker", "needs_review", 5)
    storage._make_request_with_retry.assert_awaited_with(
        method="GET",
        url="/api/curation/reconciler/proposals",
        params={"project_id": "landing-maker", "status": "needs_review", "limit": 5},
    )
    await storage.list_reconciler_candidates("landing-maker", run_id, 5, 2)
    storage._make_request_with_retry.assert_awaited_with(
        method="GET",
        url=f"/api/curation/reconciler/runs/{run_id}/candidates",
        params={"project_id": "landing-maker", "limit": 5, "offset": 2},
    )
    candidate_id = "rc_" + "a" * 32
    await storage.get_reconciler_candidate("landing-maker", candidate_id)
    storage._make_request_with_retry.assert_awaited_with(
        method="GET",
        url=f"/api/curation/reconciler/candidates/{candidate_id}",
        params={"project_id": "landing-maker"},
    )
    result_id = "cr_" + "a" * 32
    await storage.get_reconciler_result("landing-maker", result_id)
    storage._make_request_with_retry.assert_awaited_with(
        method="GET",
        url=f"/api/curation/reconciler/results/{result_id}",
        params={"project_id": "landing-maker"},
    )


@pytest.mark.asyncio
async def test_reconciler_mcp_execution_is_project_scoped(temp_db, monkeypatch):
    from app.core.schemas.reconciler import ReconcilerRunRequest

    monkeypatch.setattr(
        "app.core.services.llm_resolver.resolve_service_llm",
        AsyncMock(
            return_value={
                "provider": "openai",
                "api_key": "test-key",
                "model": "judge-test",
                "base_url": "http://127.0.0.1:8000/v1",
            }
        ),
    )
    storage = DirectStorageBackend(temp_db.db_path)
    storage.db = temp_db
    request = ReconcilerRunRequest(project_id="landing-maker")

    run = await storage.start_reconciler_run(request)

    assert run["dry_run"] == 1
    assert run["model"] == "judge-test"
    assert run["stats"]["llm_configuration"]["provider"] == "openai"
    assert run["status"] == "queued"
    with pytest.raises(ValueError, match="not found"):
        await storage.cancel_reconciler_run("another-project", run["id"])
    assert (await storage.cancel_reconciler_run("landing-maker", run["id"]))[
        "id"
    ] == run["id"]

    api = APIStorageBackend("http://test")
    api.client = MagicMock()
    api._make_request_with_retry = AsyncMock(
        return_value={"id": run["id"], "project_id": "landing-maker"}
    )
    await api.start_reconciler_run(request)
    api._make_request_with_retry.assert_awaited_with(
        method="POST",
        url="/api/curation/reconciler/runs",
        json_data={"project_id": "landing-maker", "dry_run": True},
    )
    await api.cancel_reconciler_run("landing-maker", run["id"])
    api._make_request_with_retry.assert_awaited_with(
        method="POST",
        url=f"/api/curation/reconciler/runs/{run['id']}/cancel",
    )
    with pytest.raises(ValueError, match="not found"):
        await api.cancel_reconciler_run("another-project", run["id"])


@pytest.mark.asyncio
async def test_reconciler_mcp_handler_validates_input():
    storage = MagicMock()
    storage.get_reconciler_run = AsyncMock(return_value={"id": "rr_valid"})
    candidate_id = "rc_" + "a" * 32
    storage.get_reconciler_candidate = AsyncMock(return_value={"id": candidate_id})
    result_id = "cr_" + "a" * 32
    storage.get_reconciler_result = AsyncMock(return_value={"id": result_id})
    handlers = MCPToolHandlers(storage)

    assert (await handlers.reconciler_candidate("landing-maker", candidate_id))[
        "id"
    ] == candidate_id
    storage.get_reconciler_candidate.assert_awaited_once_with(
        "landing-maker", candidate_id
    )
    assert (await handlers.reconciler_result("landing-maker", result_id))[
        "id"
    ] == result_id
    storage.get_reconciler_result.assert_awaited_once_with("landing-maker", result_id)

    with pytest.raises(ValidationError):
        await handlers.reconciler_run("landing-maker", "not-a-run-id")
    with pytest.raises(ValidationError):
        await handlers.reconciler_proposals("../other", limit=5)
    with pytest.raises(ValidationError):
        await handlers.reconciler_candidates("landing-maker", "bad-run")
    with pytest.raises(ValidationError):
        await handlers.reconciler_candidate("../other", "rc_" + "a" * 32)
    with pytest.raises(ValidationError):
        await handlers.reconciler_candidate("landing-maker", "cg_" + "a" * 32)
    with pytest.raises(ValidationError):
        await handlers.reconciler_result("landing-maker", "rc_" + "a" * 32)
    with pytest.raises(ValidationError):
        await handlers.reconciler_start("landing-maker", created_after="2026-10-20")
    with pytest.raises(ValidationError):
        await handlers.reconciler_cancel("landing-maker", "bad-run")

    storage.get_reconciler_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_fastmcp_reconciler_schemas_match_shared_schemas():
    from app.mcp_stdio.server import mcp

    shared = {item["name"]: item["inputSchema"] for item in get_all_tool_schemas()}
    registered = {tool.name: tool.parameters for tool in await mcp.list_tools()}

    for name in (
        "reconciler_run",
        "reconciler_proposals",
        "reconciler_candidates",
        "reconciler_candidate",
        "reconciler_result",
        "reconciler_start",
        "reconciler_cancel",
    ):
        assert registered[name] == shared[name]


@pytest.mark.asyncio
async def test_mcp_memory_tools_forward_reconciler_protection():
    handlers = MagicMock()
    handlers.add = AsyncMock(return_value={"id": "m1"})
    handlers.update = AsyncMock(return_value={"id": "m1"})
    dispatcher = MCPDispatcher(handlers)

    await dispatcher.dispatch(
        "add", {"content": "Protected memory content", "reconciler_protected": True}
    )
    await dispatcher.dispatch(
        "update", {"memory_id": "m1", "reconciler_protected": False}
    )

    assert handlers.add.await_args.kwargs["reconciler_protected"] is True
    assert handlers.update.await_args.kwargs["reconciler_protected"] is False

    from app.mcp_stdio.server import mcp

    shared = {item["name"]: item["inputSchema"] for item in get_all_tool_schemas()}
    registered = {tool.name: tool.parameters for tool in await mcp.list_tools()}
    assert shared["add"]["properties"]["reconciler_protected"]["default"] is False
    assert registered["add"]["properties"]["reconciler_protected"]["default"] is False
    assert "reconciler_protected" in registered["update"]["properties"]


@pytest.mark.asyncio
async def test_batch_add_keeps_each_memory_protection_choice():
    memory_service = MagicMock()
    memory_service.add_with_embedding = AsyncMock(
        side_effect=[SimpleNamespace(id="m1"), SimpleNamespace(id="m2")]
    )
    embedding_service = MagicMock()
    embedding_service.aembed_batch = AsyncMock(return_value=[[0.1], [0.2]])
    handler = BatchOperationHandler(
        memory_service=memory_service,
        search_service=MagicMock(),
        embedding_service=embedding_service,
        db=MagicMock(),
    )

    result = await handler.batch_add_memories(
        contents=["first memory", "second memory"],
        protected_list=[True, False],
    )

    assert result["successful"] == 2
    assert [
        call.kwargs["reconciler_protected"]
        for call in memory_service.add_with_embedding.await_args_list
    ] == [True, False]
