"""Relay HTTP API tests with dependency-overridden temporary DB."""

import os
import tempfile
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database.base import Database
from app.core.schemas.relay import RelayIngestRequest
from app.core.services.relay import RelayService
from app.web.common.dependencies import get_database, get_embedding_service
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
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_embedding_service] = lambda: None
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
    model = "fake-sonnet"
    model_version = "fake-sonnet-v1"

    async def enrich(self, content: str):
        return {
            "title": "SQLite relay queue",
            "abstract": "Relay uses a durable SQLite queue.",
            "tags": ["relay", "queue"],
            "display_kind": "decision",
            "confidence": 0.9,
        }


class _FakeDigestGenerator:
    model = "fake-sonnet"
    model_version = "fake-sonnet-v1"

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
        assert data["item_queue_counts"] == [{"status": "pending", "count": 1}]
        assert data["outbox_counts"] == [{"status": "pending", "count": 1}]


@pytest.mark.asyncio
async def test_relay_admin_settings_endpoint_persists_defaults_and_identity(
    monkeypatch,
):
    monkeypatch.delenv("MEM_MESH_RELAY_HUB_URL", raising=False)
    monkeypatch.delenv("MEM_MESH_RELAY_SOURCE_NODE_ID", raising=False)

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
            settings = await client.get("/api/relay/v1/admin/settings")

        assert updated.status_code == 200
        assert updated.json()["hub_url"]["value"] == "https://hub.local"
        assert updated.json()["hub_url"]["source"] == "db"
        assert updated.json()["default_source_version"] == 7

        assert identity.status_code == 200
        identity_data = identity.json()
        assert identity_data["token_generated"] is True
        assert len(identity_data["token"]) >= 32
        assert identity_data["identity"]["source_node_id"] == "node-1"

        assert settings.status_code == 200
        data = settings.json()
        assert data["source_node_id"]["value"] == "node-1"
        assert data["identities"][0]["display_name"] == "Jinwoo"
        assert data["identities"][0]["token_hash_prefix"] == identity_data["token_hash_prefix"]


@pytest.mark.asyncio
async def test_relay_share_memory_endpoint_enqueues_existing_memory():
    async with _temp_db() as db:
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
                json={
                    "source_node_id": "node-1",
                    "source_version": 3,
                    "target_hub": "https://hub.local",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        outbox = await db.fetchone("SELECT * FROM relay_outbox WHERE id = ?", (data["outbox_id"],))
        assert outbox["idempotency_key"] == "node-1:memory-1:v3:update"
