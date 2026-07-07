"""Relay pairing invite tests — invite lifecycle, redemption, and the
node-side /admin/pair self-configuration flow."""

import os
import tempfile
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database.base import Database
from app.core.errors import RelayInviteInvalid
from app.core.schemas.relay import (
    RelayInviteCreateRequest,
    RelayPairRequest,
    RelayPairResponse,
)
from app.core.services.relay import RelayService
from app.web.common.dependencies import get_database, get_embedding_service
from app.web.dashboard.route_modules.relay import router as relay_router


@asynccontextmanager
async def _temp_db():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path, embedding_dim=3)
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
        for ext in ["", "-wal", "-shm"]:
            path = db_path + ext
            if os.path.exists(path):
                os.unlink(path)


class _FakeEmbeddingService:
    model_name = "fake-embedding"
    dimension = 3

    async def aembed(self, text: str):
        return [0.1, 0.2, 0.3]


def _app(db: Database) -> FastAPI:
    app = FastAPI()
    app.include_router(relay_router, prefix="/api")
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_embedding_service] = lambda: _FakeEmbeddingService()
    return app


def _invite_request(**overrides) -> RelayInviteCreateRequest:
    payload = {
        "user_id": "user-2",
        "display_name": "New Member",
        "source_node_id": "node-2",
        "scopes": ["read", "write"],
        "expires_in_seconds": 3600,
    }
    payload.update(overrides)
    return RelayInviteCreateRequest(**payload)


@pytest.mark.asyncio
async def test_create_invite_returns_code_once_and_lists_summary():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()

        invite, code = await service.create_invite(_invite_request())

        assert code and len(code) >= 24
        assert invite.code_prefix == service._hash_token(code)[:12]
        assert invite.redeemed_at is None

        invites = await service.list_invites()
        assert [i.code_prefix for i in invites] == [invite.code_prefix]
        # The code itself is never stored or re-listed.
        assert not hasattr(invites[0], "code")


@pytest.mark.asyncio
async def test_redeem_invite_registers_identity_and_is_single_use():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        _, code = await service.create_invite(_invite_request())

        result = await service.redeem_invite(RelayPairRequest(code=code))

        assert result.source_node_id == "node-2"
        assert result.user_id == "user-2"
        assert sorted(result.scopes) == ["read", "write"]
        # The minted token authenticates with write scope (ingest-capable).
        identity = await service.authorize(result.token, require_scope="write")
        assert identity["source_node_id"] == "node-2"

        # Invite is single-use.
        with pytest.raises(RelayInviteInvalid):
            await service.redeem_invite(RelayPairRequest(code=code))
        invites = await service.list_invites()
        assert invites[0].redeemed_at is not None
        assert invites[0].redeemed_source_node_id == "node-2"


@pytest.mark.asyncio
async def test_redeem_invite_rejects_unknown_expired_and_revoked_codes():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()

        with pytest.raises(RelayInviteInvalid):
            await service.redeem_invite(RelayPairRequest(code="x" * 32))

        _, expired_code = await service.create_invite(_invite_request())
        await db.execute(
            "UPDATE relay_invite SET expires_at = ?",
            ("2000-01-01T00:00:00+00:00",),
        )
        with pytest.raises(RelayInviteInvalid):
            await service.redeem_invite(RelayPairRequest(code=expired_code))

        invite, revoked_code = await service.create_invite(
            _invite_request(source_node_id="node-3")
        )
        assert await service.delete_invite(invite.code_prefix) is True
        with pytest.raises(RelayInviteInvalid):
            await service.redeem_invite(RelayPairRequest(code=revoked_code))


@pytest.mark.asyncio
async def test_redeem_invite_rejects_taken_source_node_id():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="existing-token",
            user_id="user-1",
            source_node_id="node-2",
            display_name="Existing",
        )
        _, code = await service.create_invite(_invite_request())

        with pytest.raises(RelayInviteInvalid):
            await service.redeem_invite(RelayPairRequest(code=code))

        # The failed redemption did not consume the invite... and once the
        # conflict clears, the same code still works.
        await service.delete_identity(service._hash_token("existing-token")[:12])
        result = await service.redeem_invite(RelayPairRequest(code=code))
        assert result.source_node_id == "node-2"


