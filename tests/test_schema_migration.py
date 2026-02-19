"""Tests for automatic schema migration system."""

import asyncio
import os
import tempfile
import pytest

from app.core.database import Database, SchemaMigrator, CURRENT_SCHEMA_VERSION
from app.core.database.connection import DatabaseConnection


@pytest.fixture
def temp_db_path():
    """Create a temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


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
        if os.path.exists(path):
            os.unlink(path)


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
        added = await migrator._add_column_if_missing("test_table", "new_col", "TEXT", "'default'")
        assert added is True
        
        # Try to add same column again
        added_again = await migrator._add_column_if_missing("test_table", "new_col", "TEXT", "'default'")
        assert added_again is False
        
        # Verify column exists with default
        conn.connection.execute("INSERT INTO test_table (id) VALUES ('test')")
        conn.commit()
        
        cursor = conn.connection.execute("SELECT new_col FROM test_table WHERE id = 'test'")
        row = cursor.fetchone()
        assert row[0] == "default"
        
        await conn.close()
    finally:
        if os.path.exists(path):
            os.unlink(path)
