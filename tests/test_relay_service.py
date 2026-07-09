"""Relay service regression tests.

These tests pin the PRD v0.2 invariants that are easy to break:
idempotent ingest, append-only raw events, current projection semantics,
secret guard before persistence, and durable SQLite queue claiming.
"""

import logging
import os
import tempfile
import time
from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError

from app.core.database.base import Database
from app.core.database.models import Memory
from app.core.schemas.relay import RelayIngestRequest, RelaySettingsUpdateRequest
from app.core.services.enrich_store import EnrichmentStore
from app.core.services.relay import (
    RelayDeliveryConflict,
    RelayHTTPClient,
    RelayIdempotencyConflict,
    RelaySecretBlocked,
    RelayService,
    RelayTypeGateBlocked,
)


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


async def _service_with_identity(db: Database) -> RelayService:
    service = RelayService(db)
    await service.ensure_schema()
    await service.register_identity(
        token="relay-token",
        user_id="user-1",
        source_node_id="node-1",
        display_name="Jinwoo",
        home_domain="local.test",
    )
    return service


def _request(
    *,
    memory_id: str = "memory-1",
    version: int = 1,
    event_type: str = "create",
    payload_hash: str = "sha256:payload-v1",
    content: str = "Relay memory content about sqlite queue post-processing.",
) -> RelayIngestRequest:
    return RelayIngestRequest(
        idempotency_key=f"node-1:{memory_id}:v{version}:{event_type}",
        payload_hash=payload_hash,
        event_type=event_type,
        source_memory_id=memory_id,
        source_version=version,
        source_project_key="relay",
        kind="decision",
        status="deleted" if event_type == "retract" else "active",
        content=None if event_type == "retract" else content,
        tags=["relay", "sqlite"],
        links=[],
    )


@pytest.mark.asyncio
async def test_ingest_is_idempotent_and_detects_payload_collision():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        request = _request()

        first = await service.ingest("relay-token", request)
        replay = await service.ingest("relay-token", request)

        assert first.accepted is True
        assert first.replayed is False
        assert first.queued_item is True
        assert replay.accepted is True
        assert replay.replayed is True
        assert replay.event_id == first.event_id
        assert replay.current_memory_id == first.current_memory_id
        assert replay.queued_item is False

        raw_count = await db.fetchone("SELECT COUNT(*) AS count FROM relay_raw_event")
        queue_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM relay_queue_item"
        )
        materialized = await db.fetchone(
            """
            SELECT id, project_id, category, source, client, content, tags
            FROM memories
            WHERE id = ?
            """,
            (f"relay:{first.current_memory_id}",),
        )
        assert raw_count["count"] == 1
        assert queue_count["count"] == 1
        assert materialized["project_id"] == "relay"
        assert materialized["category"] == "decision"
        assert materialized["source"] == "relay"
        assert materialized["client"] == "relay:node-1"
        assert materialized["content"] == request.content
        assert '"shared"' in materialized["tags"]

        collision = request.model_copy(update={"payload_hash": "sha256:changed"})
        with pytest.raises(RelayIdempotencyConflict):
            await service.ingest("relay-token", collision)


@pytest.mark.asyncio
async def test_update_appends_raw_event_and_older_event_does_not_replace_current():
    async with _temp_db() as db:
        service = await _service_with_identity(db)

        newer = _request(
            version=2,
            payload_hash="sha256:newer",
            content="Newer relay decision that should remain current.",
        )
        older = _request(
            version=1,
            event_type="update",
            payload_hash="sha256:older",
            content="Older relay decision that arrived late.",
        )

        newer_response = await service.ingest("relay-token", newer)
        older_response = await service.ingest("relay-token", older)

        assert newer_response.applied_to_current is True
        assert older_response.applied_to_current is False

        raw_count = await db.fetchone("SELECT COUNT(*) AS count FROM relay_raw_event")
        current = await db.fetchone(
            """
            SELECT source_version, content, visible
            FROM relay_memory_current
            WHERE id = ?
            """,
            (newer_response.current_memory_id,),
        )
        queue_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM relay_queue_item"
        )
        materialized = await db.fetchone(
            "SELECT content FROM memories WHERE id = ?",
            (f"relay:{newer_response.current_memory_id}",),
        )

        assert raw_count["count"] == 2
        assert current["source_version"] == 2
        assert current["content"] == newer.content
        assert current["visible"] == 1
        assert queue_count["count"] == 1
        assert materialized["content"] == newer.content


@pytest.mark.asyncio
async def test_retract_hides_current_projection_without_deleting_raw_history():
    async with _temp_db() as db:
        service = await _service_with_identity(db)

        created = await service.ingest("relay-token", _request())
        retracted = await service.ingest(
            "relay-token",
            _request(
                version=2,
                event_type="retract",
                payload_hash="sha256:retract-v2",
            ),
        )

        assert retracted.applied_to_current is True
        assert retracted.current_memory_id == created.current_memory_id

        raw_count = await db.fetchone("SELECT COUNT(*) AS count FROM relay_raw_event")
        current = await db.fetchone(
            "SELECT visible, tombstoned_at FROM relay_memory_current WHERE id = ?",
            (created.current_memory_id,),
        )
        materialized_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM memories WHERE id = ?",
            (f"relay:{created.current_memory_id}",),
        )

        assert raw_count["count"] == 2
        assert current["visible"] == 0
        assert current["tombstoned_at"] is not None
        assert materialized_count["count"] == 0


@pytest.mark.asyncio
async def test_materialize_current_memories_backfills_existing_current_rows():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        ingest = await service.ingest("relay-token", _request())
        memory_id = f"relay:{ingest.current_memory_id}"
        await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

        missing = await db.fetchone(
            "SELECT COUNT(*) AS count FROM memories WHERE id = ?",
            (memory_id,),
        )
        result = await service.materialize_current_memories(limit=10)
        materialized = await db.fetchone(
            """
            SELECT id, content, project_id, category, source
            FROM memories
            WHERE id = ?
            """,
            (memory_id,),
        )

        assert missing["count"] == 0
        assert result.scanned == 1
        assert result.materialized == 1
        assert result.deleted == 0
        assert materialized["content"] == _request().content
        assert materialized["project_id"] == "relay"
        assert materialized["category"] == "decision"
        assert materialized["source"] == "relay"


@pytest.mark.asyncio
async def test_delete_materialized_memory_tombstones_current_and_blocks_backfill():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        ingest = await service.ingest("relay-token", _request())
        memory_id = f"relay:{ingest.current_memory_id}"

        deleted = await service.delete_materialized_memory(memory_id)
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
        queue_count = await db.fetchone(
            """
            SELECT COUNT(*) AS count
            FROM relay_queue_item
            WHERE ref_id = ? AND status IN ('pending', 'processing')
            """,
            (ingest.current_memory_id,),
        )

        result = await service.materialize_current_memories(limit=10)
        after_backfill_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM memories WHERE id = ?",
            (memory_id,),
        )

        assert deleted is True
        assert current["visible"] == 0
        assert current["authoritative_status"] == "deleted"
        assert current["tombstoned_at"] is not None
        assert materialized_count["count"] == 0
        assert queue_count["count"] == 0
        assert result.scanned == 1
        assert result.materialized == 0
        assert result.deleted == 1
        assert after_backfill_count["count"] == 0


