"""Relay HTTP API tests with dependency-overridden temporary DB."""

import os
import tempfile
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database.base import Database
from app.core.schemas.relay import RelayHubCheckResponse, RelayIngestRequest
from app.core.services.memory import MemoryService
from app.core.services.relay import RelayService, RelayUnauthorized
from app.web.common.dependencies import (
    get_database,
    get_embedding_service,
    get_memory_service,
)
from app.web.dashboard.route_modules.memories import router as memories_router
from app.web.dashboard.route_modules.relay import router as relay_router


@asynccontextmanager
async def _temp_db():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path)
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
        for ext in ["", "-wal", "-shm"]:
            path = db_path + ext
            if os.path.exists(path):
                os.unlink(path)


def _app(db: Database) -> FastAPI:
    app = FastAPI()
    app.include_router(relay_router, prefix="/api")
    app.include_router(memories_router, prefix="/api")
    embedding_service = _FakeEmbeddingService()
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_embedding_service] = lambda: embedding_service
    app.dependency_overrides[get_memory_service] = lambda: MemoryService(
        db, embedding_service
    )
    return app


def _request() -> RelayIngestRequest:
    return RelayIngestRequest(
        idempotency_key="node-1:memory-1:v1:create",
        payload_hash="sha256:payload",
        event_type="create",
        source_memory_id="memory-1",
        source_version=1,
        source_project_key="relay",
        kind="decision",
        status="active",
        content="Relay API memory content using a SQLite queue.",
        tags=["relay"],
    )


class _FakeEmbeddingService:
    model_name = "fake-embedding"
    dimension = 3

    async def aembed(self, text: str):
        return [0.1, 0.2, 0.3]


class _FakeTextEnricher:
    model = "fake-llm"
    model_version = "fake-llm-v1"

    async def enrich(self, content: str):
        return {
            "title": "SQLite relay queue",
            "abstract": "Relay uses a durable SQLite queue.",
            "tags": ["relay", "queue"],
            "display_kind": "decision",
            "confidence": 0.9,
        }


class _FakeDigestGenerator:
    model = "fake-llm"
    model_version = "fake-llm-v1"

    async def generate(self, *, team_project_id, items):
        return {
            "rollup": {"decisions": [items[0]["current_memory_id"]]},
            "contributors": ["node-1"],
            "recent_activity": [items[0]["title"]],
            "narrative": f"{team_project_id} digest cites {items[0]['current_memory_id']}",
            "source_memory_ids": [items[0]["current_memory_id"]],
        }


@pytest.mark.asyncio
async def test_relay_ingest_endpoint_maps_replay_and_collision_status_codes():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="relay-token",
            user_id="user-1",
            source_node_id="node-1",
            display_name="Jinwoo",
        )

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = _request().model_dump(mode="json")
            first = await client.post(
                "/api/relay/v1/ingest",
                json=payload,
                headers={"Authorization": "Bearer relay-token"},
            )
            replay = await client.post(
                "/api/relay/v1/ingest",
                json=payload,
                headers={"Authorization": "Bearer relay-token"},
            )
            collision_payload = {**payload, "payload_hash": "sha256:changed"}
            collision = await client.post(
                "/api/relay/v1/ingest",
                json=collision_payload,
                headers={"Authorization": "Bearer relay-token"},
            )

        assert first.status_code == 200
        assert first.json()["replayed"] is False
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True
        assert collision.status_code == 409


@pytest.mark.asyncio
async def test_relay_ingest_endpoint_rejects_missing_or_bad_authorization():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/relay/v1/ingest",
                json=_request().model_dump(mode="json"),
            )

        assert response.status_code == 401


