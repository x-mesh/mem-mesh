"""Automatic schema migration for mem-mesh.

This module handles automatic database schema migrations:
- Tracks schema version in database
- Auto-adds missing columns
- Runs versioned migration scripts

Similar to Prisma migrations but simpler for SQLite.
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Awaitable, Callable, Dict, Optional

if TYPE_CHECKING:
    from .connection import DatabaseConnection

logger = logging.getLogger(__name__)

# Current schema version - increment when adding new migrations
CURRENT_SCHEMA_VERSION = 20


class SchemaMigrator:
    """Handles automatic schema migrations.

    Features:
    - Version tracking in _schema_migrations table
    - Auto-detection and addition of missing columns
    - Ordered migration execution
    """

    def __init__(self, connection: "DatabaseConnection"):
        self.connection = connection
        self._migrations: Dict[int, Callable[["SchemaMigrator"], Awaitable[None]]] = {
            1: self._migration_v1_initial,
            2: self._migration_v2_work_tracking_columns,
            3: self._migration_v3_relation_tables,
            4: self._migration_v4_pin_columns_integrity,
            5: self._migration_v5_client_column,
            6: self._migration_v6_session_ide_columns,
            7: self._migration_v7_pin_client_column,
            8: self._migration_v8_pin_staging_column,
            9: self._migration_v9_content_bytes,
            10: self._migration_v10_access_tracking,
            11: self._migration_v11_reconcile,
            12: self._migration_v12_injection_anchors,
            13: self._migration_v13_injection_utilization,
            14: self._migration_v14_stale_status,
            15: self._migration_v15_starred,
            16: self._migration_v16_hook_event_client_time,
            17: self._migration_v17_reconciler,
            18: self._migration_v18_external_llm_policy,
            19: self._migration_v19_memory_read_revision,
            20: self._migration_v20_reconciler_protection,
        }

    async def migrate(self) -> None:
        """Run all pending migrations."""
        if not self.connection.connection:
            raise RuntimeError("Database not connected")

        # Ensure migrations table exists
        await self._ensure_migrations_table()

        current_version = await self._get_current_version()
        logger.info(
            f"Current schema version: {current_version}, target: {CURRENT_SCHEMA_VERSION}"
        )

        if current_version >= CURRENT_SCHEMA_VERSION:
            logger.info("Schema is up to date")
            return

        # Run migrations in order
        for version in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
            if version in self._migrations:
                logger.info(f"Running migration v{version}...")
                try:
                    await self._migrations[version](self)
                    await self._set_version(version)
                    self.connection.commit()
                    logger.info(f"Migration v{version} completed")
                except Exception as e:
                    logger.error(f"Migration v{version} failed: {e}")
                    raise

    async def _ensure_migrations_table(self) -> None:
        """Create migrations tracking table if not exists."""
        conn = self.connection.connection
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT
            )
        """)
        self.connection.commit()

    async def _get_current_version(self) -> int:
        """Get current schema version from database."""
        try:
            cursor = await self.connection.execute(
                "SELECT MAX(version) as version FROM _schema_migrations"
            )
            row = cursor.fetchone()
            return row["version"] if row and row["version"] else 0
        except Exception as e:
            logger.debug(f"Failed to get schema version, assuming 0: {e}")
            return 0

    async def _set_version(self, version: int, description: str = "") -> None:
        """Record migration version."""
        await self.connection.execute(
            "DELETE FROM _schema_migrations WHERE version = ?", (version,)
        )
        await self.connection.execute(
            """
            INSERT INTO _schema_migrations (version, applied_at, description)
            VALUES (?, ?, ?)
            """,
            (version, datetime.now(timezone.utc).isoformat(), description),
        )

    async def _column_exists(self, table: str, column: str) -> bool:
        """Check if a column exists in a table."""
        try:
            cursor = await self.connection.execute(f"PRAGMA table_info({table})")
            columns = [row["name"] for row in cursor.fetchall()]
            return column in columns
        except Exception as e:
            logger.debug(f"Failed to check column existence: {e}")
            return False

    async def _add_column_if_missing(
        self, table: str, column: str, column_type: str, default: Optional[str] = None
    ) -> bool:
        """Add column to table if it doesn't exist.

        Returns True if column was added, False if already exists.
        """
        if await self._column_exists(table, column):
            logger.debug(f"Column {table}.{column} already exists")
            return False

        default_clause = f" DEFAULT {default}" if default is not None else ""
        sql = f"ALTER TABLE {table} ADD COLUMN {column} {column_type}{default_clause}"

        try:
            await self.connection.execute(sql)
            logger.info(f"Added column {table}.{column}")
            return True
        except Exception as e:
            logger.error(f"Failed to add column {table}.{column}: {e}")
            raise

    async def _table_exists(self, table: str) -> bool:
        """Check if a table exists."""
        cursor = await self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return cursor.fetchone() is not None

    # ========== Migration Definitions ==========

    async def _migration_v1_initial(self, migrator: "SchemaMigrator") -> None:
        """Initial migration - marks existing databases as v1."""
        # This migration just marks the baseline
        # All tables should already exist from initializer
        logger.info("Marking initial schema version")

    async def _migration_v2_work_tracking_columns(
        self, migrator: "SchemaMigrator"
    ) -> None:
        """Add work tracking columns that may be missing."""

        # pins table columns
        if await self._table_exists("pins"):
            await self._add_column_if_missing(
                "pins", "promoted_to_memory_id", "TEXT", "NULL"
            )
            await self._add_column_if_missing("pins", "auto_importance", "INTEGER", "0")
            await self._add_column_if_missing(
                "pins", "estimated_tokens", "INTEGER", "0"
            )
            await self._add_column_if_missing("pins", "user_id", "TEXT", "'default'")

        # sessions table columns
        if await self._table_exists("sessions"):
            await self._add_column_if_missing(
                "sessions", "user_id", "TEXT", "'default'"
            )
            await self._add_column_if_missing(
                "sessions", "initial_context_tokens", "INTEGER", "0"
            )
            await self._add_column_if_missing(
                "sessions", "total_loaded_tokens", "INTEGER", "0"
            )
            await self._add_column_if_missing(
                "sessions", "total_saved_tokens", "INTEGER", "0"
            )

        # projects table columns (if any new ones needed)
        if await self._table_exists("projects"):
            await self._add_column_if_missing(
                "projects", "global_rules", "TEXT", "NULL"
            )
            await self._add_column_if_missing(
                "projects", "global_context", "TEXT", "NULL"
            )

    async def _migration_v3_relation_tables(self, migrator: "SchemaMigrator") -> None:
        """Add memory_relations table for existing databases."""
        conn = self.connection.connection

        if not await self._table_exists("memory_relations"):
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_relations (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL DEFAULT 'related',
                    strength REAL NOT NULL DEFAULT 1.0,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (source_id) REFERENCES memories(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_id) REFERENCES memories(id) ON DELETE CASCADE
                )
            """)
            logger.info("Created memory_relations table via migration v3")

    async def _migration_v4_pin_columns_integrity(
        self, migrator: "SchemaMigrator"
    ) -> None:
        """Ensure all pin columns exist for databases that skipped earlier migrations."""
        if await self._table_exists("pins"):
            await self._add_column_if_missing("pins", "auto_importance", "INTEGER", "0")
            await self._add_column_if_missing(
                "pins", "estimated_tokens", "INTEGER", "0"
            )
            await self._add_column_if_missing(
                "pins", "promoted_to_memory_id", "TEXT", "NULL"
            )
            await self._add_column_if_missing("pins", "embedding", "BLOB", "NULL")
            await self._add_column_if_missing("pins", "user_id", "TEXT", "'default'")
            logger.info("Pin columns integrity check completed via migration v4")

    async def _migration_v5_client_column(self, migrator: "SchemaMigrator") -> None:
        """Add client column to memories table for tracking creation tool."""
        if await self._table_exists("memories"):
            await self._add_column_if_missing("memories", "client", "TEXT", "NULL")
            logger.info("Added client column to memories table via migration v5")

    async def _migration_v6_session_ide_columns(
        self, migrator: "SchemaMigrator"
    ) -> None:
        """Add IDE session tracking columns to sessions table.

        - ide_session_id: Maps to the IDE's native session ID (e.g. Claude Code session_id)
        - client_type: Identifies the IDE/tool (e.g. 'claude-ai', 'Cursor', 'Windsurf')
        """
        if await self._table_exists("sessions"):
            await self._add_column_if_missing(
                "sessions", "ide_session_id", "TEXT", "NULL"
            )
            await self._add_column_if_missing("sessions", "client_type", "TEXT", "NULL")
            logger.info(
                "Added ide_session_id, client_type columns to sessions table "
                "via migration v6"
            )

    async def _migration_v7_pin_client_column(self, migrator: "SchemaMigrator") -> None:
        """Add client column to pins table for tracking creation source."""
        if await self._table_exists("pins"):
            await self._add_column_if_missing("pins", "client", "TEXT", "NULL")
            logger.info("Added client column to pins table via migration v7")

    async def _migration_v8_pin_staging_column(
        self, migrator: "SchemaMigrator"
    ) -> None:
        """Add is_staging column to pins table for staging pin support."""
        if await self._table_exists("pins"):
            await self._add_column_if_missing("pins", "is_staging", "INTEGER", "0")
            logger.info("Added is_staging column to pins table via migration v8")

    async def _migration_v9_content_bytes(self, migrator: "SchemaMigrator") -> None:
        """Add denormalized content_bytes (= LENGTH(content)) to memories.

        Per-project size aggregates can then SUM(content_bytes) instead of
        SUM(LENGTH(content)). The latter forced a full table scan that paged in
        the inline ~4KB embedding BLOB on every row (~159ms on a 16k-row DB);
        summing the narrow integer column avoids touching the payload. Backfills
        existing rows; the column is kept in sync by add_memory on insert
        (memories are immutable — updates are delete+insert).
        """
        if await self._table_exists("memories"):
            await self._add_column_if_missing(
                "memories", "content_bytes", "INTEGER", "NULL"
            )
            # Idempotent backfill: only fills rows that don't have it yet.
            await self.connection.execute(
                "UPDATE memories SET content_bytes = LENGTH(content) "
                "WHERE content_bytes IS NULL"
            )
            logger.info("Added + backfilled content_bytes on memories via migration v9")

    async def _migration_v10_access_tracking(self, migrator: "SchemaMigrator") -> None:
        """Add recall-tracking columns to memories for usage analytics.

        - access_count: number of times the memory was surfaced by a search.
        - last_accessed_at: ISO8601 timestamp of the most recent surfacing.

        These power the Analytics "recall" panel (most-recalled memories, dead
        memories that were stored but never retrieved). The columns default so
        existing rows and add_memory inserts (which omit them) stay valid; the
        search hot path increments them best-effort on every non-empty query.
        """
        if await self._table_exists("memories"):
            await self._add_column_if_missing(
                "memories", "access_count", "INTEGER", "0"
            )
            await self._add_column_if_missing(
                "memories", "last_accessed_at", "TEXT", "NULL"
            )
            # Idempotent backfill: NULL access_count -> 0 so analytics SQL can
            # treat "never recalled" uniformly without COALESCE everywhere.
            await self.connection.execute(
                "UPDATE memories SET access_count = 0 WHERE access_count IS NULL"
            )
            logger.info(
                "Added access_count/last_accessed_at on memories via migration v10"
            )

    async def _migration_v11_reconcile(self, migrator: "SchemaMigrator") -> None:
        """Write-time reconcile foundation (SSOT #3).

        - memories.status: 'canonical' (default, search-visible) | 'deprecated'
          (superseded, hidden after human approval). Backfill-safe default so
          existing rows and add_memory inserts stay valid.
        - reconcile_queue: mirrors relay_queue_item's lease columns (status/
          attempts/next_attempt_at/locked_by/locked_at/last_error) for the async
          reconcile worker. UNIQUE(new_memory_id, old_memory_id) holds the
          many-to-many conflict set (one new vs N old) — a per-pair row, not
          UNIQUE(new_memory_id) which would silent-drop the 2nd+ candidate (C1).
          new/old content_hash snapshots let the worker revalidate at apply time
          and skip rows whose memories were edited/deleted in between (C2 TOCTOU).
        """
        if await self._table_exists("memories"):
            await self._add_column_if_missing(
                "memories", "status", "TEXT", "'canonical'"
            )
            await self.connection.execute(
                "UPDATE memories SET status = 'canonical' WHERE status IS NULL"
            )
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS reconcile_queue (
                id TEXT PRIMARY KEY,
                new_memory_id TEXT NOT NULL,
                old_memory_id TEXT NOT NULL,
                project_id TEXT,
                similarity REAL,
                new_content_hash TEXT,
                old_content_hash TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL DEFAULT 0,
                locked_by TEXT,
                locked_at REAL,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(new_memory_id, old_memory_id),
                FOREIGN KEY (new_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                FOREIGN KEY (old_memory_id) REFERENCES memories(id) ON DELETE CASCADE
            )
            """)
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_reconcile_queue_claim "
            "ON reconcile_queue(status, next_attempt_at, created_at)"
        )
        logger.info("Added memories.status + reconcile_queue via migration v11")

    async def _migration_v12_injection_anchors(
        self, migrator: "SchemaMigrator"
    ) -> None:
        """Injection instrumentation (M2) + memory anchors (M3) foundation.

        - injected_memories: records every memory surfaced into an IDE session,
          keyed by (ide_session_id, memory_id), so injection effectiveness can be
          measured per turn/position. Written by the injection path (t8), queried
          by the effectiveness analytics (t11). No FK to memories: an injected
          memory may be deleted later, but its injection event should still count.
        - memories.anchors: JSON blob {commit_hash, file_paths, branch} pinning a
          memory to the code state it was captured against. NULL default so
          existing rows and add_memory inserts (which omit it) stay valid.
        """
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS injected_memories (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                ide_session_id TEXT NOT NULL,
                memory_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL DEFAULT 0,
                position INTEGER NOT NULL DEFAULT 0,
                injected_via TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """)
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_injected_memories_session "
            "ON injected_memories(ide_session_id, memory_id)"
        )
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_injected_memories_project_created "
            "ON injected_memories(project_id, created_at)"
        )
        if await self._table_exists("memories"):
            await self._add_column_if_missing("memories", "anchors", "TEXT", "NULL")
        logger.info(
            "Added injected_memories table + memories.anchors via migration v12"
        )

    async def _migration_v13_injection_utilization(
        self, migrator: "SchemaMigrator"
    ) -> None:
        """Injection *utilization* verdict columns on injected_memories (t9).

        v12 recorded what was *injected*; this records whether it was *utilized*.
        The Stop-time judge (HookService.judge_injected) writes one verdict per
        injected row so the weekly review can report an injection hit rate even
        for users with no LLM judge configured — a conservative deterministic
        proxy is better than no signal.

        - utilized: NULL = not yet judged, 0 = judged unused, 1 = judged used.
          NULL default so the v12 rows already on disk stay unjudged until the
          next Stop sweeps them.
        - judged_at: ISO8601 timestamp the verdict was written.
        - judge_method: how the verdict was reached — 'id_ref' | 'keyword' |
          'activity_only' | 'none' (deterministic), reserved for a future
          'llm' method.

        Added via _add_column_if_missing (not folded into the v12 DDL) so a dev
        DB already migrated to v12 gains the columns without a table rebuild.
        """
        if await self._table_exists("injected_memories"):
            await self._add_column_if_missing(
                "injected_memories", "utilized", "INTEGER", "NULL"
            )
            await self._add_column_if_missing(
                "injected_memories", "judged_at", "TEXT", "NULL"
            )
            await self._add_column_if_missing(
                "injected_memories", "judge_method", "TEXT", "NULL"
            )
            logger.info(
                "Added utilized/judged_at/judge_method on injected_memories "
                "via migration v13"
            )

    async def _migration_v14_stale_status(self, migrator: "SchemaMigrator") -> None:
        """Anchor-verification stale columns on memories (t12 — 2-stage stale).

        The server has no git access, so it can only compute a weak *age* signal
        from anchors + created_at at read time (no column needed for that). The
        strong signal is a client that locally verified a memory's anchors
        (file_paths exist, commit reachable) and reported the verdict via the
        ``report_anchor_status`` tool — that verdict is persisted here.

        - stale_status: NULL = never client-verified, 'fresh' = verified intact,
          'stale' = verified rotten (files gone / commit unreachable). A 'stale'
          memory is excluded from auto-injection; 'fresh' clears the weak
          aged-anchor warning. NULL default so v12/v13 rows already on disk stay
          unverified until the next report.
        - stale_checked_at: ISO8601 timestamp the verdict was written.

        Added via _add_column_if_missing (idempotent) so a fresh DB that already
        got the columns from the initializer, and an existing DB that did not,
        both converge without a table rebuild.
        """
        if await self._table_exists("memories"):
            await self._add_column_if_missing(
                "memories", "stale_status", "TEXT", "NULL"
            )
            await self._add_column_if_missing(
                "memories", "stale_checked_at", "TEXT", "NULL"
            )
            logger.info(
                "Added stale_status/stale_checked_at on memories via migration v14"
            )

    async def _migration_v16_hook_event_client_time(
        self, migrator: "SchemaMigrator"
    ) -> None:
        """Client-clock start time on hook events, for Stop/prompt pairing.

        ``get_last_prompt`` picked the prompt with the highest ``turn_index``,
        i.e. record order. A Stop whose send outlives the host's cancel (the
        TERM shield in the forwarders) can be recorded after the next turn's
        prompt and would pair the answer with the wrong question. Hooks now
        send ``hook_fired_at`` (epoch seconds from ``jq now``) and the server
        pairs by that clock; rows without it keep the turn_index path.
        """
        if await self._table_exists("hook_events"):
            await self._add_column_if_missing("hook_events", "client_fired_at", "REAL")
            logger.info("Added client_fired_at column to hook_events via migration v16")

    async def _migration_v15_starred(self, migrator: "SchemaMigrator") -> None:
        """Durable star (favorite) flag on memories.

        A user-set marker meaning "this one matters, keep it in reach" — a
        display/filter axis only. It never touches ``similarity_score``, ranking
        or auto-injection, so mis-starring cannot pollute search. There is no
        lifecycle (no done/dismiss state): the flag simply toggles.

        ``DEFAULT 0`` (not NULL) is load-bearing: relay's memory materialization
        INSERTs an explicit column list that omits this column, so the column
        must supply its own value. For the same reason it is never declared
        ``NOT NULL`` without a default.

        The partial index only covers starred rows — starred memories are a
        small fraction of the table, so it stays tiny while still serving the
        ``starred_only`` filter.
        """
        if await self._table_exists("memories"):
            await self._add_column_if_missing("memories", "is_starred", "INTEGER", "0")
            # Rows added before the column existed can hold NULL; normalize so
            # `is_starred = 1` / `= 0` predicates never miss them.
            await self.connection.execute(
                "UPDATE memories SET is_starred = 0 WHERE is_starred IS NULL"
            )
            # Indexes in the initializer only run on a fresh DB — an existing DB
            # gets the index here.
            await self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_starred "
                "ON memories(is_starred) WHERE is_starred = 1"
            )
            logger.info("Added is_starred on memories via migration v15")

    async def _migration_v17_reconciler(self, migrator: "SchemaMigrator") -> None:
        """Create the immutable Reconciler ledger and derived-result records."""

        statements = [
            """
            CREATE TABLE IF NOT EXISTS reconciler_runs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created', dry_run INTEGER NOT NULL DEFAULT 1,
                detector_version TEXT NOT NULL DEFAULT 'candidate-v1',
                policy_hash TEXT NOT NULL, model TEXT, prompt_version TEXT,
                budget_json TEXT NOT NULL DEFAULT '{}', stats_json TEXT NOT NULL DEFAULT '{}',
                error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS reconciler_inputs (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, project_id TEXT NOT NULL,
                memory_id TEXT NOT NULL, input_hash TEXT NOT NULL, content_hash TEXT,
                metadata_hash TEXT NOT NULL, relation_hash TEXT NOT NULL, anchor_hash TEXT NOT NULL,
                snapshot_json TEXT NOT NULL, captured_at TEXT NOT NULL,
                UNIQUE(run_id, memory_id), FOREIGN KEY(run_id) REFERENCES reconciler_runs(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS reconciler_candidates (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, project_id TEXT NOT NULL,
                group_key TEXT NOT NULL, memory_ids_json TEXT NOT NULL,
                signal_json TEXT NOT NULL DEFAULT '[]', input_policy_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending_judgment', terminal_reason TEXT,
                lease_owner TEXT, lease_until REAL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(project_id, input_policy_hash), FOREIGN KEY(run_id) REFERENCES reconciler_runs(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS reconciler_proposals (
                id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, run_id TEXT NOT NULL,
                project_id TEXT NOT NULL, action TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'needs_approval', representative_memory_id TEXT,
                body TEXT, claims_json TEXT NOT NULL DEFAULT '[]', proposal_json TEXT NOT NULL DEFAULT '{}',
                input_policy_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL DEFAULT 0,
                decision TEXT, decision_actor TEXT, decision_at TEXT, result_id TEXT, error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(candidate_id, input_policy_hash), FOREIGN KEY(candidate_id) REFERENCES reconciler_candidates(id) ON DELETE CASCADE,
                FOREIGN KEY(run_id) REFERENCES reconciler_runs(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS curated_results (
                id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE, candidate_id TEXT NOT NULL,
                project_id TEXT NOT NULL, representative_memory_id TEXT, body TEXT NOT NULL,
                action TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'inactive', revision INTEGER NOT NULL DEFAULT 0,
                input_policy_hash TEXT NOT NULL, created_at TEXT NOT NULL, activated_at TEXT,
                cancelled_at TEXT, stale_at TEXT, stale_reason TEXT,
                FOREIGN KEY(proposal_id) REFERENCES reconciler_proposals(id), FOREIGN KEY(candidate_id) REFERENCES reconciler_candidates(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS curated_sources (
                result_id TEXT NOT NULL, memory_id TEXT NOT NULL, input_hash TEXT NOT NULL,
                source_role TEXT NOT NULL DEFAULT 'source', PRIMARY KEY(result_id, memory_id),
                FOREIGN KEY(result_id) REFERENCES curated_results(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS curated_claims (
                id TEXT PRIMARY KEY, result_id TEXT NOT NULL, claim_id TEXT NOT NULL,
                text TEXT NOT NULL, conditions_json TEXT NOT NULL DEFAULT '[]',
                UNIQUE(result_id, claim_id), FOREIGN KEY(result_id) REFERENCES curated_results(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS curated_claim_sources (
                claim_id TEXT NOT NULL, result_id TEXT NOT NULL, memory_id TEXT NOT NULL,
                input_hash TEXT NOT NULL, PRIMARY KEY(claim_id, memory_id),
                FOREIGN KEY(claim_id) REFERENCES curated_claims(id) ON DELETE CASCADE,
                FOREIGN KEY(result_id) REFERENCES curated_results(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS curated_relations (
                id TEXT PRIMARY KEY, result_id TEXT NOT NULL, source_id TEXT NOT NULL,
                target_id TEXT NOT NULL, relation_type TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, FOREIGN KEY(result_id) REFERENCES curated_results(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS reconciler_receipts (
                id TEXT PRIMARY KEY, proposal_id TEXT, result_id TEXT, operation TEXT NOT NULL,
                from_status TEXT, to_status TEXT, revision INTEGER NOT NULL DEFAULT 0,
                actor TEXT, details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
                UNIQUE(proposal_id, operation, revision)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS reconciler_validations (
                id TEXT PRIMARY KEY, proposal_id TEXT, result_id TEXT, stage TEXT NOT NULL,
                status TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS reconciler_project_policy (
                project_id TEXT PRIMARY KEY, auto_noise_suppression INTEGER NOT NULL DEFAULT 0,
                auto_derived_relations INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS reconciler_state (
                state_key TEXT PRIMARY KEY, state_value TEXT NOT NULL, updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS project_overview_sources (
                project_id TEXT NOT NULL, result_id TEXT NOT NULL, result_revision INTEGER NOT NULL,
                source_hash TEXT NOT NULL, generated_at TEXT NOT NULL, PRIMARY KEY(project_id, result_id),
                FOREIGN KEY(result_id) REFERENCES curated_results(id)
            )
            """,
        ]
        for statement in statements:
            await self.connection.execute(statement)

        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_reconciler_inputs_memory ON reconciler_inputs(memory_id, input_hash)",
            "CREATE INDEX IF NOT EXISTS idx_reconciler_candidates_status ON reconciler_candidates(status, lease_until, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_reconciler_proposals_project_status ON reconciler_proposals(project_id, status, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_curated_results_project_status ON curated_results(project_id, status, revision)",
            "CREATE INDEX IF NOT EXISTS idx_curated_sources_memory ON curated_sources(memory_id, result_id)",
            "CREATE INDEX IF NOT EXISTS idx_curated_claim_sources_result ON curated_claim_sources(result_id, memory_id)",
            "CREATE INDEX IF NOT EXISTS idx_curated_relations_active ON curated_relations(source_id, target_id, active)",
        ]
        for statement in indexes:
            await self.connection.execute(statement)
        logger.info("Added Memory Reconciler ledger via migration v17")

    async def _migration_v18_external_llm_policy(
        self, migrator: "SchemaMigrator"
    ) -> None:
        if await self._table_exists("reconciler_project_policy"):
            await self._add_column_if_missing(
                "reconciler_project_policy",
                "allow_external_llm",
                "INTEGER NOT NULL",
                "0",
            )

    async def _migration_v19_memory_read_revision(
        self, migrator: "SchemaMigrator"
    ) -> None:
        if not await self._table_exists("memories") or not await self._table_exists(
            "reconciler_state"
        ):
            logger.warning(
                "Skipped memory read revision triggers: required table missing"
            )
            return
        update_columns = (
            "content, content_hash, project_id, category, source, client, tags, "
            "status, anchors, stale_status, is_starred, embedding, created_at, updated_at"
        )
        events = (
            ("insert", "AFTER INSERT"),
            ("update", f"AFTER UPDATE OF {update_columns}"),
            ("delete", "AFTER DELETE"),
        )
        for name, event in events:
            await self.connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS trg_memories_read_revision_{name} "
                f"{event} ON memories BEGIN "
                "INSERT INTO reconciler_state(state_key, state_value, updated_at) "
                "VALUES ('read_revision', '1', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
                "ON CONFLICT(state_key) DO UPDATE SET "
                "state_value = CAST(CAST(state_value AS INTEGER) + 1 AS TEXT), "
                "updated_at = excluded.updated_at; END"
            )

    async def _migration_v20_reconciler_protection(
        self, migrator: "SchemaMigrator"
    ) -> None:
        if not await self._table_exists("memories"):
            return
        await self._add_column_if_missing(
            "memories", "reconciler_protected", "INTEGER NOT NULL", "0"
        )
        if not await self._table_exists("reconciler_state"):
            return
        await self.connection.execute(
            "DROP TRIGGER IF EXISTS trg_memories_read_revision_update"
        )
        update_columns = (
            "content, content_hash, project_id, category, source, client, tags, "
            "status, anchors, stale_status, is_starred, embedding, created_at, "
            "updated_at, reconciler_protected"
        )
        await self.connection.execute(
            "CREATE TRIGGER trg_memories_read_revision_update "
            f"AFTER UPDATE OF {update_columns} ON memories BEGIN "
            "INSERT INTO reconciler_state(state_key, state_value, updated_at) "
            "VALUES ('read_revision', '1', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
            "ON CONFLICT(state_key) DO UPDATE SET "
            "state_value = CAST(CAST(state_value AS INTEGER) + 1 AS TEXT), "
            "updated_at = excluded.updated_at; END"
        )