@pytest.mark.asyncio
async def test_purge_current_memories_hides_visible_rows_and_preserves_raw_history():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        first = await service.ingest("relay-token", _request(memory_id="memory-1"))
        second = await service.ingest(
            "relay-token",
            _request(
                memory_id="memory-2",
                payload_hash="sha256:payload-v2",
                content="Second relay memory content about team hub cleanup.",
            ),
        )
        second_memory_id = f"relay:{second.current_memory_id}"
        await db.execute("DELETE FROM memories WHERE id = ?", (second_memory_id,))

        result = await service.purge_current_memories(limit=100)
        current_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM relay_memory_current WHERE visible = 1"
        )
        raw_count = await db.fetchone("SELECT COUNT(*) AS count FROM relay_raw_event")
        materialized_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM memories WHERE id LIKE 'relay:%'"
        )
        queue_count = await db.fetchone("""
            SELECT COUNT(*) AS count
            FROM relay_queue_item
            WHERE status IN ('pending', 'processing')
            """)

        assert result.scanned == 2
        assert result.purged == 2
        assert result.materialized_deleted == 1
        assert current_count["count"] == 0
        assert raw_count["count"] == 2
        assert materialized_count["count"] == 0
        assert queue_count["count"] == 0
        assert first.current_memory_id is not None


@pytest.mark.asyncio
async def test_ingest_replay_resyncs_deleted_materialized_memory():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        first = await service.ingest("relay-token", _request())
        memory_id = f"relay:{first.current_memory_id}"
        await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

        replay = await service.ingest("relay-token", _request())
        materialized = await db.fetchone(
            """
            SELECT id, content, source
            FROM memories
            WHERE id = ?
            """,
            (memory_id,),
        )

        assert replay.replayed is True
        assert replay.current_memory_id == first.current_memory_id
        assert materialized["content"] == _request().content
        assert materialized["source"] == "relay"


@pytest.mark.asyncio
async def test_secret_guard_blocks_before_raw_persistence():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        request = _request(
            payload_hash="sha256:secret",
            content="Do not share this Authorization: Bearer abcdefghijklmnop",
        )

        with pytest.raises(RelaySecretBlocked):
            await service.ingest("relay-token", request)

        raw_count = await db.fetchone("SELECT COUNT(*) AS count FROM relay_raw_event")
        assert raw_count["count"] == 0


@pytest.mark.asyncio
async def test_outbox_enqueue_is_idempotent_and_blocks_secrets_before_queueing():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()

        request = _request()
        first_id = await service.enqueue_outbox(
            payload=request,
            target_hub="https://hub.local",
        )
        replay_id = await service.enqueue_outbox(
            payload=request,
            target_hub="https://hub.local",
        )

        assert replay_id == first_id
        outbox_count = await db.fetchone("SELECT COUNT(*) AS count FROM relay_outbox")
        assert outbox_count["count"] == 1

        # A different payload on a still-pending row supersedes it (the queued
        # event was never delivered — replace with the latest instead of 409ing).
        superseded = request.model_copy(update={"payload_hash": "sha256:changed"})
        superseded_id = await service.enqueue_outbox(
            payload=superseded,
            target_hub="https://hub.local",
        )
        assert superseded_id == first_id
        row = await db.fetchone(
            "SELECT payload_hash FROM relay_outbox WHERE id = ?", (first_id,)
        )
        assert row["payload_hash"] == "sha256:changed"

        secret = _request(
            version=2,
            payload_hash="sha256:secret",
            content="Do not enqueue api_key=sk-ant-secretsecretsecret",
        )
        with pytest.raises(RelaySecretBlocked):
            await service.enqueue_outbox(
                payload=secret,
                target_hub="https://hub.local",
            )

        outbox_count = await db.fetchone("SELECT COUNT(*) AS count FROM relay_outbox")
        assert outbox_count["count"] == 1


@pytest.mark.asyncio
async def test_enqueue_outbox_force_requeues_existing_terminal_row():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()

        request = _request()
        outbox_id = await service.enqueue_outbox(
            payload=request,
            target_hub="https://hub.local",
        )
        claimed = await service.claim_outbox("outbox-worker", lease_seconds=30)
        assert claimed is not None
        await service.mark_outbox_sent(claimed.id)

        replay_id = await service.enqueue_outbox(
            payload=request,
            target_hub="https://hub.local",
            force=True,
        )

        outbox = await db.fetchone(
            """
            SELECT status, attempts, locked_by, locked_at, last_error
            FROM relay_outbox
            WHERE id = ?
            """,
            (outbox_id,),
        )
        assert replay_id == outbox_id
        assert outbox["status"] == "pending"
        assert outbox["attempts"] == 0
        assert outbox["locked_by"] is None
        assert outbox["locked_at"] is None
        assert outbox["last_error"] is None


@pytest.mark.asyncio
async def test_enqueue_outbox_different_payload_on_delivered_row_conflicts():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.enqueue_outbox(payload=_request(), target_hub="https://hub.local")
        claimed = await service.claim_outbox("outbox-worker", lease_seconds=30)
        await service.mark_outbox_sent(claimed.id)

        # Already delivered → a different payload for the same key is a real
        # conflict (only still-pending rows are superseded).
        collision = _request().model_copy(update={"payload_hash": "sha256:changed"})
        with pytest.raises(RelayIdempotencyConflict):
            await service.enqueue_outbox(
                payload=collision, target_hub="https://hub.local"
            )


@pytest.mark.asyncio
async def test_project_share_skips_conflicting_memory_without_aborting(monkeypatch):
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        for mid in ("m1", "m2"):
            await db.execute(
                """
                INSERT INTO memories (
                    id, content, content_hash, project_id, category, source,
                    embedding, tags, created_at, updated_at, content_bytes
                )
                VALUES (?, ?, ?, 'proj', 'decision', 'test', ?, '[]', ?, ?, ?)
                """,
                (
                    mid,
                    f"content {mid}",
                    f"h-{mid}",
                    b"1",
                    "2026-01-01",
                    "2026-01-01",
                    0,
                ),
            )

        async def _fake_share(memory, **kwargs):
            if str(memory.id) == "m1":
                raise RelayIdempotencyConflict("in-flight row, different payload")
            return f"ob-{memory.id}"

        monkeypatch.setattr(service, "enqueue_memory_share", _fake_share)

        result = await service.enqueue_project_share(
            "proj", source_node_id="node-1", target_hub="https://hub.local"
        )
        # m2 still queued; m1 reported as skipped rather than 409ing the batch.
        assert result.queued_count == 1
        assert [s["memory_id"] for s in result.skipped] == ["m1"]


