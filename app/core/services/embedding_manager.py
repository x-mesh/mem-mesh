"""
Embedding Model Manager Service

임베딩 모델 상태 확인 및 마이그레이션 관리 서비스
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from ..database.base import Database
from ..embeddings.service import EmbeddingService

logger = logging.getLogger(__name__)


class EmbeddingManagerService:
    """임베딩 모델 관리 서비스"""

    def __init__(self, db: Database, embedding_service: EmbeddingService):
        self.db = db
        self.embedding_service = embedding_service
        self._migration_in_progress = False
        self._migration_progress = {
            "status": "idle",
            "total": 0,
            "processed": 0,
            "failed": 0,
            "percent": 0,
            "message": "",
        }

    async def get_status(self) -> Dict[str, Any]:
        """현재 임베딩 모델 상태 조회"""
        # Model info stored in DB
        stored_model = await self.db.get_embedding_metadata("embedding_model")
        stored_dim_str = await self.db.get_embedding_metadata("embedding_dimension")
        stored_dim = int(stored_dim_str) if stored_dim_str else None
        last_migration = await self.db.get_embedding_metadata("last_migration")

        # Currently configured model info
        current_model = self.embedding_service.model_name
        current_dim = self.embedding_service.dimension

        # Memory and vector table statistics
        cursor = await self.db.execute("SELECT COUNT(*) as count FROM memories")
        total_memories = cursor.fetchone()["count"]

        vector_count = 0
        try:
            cursor = await self.db.execute(
                "SELECT COUNT(*) as count FROM memory_embeddings"
            )
            vector_count = cursor.fetchone()["count"]
        except Exception as e:
            # Table may not exist yet
            logger.debug(f"Failed to count embeddings: {e}")

        # Query target model (goal model selected during onboarding)
        target_model = await self.db.get_embedding_metadata("target_embedding_model")
        target_dim_str = await self.db.get_embedding_metadata(
            "target_embedding_dimension"
        )
        target_dim = int(target_dim_str) if target_dim_str else None

        # Check match: if target exists, compare target vs stored; otherwise stored vs current
        needs_migration = False
        if target_model and stored_model and target_model != stored_model:
            # Model changed in onboarding → need to migrate existing data
            needs_migration = True
        elif target_dim and stored_dim and target_dim != stored_dim:
            needs_migration = True
        elif stored_model and stored_model != current_model:
            needs_migration = True
        elif stored_dim and stored_dim != current_dim:
            needs_migration = True

        return {
            "stored_model": stored_model,
            "stored_dimension": stored_dim,
            "target_model": target_model,
            "target_dimension": target_dim,
            "current_model": current_model,
            "current_dimension": current_dim,
            "total_memories": total_memories,
            "vector_count": vector_count,
            "last_migration": last_migration,
            "needs_migration": needs_migration,
            "migration_in_progress": self._migration_in_progress,
            "migration_progress": self._migration_progress,
        }

    async def start_migration(
        self,
        force: bool = False,
        batch_size: int = 100,
        progress_callback: Optional[Callable[[Dict], None]] = None,
    ) -> Dict[str, Any]:
        """
        임베딩 마이그레이션 시작

        Args:
            force: 모델이 같아도 강제 재임베딩
            batch_size: 배치 크기
            progress_callback: 진행 상황 콜백 함수

        Returns:
            마이그레이션 결과
        """
        async with self.db.transaction():
            if self._migration_in_progress:
                return {
                    "success": False,
                    "error": "Migration already in progress",
                    "progress": self._migration_progress,
                }

            if await self.db.migration_in_progress():
                return {
                    "success": False,
                    "error": "Migration already in progress",
                }

            status = await self.get_status()

            # Check whether migration is needed
            if not force and not status["needs_migration"]:
                return {
                    "success": True,
                    "message": "No migration needed - models match",
                    "skipped": True,
                }

            if status["total_memories"] == 0:
                return {
                    "success": True,
                    "message": "No memories to migrate",
                    "skipped": True,
                }

            self._migration_in_progress = True
            self._migration_progress = {
                "status": "running",
                "total": status["total_memories"],
                "processed": 0,
                "failed": 0,
                "percent": 0,
                "message": "Starting migration...",
            }

            await self.db.set_migration_in_progress(True)

        # Run migration in background
        import asyncio

        asyncio.create_task(
            self._run_migration_background(batch_size, progress_callback)
        )

        return {
            "success": True,
            "message": "Migration started",
            "progress": self._migration_progress,
        }

    async def _run_migration_background(
        self,
        batch_size: int,
        progress_callback: Optional[Callable[[Dict], None]] = None,
    ) -> None:
        """백그라운드에서 마이그레이션 실행"""
        try:
            await self._run_migration(batch_size, progress_callback)
        except Exception as e:
            logger.error(f"Background migration error: {e}")
            self._migration_progress["status"] = "failed"
            self._migration_progress["message"] = f"Migration failed: {str(e)}"
        finally:
            self._migration_in_progress = False
            # Ensure dual-write is disabled even if migration failed mid-way
            # (green is partial and was never swapped in — blue stays active).
            try:
                await self.db.set_migration_in_progress(False)
            except Exception as e:
                logger.warning(f"Failed to clear migration flag: {e}")

    async def _recreate_vector_table(self, table_name: str, new_dim: int) -> None:
        """지정 슬롯의 vec0 가상테이블을 DROP → 재생성(빈 상태로 준비).

        blue-green 마이그레이션은 이 헬퍼로 inactive(green) 슬롯만 비운다.
        active(blue) 슬롯은 건드리지 않아 진행 중 검색이 유지된다.
        """
        if table_name not in {"memory_embeddings", "memory_embeddings_b"}:
            raise ValueError(f"Invalid raw vector table: {table_name}")
        try:
            await self.db.execute(f"DROP TABLE IF EXISTS {table_name}")
            if self.db._connection.is_vec_available:
                await self.db.execute(f"""CREATE VIRTUAL TABLE {table_name} USING vec0(
                        memory_id TEXT PRIMARY KEY,
                        embedding FLOAT[{new_dim}]
                    )""")
            else:
                await self.db.execute(f"""CREATE TABLE {table_name} (
                        memory_id TEXT PRIMARY KEY,
                        embedding BLOB NOT NULL
                    )""")
            self.db.connection.commit()
            logger.info(f"Recreated vector table {table_name} (dim={new_dim})")
        except Exception as e:
            logger.error(f"Failed to recreate vector table {table_name}: {e}")
            raise

    async def _drop_vector_table(self, table_name: str) -> None:
        if table_name not in {"memory_embeddings", "memory_embeddings_b"}:
            raise ValueError(f"Invalid raw vector table: {table_name}")
        await self.db.execute(f"DROP TABLE IF EXISTS {table_name}")
        self.db.connection.commit()

    @staticmethod
    def _embedding_bytes(service: Any, vector: Any) -> bytes:
        values = [float(item) for item in vector]
        if hasattr(service, "to_bytes"):
            value = service.to_bytes(values)
        else:
            import numpy as np

            value = np.asarray(values, dtype=np.float32).tobytes()
        if isinstance(value, memoryview):
            return value.tobytes()
        if not isinstance(value, (bytes, bytearray)):
            raise TypeError("embedding service returned a non-byte vector")
        return bytes(value)

    async def _snapshot_migration_state(self, metadata_keys: tuple[str, ...]) -> dict:
        metadata_rows = await self.db.fetchall(
            "SELECT key, value, updated_at FROM embedding_metadata WHERE key IN ("
            + ",".join("?" for _ in metadata_keys)
            + ")",
            metadata_keys,
        )
        memory_rows = await self.db.fetchall(
            "SELECT id, embedding, updated_at FROM memories ORDER BY id"
        )
        active_rows = await self.db.fetchall(
            "SELECT id, revision FROM curated_results WHERE status = 'active' ORDER BY id"
        )
        state_rows = await self.db.fetchall(
            "SELECT state_key, state_value, updated_at FROM reconciler_state ORDER BY state_key"
        )
        return {
            "metadata": {str(row["key"]): dict(row) for row in metadata_rows},
            "memory_rows": [dict(row) for row in memory_rows],
            "active_curated": tuple(
                (str(row["id"]), int(row["revision"])) for row in active_rows
            ),
            "state_rows": [dict(row) for row in state_rows],
            "active_raw": await self.db.active_embedding_table(),
            "read_revision": await self._read_revision(),
            "curated_active_table": await self.db._migrator.snapshot_curated_active(),
            "db_embedding_dim": self.db.embedding_dim,
        }

    async def _read_revision(self) -> int:
        row = await self.db.fetchone(
            "SELECT state_value FROM reconciler_state WHERE state_key = 'read_revision'"
        )
        try:
            return int(row["state_value"]) if row else 0
        except (TypeError, ValueError):
            return 0

    async def _write_metadata(self, values: dict[str, str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with self.db.transaction():
            for key, value in values.items():
                await self.db.execute(
                    "INSERT INTO embedding_metadata(key, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                    (key, str(value), now),
                )

    async def _restore_migration_state(
        self, snapshot: dict, green: str, promoted: bool
    ) -> None:
        if promoted:
            await self.db._migrator.restore_curated_active(
                snapshot["curated_active_table"]
            )
        await self.db._migrator.invalidate_curated_next()
        await self._drop_vector_table(green)
        async with self.db.transaction():
            for row in snapshot["memory_rows"]:
                await self.db.execute(
                    "UPDATE memories SET embedding = ?, updated_at = ? WHERE id = ?",
                    (row["embedding"], row["updated_at"], row["id"]),
                )
            for key in (
                "embedding_model",
                "embedding_dimension",
                "last_migration",
                "active_embedding_table",
                "migration_in_progress",
                "reconciler_embedding_model",
                "reconciler_embedding_dimension",
                "target_embedding_model",
                "target_embedding_dimension",
            ):
                await self.db.execute(
                    "DELETE FROM embedding_metadata WHERE key = ?", (key,)
                )
            for row in snapshot["metadata"].values():
                await self.db.execute(
                    "INSERT INTO embedding_metadata(key, value, updated_at) VALUES (?, ?, ?)",
                    (row["key"], row["value"], row["updated_at"]),
                )
            await self.db.execute("DELETE FROM reconciler_state")
            for row in snapshot["state_rows"]:
                await self.db.execute(
                    "INSERT INTO reconciler_state(state_key, state_value, updated_at) VALUES (?, ?, ?)",
                    (row["state_key"], row["state_value"], row["updated_at"]),
                )
        self.db._active_embedding_table = snapshot["active_raw"]
        self.db.embedding_dim = snapshot["db_embedding_dim"]

    async def _run_migration(
        self,
        batch_size: int,
        progress_callback: Optional[Callable[[Dict], None]] = None,
    ) -> Dict[str, Any]:
        """실제 마이그레이션 수행"""
        stats = {
            "total": self._migration_progress["total"],
            "migrated": 0,
            "failed": 0,
            "skipped": 0,
        }
        metadata_keys = (
            "embedding_model",
            "embedding_dimension",
            "last_migration",
            "active_embedding_table",
            "migration_in_progress",
            "reconciler_embedding_model",
            "reconciler_embedding_dimension",
            "target_embedding_model",
            "target_embedding_dimension",
        )
        snapshot = await self._snapshot_migration_state(metadata_keys)
        green = await self.db.inactive_embedding_table()
        promoted = False
        migration_started = False
        temp_table = "mem_mesh_embedding_stage"
        try:
            ready = getattr(self.embedding_service, "is_ready", True)
            if not ready:
                self._migration_progress["message"] = "Loading embedding model..."
                if progress_callback:
                    progress_callback(self._migration_progress)
                await asyncio.to_thread(self.embedding_service.load_model)

            new_dim = int(self.embedding_service.dimension)
            new_model = str(getattr(self.embedding_service, "model_name", ""))
            await self.db.set_migration_in_progress(True)
            migration_started = True
            self._migration_progress["message"] = (
                f"Preparing curated and raw green slots (dim={new_dim})..."
            )
            if progress_callback:
                progress_callback(self._migration_progress)

            await self.db._migrator.prepare_curated_next(new_dim)
            curated_rows = await self.db.fetchall(
                "SELECT id, body, revision FROM curated_results "
                "WHERE status = 'active' ORDER BY id"
            )
            expected_curated_ids = [str(row["id"]) for row in curated_rows]
            for row in curated_rows:
                vector = await self.embedding_service.aembed(str(row["body"] or ""))
                if len(vector) != new_dim:
                    raise ValueError(
                        f"curated result {row['id']} returned dimension {len(vector)}, expected {new_dim}"
                    )
                await self.db._migrator.write_curated_next(row["id"], vector)
            if not await self.db._migrator.validate_curated_next(
                expected_curated_ids, new_dim
            ):
                raise ValueError("curated next validation failed")

            await self._recreate_vector_table(green, new_dim)
            await self.db.execute(
                f"CREATE TEMP TABLE {temp_table} ("
                "memory_id TEXT PRIMARY KEY, embedding BLOB NOT NULL, updated_at TEXT NOT NULL)"
            )
            expected_memory_ids = []
            last_id = ""
            while True:
                memories = await self.db.fetchall(
                    "SELECT id, content FROM memories WHERE id > ? ORDER BY id LIMIT ?",
                    (last_id, max(1, batch_size)),
                )
                if not memories:
                    break
                expected_memory_ids.extend(str(memory["id"]) for memory in memories)
                last_id = str(memories[-1]["id"])
                for memory in memories:
                    try:
                        vector = await self.embedding_service.aembed(
                            str(memory["content"] or "")[:2000]
                        )
                        if len(vector) != new_dim:
                            raise ValueError(
                                f"memory {memory['id']} returned dimension {len(vector)}, expected {new_dim}"
                            )
                        values = [float(item) for item in vector]
                        embedding_bytes = self._embedding_bytes(
                            self.embedding_service, values
                        )
                        if len(embedding_bytes) != new_dim * 4:
                            raise ValueError(
                                f"memory {memory['id']} returned invalid embedding bytes"
                            )
                        now = datetime.now(timezone.utc).isoformat()
                        await self.db.execute(
                            f"DELETE FROM {temp_table} WHERE memory_id = ?",
                            (memory["id"],),
                        )
                        await self.db.execute(
                            f"INSERT INTO {temp_table}(memory_id, embedding, updated_at) VALUES (?, ?, ?)",
                            (memory["id"], embedding_bytes, now),
                        )
                        await self.db.execute(
                            f"DELETE FROM {green} WHERE memory_id = ?", (memory["id"],)
                        )
                        vector_table_sql = await self.db._migrator._raw_table_sql(green)
                        await self.db.execute(
                            f"INSERT INTO {green}(memory_id, embedding) VALUES (?, ?)",
                            (
                                memory["id"],
                                (
                                    json.dumps(values)
                                    if vector_table_sql
                                    and "USING VEC0" in vector_table_sql.upper()
                                    else embedding_bytes
                                ),
                            ),
                        )
                        stats["migrated"] += 1
                    except Exception:
                        stats["failed"] += 1
                        self._migration_progress["failed"] = stats["failed"]
                        raise
                    self._migration_progress["processed"] = stats["migrated"]
                    self._migration_progress["percent"] = int(
                        stats["migrated"] / max(stats["total"], 1) * 100
                    )
                    if progress_callback:
                        progress_callback(self._migration_progress)

            if not await self.db._migrator.validate_raw_slot(
                green, expected_memory_ids, new_dim
            ):
                raise ValueError("raw green validation failed")

            async with self.db.transaction():
                current_curated_rows = await self.db.fetchall(
                    "SELECT id, revision FROM curated_results WHERE status = 'active' ORDER BY id"
                )
                current_curated = tuple(
                    (str(row["id"]), int(row["revision"]))
                    for row in current_curated_rows
                )
                if current_curated != snapshot["active_curated"]:
                    raise RuntimeError(
                        "active curated results changed during migration"
                    )
                if await self._read_revision() != snapshot["read_revision"]:
                    raise RuntimeError(
                        "reconciler read revision changed during migration"
                    )

                await self.db._migrator.promote_curated_next(new_dim)
                staged_rows = await self.db.fetchall(
                    f"SELECT memory_id, embedding, updated_at FROM {temp_table}"
                )
                now = datetime.now(timezone.utc).isoformat()
                metadata = {
                    "active_embedding_table": green,
                    "embedding_model": new_model,
                    "embedding_dimension": str(new_dim),
                    "reconciler_embedding_model": new_model,
                    "reconciler_embedding_dimension": str(new_dim),
                    "last_migration": now,
                    "migration_in_progress": "0",
                }
                target_model = await self.db.get_embedding_metadata(
                    "target_embedding_model"
                )
                if target_model and target_model == new_model:
                    metadata["target_embedding_model"] = ""
                    metadata["target_embedding_dimension"] = ""
                async with self.db.transaction():
                    for row in staged_rows:
                        await self.db.execute(
                            "UPDATE memories SET embedding = ?, updated_at = ? WHERE id = ?",
                            (row["embedding"], row["updated_at"], row["memory_id"]),
                        )
                    for key, value in metadata.items():
                        await self.db.execute(
                            "INSERT INTO embedding_metadata(key, value, updated_at) VALUES (?, ?, ?) "
                            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                            (key, value, now),
                        )
                from .effective_read import EffectiveReadService

                await EffectiveReadService(self.db).bump_read_revision(
                    "embedding-migration"
                )
            promoted = True
            self.db._active_embedding_table = green
            self.db.embedding_dim = new_dim
            try:
                await self.db._migrator.invalidate_curated_next()
            except Exception as exc:
                logger.warning(
                    "Failed to retire curated staging table after publication: %s", exc
                )
            try:
                await self._drop_vector_table(snapshot["active_raw"])
            except Exception as exc:
                logger.warning("Failed to retire old raw vector slot: %s", exc)

            self._migration_progress["status"] = "completed"
            self._migration_progress["message"] = (
                f"Migration completed: {stats['migrated']} migrated, {stats['failed']} failed"
            )
            return {
                "success": True,
                "stats": stats,
                "message": self._migration_progress["message"],
            }
        except Exception:
            if migration_started:
                if promoted:
                    await self._restore_migration_state(snapshot, green, promoted)
                else:
                    await self.db._migrator.invalidate_curated_next()
                    await self._drop_vector_table(green)
                    await self.db.set_migration_in_progress(False)
            raise
        finally:
            try:
                await self.db.execute(f"DROP TABLE IF EXISTS temp.{temp_table}")
                self.db.connection.commit()
            except Exception:
                logger.exception("Failed to drop migration staging table")

    def get_migration_progress(self) -> Dict[str, Any]:
        """현재 마이그레이션 진행 상황 조회"""
        return {"in_progress": self._migration_in_progress, **self._migration_progress}

    async def set_model_metadata(self, model_name: str, dimension: int) -> None:
        """모델 메타데이터 수동 설정 (마이그레이션 없이)"""
        now = datetime.now(timezone.utc).isoformat()
        await self.db.set_embedding_metadata("embedding_model", model_name)
        await self.db.set_embedding_metadata("embedding_dimension", str(dimension))
        await self.db.set_embedding_metadata("metadata_set_manually", now)
        # Clear if it matches target
        target = await self.db.get_embedding_metadata("target_embedding_model")
        if target and target == model_name:
            await self.db.set_embedding_metadata("target_embedding_model", "")
            await self.db.set_embedding_metadata("target_embedding_dimension", "")
        logger.info(f"Model metadata set manually: {model_name} (dim: {dimension})")