@pytest.mark.asyncio
async def test_redeem_invite_uses_node_proposed_id_when_not_pinned():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        _, code = await service.create_invite(_invite_request(source_node_id=None))

        with pytest.raises(RelayInviteInvalid):
            # No pinned id and no proposal → rejected.
            await service.redeem_invite(RelayPairRequest(code=code))

        result = await service.redeem_invite(
            RelayPairRequest(code=code, source_node_id="laptop-7")
        )
        assert result.source_node_id == "laptop-7"


@pytest.mark.asyncio
async def test_pair_endpoint_redeems_invite_and_maps_errors():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        _, code = await service.create_invite(_invite_request())

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            ok = await client.post("/api/relay/v1/pair", json={"code": code})
            assert ok.status_code == 200
            body = ok.json()
            assert body["token"]
            assert body["source_node_id"] == "node-2"

            replay = await client.post("/api/relay/v1/pair", json={"code": code})
            assert replay.status_code == 400


@pytest.mark.asyncio
async def test_invite_admin_endpoints_issue_list_and_revoke():
    async with _temp_db() as db:
        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/relay/v1/admin/invites",
                json={"user_id": "user-9", "display_name": "Nine"},
            )
            assert created.status_code == 200
            code = created.json()["code"]
            prefix = created.json()["invite"]["code_prefix"]
            assert code

            listed = await client.get("/api/relay/v1/admin/invites")
            assert listed.status_code == 200
            assert [i["code_prefix"] for i in listed.json()["invites"]] == [prefix]

            revoked = await client.delete(f"/api/relay/v1/admin/invites/{prefix}")
            assert revoked.status_code == 200
            missing = await client.delete(f"/api/relay/v1/admin/invites/{prefix}")
            assert missing.status_code == 404


@pytest.mark.asyncio
async def test_admin_pair_configures_node_from_hub_response(monkeypatch):
    async with _temp_db() as db:
        captured = {}

        async def _fake_send_pair(self, *, target_hub, payload, timeout=None):
            captured["target_hub"] = target_hub
            captured["code"] = payload.code
            return RelayPairResponse(
                ok=True,
                token="hub-issued-token",
                user_id="user-2",
                source_node_id="node-2",
                display_name="New Member",
                scopes=["read", "write"],
            )

        from app.core.services import relay as relay_module

        monkeypatch.setattr(relay_module.RelayHTTPClient, "send_pair", _fake_send_pair)

        async def _fake_check_hub(self, hub_url, *, token=None, timeout=5.0, **_):
            from app.core.schemas.relay import RelayHubCheckResponse

            return RelayHubCheckResponse(
                ok=True,
                hub_url=hub_url,
                health_url=f"{hub_url}/api/relay/v1/health",
                status_code=200,
                message="hub reachable",
                token_checked=True,
                token_ok=True,
                node_id="node-2",
            )

        monkeypatch.setattr(relay_module.RelayService, "check_hub", _fake_check_hub)

        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/relay/v1/admin/pair",
                json={"hub_url": "https://hub.example.com", "code": "c" * 32},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["source_node_id"] == "node-2"
        assert body["check"]["token_ok"] is True
        assert captured["target_hub"] == "https://hub.example.com"

        # Settings were self-configured from the pairing result.
        service = RelayService(db)
        await service.ensure_schema()
        assert await db.get_app_config("relay.hub_url") == "https://hub.example.com"
        assert await db.get_app_config("relay.hub_token") == "hub-issued-token"
        assert await db.get_app_config("relay.source_node_id") == "node-2"


@pytest.mark.asyncio
async def test_search_kinds_filter_applies_hub_side():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="relay-token",
            user_id="user-1",
            source_node_id="node-1",
            display_name="Jinwoo",
        )

        from app.core.schemas.relay import RelayIngestRequest

        for idx, kind in enumerate(("decision", "bug"), start=1):
            await service.ingest(
                "relay-token",
                RelayIngestRequest(
                    idempotency_key=f"node-1:memory-{idx}:v1:create",
                    payload_hash=f"sha256:payload-{idx}",
                    event_type="create",
                    source_memory_id=f"memory-{idx}",
                    source_version=1,
                    source_project_key="relay",
                    kind=kind,
                    status="active",
                    content=f"Shared {kind} about the sqlite relay queue.",
                    tags=["relay"],
                ),
            )

        unfiltered = await service.search(query="relay queue")
        assert {r.kind for r in unfiltered.results} == {"decision", "bug"}

        filtered = await service.search(query="relay queue", kinds=["bug"])
        assert [r.kind for r in filtered.results] == ["bug"]
