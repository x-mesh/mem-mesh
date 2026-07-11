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


def test_current_schema_version_is_15():
    """CURRENT_SCHEMA_VERSION bumped to 15 for the memories.is_starred flag."""
    assert CURRENT_SCHEMA_VERSION == 15


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