@pytest.mark.asyncio
async def test_enqueue_memory_share_builds_outbox_payload_from_memory():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        memory = Memory(
            id="memory-1",
            content="A relay decision memory with enough useful project detail.",
            content_hash="hash-v1",
            project_id="relay",
            category="decision",
            source="test",
            embedding=b"123",
            tags='["relay", "share"]',
            created_at="2026-06-25T00:00:00Z",
            updated_at="2026-06-25T00:01:00Z",
        )

        outbox_id = await service.enqueue_memory_share(
            memory,
            source_node_id="node-1",
            source_version=7,
            target_hub="https://hub.local",
        )

        outbox = await db.fetchone(
            "SELECT * FROM relay_outbox WHERE id = ?", (outbox_id,)
        )
        payload = outbox["payload_json"]
        assert outbox["idempotency_key"] == "node-1:memory-1:v7:update"
        assert '"source_memory_id": "memory-1"' in payload
        assert '"source_project_key": "relay"' in payload
        assert '"kind": "decision"' in payload
        assert '"relay"' in payload


@pytest.mark.asyncio
async def test_enqueue_memory_share_auto_derives_version_when_omitted():
    """Manual share (source_version omitted) must derive a version from the
    memory's updated_at, same as auto-share — matching _auto_share_version
    exactly, not the old sticky relay.default_source_version config."""
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        memory = Memory(
            id="memory-1",
            content="A relay decision memory.",
            content_hash="hash-v1",
            project_id="relay",
            category="decision",
            source="test",
            embedding=b"123",
            updated_at="2026-06-25T00:01:00Z",
        )

        outbox_id = await service.enqueue_memory_share(
            memory,
            source_node_id="node-1",
            target_hub="https://hub.local",
        )

        outbox = await db.fetchone(
            "SELECT * FROM relay_outbox WHERE id = ?", (outbox_id,)
        )
        expected_version = RelayService._auto_share_version(memory)
        assert (
            outbox["idempotency_key"] == f"node-1:memory-1:v{expected_version}:update"
        )


@pytest.mark.asyncio
async def test_reshare_after_content_edit_does_not_collide():
    """The exact bug scenario: share a memory, edit its content locally
    (e.g. via 'improve with AI'), share again. With auto-derived
    (updated_at-based) versions, the second share gets a fresh
    idempotency_key instead of reusing the first one with a different
    payload hash — which used to raise RelayIdempotencyConflict on ingest,
    since the old default source_version was a sticky static config value
    that never changed between shares."""
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()

        first = Memory(
            id="memory-1",
            content="Original content before enrichment.",
            content_hash="hash-v1",
            project_id="relay",
            category="decision",
            source="test",
            embedding=b"123",
            updated_at="2026-06-25T00:01:00Z",
        )
        first_outbox_id = await service.enqueue_memory_share(
            first, source_node_id="node-1", target_hub="https://hub.local"
        )

        edited = Memory(
            id="memory-1",
            content="Edited content after enrichment ran.",
            content_hash="hash-v2",
            project_id="relay",
            category="decision",
            source="test",
            embedding=b"123",
            updated_at="2026-06-25T00:05:00Z",  # content changed later
        )
        second_outbox_id = await service.enqueue_memory_share(
            edited, source_node_id="node-1", target_hub="https://hub.local"
        )

        first_row = await db.fetchone(
            "SELECT idempotency_key FROM relay_outbox WHERE id = ?",
            (first_outbox_id,),
        )
        second_row = await db.fetchone(
            "SELECT idempotency_key FROM relay_outbox WHERE id = ?",
            (second_outbox_id,),
        )
        assert first_row["idempotency_key"] != second_row["idempotency_key"]


@pytest.mark.asyncio
async def test_enqueue_memory_share_carries_local_enrichment_to_hub():
    """The dashboard 'Enrich' button's title/abstract (EnrichmentStore,
    separate from Memory.content) must ride along through share -> ingest and
    land in the hub's OWN EnrichmentStore, keyed by the MATERIALIZED memory id
    (relay:<current_id>) — that's what the memory-detail page's 'AI
    enrichment' box actually reads, not relay_item_enrichment."""
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="relay-token",
            user_id="user-1",
            source_node_id="sender-node",
            display_name="Sender",
        )

        memory = Memory(
            id="memory-1",
            content="Original content.",
            content_hash="hash-v1",
            project_id="relay",
            category="decision",
            source="test",
            embedding=b"123",
            updated_at="2026-06-25T00:01:00Z",
        )
        await EnrichmentStore(db).upsert(
            memory_id="memory-1",
            title="A generated title",
            abstract="A generated abstract.",
            tags=["decision"],
            display_kind="decision",
            model="test-model",
        )

        await service.enqueue_memory_share(
            memory, source_node_id="sender-node", target_hub="https://hub.local"
        )
        job = await service.claim_outbox("w1", lease_seconds=30)
        assert job.payload.title == "A generated title"
        assert job.payload.abstract == "A generated abstract."

        result = await service.ingest("relay-token", job.payload)
        assert result.applied_to_current is True

        materialized_id = f"relay:{result.current_memory_id}"
        enrichment = await EnrichmentStore(db).get(materialized_id)
        assert enrichment is not None
        assert enrichment["title"] == "A generated title"
        assert enrichment["abstract"] == "A generated abstract."


@pytest.mark.asyncio
async def test_reshare_after_enrich_only_does_not_collide():
    """Enriching without touching content doesn't bump memory.updated_at, so
    the version must still advance from EnrichmentStore's own timestamp —
    otherwise re-sharing after Enrich reuses the same idempotency_key with a
    now-different payload hash (title/abstract included) and collides,
    exactly like the content-edit case."""
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()

        memory = Memory(
            id="memory-1",
            content="Same content the whole time.",
            content_hash="hash-v1",
            project_id="relay",
            category="decision",
            source="test",
            embedding=b"123",
            updated_at="2026-06-25T00:01:00Z",
        )
        first_outbox_id = await service.enqueue_memory_share(
            memory, source_node_id="node-1", target_hub="https://hub.local"
        )

        await EnrichmentStore(db).upsert(
            memory_id="memory-1", title="New title", abstract="New abstract."
        )
        second_outbox_id = await service.enqueue_memory_share(
            memory, source_node_id="node-1", target_hub="https://hub.local"
        )

        first_row = await db.fetchone(
            "SELECT idempotency_key FROM relay_outbox WHERE id = ?",
            (first_outbox_id,),
        )
        second_row = await db.fetchone(
            "SELECT idempotency_key FROM relay_outbox WHERE id = ?",
            (second_outbox_id,),
        )
        assert first_row["idempotency_key"] != second_row["idempotency_key"]


@pytest.mark.asyncio
async def test_enqueue_memory_share_blocks_type_gate_and_secret_before_outbox():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        task_memory = Memory(
            id="memory-task",
            content="A task memory should not be shared by the default type gate.",
            content_hash="task-hash",
            project_id="relay",
            category="task",
            source="test",
            embedding=b"123",
        )
        secret_memory = Memory(
            id="memory-secret",
            content="A decision with api_key=sk-ant-secretsecretsecret should block.",
            content_hash="secret-hash",
            project_id="relay",
            category="decision",
            source="test",
            embedding=b"123",
        )

        with pytest.raises(RelayTypeGateBlocked):
            await service.enqueue_memory_share(
                task_memory,
                source_node_id="node-1",
                source_version=1,
                target_hub="https://hub.local",
            )
        with pytest.raises(RelaySecretBlocked):
            await service.enqueue_memory_share(
                secret_memory,
                source_node_id="node-1",
                source_version=1,
                target_hub="https://hub.local",
            )

        outbox_count = await db.fetchone("SELECT COUNT(*) AS count FROM relay_outbox")
        assert outbox_count["count"] == 0


