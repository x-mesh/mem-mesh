"""Tests for automatic schema migration system."""

import os
import tempfile

import pytest

from app.core.database import CURRENT_SCHEMA_VERSION, Database, SchemaMigrator
from app.core.database.connection import DatabaseConnection


@pytest.fixture
def temp_db_path():
    """Create a temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    for ext in ["", "-wal", "-shm"]:
        p = path + ext
        if os.path.exists(p):
            os.unlink(p)


@pytest.mark.asyncio
async def test_schema_migrator_creates_migrations_table(temp_db_path):
    """Test that migrations table is created."""
    db = Database(temp_db_path)
    await db.connect()

    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='_schema_migrations'"
    )
    result = cursor.fetchone()
    assert result is not None
    assert result["name"] == "_schema_migrations"

    await db.close()


@pytest.mark.asyncio
async def test_schema_migrator_records_version(temp_db_path):
    """Test that schema version is recorded after migration."""
    db = Database(temp_db_path)
    await db.connect()

    cursor = await db.execute("SELECT MAX(version) as version FROM _schema_migrations")
    result = cursor.fetchone()
    assert result["version"] == CURRENT_SCHEMA_VERSION

    await db.close()


@pytest.mark.asyncio
async def test_memory_mutations_advance_read_revision_without_access_counter_churn(
    temp_db_path,
):
    db = Database(temp_db_path)
    await db.connect()
    try:
        before = await db.fetchone(
            "SELECT state_value FROM reconciler_state WHERE state_key = 'read_revision'"
        )
        initial = int(before["state_value"]) if before else 0
        await db.add_memory(
            {
                "id": "revision-test",
                "content": "A canonical memory for revision tracking.",
                "content_hash": "hash-one",
                "project_id": "revision-project",
                "category": "task",
                "status": "canonical",
                "source": "test",
                "client": "pytest",
                "embedding": b"\x00" * (db.embedding_dim * 4),
                "tags": "[]",
                "anchors": "{}",
                "created_at": "2026-10-20T00:00:00+00:00",
                "updated_at": "2026-10-20T00:00:00+00:00",
            }
        )
        inserted = await db.fetchone(
            "SELECT state_value FROM reconciler_state WHERE state_key = 'read_revision'"
        )
        await db.execute(
            "UPDATE memories SET access_count = 1 WHERE id = ?", ("revision-test",)
        )
        accessed = await db.fetchone(
            "SELECT state_value FROM reconciler_state WHERE state_key = 'read_revision'"
        )
        await db.execute(
            "UPDATE memories SET content = ? WHERE id = ?",
            ("A changed canonical memory.", "revision-test"),
        )
        updated = await db.fetchone(
            "SELECT state_value FROM reconciler_state WHERE state_key = 'read_revision'"
        )
        await db.execute("DELETE FROM memories WHERE id = ?", ("revision-test",))
        deleted = await db.fetchone(
            "SELECT state_value FROM reconciler_state WHERE state_key = 'read_revision'"
        )

        assert int(inserted["state_value"]) == initial + 1
        assert accessed["state_value"] == inserted["state_value"]
        assert int(updated["state_value"]) == initial + 2
        assert int(deleted["state_value"]) == initial + 3
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_schema_migrator_adds_missing_columns(temp_db_path):
    """Test that missing columns are added during migration."""
    # First, create a database with old schema (missing columns)
    import sqlite3

    conn = sqlite3.connect(temp_db_path)
    conn.execute("""
        CREATE TABLE pins (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER DEFAULT 3,
            status TEXT DEFAULT 'open',
            tags TEXT,
            embedding BLOB,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    # Now connect with Database which should run migrations
    db = Database(temp_db_path)
    await db.connect()

    # Check that new columns were added
    cursor = await db.execute("PRAGMA table_info(pins)")
    columns = [row["name"] for row in cursor.fetchall()]

    assert "promoted_to_memory_id" in columns
    assert "auto_importance" in columns
    assert "estimated_tokens" in columns
    assert "user_id" in columns

    await db.close()


@pytest.mark.asyncio
async def test_schema_migrator_idempotent(temp_db_path):
    """Test that running migrations multiple times is safe."""
    db = Database(temp_db_path)
    await db.connect()

    # Get initial version
    cursor = await db.execute("SELECT MAX(version) as version FROM _schema_migrations")
    initial_version = cursor.fetchone()["version"]

    await db.close()

    # Connect again (should not fail or change version)
    db2 = Database(temp_db_path)
    await db2.connect()

    cursor = await db2.execute("SELECT MAX(version) as version FROM _schema_migrations")
    final_version = cursor.fetchone()["version"]

    assert initial_version == final_version

    await db2.close()


@pytest.mark.asyncio
async def test_column_exists_check():
    """Test _column_exists helper method."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        conn = DatabaseConnection(path)
        await conn.connect()

        migrator = SchemaMigrator(conn)

        # Create test table
        conn.connection.execute("CREATE TABLE test_table (id TEXT, name TEXT)")
        conn.commit()

        assert await migrator._column_exists("test_table", "id") is True
        assert await migrator._column_exists("test_table", "name") is True
        assert await migrator._column_exists("test_table", "nonexistent") is False

        await conn.close()
    finally:
        for ext in ["", "-wal", "-shm"]:
            p = path + ext
            if os.path.exists(p):
                os.unlink(p)


@pytest.mark.asyncio
async def test_add_column_if_missing():
    """Test _add_column_if_missing helper method."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        conn = DatabaseConnection(path)
        await conn.connect()

        migrator = SchemaMigrator(conn)

        # Create test table
        conn.connection.execute("CREATE TABLE test_table (id TEXT)")
        conn.commit()

        # Add new column
        added = await migrator._add_column_if_missing(
            "test_table", "new_col", "TEXT", "'default'"
        )
        assert added is True

        # Try to add same column again
        added_again = await migrator._add_column_if_missing(
            "test_table", "new_col", "TEXT", "'default'"
        )
        assert added_again is False

        # Verify column exists with default
        conn.connection.execute("INSERT INTO test_table (id) VALUES ('test')")
        conn.commit()

        cursor = conn.connection.execute(
            "SELECT new_col FROM test_table WHERE id = 'test'"
        )
        row = cursor.fetchone()
        assert row[0] == "default"

        await conn.close()
    finally:
        for ext in ["", "-wal", "-shm"]:
            p = path + ext
            if os.path.exists(p):
                os.unlink(p)


def test_current_schema_version_includes_memory_reconciler():
    """CURRENT_SCHEMA_VERSION includes the Memory Reconciler ledger."""
    assert CURRENT_SCHEMA_VERSION == 20


@pytest.mark.asyncio
async def test_reconciler_protection_defaults_off_and_bumps_read_revision(temp_db_path):
    db = Database(temp_db_path)
    await db.connect()
    try:
        await db.add_memory(
            {
                "id": "protected-test",
                "content": "A canonical memory used to verify protection metadata.",
                "content_hash": "hash",
                "project_id": "test-project",
                "category": "task",
                "source": "test",
                "embedding": b"\x00" * 16,
                "created_at": "2026-10-20T00:00:00Z",
                "updated_at": "2026-10-20T00:00:00Z",
            }
        )
        before = await db.fetchone(
            "SELECT state_value FROM reconciler_state WHERE state_key = 'read_revision'"
        )
        row = await db.fetchone(
            "SELECT reconciler_protected FROM memories WHERE id = 'protected-test'"
        )
        assert row["reconciler_protected"] == 0
        await db.execute(
            "UPDATE memories SET reconciler_protected = 1 WHERE id = 'protected-test'"
        )
        after = await db.fetchone(
            "SELECT state_value FROM reconciler_state WHERE state_key = 'read_revision'"
        )
        assert int(after["state_value"]) == int(before["state_value"]) + 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_external_llm_policy_defaults_to_denied(temp_db_path):
    db = Database(temp_db_path)
    await db.connect()
    try:
        columns = await db.fetchall("PRAGMA table_info(reconciler_project_policy)")
        assert "allow_external_llm" in {row["name"] for row in columns}
        await db.execute(
            "INSERT INTO reconciler_project_policy(project_id, updated_at) VALUES (?, datetime('now'))",
            ("new-project",),
        )
        row = await db.fetchone(
            "SELECT allow_external_llm FROM reconciler_project_policy WHERE project_id = ?",
            ("new-project",),
        )
        assert row["allow_external_llm"] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_v18_preserves_existing_reconciler_policy_flags(temp_db_path):
    db = Database(temp_db_path)
    await db.connect()
    await db.execute(
        "INSERT INTO reconciler_project_policy(project_id, auto_noise_suppression, auto_derived_relations, revision, updated_at) VALUES ('existing', 1, 1, 7, datetime('now'))"
    )
    await db.execute(
        "ALTER TABLE reconciler_project_policy DROP COLUMN allow_external_llm"
    )
    await db.execute("DELETE FROM _schema_migrations WHERE version >= 18")
    await db.close()

    upgraded = Database(temp_db_path)
    await upgraded.connect()
    try:
        row = await upgraded.fetchone(
            "SELECT auto_noise_suppression, auto_derived_relations, allow_external_llm, revision FROM reconciler_project_policy WHERE project_id = 'existing'"
        )
        assert dict(row) == {
            "auto_noise_suppression": 1,
            "auto_derived_relations": 1,
            "allow_external_llm": 0,
            "revision": 7,
        }
    finally:
        await upgraded.close()


@pytest.mark.asyncio
async def test_v12_new_db_has_injection_table_and_anchors(temp_db_path):
    """DoD (a): a freshly created DB exposes injected_memories + memories.anchors."""
    db = Database(temp_db_path)
    await db.connect()

    # injected_memories table exists
    cursor = await db.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='injected_memories'"
    )
    assert cursor.fetchone() is not None

    # injected_memories has the full column set
    cursor = await db.execute("PRAGMA table_info(injected_memories)")
    inj_cols = [row["name"] for row in cursor.fetchall()]
    for col in (
        "id",
        "project_id",
        "ide_session_id",
        "memory_id",
        "turn_index",
        "position",
        "injected_via",
        "created_at",
        # v13 utilization-verdict columns.
        "utilized",
        "judged_at",
        "judge_method",
    ):
        assert col in inj_cols

    # memories.anchors column exists
    cursor = await db.execute("PRAGMA table_info(memories)")
    memory_cols = [row["name"] for row in cursor.fetchall()]
    assert "anchors" in memory_cols

    # both injected_memories indexes exist
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name IN "
        "('idx_injected_memories_session', 'idx_injected_memories_project_created')"
    )
    idx_names = {row["name"] for row in cursor.fetchall()}
    assert "idx_injected_memories_session" in idx_names
    assert "idx_injected_memories_project_created" in idx_names

    await db.close()


