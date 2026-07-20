"""End-to-end personal-node -> team-hub delivery over two real databases.

Every other relay test exercises one side. These wire a real personal node to a
real hub through a transport that calls the hub's own ingest(), so the whole
chain runs for real — enqueue, claim, deliver, authenticate, project mapping,
projection — while staying deterministic enough to assert on.

The transport is the only seam. That lets a test make the hub fail, stall, or
receive the same event twice, which is what the interesting cases need: the
happy path was never the risk.
"""

import asyncio
import uuid

import pytest

from app.core.database import Database
from app.core.errors import RelayDeliveryConflict
from app.core.services.relay import RelayService, _epoch_now

HUB = "http://hub.invalid"
NODE = "personal-node"
TOKEN = "test-relay-token-0123456789"
PROJECT = "e2e-project"


class DirectHubTransport:
    """Delivers straight into the hub's ingest(), no HTTP.

    Records every attempt so a test can prove a retry re-sent the SAME payload
    rather than a fresh one, and can inject failures per attempt.
    """

    def __init__(self, hub_service: RelayService):
        self.hub = hub_service
        self.attempts: list = []
        self.fail_next = 0
        self.fail_with: Exception | None = None
        self.delay = 0.0

    async def send_ingest(self, *, target_hub, bearer_token, payload):
        self.attempts.append(payload)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_next > 0:
            self.fail_next -= 1
            raise self.fail_with or RuntimeError("hub unreachable")
        return await self.hub.ingest(bearer_token, payload)


@pytest.fixture
async def hub_db(tmp_path):
    db = Database(str(tmp_path / "hub.db"))
    await db.connect()
    service = RelayService(db)
    await service.ensure_schema()
    await service.register_identity(
        token=TOKEN,
        user_id="tester",
        source_node_id=NODE,
        display_name="personal node under test",
        scopes=["read", "write"],
    )
    yield db, service
    await db.close()


@pytest.fixture
async def node(temp_db):
    service = RelayService(temp_db)
    await service.ensure_schema()
    return temp_db, service


async def _share(node_service, *, memory_id, version=1, content="body", event="create"):
    """Queue one memory for delivery, mirroring what auto-share enqueues."""
    return await node_service.enqueue_outbox(
        target_hub=HUB,
        payload={
            "idempotency_key": f"{NODE}:{memory_id}:{version}",
            "payload_hash": f"sha256:{uuid.uuid5(uuid.NAMESPACE_OID, content).hex}",
            "event_type": event,
            "source_memory_id": memory_id,
            "source_version": version,
            "source_project_key": PROJECT,
            "kind": "decision",
            "status": "active",
            "content": content,
            "tags": [],
            "links": [],
        },
    )


async def _drain(node_service, transport, *, limit=50):
    """Deliver until the outbox stops yielding work. Returns delivered count."""
    delivered = 0
    for _ in range(limit):
        result = await node_service.drain_next_outbox(
            worker_id="e2e-worker", sender=transport, bearer_token=TOKEN
        )
        if not result.job_id:
            break
        if result.processed:
            delivered += 1
    return delivered


async def _hub_contents(hub_db):
    rows = await hub_db.fetchall(
        "SELECT source_memory_id, content, source_version, authoritative_status "
        "FROM relay_memory_current ORDER BY source_memory_id"
    )
    return {r["source_memory_id"]: dict(r) for r in rows}


async def _outbox_status(node_db):
    rows = await node_db.fetchall(
        "SELECT status, count(*) AS n FROM relay_outbox GROUP BY status"
    )
    return {r["status"]: r["n"] for r in rows}


async def _elapse_backoff(node_db):
    """Pretend the retry backoff has passed, without sleeping for it.

    Sleeping through a real exponential backoff would make these tests slow and
    flaky for no added coverage — the scheduling itself is asserted separately.
    """
    await node_db.execute("UPDATE relay_outbox SET next_attempt_at = 0")


# --- 1. it actually arrives ------------------------------------------------


@pytest.mark.asyncio
async def test_memories_reach_the_hub_intact(node, hub_db):
    node_db, node_service = node
    hub_database, hub_service = hub_db
    transport = DirectHubTransport(hub_service)

    for i in range(25):
        await _share(node_service, memory_id=f"mem-{i:02d}", content=f"payload {i}")

    delivered = await _drain(node_service, transport)

    assert delivered == 25
    assert await _outbox_status(node_db) == {"sent": 25}

    arrived = await _hub_contents(hub_database)
    assert len(arrived) == 25
    # Content survives the trip, not just the row count.
    assert arrived["mem-07"]["content"] == "payload 7"

    mapping = await hub_database.fetchone(
        "SELECT source_node_id, source_project_key, team_project_id "
        "FROM relay_project_mapping"
    )
    assert mapping["source_node_id"] == NODE
    assert mapping["team_project_id"] == f"{NODE}:{PROJECT}"