@pytest.mark.asyncio
async def test_relay_ingest_endpoint_broadcasts_realtime_notifications(monkeypatch):
    events = []

    async def fake_relay_ingested(payload):
        events.append(("relay_ingested", payload))

    async def fake_memory_created(memory):
        events.append(("memory_created", memory))

    from app.web.websocket import realtime

    monkeypatch.setattr(realtime.notifier, "notify_relay_ingested", fake_relay_ingested)
    monkeypatch.setattr(realtime.notifier, "notify_memory_created", fake_memory_created)

    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="relay-token",
            user_id="user-1",
            source_node_id="node-1",
            display_name="Jinwoo",
        )

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/relay/v1/ingest",
                json=_request().model_dump(mode="json"),
                headers={"Authorization": "Bearer relay-token"},
            )

    assert response.status_code == 200
    assert response.json()["current_created"] is True
    assert [event[0] for event in events] == ["relay_ingested", "memory_created"]
    relay_payload = events[0][1]
    memory_payload = events[1][1]
    assert relay_payload["action"] == "create"
    assert relay_payload["relay_memory"]["source_memory_id"] == "memory-1"
    assert relay_payload["memory"]["id"].startswith("relay:")
    assert memory_payload["id"] == relay_payload["memory"]["id"]
    assert memory_payload["source"] == "relay"


@pytest.mark.asyncio
async def test_relay_search_endpoint_returns_visible_team_view():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="relay-token",
            user_id="user-1",
            source_node_id="node-1",
            display_name="Jinwoo",
        )
        await service.ingest("relay-token", _request())

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/relay/v1/search",
                json={"query": "SQLite", "limit": 10},
                headers={"Authorization": "Bearer relay-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["results"][0]["source_memory_id"] == "memory-1"


@pytest.mark.asyncio
async def test_relay_digest_endpoint_returns_generated_project_digest():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="relay-token",
            user_id="user-1",
            source_node_id="node-1",
            display_name="Jinwoo",
        )
        ingest = await service.ingest("relay-token", _request())
        await service.process_next_item(
            worker_id="item-worker",
            embedding_service=_FakeEmbeddingService(),
            text_enricher=_FakeTextEnricher(),
            prompt_version="item-prompt-v1",
        )
        await service.process_next_aggregate(
            worker_id="aggregate-worker",
            digest_generator=_FakeDigestGenerator(),
            prompt_version="digest-prompt-v1",
        )

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/relay/v1/projects/node-1:relay/digest",
                headers={"Authorization": "Bearer relay-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["team_project_id"] == "node-1:relay"
        assert ingest.current_memory_id in data["source_memory_ids"]
        assert ingest.current_memory_id in data["narrative"]


@pytest.mark.asyncio
async def test_relay_admin_overview_endpoint_returns_queue_status():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="relay-token",
            user_id="user-1",
            source_node_id="node-1",
            display_name="Jinwoo",
        )
        await service.ingest("relay-token", _request())
        await service.enqueue_outbox(payload=_request(), target_hub="https://hub.local")

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/relay/v1/admin/overview")

        assert response.status_code == 200
        data = response.json()
        assert data["raw_events"] == 1
        assert data["visible_memories"] == 1
        assert data["projects"] == 1
        assert data["recent_outbox"][0]["target_hub"] == "https://hub.local"
        assert data["recent_queue"][0]["queue"] == "item"
        assert data["recent_memories"][0]["source_memory_id"] == "memory-1"
        assert data["recent_memories"][0]["team_project_id"] == "node-1:relay"
        assert data["recent_memories"][0]["enriched"] is False
        assert data["item_queue_counts"] == [{"status": "pending", "count": 1}]
        assert data["outbox_counts"] == [{"status": "pending", "count": 1}]


@pytest.mark.asyncio
async def test_relay_admin_overview_lists_dead_letters_and_retry_endpoint_requeues():
    async with _temp_db() as db:
        service = RelayService(db, max_attempts=1)
        await service.ensure_schema()
        await service.enqueue_outbox(payload=_request(), target_hub="https://hub.local")
        claimed = await service.claim_outbox("outbox-worker", lease_seconds=30)
        assert claimed is not None
        await service.mark_outbox_failed(claimed.id, "hub unavailable")

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            overview = await client.get("/api/relay/v1/admin/overview")
            retry = await client.post(
                "/api/relay/v1/admin/retry-dead-letters",
                json={"queue": "outbox", "id": claimed.id, "limit": 1},
            )
            refreshed = await client.get("/api/relay/v1/admin/overview")

        overview_data = overview.json()
        refreshed_data = refreshed.json()
        assert overview.status_code == 200
        assert overview_data["outbox_counts"] == [{"status": "dead_letter", "count": 1}]
        assert overview_data["dead_letters"][0]["queue"] == "outbox"
        assert overview_data["dead_letters"][0]["id"] == claimed.id
        assert overview_data["dead_letters"][0]["target_hub"] == "https://hub.local"
        assert "hub unavailable" in overview_data["dead_letters"][0]["last_error"]
        assert retry.status_code == 200
        assert retry.json() == {
            "retried": 1,
            "outbox": 1,
            "item": 0,
            "aggregate": 0,
            "status": "ok",
        }
        assert refreshed.status_code == 200
        assert refreshed_data["outbox_counts"] == [{"status": "pending", "count": 1}]
        assert refreshed_data["dead_letters"] == []