@pytest.mark.asyncio
async def test_enqueue_memory_share_fail_open_for_unknown_category():
    """A category outside the old hardcoded allowlist (e.g. one introduced
    later) must share by default — only 'task' is structurally denylisted."""
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        memory = Memory(
            id="memory-future-cat",
            content="Something in a category nobody hardcoded a checkbox for.",
            content_hash="future-hash",
            project_id="relay",
            category="spec",
            source="test",
            embedding=b"123",
        )

        outbox_id = await service.enqueue_memory_share(
            memory,
            source_node_id="node-1",
            source_version=1,
            target_hub="https://hub.local",
        )
        assert outbox_id


@pytest.mark.asyncio
async def test_enqueue_memory_share_git_history_still_shareable_by_default():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        memory = Memory(
            id="memory-git-history",
            content="git commit abc123 touched relay.py",
            content_hash="git-hash",
            project_id="relay",
            category="git-history",
            source="test",
            embedding=b"123",
        )

        outbox_id = await service.enqueue_memory_share(
            memory,
            source_node_id="node-1",
            source_version=1,
            target_hub="https://hub.local",
        )
        assert outbox_id


@pytest.mark.asyncio
async def test_enqueue_memory_share_blocked_category_soft_block():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.update_admin_settings(
            RelaySettingsUpdateRequest(blocked_categories=["idea"])
        )
        memory = Memory(
            id="memory-idea",
            content="An idea the user chose not to share from this node.",
            content_hash="idea-hash",
            project_id="relay",
            category="idea",
            source="test",
            embedding=b"123",
        )

        with pytest.raises(RelayTypeGateBlocked, match="Sharing Policy"):
            await service.enqueue_memory_share(
                memory,
                source_node_id="node-1",
                source_version=1,
                target_hub="https://hub.local",
            )

        # Attempting to soft-block 'task' via the policy request is a no-op —
        # it's already hard-denylisted and not a user-facing toggle.
        await service.update_admin_settings(
            RelaySettingsUpdateRequest(blocked_categories=["task", "bug"])
        )
        blocked = await service._get_blocked_categories()
        assert blocked == {"bug"}


