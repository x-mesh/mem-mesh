"""Project rename/merge: move project_id across every table that carries it.

The regression these pin down: renaming only `memories` leaves sessions, pins
and stats stranded on the old id (a half-merged project), and a naive UPDATE
trips the UNIQUE constraints on the settings-style tables.
"""

import os
import tempfile
from contextlib import asynccontextmanager

import pytest

from app.core.database.base import Database
from app.core.services.project import ProjectService


@asynccontextmanager
async def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path, embedding_dim=3)
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
        for ext in ["", "-wal", "-shm"]:
            if os.path.exists(path + ext):
                os.unlink(path + ext)


async def _add_project(db, project_id):
    await db.execute(
        """
        INSERT INTO projects (id, name, created_at, updated_at)
        VALUES (?, ?, '2026-01-01', '2026-01-01')
        """,
        (project_id, project_id),
    )


async def _add_memory(db, mid, project_id):
    await db.execute(
        """
        INSERT INTO memories (
            id, content, content_hash, project_id, category, source,
            embedding, tags, status, created_at, updated_at, content_bytes
        )
        VALUES (?, ?, ?, ?, 'decision', 'test', ?, '[]', 'canonical',
                '2026-01-01', '2026-01-01', 0)
        """,
        (mid, f"content {mid}", f"hash-{mid}", project_id, b"1"),
    )


async def _add_session(db, sid, project_id, *, status="ended", user_id="default"):
    await db.execute(
        """
        INSERT INTO sessions (
            id, project_id, user_id, started_at, status, created_at, updated_at
        )
        VALUES (?, ?, ?, '2026-01-01', ?, '2026-01-01', '2026-01-01')
        """,
        (sid, project_id, user_id, status),
    )


async def _add_pin(db, pid, project_id, session_id):
    await db.execute(
        """
        INSERT INTO pins (
            id, session_id, project_id, content, importance, status,
            created_at, updated_at
        )
        VALUES (?, ?, ?, 'pin content', 3, 'open', '2026-01-01', '2026-01-01')
        """,
        (pid, session_id, project_id),
    )


async def _count(db, table, project_id):
    row = await db.fetchone(
        f"SELECT COUNT(*) AS c FROM {table} WHERE project_id = ?", (project_id,)
    )
    return row["c"]


@pytest.mark.asyncio
async def test_rename_merges_every_table_carrying_project_id():
    async with _temp_db() as db:
        await _add_project(db, "aic")
        await _add_project(db, "aic-rust")
        await _add_memory(db, "m-old", "aic-rust")
        await _add_memory(db, "m-new", "aic")
        await _add_session(db, "s-old", "aic-rust")
        await _add_pin(db, "p-old", "aic-rust", "s-old")

        result = await ProjectService(db).rename_project("aic-rust", "aic")

        assert result.merged is True
        assert result.total_moved == 3  # memory + session + pin
        assert await _count(db, "memories", "aic") == 2
        assert await _count(db, "memories", "aic-rust") == 0
        assert await _count(db, "pins", "aic") == 1
        assert await _count(db, "sessions", "aic") == 1
        assert await db.fetchone("SELECT 1 FROM projects WHERE id = 'aic-rust'") is None
        # FTS is trigger-maintained: it must follow the memories update.
        fts = await db.fetchone(
            "SELECT COUNT(*) AS c FROM memories_fts WHERE project_id = 'aic-rust'"
        )
        assert fts["c"] == 0


@pytest.mark.asyncio
async def test_rename_to_unused_id_keeps_project_metadata():
    async with _temp_db() as db:
        await _add_project(db, "aic-rust")
        await _add_memory(db, "m1", "aic-rust")

        result = await ProjectService(db).rename_project("aic-rust", "aic")

        assert result.merged is False
        assert await _count(db, "memories", "aic") == 1
        row = await db.fetchone("SELECT id FROM projects WHERE id = 'aic'")
        assert row is not None


@pytest.mark.asyncio
async def test_rename_closes_conflicting_active_session():
    """Only one active session per (project, user) is allowed — the incoming
    active session must be closed, not dropped, and not blow up the merge."""

    async with _temp_db() as db:
        await _add_project(db, "aic")
        await _add_project(db, "aic-rust")
        await _add_session(db, "s-target", "aic", status="active")
        await _add_session(db, "s-source", "aic-rust", status="active")

        result = await ProjectService(db).rename_project("aic-rust", "aic")

        assert result.sessions_ended == 1
        assert await _count(db, "sessions", "aic") == 2
        assert await _count(db, "sessions", "aic-rust") == 0
        moved = await db.fetchone(
            "SELECT status, ended_at FROM sessions WHERE id = ?", ("s-source",)
        )
        assert moved["status"] == "ended"
        assert moved["ended_at"] is not None
        kept = await db.fetchone(
            "SELECT status FROM sessions WHERE id = ?", ("s-target",)
        )
        assert kept["status"] == "active"