@pytest.mark.asyncio
async def test_relay_admin_materialize_endpoint_backfills_memories(monkeypatch):
    events = []

    async def fake_relay_materialized(payload):
        events.append(payload)

    from app.web.websocket import realtime

    monkeypatch.setattr(
        realtime.notifier,
        "notify_relay_materialized",
        fake_relay_materialized,
    )

    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="relay-token",
            user_id="user-1",
            source_node_id="node-1",
            display_name="Jinwoo",
        )
        ingest = await service.ingest("relay-token", _request())
        memory_id = f"relay:{ingest.current_memory_id}"
        await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/relay/v1/admin/materialize?limit=20")

        materialized = await db.fetchone(
            "SELECT source, content FROM memories WHERE id = ?",
            (memory_id,),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["scanned"] == 1
        assert data["materialized"] == 1
        assert materialized["source"] == "relay"
        assert materialized["content"] == _request().content
        assert events == [
            {
                "scanned": 1,
                "materialized": 1,
                "deleted": 0,
                "skipped": 0,
                "status": "ok",
            }
        ]


@pytest.mark.asyncio
async def test_memory_delete_endpoint_tombstones_relay_materialized_memory():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="relay-token",
            user_id="user-1",
            source_node_id="node-1",
            display_name="Jinwoo",
        )
        ingest = await service.ingest("relay-token", _request())
        memory_id = f"relay:{ingest.current_memory_id}"

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(f"/api/memories/{memory_id}")

        current = await db.fetchone(
            """
            SELECT visible, authoritative_status, tombstoned_at
            FROM relay_memory_current
            WHERE id = ?
            """,
            (ingest.current_memory_id,),
        )
        materialized_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM memories WHERE id = ?",
            (memory_id,),
        )

        backfill = await service.materialize_current_memories(limit=20)
        after_backfill_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM memories WHERE id = ?",
            (memory_id,),
        )

        assert response.status_code == 200
        assert response.json() == {"id": memory_id, "status": "deleted"}
        assert current["visible"] == 0
        assert current["authoritative_status"] == "deleted"
        assert current["tombstoned_at"] is not None
        assert materialized_count["count"] == 0
        assert backfill.materialized == 0
        assert backfill.deleted == 1
        assert after_backfill_count["count"] == 0


@pytest.mark.asyncio
async def test_relay_admin_purge_current_endpoint_hides_received_projection():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="relay-token",
            user_id="user-1",
            source_node_id="node-1",
            display_name="Jinwoo",
        )
        first = await service.ingest("relay-token", _request())
        second_payload = _request().model_copy(
            update={
                "idempotency_key": "node-1:memory-2:v1:create",
                "payload_hash": "sha256:payload-2",
                "source_memory_id": "memory-2",
                "content": "Second relay API memory content using a SQLite queue.",
            }
        )
        second = await service.ingest("relay-token", second_payload)
        await db.execute(
            "DELETE FROM memories WHERE id = ?",
            (f"relay:{second.current_memory_id}",),
        )

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/relay/v1/admin/purge-current?limit=20")

        current_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM relay_memory_current WHERE visible = 1"
        )
        raw_count = await db.fetchone("SELECT COUNT(*) AS count FROM relay_raw_event")
        materialized_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM memories WHERE id LIKE 'relay:%'"
        )

        assert response.status_code == 200
        assert response.json() == {
            "scanned": 2,
            "purged": 2,
            "materialized_deleted": 1,
            "status": "ok",
        }
        assert current_count["count"] == 0
        assert raw_count["count"] == 2
        assert materialized_count["count"] == 0
        assert first.current_memory_id is not None