@pytest.mark.asyncio
async def test_list_category_policies_reflects_live_categories_and_blocks():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        for category in ("decision", "task", "spec"):
            await db.execute(
                """
                INSERT INTO memories (
                    id, content, content_hash, project_id, category, source,
                    client, embedding, tags, created_at, updated_at, content_bytes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"mem-{category}",
                    f"content for {category}",
                    f"hash-{category}",
                    "relay",
                    category,
                    "test",
                    None,
                    b"123",
                    "[]",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                    0,
                ),
            )
        await service.update_admin_settings(
            RelaySettingsUpdateRequest(blocked_categories=["spec"])
        )

        policies = await service.list_category_policies()
        by_category = {p.category: p.shared for p in policies}

        # 'task' never appears — it's denylisted, not a policy choice.
        assert "task" not in by_category
        assert by_category["decision"] is True
        assert by_category["spec"] is False


@pytest.mark.asyncio
async def test_outbox_claim_and_failure_moves_to_dead_letter_at_max_attempts():
    async with _temp_db() as db:
        service = RelayService(db, max_attempts=1)
        await service.ensure_schema()
        await service.enqueue_outbox(
            payload=_request(),
            target_hub="https://hub.local",
        )

        claimed = await service.claim_outbox("outbox-worker", lease_seconds=30)
        assert claimed is not None
        assert claimed.status == "processing"
        assert claimed.locked_by == "outbox-worker"
        assert claimed.payload.source_memory_id == "memory-1"

        await service.mark_outbox_failed(claimed.id, "hub unavailable")

        outbox = await db.fetchone(
            """
            SELECT status, attempts, locked_by, locked_at, last_error
            FROM relay_outbox
            WHERE id = ?
            """,
            (claimed.id,),
        )
        assert outbox["status"] == "dead_letter"
        assert outbox["attempts"] == 1
        assert outbox["locked_by"] is None
        assert outbox["locked_at"] is None
        assert "hub unavailable" in outbox["last_error"]


@pytest.mark.asyncio
async def test_retry_dead_letters_requeues_outbox_and_clears_failure_state():
    async with _temp_db() as db:
        service = RelayService(db, max_attempts=1)
        await service.ensure_schema()
        await service.enqueue_outbox(
            payload=_request(),
            target_hub="https://hub.local",
        )
        claimed = await service.claim_outbox("outbox-worker", lease_seconds=30)
        assert claimed is not None
        await service.mark_outbox_failed(claimed.id, "hub unavailable")

        result = await service.retry_dead_letters(queue="outbox", job_id=claimed.id)

        outbox = await db.fetchone(
            """
            SELECT status, attempts, next_attempt_at, locked_by, locked_at, last_error
            FROM relay_outbox
            WHERE id = ?
            """,
            (claimed.id,),
        )
        assert result.retried == 1
        assert result.outbox == 1
        assert result.item == 0
        assert result.aggregate == 0
        assert outbox["status"] == "pending"
        assert outbox["attempts"] == 0
        assert outbox["next_attempt_at"] <= time.time() + 1
        assert outbox["locked_by"] is None
        assert outbox["locked_at"] is None
        assert outbox["last_error"] is None


@pytest.mark.asyncio
async def test_outbox_failure_uses_configured_backoff_cap():
    async with _temp_db() as db:
        service = RelayService(db, max_attempts=3, backoff_max_seconds=0.5)
        await service.ensure_schema()
        await service.enqueue_outbox(
            payload=_request(),
            target_hub="https://hub.local",
        )

        claimed = await service.claim_outbox("outbox-worker", lease_seconds=30)
        assert claimed is not None
        before = time.time()

        await service.mark_outbox_failed(claimed.id, "hub unavailable")

        outbox = await db.fetchone(
            """
            SELECT status, next_attempt_at
            FROM relay_outbox
            WHERE id = ?
            """,
            (claimed.id,),
        )
        assert outbox["status"] == "pending"
        assert before <= outbox["next_attempt_at"] <= before + 0.75


@pytest.mark.asyncio
async def test_queue_claim_uses_processing_lease_and_can_reclaim_expired_jobs():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        await service.ingest("relay-token", _request())

        first = await service.claim_queue_item("worker-1", lease_seconds=30)
        second = await service.claim_queue_item("worker-2", lease_seconds=30)

        assert first is not None
        assert first.status == "processing"
        assert first.locked_by == "worker-1"
        assert second is None

        await db.execute(
            "UPDATE relay_queue_item SET locked_at = 0 WHERE id = ?",
            (first.id,),
        )
        reclaimed = await service.claim_queue_item("worker-2", lease_seconds=1)

        assert reclaimed is not None
        assert reclaimed.id == first.id
        assert reclaimed.locked_by == "worker-2"


class _FakeEmbeddingService:
    model_name = "fake-embedding"
    dimension = 3

    async def aembed(self, text: str):
        if "other vector" in text:
            return [0.0, 1.0, 0.0]
        return [0.1, 0.2, 0.3]


class _VectorSearchEmbeddingService:
    model_name = "fake-embedding"
    dimension = 3

    async def aembed(self, text: str):
        if text == "target vector":
            return [1.0, 0.0, 0.0]
        if "other vector" in text:
            return [0.0, 1.0, 0.0]
        return [1.0, 0.0, 0.0]


class _FakeTextEnricher:
    model = "fake-llm"
    model_version = "fake-llm-v1"

    async def enrich(self, content: str):
        return {
            "title": "SQLite relay queue",
            "abstract": "Relay uses a durable SQLite queue for post-processing.",
            "tags": ["relay", "queue"],
            "display_kind": "decision",
            "problem": "Postgres looked required for background work.",
            "resolution": "Use a SQLite queue with short claims.",
            "lesson": "Keep LLM work outside write transactions.",
            "confidence": 0.9,
        }


class _FakeOutboxSender:
    def __init__(self):
        self.calls = []

    async def send_ingest(self, *, target_hub, bearer_token, payload):
        self.calls.append((target_hub, bearer_token, payload))
        return {
            "accepted": True,
            "event_id": "hub-event",
            "current_memory_id": "hub-current",
        }


class _FailingOutboxSender:
    async def send_ingest(self, *, target_hub, bearer_token, payload):
        raise RuntimeError("hub unavailable")


class _FakeDigestGenerator:
    model = "fake-llm"
    model_version = "fake-llm-v1"

    def __init__(self):
        self.items_seen = None

    async def generate(self, *, team_project_id, items):
        self.items_seen = items
        return {
            "rollup": {"decisions": [items[0]["current_memory_id"]]},
            "contributors": ["node-1"],
            "recent_activity": [items[0]["title"]],
            "narrative": f"{team_project_id} digest cites {items[0]['current_memory_id']}",
            "source_memory_ids": [items[0]["current_memory_id"]],
        }


class _FailingDigestGenerator:
    model = "fake-llm"
    model_version = "fake-llm-v1"

    async def generate(self, *, team_project_id, items):
        raise RuntimeError("temporary digest failure")


class _FakeHTTPResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeAsyncHTTPClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def post(self, url, *, headers, json, timeout):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self.response


class _FailingTextEnricher:
    model = "fake-llm"
    model_version = "fake-llm-v1"

    async def enrich(self, content: str):
        raise RuntimeError("temporary LLM failure")


@pytest.mark.asyncio
async def test_process_next_item_writes_enrichment_and_coalesces_aggregate_queue():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        ingest = await service.ingest("relay-token", _request())
        memory_id = f"relay:{ingest.current_memory_id}"
        before_memory = await db.fetchone(
            "SELECT embedding FROM memories WHERE id = ?",
            (memory_id,),
        )

        result = await service.process_next_item(
            worker_id="worker-1",
            embedding_service=_FakeEmbeddingService(),
            text_enricher=_FakeTextEnricher(),
            prompt_version="test-prompt-v1",
        )

        assert result.processed is True
        assert result.error is None

        enrichment_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM relay_item_enrichment"
        )
        aggregate_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM relay_queue_aggregate"
        )
        item_status = await db.fetchone("SELECT status FROM relay_queue_item")
        after_memory = await db.fetchone(
            "SELECT embedding FROM memories WHERE id = ?",
            (memory_id,),
        )

        assert enrichment_count["count"] == 1
        assert aggregate_count["count"] == 1
        assert item_status["status"] == "done"
        assert before_memory["embedding"] != after_memory["embedding"]


class _MustNotEnrich:
    """Enricher stub that fails the test if the hub burns an LLM call."""

    model = "fake-llm"
    model_version = "fake-llm-v1"

    async def enrich(self, content: str):
        raise AssertionError("hub must not re-enrich sender-enriched memories")


@pytest.mark.asyncio
async def test_process_next_item_skips_llm_when_sender_provided_enrichment():
    """A share that carries the sender's local enrichment must not trigger a
    second LLM pass on the hub — the item worker copies the sender's result
    into relay_item_enrichment and still computes the embedding."""
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        request = _request()
        request.title = "Sender title"
        request.abstract = "Sender abstract from the personal node."
        request.display_kind = "decision"
        ingest = await service.ingest("relay-token", request)
        memory_id = f"relay:{ingest.current_memory_id}"
        before_memory = await db.fetchone(
            "SELECT embedding FROM memories WHERE id = ?", (memory_id,)
        )

        result = await service.process_next_item(
            worker_id="worker-1",
            embedding_service=_FakeEmbeddingService(),
            text_enricher=_MustNotEnrich(),
            prompt_version="test-prompt-v1",
        )

        assert result.processed is True
        assert result.error is None
        row = await db.fetchone(
            "SELECT title, abstract, display_kind, model, model_version "
            "FROM relay_item_enrichment"
        )
        assert row["title"] == "Sender title"
        assert row["abstract"] == "Sender abstract from the personal node."
        assert row["model"] == "relay:sender-provided"
        assert row["model_version"] == "relay:sender-provided"
        # Embedding still runs — it never ships in the payload.
        after_memory = await db.fetchone(
            "SELECT embedding FROM memories WHERE id = ?", (memory_id,)
        )
        assert before_memory["embedding"] != after_memory["embedding"]
        item_status = await db.fetchone("SELECT status FROM relay_queue_item")
        assert item_status["status"] == "done"


@pytest.mark.asyncio
async def test_process_next_item_failure_requeues_without_losing_job():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        await service.ingest("relay-token", _request())

        result = await service.process_next_item(
            worker_id="worker-1",
            embedding_service=_FakeEmbeddingService(),
            text_enricher=_FailingTextEnricher(),
            prompt_version="test-prompt-v1",
        )

        queue_row = await db.fetchone("""
            SELECT status, attempts, locked_by, locked_at, last_error, next_attempt_at
            FROM relay_queue_item
            """)
        enrichment_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM relay_item_enrichment"
        )

        assert result.processed is False
        assert "temporary LLM failure" in result.error
        assert queue_row["status"] == "pending"
        assert queue_row["attempts"] == 1
        assert queue_row["locked_by"] is None
        assert queue_row["locked_at"] is None
        assert "temporary LLM failure" in queue_row["last_error"]
        assert queue_row["next_attempt_at"] > 0
        assert enrichment_count["count"] == 0


@pytest.mark.asyncio
async def test_drain_next_outbox_sends_payload_and_marks_sent():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.enqueue_outbox(
            payload=_request(),
            target_hub="https://hub.local",
        )
        sender = _FakeOutboxSender()

        result = await service.drain_next_outbox(
            worker_id="outbox-worker",
            sender=sender,
            bearer_token="hub-token",
        )

        outbox = await db.fetchone("SELECT status FROM relay_outbox")
        assert result.processed is True
        assert result.error is None
        assert outbox["status"] == "sent"
        assert len(sender.calls) == 1
        target_hub, bearer_token, payload = sender.calls[0]
        assert target_hub == "https://hub.local"
        assert bearer_token == "hub-token"
        assert payload.source_memory_id == "memory-1"


@pytest.mark.asyncio
async def test_drain_next_outbox_failure_requeues_without_losing_payload(caplog):
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.enqueue_outbox(
            payload=_request(),
            target_hub="https://hub.local",
        )

        with caplog.at_level(logging.WARNING, logger="app.core.services.relay"):
            result = await service.drain_next_outbox(
                worker_id="outbox-worker",
                sender=_FailingOutboxSender(),
                bearer_token="hub-token",
            )

        outbox = await db.fetchone("""
            SELECT status, attempts, locked_by, locked_at, last_error
            FROM relay_outbox
            """)
        assert result.processed is False
        assert "hub unavailable" in result.error
        assert any(
            "Relay outbox delivery failed" in record.message and record.exc_info is None
            for record in caplog.records
        )
        assert outbox["status"] == "pending"
        assert outbox["attempts"] == 1
        assert outbox["locked_by"] is None
        assert outbox["locked_at"] is None
        assert "hub unavailable" in outbox["last_error"]


@pytest.mark.asyncio
async def test_process_next_aggregate_writes_grounded_project_digest():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        ingest = await service.ingest("relay-token", _request())
        item_result = await service.process_next_item(
            worker_id="item-worker",
            embedding_service=_FakeEmbeddingService(),
            text_enricher=_FakeTextEnricher(),
            prompt_version="item-prompt-v1",
        )
        assert item_result.processed is True

        generator = _FakeDigestGenerator()
        result = await service.process_next_aggregate(
            worker_id="aggregate-worker",
            digest_generator=generator,
            prompt_version="digest-prompt-v1",
        )

        digest = await db.fetchone("SELECT * FROM relay_project_digest")
        aggregate_queue = await db.fetchone("SELECT status FROM relay_queue_aggregate")

        assert result.processed is True
        assert result.error is None
        assert digest["team_project_id"] == "node-1:relay"
        assert ingest.current_memory_id in digest["source_memory_ids_json"]
        assert ingest.current_memory_id in digest["narrative"]
        assert aggregate_queue["status"] == "done"
        assert generator.items_seen[0]["current_memory_id"] == ingest.current_memory_id


@pytest.mark.asyncio
async def test_process_next_aggregate_failure_requeues_without_digest():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        await service.ingest("relay-token", _request())
        item_result = await service.process_next_item(
            worker_id="item-worker",
            embedding_service=_FakeEmbeddingService(),
            text_enricher=_FakeTextEnricher(),
            prompt_version="item-prompt-v1",
        )
        assert item_result.processed is True

        result = await service.process_next_aggregate(
            worker_id="aggregate-worker",
            digest_generator=_FailingDigestGenerator(),
            prompt_version="digest-prompt-v1",
        )

        aggregate_queue = await db.fetchone("""
            SELECT status, attempts, locked_by, locked_at, last_error
            FROM relay_queue_aggregate
            """)
        digest_count = await db.fetchone(
            "SELECT COUNT(*) AS count FROM relay_project_digest"
        )

        assert result.processed is False
        assert "temporary digest failure" in result.error
        assert aggregate_queue["status"] == "pending"
        assert aggregate_queue["attempts"] == 1
        assert aggregate_queue["locked_by"] is None
        assert aggregate_queue["locked_at"] is None
        assert "temporary digest failure" in aggregate_queue["last_error"]
        assert digest_count["count"] == 0


@pytest.mark.asyncio
async def test_search_uses_sqlite_vec_relay_index_when_available():
    async with _temp_db() as db:
        if not db._connection.is_vec_available:
            pytest.skip("sqlite-vec is not available in this environment")

        service = await _service_with_identity(db)
        target = _request(
            memory_id="memory-target",
            payload_hash="sha256:target",
            content="Relay target vector memory.",
        )
        other = _request(
            memory_id="memory-other",
            payload_hash="sha256:other",
            content="Relay other vector memory.",
        )
        await service.ingest("relay-token", target)
        await service.ingest("relay-token", other)
        embedding_service = _VectorSearchEmbeddingService()

        first = await service.process_next_item(
            worker_id="item-worker",
            embedding_service=embedding_service,
            text_enricher=_FakeTextEnricher(),
            prompt_version="item-prompt-v1",
        )
        second = await service.process_next_item(
            worker_id="item-worker",
            embedding_service=embedding_service,
            text_enricher=_FakeTextEnricher(),
            prompt_version="item-prompt-v1",
        )
        assert first.processed is True
        assert second.processed is True

        results = await service.search(
            query="target vector",
            embedding_service=embedding_service,
            limit=2,
        )

        assert results.results[0].source_memory_id == "memory-target"
        assert results.metadata["search_mode"] == "vector"


@pytest.mark.asyncio
async def test_relay_http_client_posts_ingest_with_bearer_token():
    response = _FakeHTTPResponse(
        200,
        {
            "accepted": True,
            "event_id": "hub-event",
            "current_memory_id": "hub-current",
            "replayed": False,
            "applied_to_current": True,
            "queued_item": True,
        },
    )
    http_client = _FakeAsyncHTTPClient(response)
    client = RelayHTTPClient(http_client=http_client)

    result = await client.send_ingest(
        target_hub="https://hub.local/",
        bearer_token="hub-token",
        payload=_request(),
    )

    assert result.event_id == "hub-event"
    assert http_client.calls[0]["url"] == "https://hub.local/api/relay/v1/ingest"
    assert http_client.calls[0]["headers"]["Authorization"] == "Bearer hub-token"
    assert http_client.calls[0]["json"]["source_memory_id"] == "memory-1"


@pytest.mark.asyncio
async def test_relay_http_client_maps_409_to_delivery_conflict():
    client = RelayHTTPClient(
        http_client=_FakeAsyncHTTPClient(
            _FakeHTTPResponse(409, {"detail": "payload collision"})
        )
    )

    with pytest.raises(RelayDeliveryConflict):
        await client.send_ingest(
            target_hub="https://hub.local",
            bearer_token="hub-token",
            payload=_request(),
        )


@pytest.mark.asyncio
async def test_relay_http_client_maps_5xx_to_retryable_error():
    client = RelayHTTPClient(
        http_client=_FakeAsyncHTTPClient(_FakeHTTPResponse(503, text="down"))
    )

    with pytest.raises(RuntimeError):
        await client.send_ingest(
            target_hub="https://hub.local",
            bearer_token="hub-token",
            payload=_request(),
        )


# ── Auto-share (continuous project sharing) ─────────────────────────────────


async def _enable_auto_share(
    service: RelayService,
    project_id: str,
    *,
    enabled: bool = True,
    include_relay_origin: bool = False,
    hub: str = "https://hub.local",
    node: str = "node-1",
) -> None:
    await service.ensure_schema()
    await service.db.execute(
        """
        INSERT INTO relay_auto_share_subscription
            (project_id, enabled, include_relay_origin, target_hub,
             source_node_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id) DO UPDATE SET
            enabled = excluded.enabled,
            include_relay_origin = excluded.include_relay_origin
        """,
        (
            project_id,
            1 if enabled else 0,
            1 if include_relay_origin else 0,
            hub,
            node,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )


def _shareable_memory(**overrides) -> Memory:
    base = dict(
        content="Relay auto-share content using a SQLite queue.",
        source="cli",
        category="decision",
        project_id="proj-1",
        embedding=b"\x00" * 12,
        updated_at="2026-02-01T00:00:00Z",
    )
    base.update(overrides)
    return Memory(**base)


async def _outbox_count(db: Database) -> int:
    row = await db.fetchone("SELECT COUNT(*) AS count FROM relay_outbox")
    return int(row["count"]) if row else 0


@pytest.mark.asyncio
async def test_auto_share_enqueues_for_subscribed_project():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        await _enable_auto_share(service, "proj-1")

        outbox_id = await service.auto_share_on_write(
            _shareable_memory(id="mem-1"), event_type="create"
        )

        assert outbox_id is not None
        assert await _outbox_count(db) == 1
        row = await db.fetchone("SELECT idempotency_key FROM relay_outbox LIMIT 1")
        # version is derived from updated_at epoch → distinct per write
        assert ":v" in row["idempotency_key"]
        assert row["idempotency_key"].endswith(":create")


@pytest.mark.asyncio
async def test_auto_share_excludes_relay_origin_memory():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        await _enable_auto_share(service, "proj-1", include_relay_origin=False)

        result = await service.auto_share_on_write(
            _shareable_memory(id="mem-2", source="relay"), event_type="create"
        )

        assert result is None
        assert await _outbox_count(db) == 0


@pytest.mark.asyncio
async def test_auto_share_skips_disabled_subscription():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        await _enable_auto_share(service, "proj-1", enabled=False)

        result = await service.auto_share_on_write(
            _shareable_memory(id="mem-3"), event_type="create"
        )

        assert result is None
        assert await _outbox_count(db) == 0


@pytest.mark.asyncio
async def test_auto_share_skips_non_shareable_kind_without_raising():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        await _enable_auto_share(service, "proj-1")

        # "task" is structurally denylisted → type gate skip, no raise.
        result = await service.auto_share_on_write(
            _shareable_memory(id="mem-4", category="task"), event_type="create"
        )

        assert result is None
        assert await _outbox_count(db) == 0


@pytest.mark.asyncio
async def test_auto_share_noop_without_subscription():
    async with _temp_db() as db:
        service = await _service_with_identity(db)

        result = await service.auto_share_on_write(
            _shareable_memory(id="mem-5"), event_type="create"
        )

        assert result is None
        assert await _outbox_count(db) == 0


@pytest.mark.asyncio
async def test_auto_share_create_then_update_emit_distinct_events():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        await _enable_auto_share(service, "proj-1")

        await service.auto_share_on_write(
            _shareable_memory(id="mem-6", updated_at="2026-02-01T00:00:00Z"),
            event_type="create",
        )
        await service.auto_share_on_write(
            _shareable_memory(id="mem-6", updated_at="2026-02-01T00:05:00Z"),
            event_type="update",
        )

        # Distinct versions (updated_at epoch) → two separate outbox rows.
        assert await _outbox_count(db) == 2


@pytest.mark.asyncio
async def test_admin_overview_includes_item_and_aggregate_dead_letters():
    """get_admin_overview must surface dead-lettered item/aggregate queue jobs
    (with ref_id/raw_event_id), not just the outbox queue."""
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        await db.execute(
            """
            INSERT INTO relay_queue_item
                (id, ref_id, raw_event_id, status, attempts, next_attempt_at,
                 last_error, created_at, updated_at)
            VALUES (?, ?, ?, 'dead_letter', 3, 0, ?, ?, ?)
            """,
            (
                "item-1",
                "cur-1",
                "raw-1",
                "boom",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        await db.execute(
            """
            INSERT INTO relay_queue_aggregate
                (id, ref_id, raw_event_id, coalesce_key, status, attempts,
                 next_attempt_at, last_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'dead_letter', 3, 0, ?, ?, ?)
            """,
            (
                "agg-1",
                "cur-2",
                "raw-2",
                "ck-1",
                "boom2",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )

        overview = await service.get_admin_overview()
        by_queue = {d.queue: d for d in overview.dead_letters}

        assert "item" in by_queue
        assert "aggregate" in by_queue
        assert by_queue["item"].ref_id == "cur-1"
        assert by_queue["item"].raw_event_id == "raw-1"
        assert by_queue["item"].idempotency_key is None
        assert by_queue["aggregate"].ref_id == "cur-2"
        assert by_queue["aggregate"].raw_event_id == "raw-2"


class _AutoShareFakeEmbedding:
    model_name = "fake-embedding"
    dimension = 3

    async def aembed(self, text: str):
        return [0.1, 0.2, 0.3]

    def to_bytes(self, embedding):
        import struct

        return struct.pack(f"{len(embedding)}f", *embedding)


@pytest.mark.asyncio
async def test_auto_share_hook_fires_on_memory_service_create():
    """End-to-end: a real MemoryService.create on a subscribed project enqueues
    a relay outbox event via the post-write hook."""
    from app.core.services.memory import MemoryService

    async with _temp_db() as db:
        service = await _service_with_identity(db)
        await _enable_auto_share(service, "proj-x")

        memory_service = MemoryService(db, _AutoShareFakeEmbedding())
        await memory_service.create(
            content=(
                "A shareable decision memory for the relay auto-share hook. "
                "We decided to enqueue team-relevant decisions automatically "
                "when a project opts into continuous sharing from the dashboard."
            ),
            project_id="proj-x",
            category="decision",
            source="cli",
        )

        assert await _outbox_count(db) == 1


@pytest.mark.asyncio
async def test_auto_share_hook_fires_on_create_with_embedding():
    """The batch/MCP path (add_with_embedding → create_with_embedding) must also
    enqueue auto-share for a subscribed project, not just the plain create()."""
    from app.core.services.memory import MemoryService

    async with _temp_db() as db:
        service = await _service_with_identity(db)
        await _enable_auto_share(service, "proj-batch")

        memory_service = MemoryService(db, _AutoShareFakeEmbedding())
        await memory_service.add_with_embedding(
            content=(
                "A batch-created shareable decision that must auto-share to the "
                "team relay through the pre-computed embedding path as well."
            ),
            embedding=[0.1, 0.2, 0.3],
            project_id="proj-batch",
            category="decision",
            source="mcp_batch",
        )

        assert await _outbox_count(db) == 1


@pytest.mark.asyncio
async def test_auto_share_hook_noop_for_unsubscribed_project_create():
    from app.core.services.memory import MemoryService

    async with _temp_db() as db:
        await _service_with_identity(db)

        memory_service = MemoryService(db, _AutoShareFakeEmbedding())
        await memory_service.create(
            content=(
                "A decision memory in a project that has not enabled relay "
                "auto-share. This write must not enqueue any relay outbox event "
                "because no subscription exists for the project at all here."
            ),
            project_id="proj-none",
            category="decision",
            source="cli",
        )

        assert await _outbox_count(db) == 0


def test_relay_settings_update_request_validates_llm_provider():
    with pytest.raises(ValidationError):
        RelaySettingsUpdateRequest(llm_provider="gemini")
    # case/whitespace normalized
    assert RelaySettingsUpdateRequest(llm_provider="  OpenAI ").llm_provider == "openai"
    # None and empty pass through as unset (no change)
    assert RelaySettingsUpdateRequest(llm_provider=None).llm_provider is None
    assert RelaySettingsUpdateRequest(llm_provider="").llm_provider is None


@pytest.mark.asyncio
async def test_update_admin_settings_persists_and_normalizes_llm_provider():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()

        resp = await service.update_admin_settings(
            RelaySettingsUpdateRequest(
                llm_provider="OpenAI",
                llm_model="gpt-4o",
                llm_base_url="https://api.groq.com/openai/v1",
            )
        )

        assert resp.llm_provider.value == "openai"
        assert resp.llm_model.value == "gpt-4o"
        # persisted under the renamed DB key
        assert await db.get_app_config("relay.llm_provider") == "openai"

        effective = await service.get_effective_config(_RelaySettingsStub())
        assert effective["values"]["llm_provider"] == "openai"
        assert effective["sources"]["llm_provider"] == "db"


class _RelaySettingsStub:
    """Minimal settings object for get_effective_config env fallback."""

    relay_hub_url = ""
    relay_source_node_id = ""
    relay_hub_token = ""
    relay_llm_provider = "anthropic"
    relay_llm_api_key = ""
    relay_llm_model = ""
    relay_llm_base_url = ""
    relay_prompt_version = "relay-v1"


@pytest.mark.asyncio
async def test_search_exclude_source_node_omits_that_nodes_memories():
    async with _temp_db() as db:
        service = await _service_with_identity(db)
        await service.register_identity(
            token="relay-token-2",
            user_id="user-2",
            source_node_id="node-2",
            display_name="Teammate",
            home_domain="local.test",
        )
        mine = _request(
            memory_id="memory-mine",
            payload_hash="sha256:mine",
            content="Relay shared queue design from my node.",
        )
        theirs = RelayIngestRequest(
            idempotency_key="node-2:memory-theirs:v1:create",
            payload_hash="sha256:theirs",
            event_type="create",
            source_memory_id="memory-theirs",
            source_version=1,
            source_project_key="relay",
            kind="decision",
            status="active",
            content="Relay shared queue design from teammate node.",
            tags=["relay"],
            links=[],
        )
        await service.ingest("relay-token", mine)
        await service.ingest("relay-token-2", theirs)

        everyone = await service.search(query="queue design", limit=10)
        assert {r.source_node_id for r in everyone.results} == {"node-1", "node-2"}

        excluded = await service.search(
            query="queue design", limit=10, exclude_source_node="node-1"
        )
        assert [r.source_node_id for r in excluded.results] == ["node-2"]
        assert excluded.results[0].source_memory_id == "memory-theirs"


@pytest.mark.asyncio
async def test_vector_search_exclude_source_node_omits_that_nodes_memories():
    async with _temp_db() as db:
        if not db._connection.is_vec_available:
            pytest.skip("sqlite-vec is not available in this environment")

        service = await _service_with_identity(db)
        await service.register_identity(
            token="relay-token-2",
            user_id="user-2",
            source_node_id="node-2",
            display_name="Teammate",
            home_domain="local.test",
        )
        mine = _request(
            memory_id="memory-mine",
            payload_hash="sha256:mine",
            content="Relay target vector memory.",
        )
        theirs = RelayIngestRequest(
            idempotency_key="node-2:memory-theirs:v1:create",
            payload_hash="sha256:theirs",
            event_type="create",
            source_memory_id="memory-theirs",
            source_version=1,
            source_project_key="relay",
            kind="decision",
            status="active",
            content="Relay target vector memory from teammate.",
            tags=["relay"],
            links=[],
        )
        await service.ingest("relay-token", mine)
        await service.ingest("relay-token-2", theirs)
        embedding_service = _VectorSearchEmbeddingService()
        for _ in range(2):
            processed = await service.process_next_item(
                worker_id="item-worker",
                embedding_service=embedding_service,
                text_enricher=_FakeTextEnricher(),
                prompt_version="item-prompt-v1",
            )
            assert processed.processed is True

        results = await service.search(
            query="target vector",
            embedding_service=embedding_service,
            limit=5,
            exclude_source_node="node-1",
        )

        assert results.metadata["search_mode"] == "vector"
        assert results.results, "expected teammate results to remain"
        assert {r.source_node_id for r in results.results} == {"node-2"}


@pytest.mark.asyncio
async def test_relay_http_client_send_search_posts_bearer_and_parses_response():
    response = _FakeHTTPResponse(
        200,
        {
            "results": [
                {
                    "id": "cur-1",
                    "content": "hub content",
                    "team_project_id": "team-proj",
                    "source_node_id": "node-2",
                    "source_memory_id": "mem-9",
                    "source_version": 1,
                    "kind": "decision",
                    "status": "active",
                    "tags": ["relay"],
                    "title": "Hub title",
                    "abstract": "Hub abstract",
                    "rank": 1,
                    "score": 0.9,
                    "updated_at": "2026-07-01T00:00:00Z",
                }
            ],
            "total": 1,
        },
    )
    http_client = _FakeAsyncHTTPClient(response)
    client = RelayHTTPClient(http_client=http_client)

    from app.core.schemas.relay import RelaySearchRequest

    result = await client.send_search(
        target_hub="https://hub.example.com",
        bearer_token="hub-token",
        payload=RelaySearchRequest(
            query="queue", limit=5, exclude_source_node="node-1"
        ),
        timeout=2.0,
    )

    call = http_client.calls[0]
    assert call["url"] == "https://hub.example.com/api/relay/v1/search"
    assert call["headers"]["Authorization"] == "Bearer hub-token"
    assert call["json"]["exclude_source_node"] == "node-1"
    assert call["timeout"] == 2.0
    assert result.total == 1
    assert result.results[0].source_node_id == "node-2"
    assert result.results[0].updated_at == "2026-07-01T00:00:00Z"


@pytest.mark.asyncio
async def test_vector_search_with_empty_index_falls_back_to_text():
    async with _temp_db() as db:
        if not db._connection.is_vec_available:
            pytest.skip("sqlite-vec is not available in this environment")

        service = await _service_with_identity(db)
        await service.ingest("relay-token", _request())
        # No process_next_item → relay_memory_vec stays empty (fresh hub).
        embedding_service = _VectorSearchEmbeddingService()

        results = await service.search(
            query="sqlite queue",
            embedding_service=embedding_service,
            limit=5,
        )

        assert results.metadata["search_mode"] == "text"
        assert results.results, "text fallback should find the ingested memory"
