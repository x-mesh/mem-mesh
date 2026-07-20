"""End-to-end relay coverage beyond plain delivery.

Companion to test_relay_e2e_delivery.py, which stops once an event lands in
relay_memory_current. These follow it further — through the item queue into the
vector index and back out of a search — and cover the paths where "delivered"
is the wrong outcome: retractions, secrets, and another node's memories.
"""

import uuid

import pytest

from app.core.database import Database
from app.core.errors import RelaySecretBlocked
from app.core.services.relay import RelayService

HUB = "http://hub.invalid"
NODE_A = "node-alpha"
NODE_B = "node-beta"
TOKEN_A = "token-alpha-0123456789abcdef"
TOKEN_B = "token-beta-0123456789abcdef"
PROJECT = "pipeline-project"


class DirectHubTransport:
    def __init__(self, hub_service):
        self.hub = hub_service
        self.attempts = []

    async def send_ingest(self, *, target_hub, bearer_token, payload):
        self.attempts.append(payload)
        return await self.hub.ingest(bearer_token, payload)


class AxisEmbedding:
    """Deterministic embeddings: each distinct text maps to its own axis.

    Real vectors would make these tests depend on model behaviour; the point
    here is the plumbing between the queue, the index, and the search.
    """

    def __init__(self, dim):
        self.dim = dim
        self._axes = {}

    def _axis_for(self, text):
        return self._axes.setdefault(text, len(self._axes) % self.dim)

    async def aembed(self, text):
        values = [0.0] * self.dim
        values[self._axis_for(text)] = 1.0
        return values


@pytest.fixture
async def hub(tmp_path):
    db = Database(str(tmp_path / "hub.db"))
    await db.connect()
    service = RelayService(db)
    await service.ensure_schema()
    for token, node in ((TOKEN_A, NODE_A), (TOKEN_B, NODE_B)):
        await service.register_identity(
            token=token,
            user_id=f"user-{node}",
            source_node_id=node,
            display_name=node,
            scopes=["read", "write"],
        )
    yield db, service
    await db.close()


@pytest.fixture
async def node(temp_db):
    service = RelayService(temp_db)
    await service.ensure_schema()
    return temp_db, service


def _payload(node_id, memory_id, *, version=1, content="body", event="create"):
    return {
        "idempotency_key": f"{node_id}:{memory_id}:{version}",
        "payload_hash": f"sha256:{uuid.uuid5(uuid.NAMESPACE_OID, f'{memory_id}{version}{content}').hex}",
        "event_type": event,
        "source_memory_id": memory_id,
        "source_version": version,
        "source_project_key": PROJECT,
        "kind": "decision",
        "status": "active",
        "content": content,
        "tags": [],
        "links": [],
    }


async def _deliver(node_service, transport, token, payload):
    await node_service.enqueue_outbox(target_hub=HUB, payload=payload)
    return await node_service.drain_next_outbox(
        worker_id="w", sender=transport, bearer_token=token
    )


async def _drain_items(hub_service, embedding, *, limit=100):
    processed = 0
    for _ in range(limit):
        result = await hub_service.process_next_item(
            worker_id="item-worker",
            embedding_service=embedding,
            prompt_version="relay-v1",
        )
        if not result.processed:
            break
        processed += 1
    return processed


# --- retraction -----------------------------------------------------------


@pytest.mark.asyncio
async def test_retraction_is_a_soft_delete_that_retains_the_body(node, hub):
    """Retract hides the row; the hub deliberately keeps the content.

    A retract event carries content=None over the wire, and the hub restores
    the stored body rather than blanking it, so the projection stays
    reconstructable. Worth pinning down explicitly: "deleted locally" therefore
    means invisible on the hub, NOT erased from it.
    """
    node_db, node_service = node
    hub_db, hub_service = hub
    transport = DirectHubTransport(hub_service)

    await _deliver(
        node_service, transport, TOKEN_A, _payload(NODE_A, "mem-x", content="the body")
    )
    row = await hub_db.fetchone(
        "SELECT visible, content FROM relay_memory_current WHERE source_memory_id='mem-x'"
    )
    assert row["visible"] == 1

    retract = _payload(NODE_A, "mem-x", version=2, event="retract")
    retract["content"] = None  # what the node actually sends for a retract
    await _deliver(node_service, transport, TOKEN_A, retract)

    row = await hub_db.fetchone(
        "SELECT visible, content, tombstoned_at FROM relay_memory_current "
        "WHERE source_memory_id='mem-x'"
    )
    assert row["visible"] == 0
    assert row["tombstoned_at"]
    assert row["content"] == "the body"


