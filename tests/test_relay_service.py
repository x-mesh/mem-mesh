"""Relay service regression tests.

These tests pin the PRD v0.2 invariants that are easy to break:
idempotent ingest, append-only raw events, current projection semantics,
secret guard before persistence, and durable SQLite queue claiming.
"""

import os
import tempfile
import logging
import time
from contextlib import asynccontextmanager

import pytest

from app.core.database.base import Database
from app.core.database.models import Memory
from app.core.schemas.relay import RelayIngestRequest
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
        assert materialized["project_id"] == "node-1:relay"
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
        assert materialized["project_id"] == "node-1:relay"
        assert materialized["category"] == "decision"
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

        collision = request.model_copy(update={"payload_hash": "sha256:changed"})
        with pytest.raises(RelayIdempotencyConflict):
            await service.enqueue_outbox(
                payload=collision,
                target_hub="https://hub.local",
            )

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
    model = "fake-sonnet"
    model_version = "fake-sonnet-v1"

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
    model = "fake-sonnet"
    model_version = "fake-sonnet-v1"

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
    model = "fake-sonnet"
    model_version = "fake-sonnet-v1"

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
    model = "fake-sonnet"
    model_version = "fake-sonnet-v1"

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