@pytest.mark.asyncio
async def test_relay_admin_destructive_endpoints_reject_unauthenticated_remote():
    """Destructive relay admin endpoints must 403 a non-loopback, unauthenticated
    caller even with auth disabled (default), so a 0.0.0.0-exposed hub cannot be
    wiped remotely. Loopback callers stay allowed (covered by the other admin
    tests, which use the default 127.0.0.1 transport).
    """
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="relay-token",
            user_id="user-1",
            source_node_id="node-1",
            display_name="Jinwoo",
        )
        await service.ingest("relay-token", _request())

        app = _app(db)
        # Simulate a remote (non-loopback) client; the default ASGITransport host
        # is 127.0.0.1, which the loopback fallback would allow.
        transport = ASGITransport(app=app, client=("203.0.113.10", 44321))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            purge = await client.post("/api/relay/v1/admin/purge-current?limit=20")
            materialize = await client.post("/api/relay/v1/admin/materialize?limit=20")
            retry = await client.post(
                "/api/relay/v1/admin/retry-dead-letters",
                json={"queue": "outbox"},
            )

        assert purge.status_code == 403
        assert materialize.status_code == 403
        assert retry.status_code == 403

        # The destructive action was blocked: the visible projection survives.
        current_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM relay_memory_current WHERE visible = 1"
        )
        assert current_count["count"] == 1


@pytest.mark.asyncio
async def test_relay_share_endpoints_reject_unauthenticated_remote():
    """Outbox share endpoints expose local memories to the team hub, so they must
    also 403 a non-loopback, unauthenticated caller (auth disabled by default).
    Loopback/authenticated dashboard callers stay allowed.
    """
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()

        app = _app(db)
        transport = ASGITransport(app=app, client=("203.0.113.10", 44322))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            share_memory = await client.post(
                "/api/relay/v1/outbox/share/some-memory-id",
                json={},
            )
            share_project = await client.post(
                "/api/relay/v1/outbox/share-project/some-project",
                json={},
            )

        assert share_memory.status_code == 403
        assert share_project.status_code == 403


