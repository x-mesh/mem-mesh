"""exclude_source_node must filter INSIDE the KNN scan, not after it.

Regression: relay_memory_vec carried no node column, so the hub took the
nearest `limit * 3` vectors first and dropped the excluded node's rows
afterwards. When that node owned the whole neighbourhood — the normal case for
a federated caller whose own memories dominate the hub — every candidate was
discarded and the search returned zero. The over-fetch needed to compensate
scales with the excluded node's corpus size, so no fixed multiplier fixes it.
"""

from unittest.mock import Mock

import pytest

from app.core.services.relay import RelayService

DIM_AXES = 8


def _vec(dim: int, axis: int, jitter: float = 0.0) -> list[float]:
    values = [0.0] * dim
    values[axis] = 1.0 - jitter
    values[(axis + 1) % dim] = jitter
    return values


async def _seed(db, *, node: str, count: int, axis: int, dim: int, offset: int = 0):
    """Insert `count` memories for `node`, clustered on `axis`."""
    service = RelayService(db)
    for i in range(count):
        mem_id = f"{node}-{offset + i}"
        await db.execute(
            """
            INSERT INTO relay_memory_current
                (id, source_node_id, source_memory_id, source_version,
                 latest_event_id, team_project_id, source_project_key,
                 authoritative_kind, authoritative_status, content,
                 content_hash, tags_json, links_json, visible, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, 'proj', 'decision', 'active', ?, ?,
                    '[]', '[]', 1, '2026-01-01T00:00:00+00:00')
            """,
            (
                mem_id,
                node,
                mem_id,
                f"evt-{mem_id}",
                f"{node}:proj",
                f"content for {mem_id}",
                f"sha256:{mem_id}",
            ),
        )
        await service._write_relay_vector_locked(
            current_memory_id=mem_id,
            embedding_values=_vec(dim, axis, jitter=0.001 * i),
            source_node_id=node,
        )


@pytest.fixture
def embedding_stub(temp_db):
    """Embedding service returning a fixed query vector on the dominant axis."""
    service = Mock()

    async def _aembed(_query):
        return _vec(temp_db.embedding_dim, 0)

    service.aembed = _aembed
    return service


@pytest.mark.asyncio
async def test_exclude_source_node_survives_a_dominant_neighbourhood(
    temp_db, embedding_stub
):
    """The exact production shape: every nearest vector belongs to the excluded node."""
    if not temp_db._connection.is_vec_available:
        pytest.skip("sqlite-vec unavailable")

    service = RelayService(temp_db)
    await service.ensure_schema()

    dim = temp_db.embedding_dim
    # 60 dominant docs on the query axis, 20 others far away. Under the old
    # post-filter, limit=5 over-fetched 15 — all dominant — and returned none.
    await _seed(temp_db, node="dominant", count=60, axis=0, dim=dim)
    await _seed(temp_db, node="other", count=20, axis=4, dim=dim)

    response = await service.search(
        query="anything",
        limit=5,
        embedding_service=embedding_stub,
        exclude_source_node="dominant",
    )

    assert len(response.results) == 5
    assert {r.source_node_id for r in response.results} == {"other"}


@pytest.mark.asyncio
async def test_search_without_exclusion_still_returns_nearest(temp_db, embedding_stub):
    """Guard the other direction: the filter must not fire when unset."""
    if not temp_db._connection.is_vec_available:
        pytest.skip("sqlite-vec unavailable")

    service = RelayService(temp_db)
    await service.ensure_schema()

    dim = temp_db.embedding_dim
    await _seed(temp_db, node="dominant", count=10, axis=0, dim=dim)
    await _seed(temp_db, node="other", count=10, axis=4, dim=dim)

    response = await service.search(
        query="anything", limit=5, embedding_service=embedding_stub
    )

    assert len(response.results) == 5
    assert {r.source_node_id for r in response.results} == {"dominant"}


@pytest.mark.asyncio
async def test_vector_index_rebuild_backfills_source_node_id(temp_db):
    """A pre-existing index without the column is rebuilt from stored embeddings."""
    if not temp_db._connection.is_vec_available:
        pytest.skip("sqlite-vec unavailable")

    dim = temp_db.embedding_dim
    service = RelayService(temp_db)
    await service.ensure_schema()
    # Recreate the legacy shape: no source_node_id column.
    await temp_db.execute("DROP TABLE relay_memory_vec")
    await temp_db.execute(f"""CREATE VIRTUAL TABLE relay_memory_vec USING vec0(
                current_memory_id TEXT PRIMARY KEY,
                embedding FLOAT[{dim}]
            )""")
    await temp_db.execute("""
        INSERT INTO relay_memory_current
            (id, source_node_id, source_memory_id, source_version,
             latest_event_id, team_project_id, source_project_key,
             authoritative_kind, authoritative_status, content, content_hash,
             tags_json, links_json, visible, updated_at)
        VALUES ('m1', 'node-a', 'src1', 1, 'e1', 'node-a:proj', 'proj',
                'decision', 'active', 'body', 'sha256:h1', '[]', '[]', 1,
                '2026-01-01T00:00:00+00:00')
        """)
    import json

    await temp_db.execute(
        """
        INSERT INTO relay_item_enrichment
            (id, current_memory_id, raw_event_id, content_hash, embedding_json,
             embedding_model, embedding_dim, title, abstract, tags_json,
             display_kind, model, model_version, prompt_version, confidence,
             generated_at)
        VALUES ('e1', 'm1', 'r1', 'sha256:h1', ?, 'stub', ?, '', '', '[]', '',
                'stub', 'stub', 'relay-v1', 0.0, '2026-01-01T00:00:00+00:00')
        """,
        (json.dumps(_vec(dim, 0)), dim),
    )

    await service._ensure_vector_schema()

    ddl = await temp_db.fetchone(
        "SELECT sql FROM sqlite_master WHERE name='relay_memory_vec'"
    )
    assert "source_node_id" in ddl["sql"]
    row = await temp_db.fetchone(
        "SELECT source_node_id FROM relay_memory_vec WHERE current_memory_id='m1'"
    )
    assert row["source_node_id"] == "node-a"