@pytest.mark.asyncio
async def test_v12_migration_from_v11_state_and_idempotent():
    """DoD (b): a v11-state DB migrates to v12, and re-running is harmless."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        conn = DatabaseConnection(path)
        await conn.connect()

        # Simulate an existing v11 database: memories table without anchors,
        # migration bookkeeping pinned at version 11.
        conn.connection.execute(
            "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL)"
        )
        conn.connection.execute(
            "CREATE TABLE _schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT)"
        )
        conn.connection.execute(
            "INSERT INTO _schema_migrations (version, applied_at) "
            "VALUES (11, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()

        migrator = SchemaMigrator(conn)
        await migrator.migrate()

        assert await migrator._table_exists("injected_memories")
        assert await migrator._column_exists("memories", "anchors")

        cursor = await conn.execute(
            "SELECT MAX(version) AS version FROM _schema_migrations"
        )
        assert cursor.fetchone()["version"] == CURRENT_SCHEMA_VERSION

        # Re-running the full migration path is a no-op (already up to date).
        await migrator.migrate()
        cursor = await conn.execute(
            "SELECT MAX(version) AS version FROM _schema_migrations"
        )
        assert cursor.fetchone()["version"] == CURRENT_SCHEMA_VERSION

        # Re-applying the v12 step directly must not raise (IF NOT EXISTS /
        # _add_column_if_missing guard against the columns/tables already existing).
        await migrator._migration_v12_injection_anchors(migrator)
        assert await migrator._table_exists("injected_memories")
        assert await migrator._column_exists("memories", "anchors")

        await conn.close()
    finally:
        for ext in ["", "-wal", "-shm"]:
            p = path + ext
            if os.path.exists(p):
                os.unlink(p)


@pytest.mark.asyncio
async def test_v13_adds_utilization_columns_from_v12_state():
    """A v12-state injected_memories (no verdict columns) gains them at v13, and
    re-applying the v13 step is idempotent."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        conn = DatabaseConnection(path)
        await conn.connect()

        # Simulate a v12 database: injected_memories as v12 shipped it (no
        # utilized/judged_at/judge_method), bookkeeping pinned at version 12.
        conn.connection.execute(
            "CREATE TABLE injected_memories ("
            "id TEXT PRIMARY KEY, project_id TEXT NOT NULL, "
            "ide_session_id TEXT NOT NULL, memory_id TEXT NOT NULL, "
            "turn_index INTEGER NOT NULL DEFAULT 0, "
            "position INTEGER NOT NULL DEFAULT 0, "
            "injected_via TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.connection.execute(
            "CREATE TABLE _schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT)"
        )
        conn.connection.execute(
            "INSERT INTO _schema_migrations (version, applied_at) "
            "VALUES (12, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()

        migrator = SchemaMigrator(conn)
        await migrator.migrate()

        for col in ("utilized", "judged_at", "judge_method"):
            assert await migrator._column_exists("injected_memories", col)

        cursor = await conn.execute(
            "SELECT MAX(version) AS version FROM _schema_migrations"
        )
        assert cursor.fetchone()["version"] == CURRENT_SCHEMA_VERSION

        # Re-applying the v13 step directly must not raise (_add_column_if_missing
        # short-circuits on the already-present columns).
        await migrator._migration_v13_injection_utilization(migrator)
        for col in ("utilized", "judged_at", "judge_method"):
            assert await migrator._column_exists("injected_memories", col)

        await conn.close()
    finally:
        for ext in ["", "-wal", "-shm"]:
            p = path + ext
            if os.path.exists(p):
                os.unlink(p)


@pytest.mark.asyncio
async def test_v14_new_db_has_stale_columns(temp_db_path):
    """A freshly created DB exposes memories.stale_status + stale_checked_at."""
    db = Database(temp_db_path)
    await db.connect()

    cursor = await db.execute("PRAGMA table_info(memories)")
    memory_cols = [row["name"] for row in cursor.fetchall()]
    assert "stale_status" in memory_cols
    assert "stale_checked_at" in memory_cols

    await db.close()


@pytest.mark.asyncio
async def test_v14_adds_stale_columns_from_v13_state():
    """A v13-state memories table (no stale columns) gains them at v14, and
    re-applying the v14 step is idempotent."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        conn = DatabaseConnection(path)
        await conn.connect()

        # Simulate a v13 database: memories without stale columns, bookkeeping
        # pinned at version 13.
        conn.connection.execute(
            "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL)"
        )
        conn.connection.execute(
            "CREATE TABLE _schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT)"
        )
        conn.connection.execute(
            "INSERT INTO _schema_migrations (version, applied_at) "
            "VALUES (13, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()

        migrator = SchemaMigrator(conn)
        await migrator.migrate()

        for col in ("stale_status", "stale_checked_at"):
            assert await migrator._column_exists("memories", col)

        cursor = await conn.execute(
            "SELECT MAX(version) AS version FROM _schema_migrations"
        )
        assert cursor.fetchone()["version"] == CURRENT_SCHEMA_VERSION

        # Re-applying the v14 step directly must not raise (_add_column_if_missing
        # short-circuits on the already-present columns).
        await migrator._migration_v14_stale_status(migrator)
        for col in ("stale_status", "stale_checked_at"):
            assert await migrator._column_exists("memories", col)

        await conn.close()
    finally:
        for ext in ["", "-wal", "-shm"]:
            p = path + ext
            if os.path.exists(p):
                os.unlink(p)


@pytest.mark.asyncio
async def test_v15_new_db_has_is_starred(temp_db_path):
    """A freshly created DB exposes memories.is_starred defaulting to 0."""
    db = Database(temp_db_path)
    await db.connect()

    cursor = await db.execute("PRAGMA table_info(memories)")
    cols = {row["name"]: row for row in cursor.fetchall()}
    assert "is_starred" in cols
    # DEFAULT 0 is load-bearing: relay's INSERT omits this column entirely.
    assert str(cols["is_starred"]["dflt_value"]) == "0"

    await db.close()


@pytest.mark.asyncio
async def test_v15_adds_is_starred_from_v14_state():
    """A v14-state memories table (no is_starred) gains it at v15, existing rows
    are backfilled to 0, and re-applying the v15 step is idempotent."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        conn = DatabaseConnection(path)
        await conn.connect()

        # Simulate a v14 database: memories without is_starred, one row already
        # on disk, bookkeeping pinned at version 14.
        conn.connection.execute(
            "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL)"
        )
        conn.connection.execute(
            "INSERT INTO memories (id, content) VALUES ('m1', 'pre-existing row')"
        )
        conn.connection.execute(
            "CREATE TABLE _schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT)"
        )
        conn.connection.execute(
            "INSERT INTO _schema_migrations (version, applied_at) "
            "VALUES (14, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()

        migrator = SchemaMigrator(conn)
        await migrator.migrate()

        assert await migrator._column_exists("memories", "is_starred")

        # The pre-existing row must be 0, not NULL — `is_starred = 0` predicates
        # would otherwise silently skip it.
        cursor = await conn.execute("SELECT is_starred FROM memories WHERE id = 'm1'")
        assert cursor.fetchone()["is_starred"] == 0

        cursor = await conn.execute(
            "SELECT MAX(version) AS version FROM _schema_migrations"
        )
        assert cursor.fetchone()["version"] == CURRENT_SCHEMA_VERSION

        # Re-applying the v15 step directly must not raise.
        await migrator._migration_v15_starred(migrator)
        assert await migrator._column_exists("memories", "is_starred")

        await conn.close()
    finally:
        for ext in ["", "-wal", "-shm"]:
            p = path + ext
            if os.path.exists(p):
                os.unlink(p)


@pytest.mark.asyncio
async def test_v16_new_db_has_client_fired_at(temp_db_path):
    """A freshly created DB exposes hook_events.client_fired_at (nullable REAL)."""
    db = Database(temp_db_path)
    await db.connect()

    cursor = await db.execute("PRAGMA table_info(hook_events)")
    cols = {row["name"]: row for row in cursor.fetchall()}
    assert "client_fired_at" in cols
    assert cols["client_fired_at"]["type"] == "REAL"
    assert cols["client_fired_at"]["notnull"] == 0

    await db.close()


@pytest.mark.asyncio
async def test_v16_adds_client_fired_at_from_v15_state():
    """A v15-state hook_events table gains client_fired_at at v16, existing rows
    read NULL (pairing falls back to turn_index), and re-applying is idempotent."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        conn = DatabaseConnection(path)
        await conn.connect()

        conn.connection.execute(
            "CREATE TABLE hook_events (id TEXT PRIMARY KEY, ide_session_id TEXT NOT NULL, "
            "event_name TEXT NOT NULL, turn_index INTEGER NOT NULL DEFAULT 0, prompt TEXT)"
        )
        conn.connection.execute(
            "INSERT INTO hook_events (id, ide_session_id, event_name, turn_index, prompt) "
            "VALUES ('e1', 's1', 'UserPromptSubmit', 0, 'old prompt')"
        )
        conn.connection.execute(
            "CREATE TABLE _schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT)"
        )
        conn.connection.execute(
            "INSERT INTO _schema_migrations (version, applied_at) "
            "VALUES (15, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()

        migrator = SchemaMigrator(conn)
        await migrator.migrate()

        assert await migrator._column_exists("hook_events", "client_fired_at")
        cursor = await conn.execute(
            "SELECT client_fired_at FROM hook_events WHERE id = 'e1'"
        )
        assert cursor.fetchone()["client_fired_at"] is None

        # idempotent: the v16 step on an already-migrated table is a no-op
        await migrator._migration_v16_hook_event_client_time(migrator)
        assert await migrator._get_current_version() == CURRENT_SCHEMA_VERSION
    finally:
        await conn.close()
        for ext in ["", "-wal", "-shm"]:
            if os.path.exists(path + ext):
                os.unlink(path + ext)