@pytest.mark.asyncio
async def test_retracted_memory_disappears_from_hub_search(node, hub):
    node_db, node_service = node
    hub_db, hub_service = hub
    transport = DirectHubTransport(hub_service)
    embedding = AxisEmbedding(hub_db.embedding_dim)

    await _deliver(
        node_service, transport, TOKEN_A, _payload(NODE_A, "mem-s", content="findable")
    )
    await _drain_items(hub_service, embedding)

    found = await hub_service.search(
        query="findable", limit=5, embedding_service=embedding
    )
    assert [r.source_memory_id for r in found.results] == ["mem-s"]

    await _deliver(
        node_service,
        transport,
        TOKEN_A,
        _payload(NODE_A, "mem-s", version=2, content="findable", event="retract"),
    )

    found = await hub_service.search(
        query="findable", limit=5, embedding_service=embedding
    )
    assert found.results == []


# --- secrets --------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_secret_never_leaves_the_node(node, hub):
    """The outbox refuses the payload, so nothing reaches the hub to clean up."""
    node_db, node_service = node
    hub_db, hub_service = hub
    transport = DirectHubTransport(hub_service)

    leaked = "deploy key is sk-ant-abcdefghijklmnopqrstuvwxyz012345"
    with pytest.raises(RelaySecretBlocked):
        await node_service.enqueue_outbox(
            target_hub=HUB, payload=_payload(NODE_A, "mem-leak", content=leaked)
        )

    assert await node_db.fetchall("SELECT id FROM relay_outbox") == []
    assert transport.attempts == []
    assert await hub_db.fetchall("SELECT id FROM relay_memory_current") == []


@pytest.mark.asyncio
async def test_hub_rejects_a_secret_that_bypassed_the_node(hub):
    """Second line of defence: a compromised or older node cannot push one in."""
    hub_db, hub_service = hub

    leaked = "AWS root: AKIAIOSFODNN7EXAMPLE do not share"
    with pytest.raises(RelaySecretBlocked):
        await hub_service.ingest(TOKEN_A, _payload(NODE_A, "mem-leak2", content=leaked))

    assert await hub_db.fetchall("SELECT id FROM relay_memory_current") == []


# --- multi-node isolation -------------------------------------------------


@pytest.mark.asyncio
async def test_two_nodes_land_in_separate_team_projects(node, hub, temp_db_path):
    """Same project name from different nodes must not merge into one namespace."""
    node_a_db, node_a = node
    hub_db, hub_service = hub
    transport = DirectHubTransport(hub_service)

    node_b_db = Database(temp_db_path + ".beta")
    await node_b_db.connect()
    node_b = RelayService(node_b_db)
    await node_b.ensure_schema()

    try:
        await _deliver(
            node_a, transport, TOKEN_A, _payload(NODE_A, "a1", content="from a")
        )
        await _deliver(
            node_b, transport, TOKEN_B, _payload(NODE_B, "b1", content="from b")
        )

        projects = await hub_db.fetchall(
            "SELECT team_project_id FROM relay_project ORDER BY team_project_id"
        )
        assert [p["team_project_id"] for p in projects] == [
            f"{NODE_A}:{PROJECT}",
            f"{NODE_B}:{PROJECT}",
        ]

        owners = await hub_db.fetchall(
            "SELECT source_memory_id, source_node_id, team_project_id "
            "FROM relay_memory_current ORDER BY source_memory_id"
        )
        assert owners[0]["source_node_id"] == NODE_A
        assert owners[1]["source_node_id"] == NODE_B
        assert owners[0]["team_project_id"] != owners[1]["team_project_id"]
    finally:
        await node_b_db.close()


@pytest.mark.asyncio
async def test_identical_memory_ids_from_two_nodes_do_not_collide(hub):
    """Projection identity is (node, memory), not memory alone.

    source_memory_id is only unique within a node — two nodes numbering their
    memories independently will collide constantly. Keying on it alone would
    make one node's write silently overwrite the other's.
    """
    hub_db, hub_service = hub

    await hub_service.ingest(
        TOKEN_A, _payload(NODE_A, "mem-1", content="alpha wrote this")
    )
    await hub_service.ingest(
        TOKEN_B, _payload(NODE_B, "mem-1", content="beta wrote this")
    )

    rows = await hub_db.fetchall(
        "SELECT source_node_id, content FROM relay_memory_current "
        "WHERE source_memory_id='mem-1' ORDER BY source_node_id"
    )
    assert len(rows) == 2, "one node's memory must not overwrite another's"
    assert rows[0]["source_node_id"] == NODE_A
    assert rows[0]["content"] == "alpha wrote this"
    assert rows[1]["source_node_id"] == NODE_B
    assert rows[1]["content"] == "beta wrote this"


