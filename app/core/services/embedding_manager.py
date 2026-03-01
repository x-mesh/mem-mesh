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
        # DB에 저장된 모델 정보
        stored_model = await self.db.get_embedding_metadata("embedding_model")
        stored_dim_str = await self.db.get_embedding_metadata("embedding_dimension")
        stored_dim = int(stored_dim_str) if stored_dim_str else None
        last_migration = await self.db.get_embedding_metadata("last_migration")

        # 현재 설정된 모델 정보
        current_model = self.embedding_service.model_name
        current_dim = self.embedding_service.dimension

        # 메모리 및 벡터 테이블 통계
        cursor = await self.db.execute("SELECT COUNT(*) as count FROM memories")
        total_memories = cursor.fetchone()["count"]

        vector_count = 0
        try:
            cursor = await self.db.execute(
                "SELECT COUNT(*) as count FROM memory_embeddings"
            )
            vector_count = cursor.fetchone()["count"]
        except Exception:
            # Silently ignore errors when counting embeddings - table may not exist yet
            pass

        # 일치 여부 확인
        needs_migration = False
        if stored_model and stored_model != current_model:
            needs_migration = True
        elif stored_dim and stored_dim != current_dim:
            needs_migration = True

        return {
            "stored_model": stored_model,
            "stored_dimension": stored_dim,
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

        # 마이그레이션 필요 여부 확인
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

        # 백그라운드에서 마이그레이션 실행
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

        offset = 0
        batch_num = 0

        while True:
            # 메모리 배치 조회
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

                    # 새 임베딩 생성
                    embedding = self.embedding_service.embed(content[:2000])
                    embedding_bytes = self.embedding_service.to_bytes(embedding)

                    # memories 테이블 업데이트
                    now = datetime.now(timezone.utc).isoformat()
                    await self.db.execute(
                        "UPDATE memories SET embedding = ?, updated_at = ? WHERE id = ?",
                        (embedding_bytes, now, memory_id),
                    )

                    # 벡터 테이블 업데이트
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

                # 진행 상황 업데이트
                processed = stats["migrated"] + stats["failed"]
                self._migration_progress["processed"] = processed
                self._migration_progress["failed"] = stats["failed"]
                self._migration_progress["percent"] = int(
                    (processed / stats["total"]) * 100
                )

                if progress_callback:
                    progress_callback(self._migration_progress)

            # 배치 커밋
            self.db.connection.commit()
            offset += batch_size

            # 약간의 딜레이로 CPU 부하 분산
            await asyncio.sleep(0.01)

        # 메타데이터 업데이트
        now = datetime.now(timezone.utc).isoformat()
        await self.db.set_embedding_metadata(
            "embedding_model", self.embedding_service.model_name
        )
        await self.db.set_embedding_metadata(
            "embedding_dimension", str(self.embedding_service.dimension)
        )
        await self.db.set_embedding_metadata("last_migration", now)

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
        logger.info(f"Model metadata set manually: {model_name} (dim: {dimension})")
