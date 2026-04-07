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
        target_dim_str = await self.db.get_embedding_metadata("target_embedding_dimension")
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
        if self._migration_in_progress:
            return {
                "success": False,
                "error": "Migration already in progress",
                "progress": self._migration_progress,
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

    async def _recreate_vector_table(self, new_dim: int) -> None:
        """차원 변경 시 memory_embeddings 가상 테이블 DROP → 재생성"""
        conn = self.db.connection
        try:
            conn.execute("DROP TABLE IF EXISTS memory_embeddings")
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_embeddings USING vec0(
                    memory_id TEXT PRIMARY KEY,
                    embedding FLOAT[{new_dim}]
                )
            """)
            conn.commit()
            logger.info(
                f"Recreated memory_embeddings virtual table with dimension {new_dim}"
            )
        except Exception as e:
            logger.error(f"Failed to recreate vector table: {e}")
            raise

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

        # Migration regenerates all vectors, so always DROP+CREATE the vec table
        # (Safe to run even when metadata is corrupted)
        new_dim = self.embedding_service.dimension
        self._migration_progress["message"] = (
            f"Recreating vector table (dim={new_dim})..."
        )
        if progress_callback:
            progress_callback(self._migration_progress)
        await self._recreate_vector_table(new_dim)

        offset = 0
        batch_num = 0

        while True:
            # Batch-fetch memories
            cursor = await self.db.execute(
                "SELECT id, content FROM memories ORDER BY created_at LIMIT ? OFFSET ?",
                (batch_size, offset),
            )
            memories = cursor.fetchall()

            if not memories:
                break

            batch_num += 1
            self._migration_progress["message"] = f"Processing batch {batch_num}..."

            for memory in memories:
                try:
                    memory_id = memory["id"]
                    content = memory["content"]

                    # Generate new embedding
                    embedding = self.embedding_service.embed(content[:2000])
                    embedding_bytes = self.embedding_service.to_bytes(embedding)

                    # Update memories table
                    now = datetime.now(timezone.utc).isoformat()
                    await self.db.execute(
                        "UPDATE memories SET embedding = ?, updated_at = ? WHERE id = ?",
                        (embedding_bytes, now, memory_id),
                    )

                    # Update vector table
                    embedding_json = json.dumps(embedding)
                    await self.db.execute(
                        "DELETE FROM memory_embeddings WHERE memory_id = ?",
                        (memory_id,),
                    )
                    await self.db.execute(
                        "INSERT INTO memory_embeddings (memory_id, embedding) VALUES (?, ?)",
                        (memory_id, embedding_json),
                    )

                    stats["migrated"] += 1

                except Exception as e:
                    logger.error(f"Failed to migrate memory {memory['id']}: {e}")
                    stats["failed"] += 1

                # Update progress
                processed = stats["migrated"] + stats["failed"]
                self._migration_progress["processed"] = processed
                self._migration_progress["failed"] = stats["failed"]
                self._migration_progress["percent"] = int(
                    (processed / stats["total"]) * 100
                )

                if progress_callback:
                    progress_callback(self._migration_progress)

            # Commit batch
            self.db.connection.commit()
            offset += batch_size

            # Small delay to distribute CPU load
            await asyncio.sleep(0.01)

        # Update metadata: set actual data model to new model
        now = datetime.now(timezone.utc).isoformat()
        new_model = self.embedding_service.model_name
        new_dim = str(self.embedding_service.dimension)
        await self.db.set_embedding_metadata("embedding_model", new_model)
        await self.db.set_embedding_metadata("embedding_dimension", new_dim)
        await self.db.set_embedding_metadata("last_migration", now)

        # Clear target if it matches embedding_model
        target = await self.db.get_embedding_metadata("target_embedding_model")
        if target and target == new_model:
            await self.db.set_embedding_metadata("target_embedding_model", "")
            await self.db.set_embedding_metadata("target_embedding_dimension", "")

        self._migration_progress["status"] = "completed"
        self._migration_progress["message"] = (
            f"Migration completed: {stats['migrated']} migrated, {stats['failed']} failed"
        )

        return {
            "success": True,
            "stats": stats,
            "message": self._migration_progress["message"],
        }

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