@pytest.mark.asyncio
async def test_attribution_follows_the_token_not_the_caller_s_claim(hub):
    """A node's identity is derived from its bearer token.

    RelayIngestRequest has no node field at all, so this is structural rather
    than enforced — the assertion documents the guarantee and would catch any
    future field that reintroduced caller-supplied attribution.
    """
    hub_db, hub_service = hub

    assert "source_node_id" not in _payload(NODE_A, "x")
    await hub_service.ingest(TOKEN_B, _payload(NODE_A, "attributed", content="body"))

    row = await hub_db.fetchone(
        "SELECT source_node_id FROM relay_memory_current "
        "WHERE source_memory_id='attributed'"
    )
    assert row["source_node_id"] == NODE_B


# --- the rest of the pipeline --------------------------------------------


@pytest.mark.asyncio
async def test_delivered_memories_become_searchable_end_to_end(node, hub):
    """The full chain: node -> hub -> item queue -> embedding -> vec -> search."""
    node_db, node_service = node
    hub_db, hub_service = hub
    transport = DirectHubTransport(hub_service)
    embedding = AxisEmbedding(hub_db.embedding_dim)

    for i in range(6):
        await _deliver(
            node_service,
            transport,
            TOKEN_A,
            _payload(NODE_A, f"p{i}", content=f"topic {i}"),
        )

    pending = await hub_db.fetchone(
        "SELECT count(*) AS n FROM relay_queue_item WHERE status='pending'"
    )
    assert pending["n"] == 6, "ingest should queue enrichment work"

    processed = await _drain_items(hub_service, embedding)
    assert processed == 6

    vectors = await hub_db.fetchone("SELECT count(*) AS n FROM relay_memory_vec")
    assert vectors["n"] == 6
    # The pre-filter fix depends on this column being populated by the worker,
    # not only by the migration.
    nodes = await hub_db.fetchall(
        "SELECT DISTINCT source_node_id FROM relay_memory_vec"
    )
    assert [n["source_node_id"] for n in nodes] == [NODE_A]

    found = await hub_service.search(
        query="topic 3", limit=3, embedding_service=embedding
    )
    assert found.results
    assert found.results[0].source_memory_id == "p3"


@pytest.mark.asyncio
async def test_item_queue_is_idempotent_across_repeated_drains(node, hub):
    """Draining an empty queue must not re-embed or duplicate vectors."""
    node_db, node_service = node
    hub_db, hub_service = hub
    transport = DirectHubTransport(hub_service)
    embedding = AxisEmbedding(hub_db.embedding_dim)

    await _deliver(
        node_service, transport, TOKEN_A, _payload(NODE_A, "once", content="v")
    )
    assert await _drain_items(hub_service, embedding) == 1
    assert await _drain_items(hub_service, embedding) == 0

    vectors = await hub_db.fetchone("SELECT count(*) AS n FROM relay_memory_vec")
    assert vectors["n"] == 1
    enrichments = await hub_db.fetchone(
        "SELECT count(*) AS n FROM relay_item_enrichment"
    )
    assert enrichments["n"] == 1


@pytest.mark.asyncio
async def test_updating_content_refreshes_the_indexed_vector(node, hub):
    """A stale vector would keep surfacing the old text after an edit."""
    node_db, node_service = node
    hub_db, hub_service = hub
    transport = DirectHubTransport(hub_service)
    embedding = AxisEmbedding(hub_db.embedding_dim)

    await _deliver(
        node_service, transport, TOKEN_A, _payload(NODE_A, "mem-u", content="before")
    )
    await _drain_items(hub_service, embedding)

    await _deliver(
        node_service,
        transport,
        TOKEN_A,
        _payload(NODE_A, "mem-u", version=2, content="after", event="update"),
    )
    await _drain_items(hub_service, embedding)

    vectors = await hub_db.fetchone("SELECT count(*) AS n FROM relay_memory_vec")
    assert vectors["n"] == 1, "update must replace the vector, not add one"

    found = await hub_service.search(
        query="after", limit=3, embedding_service=embedding
    )
    assert [r.source_memory_id for r in found.results] == ["mem-u"]
    assert found.results[0].content == "after"