@pytest.mark.asyncio
async def test_delete_relay_origin_memory_falls_back_to_plain_delete():
    """A memory flagged relay-origin by source (not a ``relay:`` id) takes the
    relay delete branch; delete_materialized_memory returns False (no relay:
    prefix) so the route falls back to a plain delete and the row is removed."""
    async with _temp_db() as db:
        relay = RelayService(db)
        await relay.ensure_schema()
        await db.execute(
            """
            INSERT INTO memories
                (id, content, content_hash, project_id, category, source,
                 client, embedding, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "plain-1",
                "A relay-origin memory stored under a non-relay id value here.",
                "hash-1",
                "proj",
                "decision",
                "relay",  # relay-origin via source, not via id prefix
                None,
                b"\x00" * 12,
                None,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/api/memories/plain-1")

        assert resp.status_code == 200
        remaining = await db.fetchone(
            "SELECT COUNT(*) AS count FROM memories WHERE id = 'plain-1'"
        )
        assert remaining["count"] == 0


@pytest.mark.asyncio
async def test_relay_auto_share_endpoints_list_and_toggle(monkeypatch):
    monkeypatch.setenv("MEM_MESH_RELAY_HUB_URL", "https://hub.local")
    monkeypatch.setenv("MEM_MESH_RELAY_SOURCE_NODE_ID", "node-1")

    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            empty = await client.get("/api/relay/v1/admin/auto-share")
            enabled = await client.put(
                "/api/relay/v1/admin/auto-share/proj-1",
                json={"enabled": True},
            )
            listed = await client.get("/api/relay/v1/admin/auto-share")
            disabled = await client.put(
                "/api/relay/v1/admin/auto-share/proj-1",
                json={"enabled": False},
            )

        assert empty.status_code == 200
        assert empty.json()["subscriptions"] == []
        assert enabled.status_code == 200
        body = enabled.json()
        assert body["project_id"] == "proj-1"
        assert body["enabled"] is True
        # hub/node are snapshotted from effective config at enable time.
        assert body["target_hub"] == "https://hub.local"
        assert body["source_node_id"] == "node-1"
        assert listed.status_code == 200
        assert len(listed.json()["subscriptions"]) == 1
        assert disabled.json()["enabled"] is False


@pytest.mark.asyncio
async def test_relay_auto_share_toggle_rejects_unauthenticated_remote():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()

        app = _app(db)
        transport = ASGITransport(app=app, client=("203.0.113.10", 44323))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            put = await client.put(
                "/api/relay/v1/admin/auto-share/proj-1",
                json={"enabled": True},
            )
            listed = await client.get("/api/relay/v1/admin/auto-share")

        assert put.status_code == 403
        assert listed.status_code == 403


@pytest.mark.asyncio
async def test_relay_admin_settings_endpoint_persists_defaults_and_identity(
    monkeypatch,
):
    monkeypatch.delenv("MEM_MESH_RELAY_HUB_URL", raising=False)
    monkeypatch.delenv("MEM_MESH_RELAY_SOURCE_NODE_ID", raising=False)
    monkeypatch.setenv("MEM_MESH_RELAY_HUB_TOKEN", "env-token")

    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            updated = await client.put(
                "/api/relay/v1/admin/settings",
                json={
                    "hub_url": "https://hub.local",
                    "source_node_id": "node-1",
                    "default_source_version": 7,
                    "hub_token": "db-token",
                },
            )
            identity = await client.post(
                "/api/relay/v1/admin/identities",
                json={
                    "user_id": "user-1",
                    "source_node_id": "node-1",
                    "display_name": "Jinwoo",
                    "home_domain": "local",
                    "scopes": ["read", "write"],
                },
            )
            identity_update = await client.put(
                f"/api/relay/v1/admin/identities/{identity.json()['token_hash_prefix']}",
                json={
                    "display_name": "Jinwoo Local",
                    "home_domain": "laptop.local",
                    "scopes": ["read"],
                    "revoked": True,
                },
            )
            settings = await client.get("/api/relay/v1/admin/settings")

        assert updated.status_code == 200
        assert updated.json()["hub_url"]["value"] == "https://hub.local"
        assert updated.json()["hub_url"]["source"] == "db"
        assert updated.json()["hub_token"]["configured"] is True
        assert updated.json()["hub_token"]["source"] == "db"
        assert updated.json()["default_source_version"] == 7

        assert identity.status_code == 200
        identity_data = identity.json()
        assert identity_data["token_generated"] is True
        assert len(identity_data["token"]) >= 32
        assert identity_data["identity"]["source_node_id"] == "node-1"

        assert identity_update.status_code == 200
        assert identity_update.json()["identity"]["display_name"] == "Jinwoo Local"
        assert identity_update.json()["identity"]["scopes"] == ["read"]
        assert identity_update.json()["identity"]["revoked"] is True

        assert settings.status_code == 200
        data = settings.json()
        assert data["source_node_id"]["value"] == "node-1"
        assert data["identities"][0]["display_name"] == "Jinwoo Local"
        assert (
            data["identities"][0]["token_hash_prefix"]
            == identity_data["token_hash_prefix"]
        )


@pytest.mark.asyncio
async def test_relay_health_and_hub_check_endpoint(monkeypatch):
    async def fake_check_hub(self, hub_url, **kwargs):
        return RelayHubCheckResponse(
            ok=True,
            hub_url=hub_url,
            health_url=f"{hub_url}/api/relay/v1/health",
            status_code=200,
            relay="mem-mesh-relay",
            message="hub reachable",
        )

    monkeypatch.setattr(RelayService, "check_hub", fake_check_hub)

    async with _temp_db() as db:
        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/api/relay/v1/health")
            check = await client.post(
                "/api/relay/v1/admin/hub/check",
                json={"hub_url": "http://hub.local"},
            )

        assert health.status_code == 200
        assert health.json()["ok"] is True
        assert check.status_code == 200
        assert check.json()["ok"] is True
        assert check.json()["relay"] == "mem-mesh-relay"


@pytest.mark.asyncio
async def test_relay_auth_check_endpoint_validates_token():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="relay-token",
            user_id="user-1",
            source_node_id="node-1",
            display_name="Jinwoo",
        )

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            good = await client.get(
                "/api/relay/v1/auth/check",
                headers={"Authorization": "Bearer relay-token"},
            )
            bad = await client.get(
                "/api/relay/v1/auth/check",
                headers={"Authorization": "Bearer wrong-token"},
            )
            missing = await client.get("/api/relay/v1/auth/check")

        assert good.status_code == 200
        body = good.json()
        assert body["ok"] is True
        assert body["node_id"] == "node-1"
        assert "write" in body["scopes"]

        assert bad.status_code == 401
        bad_body = bad.json()
        assert "invalid or revoked" in (
            bad_body.get("message") or bad_body.get("detail") or ""
        )
        assert missing.status_code == 401


@pytest.mark.asyncio
async def test_hub_check_forwards_token_with_stored_fallback(monkeypatch):
    seen = {}

    async def fake_check_hub(self, hub_url, *, token=None, **kwargs):
        seen["token"] = token
        return RelayHubCheckResponse(
            ok=True,
            hub_url=hub_url,
            health_url=f"{hub_url}/api/relay/v1/health",
            status_code=200,
            relay="mem-mesh-relay",
            message="hub reachable",
        )

    monkeypatch.setattr(RelayService, "check_hub", fake_check_hub)

    async with _temp_db() as db:
        await db.set_app_config("relay.hub_token", "stored-tok")
        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Explicit token wins.
            await client.post(
                "/api/relay/v1/admin/hub/check",
                json={"hub_url": "http://hub.local", "token": "explicit-tok"},
            )
            assert seen["token"] == "explicit-tok"

            # Omitted token falls back to the stored hub token.
            await client.post(
                "/api/relay/v1/admin/hub/check",
                json={"hub_url": "http://hub.local"},
            )
            assert seen["token"] == "stored-tok"


@pytest.mark.asyncio
async def test_relay_identity_delete_endpoint_removes_row():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        prefix = (
            await service.register_identity(
                token="relay-token-to-delete",
                user_id="user-1",
                source_node_id="node-1",
                display_name="Jinwoo",
            )
        )[:12]

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            deleted = await client.delete(f"/api/relay/v1/admin/identities/{prefix}")
            again = await client.delete(f"/api/relay/v1/admin/identities/{prefix}")

        assert deleted.status_code == 200
        assert deleted.json()["ok"] is True
        # Second delete → gone.
        assert again.status_code == 404
        assert await service.list_identities() == []


@pytest.mark.asyncio
async def test_relay_identity_rotate_endpoint_swaps_token():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        old_prefix = (
            await service.register_identity(
                token="old-relay-token-123456",
                user_id="user-1",
                source_node_id="node-1",
                display_name="Jinwoo",
            )
        )[:12]

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            rotated = await client.post(
                f"/api/relay/v1/admin/identities/{old_prefix}/rotate",
                json={},
            )

        assert rotated.status_code == 200
        body = rotated.json()
        assert body["token_generated"] is True
        new_token = body["token"]
        assert new_token and new_token != "old-relay-token-123456"

        # Old token no longer authenticates; the new one does — metadata kept.
        with pytest.raises(RelayUnauthorized):
            await service.authorize("old-relay-token-123456", require_scope="read")
        identity = await service.authorize(new_token, require_scope="write")
        assert identity["source_node_id"] == "node-1"
        assert identity["display_name"] == "Jinwoo"
        # Exactly one identity remains (old row replaced, not duplicated).
        assert len(await service.list_identities()) == 1


@pytest.mark.asyncio
async def test_relay_share_memory_endpoint_enqueues_existing_memory():
    async with _temp_db() as db:
        await db.set_app_config("relay.hub_url", "https://hub.local")
        await db.set_app_config("relay.source_node_id", "node-1")
        # Deliberately set but must be IGNORED: source_version omitted in the
        # request now means "derive from updated_at" (matches auto-share),
        # not "fall back to this static config".
        await db.set_app_config("relay.default_source_version", "3")
        await db.execute(
            """
            INSERT INTO memories (
                id, content, content_hash, project_id, category, source,
                client, embedding, tags, created_at, updated_at, content_bytes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "memory-1",
                "A relay decision memory from the existing memories table.",
                "hash-v1",
                "relay",
                "decision",
                "test",
                None,
                b"123",
                '["relay"]',
                "2026-06-25T00:00:00Z",
                "2026-06-25T00:01:00Z",
                56,
            ),
        )

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/relay/v1/outbox/share/memory-1",
                json={},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["target_hub"] == "https://hub.local"
        assert data["source_node_id"] == "node-1"
        outbox = await db.fetchone(
            "SELECT * FROM relay_outbox WHERE id = ?", (data["outbox_id"],)
        )
        expected_version = RelayService._auto_share_version(
            SimpleNamespace(updated_at="2026-06-25T00:01:00Z")
        )
        assert (
            outbox["idempotency_key"] == f"node-1:memory-1:v{expected_version}:update"
        )

        await db.execute(
            """
            UPDATE relay_outbox
            SET status = 'sent',
                attempts = 2,
                last_error = 'previous error'
            WHERE id = ?
            """,
            (data["outbox_id"],),
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            forced = await client.post(
                "/api/relay/v1/outbox/share/memory-1",
                json={"force": True},
            )
        forced_outbox = await db.fetchone(
            "SELECT status, attempts, last_error FROM relay_outbox WHERE id = ?",
            (data["outbox_id"],),
        )
        assert forced.status_code == 200
        assert forced.json()["outbox_id"] == data["outbox_id"]
        assert forced_outbox["status"] == "pending"
        assert forced_outbox["attempts"] == 0
        assert forced_outbox["last_error"] is None


@pytest.mark.asyncio
async def test_relay_share_project_endpoint_enqueues_shareable_project_memories():
    async with _temp_db() as db:
        await db.set_app_config("relay.hub_url", "https://hub.local")
        await db.set_app_config("relay.source_node_id", "node-1")
        await db.set_app_config("relay.default_source_version", "5")
        for memory_id, category in [("memory-1", "decision"), ("memory-2", "task")]:
            await db.execute(
                """
                INSERT INTO memories (
                    id, content, content_hash, project_id, category, source,
                    client, embedding, tags, created_at, updated_at, content_bytes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    f"Relay project memory {memory_id}",
                    f"hash-{memory_id}",
                    "relay",
                    category,
                    "test",
                    None,
                    b"123",
                    '["relay"]',
                    "2026-06-25T00:00:00Z",
                    "2026-06-25T00:01:00Z",
                    32,
                ),
            )

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/relay/v1/outbox/share-project/relay",
                json={},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["queued_count"] == 1
        assert data["target_hub"] == "https://hub.local"
        assert data["skipped"][0]["memory_id"] == "memory-2"
        outbox_count = await db.fetchone("SELECT COUNT(*) AS count FROM relay_outbox")
        assert outbox_count["count"] == 1


@pytest.mark.asyncio
async def test_admin_settings_federated_tuning_roundtrip():
    """WS3 (R4): federated timeout/weight are DB-backed via GET/PUT settings."""
    async with _temp_db() as db:
        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.get("/api/relay/v1/admin/settings")
            assert r1.status_code == 200
            d1 = r1.json()
            assert "federated_timeout" in d1
            assert "federated_hub_weight" in d1
            assert d1["federated_timeout"]["source"] in ("default", "env")

            r2 = await client.put(
                "/api/relay/v1/admin/settings",
                json={"federated_timeout": 4.0, "federated_hub_weight": 1.25},
            )
            assert r2.status_code == 200
            d2 = r2.json()
            assert d2["federated_timeout"]["value"] == "4.0"
            assert d2["federated_timeout"]["source"] == "db"
            assert d2["federated_hub_weight"]["value"] == "1.25"
            assert d2["federated_hub_weight"]["source"] == "db"

            r3 = await client.get("/api/relay/v1/admin/settings")
            assert r3.json()["federated_hub_weight"]["value"] == "1.25"

            # Out-of-range weight is rejected by the request schema (ge/le).
            r4 = await client.put(
                "/api/relay/v1/admin/settings",
                json={"federated_hub_weight": 5.0},
            )
            assert r4.status_code == 422