# --- 2. duplicates --------------------------------------------------------


@pytest.mark.asyncio
async def test_resharing_an_identical_event_is_deduped_before_the_network(node, hub_db):
    """Re-sharing an unchanged memory costs nothing — the outbox collapses it.

    Dedup is by idempotency_key at enqueue time, so a repeat never becomes a
    second delivery. This is the cheaper of the two defences; the hub-side one
    below covers the case where a duplicate does reach the wire.
    """
    node_db, node_service = node
    hub_database, hub_service = hub_db
    transport = DirectHubTransport(hub_service)

    await _share(node_service, memory_id="mem-dup", content="only once")
    await _drain(node_service, transport)

    await _share(node_service, memory_id="mem-dup", content="only once")
    await _drain(node_service, transport)

    assert len(transport.attempts) == 1, "identical re-share must not re-deliver"
    rows = await node_db.fetchall(
        "SELECT id FROM relay_outbox WHERE idempotency_key = ?",
        (f"{NODE}:mem-dup:1",),
    )
    assert len(rows) == 1
    hub_rows = await hub_database.fetchall(
        "SELECT id FROM relay_memory_current WHERE source_memory_id = 'mem-dup'"
    )
    assert len(hub_rows) == 1


@pytest.mark.asyncio
async def test_hub_recognises_a_replayed_event_on_the_wire(node, hub_db):
    """The defence that matters when a response was lost mid-flight.

    The node already marked it sent, so a retry bypasses outbox dedup entirely
    and the hub is the only thing standing between a lost ACK and a duplicate.
    """
    node_db, node_service = node
    hub_database, hub_service = hub_db
    transport = DirectHubTransport(hub_service)

    await _share(node_service, memory_id="mem-replay", content="exactly once")
    await _drain(node_service, transport)

    # Same payload delivered a second time, as an at-least-once transport does.
    replayed = transport.attempts[0]
    await hub_service.ingest(TOKEN, replayed)

    rows = await hub_database.fetchall(
        "SELECT id FROM relay_memory_current WHERE source_memory_id = 'mem-replay'"
    )
    assert len(rows) == 1
    events = await hub_database.fetchall(
        "SELECT id FROM relay_raw_event WHERE source_memory_id = 'mem-replay'"
    )
    assert len(events) == 1, "replay should be recognised, not recorded twice"


@pytest.mark.asyncio
async def test_editing_before_delivery_supersedes_the_queued_payload(node, hub_db):
    """An edit while still queued replaces the unsent row — the hub sees one event."""
    node_db, node_service = node
    hub_database, hub_service = hub_db
    transport = DirectHubTransport(hub_service)

    await _share(node_service, memory_id="mem-edit", content="draft")
    await _share(node_service, memory_id="mem-edit", content="corrected")

    delivered = await _drain(node_service, transport)

    assert delivered == 1
    assert len(transport.attempts) == 1
    arrived = await _hub_contents(hub_database)
    assert arrived["mem-edit"]["content"] == "corrected"


@pytest.mark.asyncio
async def test_same_memory_at_a_new_version_updates_in_place(node, hub_db):
    node_db, node_service = node
    hub_database, hub_service = hub_db
    transport = DirectHubTransport(hub_service)

    await _share(node_service, memory_id="mem-v", version=1, content="first")
    await _drain(node_service, transport)
    await _share(
        node_service, memory_id="mem-v", version=2, content="second", event="update"
    )
    await _drain(node_service, transport)

    arrived = await _hub_contents(hub_database)
    assert len(arrived) == 1
    assert arrived["mem-v"]["content"] == "second"
    assert arrived["mem-v"]["source_version"] == 2


@pytest.mark.asyncio
async def test_out_of_order_delivery_keeps_the_newest_version(node, hub_db):
    """Retries reorder events; an older version must not overwrite a newer one."""
    node_db, node_service = node
    hub_database, hub_service = hub_db
    transport = DirectHubTransport(hub_service)

    await _share(node_service, memory_id="mem-ooo", version=5, content="newest")
    await _drain(node_service, transport)

    await _share(
        node_service, memory_id="mem-ooo", version=2, content="stale", event="update"
    )
    await _drain(node_service, transport)

    arrived = await _hub_contents(hub_database)
    assert arrived["mem-ooo"]["content"] == "newest"
    assert arrived["mem-ooo"]["source_version"] == 5


