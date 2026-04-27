"""
Memory Service for mem-mesh
메모리 CRUD 작업을 담당하는 서비스
"""

import json
import logging
from datetime import datetime
from typing import Any, List, Optional

from ..database.base import Database
from ..database.models import Memory
from ..embeddings.service import EmbeddingService
from ..errors import (
    DatabaseError,
    EmbeddingError,
    MemoryNotFoundError,
)
from ..schemas.responses import AddResponse, ConflictInfo, DeleteResponse, UpdateResponse
from .quality_gate import content_quality_gate

logger = logging.getLogger(__name__)


class MemoryService:
    """메모리 저장/조회/삭제/업데이트 서비스"""

    def __init__(
        self,
        db: Database,
        embedding_service: EmbeddingService,
        conflict_detector: Any = None,
    ):
        self.db = db
        self.embedding_service = embedding_service
        self.max_retries = 3

        # Conflict detector: injected externally or auto-created based on settings
        if conflict_detector is not None:
            self.conflict_detector = conflict_detector
        else:
            self.conflict_detector = self._init_conflict_detector()

        logger.info(
            "MemoryService initialized (conflict_detection=%s)",
            self.conflict_detector is not None,
        )

    # ------------------------------------------------------------------
    # DRY helpers
    # ------------------------------------------------------------------

    async def _resolve_vector_table(self) -> str:
        """벡터 인덱스에 사용할 테이블 이름을 반환한다.

        Returns:
            ``"memory_embeddings"`` (sqlite-vec) 또는
            ``"memories_vec_fallback"`` (폴백).
        """
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='memory_embeddings'"
        )
        if cursor.fetchone():
            return "memory_embeddings"
        return "memories_vec_fallback"

    @staticmethod
    def _embedding_to_json(embedding_bytes: bytes) -> str:
        """embedding bytes -> JSON 문자열 변환.

        ``np.frombuffer`` + ``json.dumps`` 패턴을 한곳으로 모은다.
        numpy는 선택적 의존성이므로 호출 시점에 import한다.
        """
        import numpy as np

        embedding_array = np.frombuffer(embedding_bytes, dtype=np.float32)
        return json.dumps(embedding_array.tolist())

    # ------------------------------------------------------------------

    @staticmethod
    def _init_conflict_detector() -> Any:
        """설정 기반 ConflictDetectorService 자동 생성 (lazy-load, graceful degradation)."""
        try:
            from ..config import get_settings

            settings = get_settings()
            if not settings.enable_conflict_detection:
                return None

            from .conflict_detector import ConflictDetectorService

            detector = ConflictDetectorService(
                model_name=settings.conflict_nli_model,
                preload=settings.enable_conflict_detection,  # Auto-preload when enabled
                contradiction_threshold=settings.conflict_contradiction_threshold,
                similarity_threshold=settings.conflict_similarity_threshold,
                max_candidates=settings.conflict_max_candidates,
            )
            logger.info(
                "ConflictDetectorService initialized (NLI available=%s)",
                detector.is_available,
            )
            return detector
        except Exception as e:
            logger.warning("Failed to initialize ConflictDetectorService: %s", e)
            return None

    async def create(
        self,
        content: str,
        project_id: Optional[str] = None,
        category: str = "task",
        source: str = "unknown",
        client: Optional[str] = None,
        tags: Optional[List[str]] = None,
        skip_quality_gate: bool = False,
    ) -> AddResponse:
        """
        새 메모리 생성 (중복 감지 포함)

        Args:
            content: 메모리 내용
            project_id: 프로젝트 식별자
            category: 메모리 카테고리
            source: 메모리 생성 소스
            tags: 태그 목록

        Returns:
            AddResponse: 생성 결과

        Raises:
            ValueError: 입력 검증 실패
            EmbeddingError: 임베딩 생성 실패
            DatabaseError: 데이터베이스 작업 실패
        """
        logger.info("Creating memory with content length: %d", len(content))

        # 0. Quality gate (stripping + validation)
        if not skip_quality_gate:
            content = content_quality_gate(content)

        # 1. Calculate content_hash
        content_hash = Memory.compute_hash(content)

        # 2. Duplicate check
        existing_memory = await self._find_duplicate(content_hash, project_id)
        if existing_memory:
            logger.info("Duplicate memory found: %s", existing_memory["id"])
            return AddResponse(
                id=existing_memory["id"],
                status="duplicate",
                created_at=existing_memory["created_at"],
            )

        # 3. Generate embedding (with retry logic)
        embedding_vector = await self._generate_embedding_with_retry(content)
        embedding_bytes = self.embedding_service.to_bytes(embedding_vector)

        # 3.5. Conflict detection
        conflict_infos: list[ConflictInfo] | None = None
        if self.conflict_detector is not None:
            conflict_infos = await self._check_conflicts(
                content, embedding_vector, project_id
            )

        # 4. Create Memory object
        memory = Memory(
            content=content,
            content_hash=content_hash,
            project_id=project_id,
            category=category,
            source=source,
            client=client,
            embedding=embedding_bytes,
            tags=json.dumps(tags) if tags else None,
        )

        # 5. Save to DB (transaction)
        try:
            async with self.db.transaction():
                await self.db.add_memory(memory.model_dump())
                await self._save_to_vector_index(memory.id, embedding_bytes)

            logger.info("Memory created successfully: %s", memory.id)
            return AddResponse(
                id=memory.id,
                status="saved",
                created_at=memory.created_at,
                conflicts=conflict_infos if conflict_infos else None,
            )

        except Exception as e:
            logger.error("Failed to save memory: %s", e)
            raise DatabaseError(f"Failed to save memory: {e}") from e

    async def create_with_embedding(
        self,
        content: str,
        embedding: List[float],
        project_id: Optional[str] = None,
        category: str = "task",
        source: str = "unknown",
        tags: Optional[List[str]] = None,
    ) -> AddResponse:
        """
        미리 계산된 임베딩과 함께 새 메모리 생성.

        배치/마이그레이션 작업용 -- content_quality_gate 및
        conflict detection을 의도적으로 생략합니다.

        Args:
            content: 메모리 내용
            embedding: 미리 계산된 임베딩 벡터
            project_id: 프로젝트 식별자
            category: 메모리 카테고리
            source: 메모리 생성 소스
            tags: 태그 목록

        Returns:
            AddResponse: 생성 결과

        Raises:
            ValueError: 입력 검증 실패
            DatabaseError: 데이터베이스 작업 실패
        """
        logger.info(
            "Creating memory with pre-computed embedding, content length: %d",
            len(content),
        )

        # 1. Calculate content_hash
        content_hash = Memory.compute_hash(content)

        # 2. Duplicate check
        existing_memory = await self._find_duplicate(content_hash, project_id)
        if existing_memory:
            logger.info("Duplicate memory found: %s", existing_memory["id"])
            return AddResponse(
                id=existing_memory["id"],
                status="duplicate",
                created_at=existing_memory["created_at"],
            )

        # 3. Convert embedding to bytes (use pre-calculated)
        embedding_bytes = self.embedding_service.to_bytes(embedding)

        # 4. Create Memory object
        memory = Memory(
            content=content,
            content_hash=content_hash,
            project_id=project_id,
            category=category,
            source=source,
            tags=json.dumps(tags) if tags else None,
            embedding=embedding_bytes,
        )

        try:
            async with self.db.transaction():
                await self.db.add_memory(memory.model_dump())
                await self._save_to_vector_index(memory.id, embedding_bytes)

            logger.info("Memory created with pre-computed embedding: %s", memory.id)
            return AddResponse(
                id=memory.id, status="saved", created_at=memory.created_at
            )

        except Exception as e:
            logger.error("Failed to save memory with embedding: %s", e)
            raise DatabaseError(f"Failed to save memory: {e}") from e

    # Alias for backward compatibility
    async def add_with_embedding(self, *args, **kwargs) -> AddResponse:
        """Alias for create_with_embedding for backward compatibility"""
        return await self.create_with_embedding(*args, **kwargs)

    async def get(self, memory_id: str) -> Optional[Memory]:
        """
        ID로 메모리 조회

        Args:
            memory_id: 메모리 ID

        Returns:
            Memory 객체 또는 None
        """
        logger.debug("Getting memory: %s", memory_id)

        try:
            row = await self.db.fetchone(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            )

            if row is None:
                return None

            # Convert SQLite Row to Memory object
            memory_dict = dict(row)
            return Memory(**memory_dict)

        except Exception as e:
            logger.error("Failed to get memory %s: %s", memory_id, e)
            raise DatabaseError(f"Failed to get memory: {e}") from e

    async def update(
        self,
        memory_id: str,
        content: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> UpdateResponse:
        """
        메모리 업데이트 (content 변경 시 재임베딩)

        Args:
            memory_id: 업데이트할 메모리 ID
            content: 새로운 내용 (선택적)
            category: 새로운 카테고리 (선택적)
            tags: 새로운 태그 목록 (선택적)

        Returns:
            UpdateResponse: 업데이트 결과

        Raises:
            MemoryNotFoundError: 메모리를 찾을 수 없음
            EmbeddingError: 임베딩 생성 실패
            DatabaseError: 데이터베이스 작업 실패
        """
        logger.info("Updating memory: %s", memory_id)

        # 1. Fetch existing memory
        existing_memory = await self.get(memory_id)
        if existing_memory is None:
            raise MemoryNotFoundError(memory_id)

        # 2. Quality gate (when content changes)
        if content is not None:
            content = content_quality_gate(content)

        # 3. Determine fields to update
        content_changed = content is not None and content != existing_memory.content

        try:
            async with self.db.transaction():
                if content_changed:
                    # Content changed: re-embedding required
                    logger.info("Content changed, regenerating embedding")

                    # Generate new embedding
                    embedding_vector = await self._generate_embedding_with_retry(
                        content
                    )
                    embedding_bytes = self.embedding_service.to_bytes(embedding_vector)

                    # Recalculate content_hash
                    content_hash = Memory.compute_hash(content)

                    # Update query
                    await self.db.execute(
                        """
                        UPDATE memories
                        SET content = ?, content_hash = ?, category = ?, tags = ?,
                            embedding = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            content,
                            content_hash,
                            category or existing_memory.category,
                            (
                                json.dumps(tags)
                                if tags is not None
                                else existing_memory.tags
                            ),
                            embedding_bytes,
                            datetime.utcnow().isoformat() + "Z",
                            memory_id,
                        ),
                    )

                    # Update vector index
                    await self._update_vector_index(memory_id, embedding_bytes)

                else:
                    # Only metadata changed: keep existing embedding
                    logger.info("Only metadata changed, keeping existing embedding")

                    await self.db.execute(
                        """
                        UPDATE memories
                        SET category = ?, tags = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            category or existing_memory.category,
                            (
                                json.dumps(tags)
                                if tags is not None
                                else existing_memory.tags
                            ),
                            datetime.utcnow().isoformat() + "Z",
                            memory_id,
                        ),
                    )

            logger.info("Memory updated successfully: %s", memory_id)
            return UpdateResponse(id=memory_id, status="updated")

        except Exception as e:
            logger.error("Failed to update memory %s: %s", memory_id, e)
            raise DatabaseError(f"Failed to update memory: {e}") from e

    async def delete(self, memory_id: str) -> DeleteResponse:
        """
        메모리 삭제 (SQLite + 벡터 인덱스)

        Args:
            memory_id: 삭제할 메모리 ID

        Returns:
            DeleteResponse: 삭제 결과

        Raises:
            MemoryNotFoundError: 메모리를 찾을 수 없음
            DatabaseError: 데이터베이스 작업 실패
        """
        logger.info("Deleting memory: %s", memory_id)

        # 1. Verify memory exists
        existing_memory = await self.get(memory_id)
        if existing_memory is None:
            raise MemoryNotFoundError(memory_id)

        try:
            async with self.db.transaction():
                # 2. Explicitly delete from FTS5 index (triggers may fail in async context)
                await self._delete_from_fts_index(memory_id)

                # 3. Delete from SQLite
                await self.db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

                # 4. Delete from vector index
                await self._delete_from_vector_index(memory_id)

            logger.info("Memory deleted successfully: %s", memory_id)
            return DeleteResponse(id=memory_id, status="deleted")

        except Exception as e:
            logger.error("Failed to delete memory %s: %s", memory_id, e)
            raise DatabaseError(f"Failed to delete memory: {e}") from e

    # Private helper methods

    async def _find_duplicate(
        self, content_hash: str, project_id: Optional[str]
    ) -> Optional[dict]:
        """중복 메모리 검색"""
        try:
            row = await self.db.fetchone(
                "SELECT id, created_at FROM memories WHERE content_hash = ? AND project_id = ?",
                (content_hash, project_id),
            )
            return dict(row) if row else None
        except Exception as e:
            logger.error("Failed to check for duplicates: %s", e)
            raise DatabaseError(f"Failed to check for duplicates: {e}") from e

    async def _generate_embedding_with_retry(self, content: str) -> List[float]:
        """재시도 로직을 포함한 임베딩 생성"""
        last_error = None

        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    "Generating embedding (attempt %d/%d)",
                    attempt + 1,
                    self.max_retries,
                )
                return self.embedding_service.embed(content)

            except Exception as e:
                last_error = e
                logger.warning(
                    "Embedding generation failed (attempt %d): %s",
                    attempt + 1,
                    e,
                )

                if attempt < self.max_retries - 1:
                    # Exponential backoff
                    import asyncio

                    delay = 0.1 * (2**attempt)
                    await asyncio.sleep(min(delay, 1.0))

        logger.error(
            "Embedding generation failed after %d attempts", self.max_retries
        )
        raise EmbeddingError(
            f"Failed to generate embedding after {self.max_retries} attempts: {last_error}"
        )

    async def _save_to_vector_index(
        self, memory_id: str, embedding_bytes: bytes
    ) -> None:
        """벡터 인덱스에 저장"""
        try:
            table = await self._resolve_vector_table()

            if table == "memory_embeddings":
                embedding_json = self._embedding_to_json(embedding_bytes)

                # Save to vector table (use DELETE + INSERT pattern)
                await self.db.execute(
                    "DELETE FROM memory_embeddings WHERE memory_id = ?", (memory_id,)
                )
                await self.db.execute(
                    "INSERT INTO memory_embeddings (memory_id, embedding) VALUES (?, ?)",
                    (memory_id, embedding_json),
                )
                logger.debug("Saved to vector table: %s", memory_id)
            else:
                # Use fallback table
                await self.db.execute(
                    "INSERT INTO memories_vec_fallback (memory_id, embedding) VALUES (?, ?)",
                    (memory_id, embedding_bytes),
                )
                logger.debug("Saved to fallback table: %s", memory_id)

        except Exception as e:
            logger.error("Failed to save to vector index: %s", e)
            raise DatabaseError(f"Failed to save to vector index: {e}") from e

    async def _check_conflicts(
        self,
        content: str,
        embedding_vector: List[float],
        project_id: Optional[str] = None,
    ) -> list[ConflictInfo] | None:
        """Stage 1+2 충돌 감지: 벡터 유사도 -> NLI contradiction 체크.

        Returns:
            충돌 목록 (없으면 None)
        """
        if self.conflict_detector is None:
            return None

        try:
            embedding_bytes = self.embedding_service.to_bytes(embedding_vector)
            embedding_json = self._embedding_to_json(embedding_bytes)

            # Stage 1: Search candidates by vector similarity
            cursor = await self.db.execute(
                """
                SELECT m.id, m.content,
                       vec_distance_cosine(e.embedding, ?) AS distance
                FROM memory_embeddings e
                JOIN memories m ON m.id = e.memory_id
                WHERE m.project_id = ? OR ? IS NULL
                ORDER BY distance ASC
                LIMIT ?
                """,
                (
                    embedding_json,
                    project_id,
                    project_id,
                    self.conflict_detector.max_candidates,
                ),
            )

            rows = cursor.fetchall()
            if not rows:
                return None

            candidates = []
            for row in rows:
                # Convert distance -> similarity
                similarity = max(0.0, min(1.0, 1.0 - (row[2] / 2.0)))
                candidates.append({
                    "id": row[0],
                    "content": row[1],
                    "similarity_score": similarity,
                })

            # Stage 2: Detect conflicts via ConflictDetectorService (blocking call -> thread)
            import asyncio

            conflicts = await asyncio.to_thread(
                self.conflict_detector.detect_conflicts, content, candidates
            )

            if not conflicts:
                return None

            return [
                ConflictInfo(
                    memory_id=c.memory_id,
                    content_preview=c.content_preview,
                    contradiction_score=c.contradiction_score,
                    similarity_score=c.similarity_score,
                )
                for c in conflicts
            ]

        except Exception as e:
            # Conflict detection failure does not block save (graceful degradation)
            logger.warning("Conflict detection failed (non-blocking): %s", e)
            return None

    async def _update_vector_index(
        self, memory_id: str, embedding_bytes: bytes
    ) -> None:
        """벡터 인덱스 업데이트"""
        try:
            table = await self._resolve_vector_table()

            if table == "memory_embeddings":
                embedding_json = self._embedding_to_json(embedding_bytes)

                # Update vector table (use DELETE + INSERT pattern)
                await self.db.execute(
                    "DELETE FROM memory_embeddings WHERE memory_id = ?", (memory_id,)
                )
                await self.db.execute(
                    "INSERT INTO memory_embeddings (memory_id, embedding) VALUES (?, ?)",
                    (memory_id, embedding_json),
                )
                logger.debug("Updated vector table: %s", memory_id)
            else:
                # Use fallback table
                await self.db.execute(
                    "UPDATE memories_vec_fallback SET embedding = ? WHERE memory_id = ?",
                    (embedding_bytes, memory_id),
                )
                logger.debug("Updated fallback table: %s", memory_id)

        except Exception as e:
            logger.error("Failed to update vector index: %s", e)
            raise DatabaseError(f"Failed to update vector index: {e}") from e

    async def _delete_from_fts_index(self, memory_id: str) -> None:
        """FTS5 인덱스에서 명시적 삭제"""
        try:
            cursor = await self.db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='memories_fts'"
            )

            if cursor.fetchone():
                await self.db.execute(
                    "DELETE FROM memories_fts WHERE id = ?", (memory_id,)
                )
                logger.debug("Deleted from FTS index: %s", memory_id)

        except Exception as e:
            logger.warning("Failed to delete from FTS index (non-fatal): %s", e)

    async def _delete_from_vector_index(self, memory_id: str) -> None:
        """벡터 인덱스에서 삭제"""
        try:
            table = await self._resolve_vector_table()

            if table == "memory_embeddings":
                await self.db.execute(
                    "DELETE FROM memory_embeddings WHERE memory_id = ?", (memory_id,)
                )
                logger.debug("Deleted from vector table: %s", memory_id)
            else:
                await self.db.execute(
                    "DELETE FROM memories_vec_fallback WHERE memory_id = ?",
                    (memory_id,),
                )
                logger.debug("Deleted from fallback table: %s", memory_id)

        except Exception as e:
            logger.error("Failed to delete from vector index: %s", e)
            raise DatabaseError(f"Failed to delete from vector index: {e}") from e