@pytest.mark.asyncio
async def test_rename_drops_duplicate_settings_row_and_keeps_target():
    """relay_auto_share_subscription keys on project_id: when both projects have
    a row, the target's setting wins and the source row is discarded."""

    from app.core.services.relay import RelayService

    async with _temp_db() as db:
        relay = RelayService(db)
        await relay.ensure_schema()
        await _add_project(db, "aic")
        await _add_project(db, "aic-rust")
        for project_id, hub in (
            ("aic", "https://hub-a"),
            ("aic-rust", "https://hub-b"),
        ):
            await db.execute(
                """
                INSERT INTO relay_auto_share_subscription (
                    project_id, enabled, target_hub, source_node_id,
                    include_relay_origin, created_at, updated_at
                )
                VALUES (?, 1, ?, 'node', 0, '2026-01-01', '2026-01-01')
                """,
                (project_id, hub),
            )

        result = await ProjectService(db).rename_project("aic-rust", "aic")

        sub = [t for t in result.tables if t.table == "relay_auto_share_subscription"]
        assert sub and sub[0].dropped == 1 and sub[0].moved == 0
        row = await db.fetchone(
            "SELECT target_hub FROM relay_auto_share_subscription WHERE project_id = 'aic'"
        )
        assert row["target_hub"] == "https://hub-a"  # target's setting survives
        assert await _count(db, "relay_auto_share_subscription", "aic-rust") == 0


@pytest.mark.asyncio
async def test_dry_run_reports_counts_without_writing():
    async with _temp_db() as db:
        await _add_project(db, "aic")
        await _add_project(db, "aic-rust")
        await _add_memory(db, "m1", "aic-rust")

        result = await ProjectService(db).rename_project(
            "aic-rust", "aic", dry_run=True
        )

        assert result.dry_run is True
        assert result.total_moved == 1
        assert await _count(db, "memories", "aic-rust") == 1  # untouched
        assert await db.fetchone("SELECT 1 FROM projects WHERE id = 'aic-rust'")


@pytest.mark.asyncio
async def test_rename_rejects_same_id():
    async with _temp_db() as db:
        await _add_project(db, "aic")
        with pytest.raises(ValueError):
            await ProjectService(db).rename_project("aic", "aic")


@pytest.mark.asyncio
async def test_dry_run_predicts_dropped_rows_not_just_moved():
    """Regression (review F3): the preview reported every source row as `moved`,
    including rows that apply() silently DELETES on a UNIQUE(project_id) table.
    A preview that hides a delete is asking the user to approve one blind."""

    from app.core.services.relay import RelayService

    async with _temp_db() as db:
        relay = RelayService(db)
        await relay.ensure_schema()
        await _add_project(db, "aic")
        await _add_project(db, "aic-rust")
        await _add_memory(db, "m1", "aic-rust")
        for project_id, hub in (
            ("aic", "https://hub-a"),
            ("aic-rust", "https://hub-b"),
        ):
            await db.execute(
                """
                INSERT INTO relay_auto_share_subscription (
                    project_id, enabled, target_hub, source_node_id,
                    include_relay_origin, created_at, updated_at
                )
                VALUES (?, 1, ?, 'node', 0, '2026-01-01', '2026-01-01')
                """,
                (project_id, hub),
            )

        preview = await ProjectService(db).rename_project(
            "aic-rust", "aic", dry_run=True
        )
        sub = [t for t in preview.tables if t.table == "relay_auto_share_subscription"]
        assert sub and sub[0].dropped == 1 and sub[0].moved == 0
        assert preview.total_dropped == 1
        assert preview.total_moved == 1  # the memory

        # And the preview must match what apply actually does.
        applied = await ProjectService(db).rename_project("aic-rust", "aic")
        assert applied.total_moved == preview.total_moved
        assert applied.total_dropped == preview.total_dropped


@pytest.mark.asyncio
async def test_dry_run_predicts_closed_active_sessions():
    async with _temp_db() as db:
        await _add_project(db, "aic")
        await _add_project(db, "aic-rust")
        await _add_session(db, "s-target", "aic", status="active")
        await _add_session(db, "s-source", "aic-rust", status="active")

        preview = await ProjectService(db).rename_project(
            "aic-rust", "aic", dry_run=True
        )
        assert preview.sessions_ended == 1

        applied = await ProjectService(db).rename_project("aic-rust", "aic")
        assert applied.sessions_ended == preview.sessions_ended


@pytest.mark.asyncio
async def test_rename_refuses_to_delete_rows_it_did_not_predict():
    """Regression (review F3, second half): the merge DELETEs rows that could not
    move. That is correct only for the settings-shaped tables where project_id is
    the unique key. A future table with a COMPOSITE unique on project_id would
    silently lose data — the merge must abort instead."""

    async with _temp_db() as db:
        await _add_project(db, "aic")
        await _add_project(db, "aic-rust")
        # A data table whose uniqueness is (project_id, slot) — not the settings shape.
        await db.execute("""
            CREATE TABLE widget_state (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                slot TEXT NOT NULL,
                payload TEXT,
                UNIQUE(project_id, slot)
            )
            """)
        await db.execute(
            "INSERT INTO widget_state (id, project_id, slot, payload) VALUES ('w1','aic','a','target')"
        )
        await db.execute(
            "INSERT INTO widget_state (id, project_id, slot, payload) VALUES ('w2','aic-rust','a','source')"
        )

        with pytest.raises(RuntimeError, match="refusing to delete"):
            await ProjectService(db).rename_project("aic-rust", "aic")

        # Transaction rolled back: nothing moved, nothing deleted.
        assert await _count(db, "widget_state", "aic-rust") == 1
        row = await db.fetchone("SELECT payload FROM widget_state WHERE id = 'w1'")
        assert row["payload"] == "target"