# --- 3. delay, failure, recovery ------------------------------------------


@pytest.mark.asyncio
async def test_hub_outage_retries_and_delivers_once_it_recovers(node, hub_db):
    """Nothing is lost while the hub is down, and nothing doubles when it returns."""
    node_db, node_service = node
    hub_database, hub_service = hub_db
    transport = DirectHubTransport(hub_service)

    await _share(node_service, memory_id="mem-outage", content="survives")

    transport.fail_next = 3
    for attempt in range(3):
        # Skip the wait the previous failure scheduled, or the row is simply
        # not claimable and the "retry" would silently be a no-op.
        await _elapse_backoff(node_db)
        result = await node_service.drain_next_outbox(
            worker_id="e2e-worker", sender=transport, bearer_token=TOKEN
        )
        assert result.job_id, f"attempt {attempt} claimed nothing"
        assert not result.processed

    assert await _hub_contents(hub_database) == {}
    status = await _outbox_status(node_db)
    assert "sent" not in status, "a failed delivery must not be marked sent"

    # The row is deliberately NOT claimable yet: each failure schedules an
    # exponential backoff, so a recovered hub is not hammered by every queued
    # row at once. Draining right now must find nothing.
    assert await _drain(node_service, transport) == 0
    pending = await node_db.fetchone(
        "SELECT attempts, next_attempt_at FROM relay_outbox"
    )
    assert pending["attempts"] == 3
    assert pending["next_attempt_at"] > _epoch_now(), "retry should be deferred"

    # Hub comes back and the backoff elapses.
    await _elapse_backoff(node_db)
    delivered = await _drain(node_service, transport)
    assert delivered == 1

    arrived = await _hub_contents(hub_database)
    assert len(arrived) == 1
    assert arrived["mem-outage"]["content"] == "survives"
    assert await _outbox_status(node_db) == {"sent": 1}
    assert len(transport.attempts) == 4, "same event retried, not re-queued"


@pytest.mark.asyncio
async def test_slow_hub_still_delivers(node, hub_db):
    node_db, node_service = node
    hub_database, hub_service = hub_db
    transport = DirectHubTransport(hub_service)
    transport.delay = 0.05

    for i in range(5):
        await _share(node_service, memory_id=f"slow-{i}", content=f"body {i}")
    delivered = await _drain(node_service, transport)

    assert delivered == 5
    assert len(await _hub_contents(hub_database)) == 5


@pytest.mark.asyncio
async def test_conflict_is_dead_lettered_not_retried_forever(node, hub_db):
    """A 409 means the hub will never accept it; retrying is a hot loop."""
    node_db, node_service = node
    hub_database, hub_service = hub_db
    transport = DirectHubTransport(hub_service)
    transport.fail_next = 1
    transport.fail_with = RelayDeliveryConflict("version collision")

    await _share(node_service, memory_id="mem-conflict")
    result = await node_service.drain_next_outbox(
        worker_id="e2e-worker", sender=transport, bearer_token=TOKEN
    )

    assert not result.processed
    assert await _outbox_status(node_db) == {"dead_letter": 1}

    # A dead letter is not picked up again.
    assert await _drain(node_service, transport) == 0
    assert len(transport.attempts) == 1


@pytest.mark.asyncio
async def test_bad_token_never_reaches_the_projection(node, hub_db):
    node_db, node_service = node
    hub_database, hub_service = hub_db
    transport = DirectHubTransport(hub_service)

    await _share(node_service, memory_id="mem-auth")
    result = await node_service.drain_next_outbox(
        worker_id="e2e-worker", sender=transport, bearer_token="wrong-token-000000"
    )

    assert not result.processed
    assert await _hub_contents(hub_database) == {}


# --- 4. concurrency -------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_workers_do_not_deliver_the_same_job_twice(node, hub_db):
    """The outbox lease is what stops two workers double-sending."""
    node_db, node_service = node
    hub_database, hub_service = hub_db
    transport = DirectHubTransport(hub_service)

    for i in range(20):
        await _share(node_service, memory_id=f"race-{i:02d}", content=f"body {i}")

    async def worker(name):
        count = 0
        for _ in range(40):
            result = await node_service.drain_next_outbox(
                worker_id=name, sender=transport, bearer_token=TOKEN
            )
            if not result.job_id:
                break
            if result.processed:
                count += 1
        return count

    counts = await asyncio.gather(worker("w1"), worker("w2"), worker("w3"))

    assert sum(counts) == 20
    assert len(transport.attempts) == 20, "no job delivered twice"
    assert len(await _hub_contents(hub_database)) == 20
    assert await _outbox_status(node_db) == {"sent": 20}
