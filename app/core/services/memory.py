"""
Memory Service for mem-mesh
메모리 CRUD 작업을 담당하는 서비스
"""

import json
import logging
from datetime import datetime
from typing import Any, List, Optional
from uuid import uuid4

from ..database.base import Database
from ..database.models import Memory
from ..embeddings.service import EmbeddingService
from ..errors import (
    DatabaseError,
    EmbeddingError,
    MemoryNotFoundError,
)
from ..redaction import redact_secrets
from ..schemas.responses import (
    AddResponse,
    DeleteResponse,
    UpdateResponse,
)
from .quality_gate import content_quality_gate, derivability_hint

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
        """검색/단일 조회에 쓸 active 벡터 테이블(blue-green) 또는 fallback.

        Returns:
            active 슬롯명(``memory_embeddings`` / ``memory_embeddings_b``) 또는
            ``"memories_vec_fallback"`` (vec0 미가용 폴백).
        """
        active = await self.db.active_embedding_table()
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (active,),
        )
        if cursor.fetchone():
            return active
        return "memories_vec_fallback"

    async def _write_vector_tables(self) -> list[str]:
        """벡터 write 대상 테이블 목록.

        마이그레이션 진행 중에는 active(검색용) + inactive(재임베딩 대상, green)
        양쪽에 dual-write 한다. 그래야 진행 중 들어온 신규 메모리가 포인터 스왑
        이후에도 (새 active가 된 green에) 남아 유실되지 않는다.
        """
        active = await self.db.active_embedding_table()
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (active,),
        )
        if not cursor.fetchone():
            return ["memories_vec_fallback"]
        tables = [active]
        if await self.db.migration_in_progress():
            inactive = await self.db.inactive_embedding_table()
            cur2 = await self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (inactive,),
            )
            if cur2.fetchone():
                tables.append(inactive)
        return tables

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

    def _init_conflict_detector(self) -> Any:
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
                # Scale the cosine gate to the active embedding model. The Stage-1
                # vector filter compares raw cosine, and arctic-ko scores lower
                # than KURE — a fixed 0.7 would drop every candidate and silently
                # disable dup/conflict detection. KURE is unchanged (identity).
                similarity_threshold=self.embedding_service.scaled_threshold(
                    settings.conflict_similarity_threshold
                ),
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
        anchors: Optional[dict] = None,
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
            anchors: git 앵커 dict (commit_hash/file_paths/branch) — 표시·수명
                판단용 메타데이터. 검색/임베딩에는 포함하지 않는다.

        Returns:
            AddResponse: 생성 결과

        Raises:
            ValueError: 입력 검증 실패
            EmbeddingError: 임베딩 생성 실패
            DatabaseError: 데이터베이스 작업 실패
        """
        logger.info("Creating memory with content length: %d", len(content))

        # 0. Redact secrets/PII at the single save chokepoint (CLAUDE.md M4).
        # Every save path — HTTP hook, command hook (POST /api/memories),
        # explicit MCP add, direct storage, pin promotion — flows through
        # create(), so redacting here guarantees no credential reaches
        # long-term memory regardless of hook mode. Idempotent, so an upstream
        # caller that already redacted (e.g. the HTTP hook) is harmless. Done
        # before hashing/embedding so dedup and vectors reflect the safe text.
        content = redact_secrets(content)

        # 0.5 Quality gate (stripping + validation)
        if not skip_quality_gate:
            content = content_quality_gate(content)

        # 0.6 Derivability pre-check (R17). Conversation dumps and pasted git
        # output are low-value long-term memory, but a hard reject would lose
        # real content. So this pure/synchronous rule check (no LLM on the write
        # path — CLAUDE.md L1/L5) only *classifies*; the memory is still stored
        # and later routed to the async improve worker to be distilled.
        quality_hint_kind = (
            None if skip_quality_gate else derivability_hint(content, category)
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

        # 3. Generate embedding (with retry logic)
        embedding_vector = await self._generate_embedding_with_retry(content)
        embedding_bytes = self.embedding_service.to_bytes(embedding_vector)

        # 3.5. F1 sync gate (reconcile): nearest-neighbor candidates only.
        # The NLI/LLM contradiction judgment is moved off the write path to the
        # async reconcile worker (per-add cross-encoder = L1 system-stall risk).
        # Gated by reconcile_enabled (env enable_conflict_detection OR app_config
        # reconcile.enabled) — F1 needs no NLI model, only vector candidates.
        reconcile_on = await self._reconcile_enabled()
        reconcile_candidates: list[dict] | None = None
        if reconcile_on:
            reconcile_candidates = await self._find_reconcile_candidates(
                embedding_vector, project_id
            )

        # 4. Create Memory object (status defaults to 'canonical': new memories
        # are immediately search-visible; only superseded old rows are demoted,
        # and only after human approval).
        memory = Memory(
            content=content,
            content_hash=content_hash,
            project_id=project_id,
            category=category,
            source=source,
            client=client,
            embedding=embedding_bytes,
            tags=json.dumps(tags) if tags else None,
            anchors=json.dumps(anchors) if anchors else None,
        )

        # 5. Save + enqueue reconcile in ONE transaction (C2: a canonical memory
        # is never left without its queue rows).
        try:
            async with self.db.transaction():
                await self.db.add_memory(memory.model_dump())
                await self._save_to_vector_index(memory.id, embedding_bytes)
                if reconcile_candidates:
                    await self._enqueue_reconcile(
                        memory.id,
                        memory.content_hash,
                        reconcile_candidates,
                        project_id,
                    )

            logger.info("Memory created successfully: %s", memory.id)
            response = AddResponse(
                id=memory.id,
                status="saved",
                created_at=memory.created_at,
                conflicts=None,
            )

        except Exception as e:
            logger.error("Failed to save memory: %s", e)
            raise DatabaseError(f"Failed to save memory: {e}") from e

        # 5.5 C2 post-commit re-scan: a concurrent add that committed between the
        # pre-save scan and this commit was invisible mid-transaction, so neither
        # add saw the other. Re-scanning after commit lets the later committer
        # catch the earlier one and enqueue the pair. INSERT OR IGNORE keeps it
        # idempotent with the pre-save enqueue; failure is non-blocking (the
        # memory is already canonical with its pre-save queue rows, if any).
        if reconcile_on:
            try:
                post = await self._find_reconcile_candidates(
                    embedding_vector, project_id, exclude_id=memory.id
                )
                if post:
                    await self._enqueue_reconcile(
                        memory.id, memory.content_hash, post, project_id
                    )
            except Exception as e:
                logger.warning(
                    "Post-commit reconcile re-scan failed (non-blocking): %s", e
                )

        # R17: route derivable content to the async improve worker (best-effort,
        # outside the save transaction). Sets response.quality_hint so the caller
        # (agent) knows the memory was stored but flagged for distillation.
        if quality_hint_kind:
            response.quality_hint = await self._route_derivable_to_improve(
                memory.id, memory.content_hash, project_id, quality_hint_kind
            )

        # Continuous relay sharing (best-effort, outside the save transaction).
        await self._relay_auto_share(memory, event_type="create")
        return response

    async def _route_derivable_to_improve(
        self,
        memory_id: str,
        content_hash: str,
        project_id: Optional[str],
        hint_kind: str,
    ) -> str:
        """Enqueue a derivable memory for the improve worker; return a quality_hint.

        Skips the enqueue when no chat LLM is configured — the improve worker
        needs one to run, so queuing a job nothing can drain would just pollute
        the queue; the hint is still returned so the caller knows the memory
        should be distilled. Best-effort: any failure degrades to a hint-only
        result and never blocks the save.
        """
        from ..config import get_settings
        from .chat import ChatService
        from .maintenance import MaintenanceService

        try:
            settings = get_settings()
            if not await ChatService(self.db).is_configured(settings):
                return f"{hint_kind} — improve 큐 미등록 (LLM 미설정)"
            await MaintenanceService(self.db).enqueue_memory(
                memory_id=memory_id,
                operation="improve",
                project_id=project_id,
                content_hash=content_hash,
            )
            return f"{hint_kind} — improve 큐에 등록됨"
        except Exception as e:  # noqa: BLE001 - hint is best-effort, never blocks
            logger.warning("Derivable improve enqueue failed (non-blocking): %s", e)
            return f"{hint_kind} — improve 큐 등록 실패"

    async def enqueue_project_reconcile(self, project_id: str) -> dict:
        """Retroactively enqueue reconcile candidate pairs for a whole project.

        Write-time reconcile (F1) only ever fires on ``create()``, so memories
        that already existed before reconcile was enabled — or that were added
        via the batch/embedding path (which skips conflict detection) — are
        never compared. This scans every canonical memory in the project for
        near-duplicate/conflict candidates and enqueues the pairs into the same
        ``reconcile_queue`` the async worker already drains (NLI pre-gate → LLM →
        proposal → human curation). No LLM/NLI runs here; only cheap vector
        candidate lookup, so it's safe to run inline for the request.

        Returns ``{scanned, enqueued}``. ``enqueued`` is the number of pairs
        actually inserted (from INSERT OR IGNORE rowcounts — no table COUNT, so
        it doesn't race under concurrent writers). The queue's
        ``UNIQUE(new_memory_id, old_memory_id)`` keeps re-runs idempotent.

        Each undirected pair {A, B} is enqueued once: once A→B is queued, B's
        scan skips A rather than queuing the mirror B→A (which is a distinct
        row and would double the worker's LLM cost for the same comparison).
        """
        rows = await self.db.fetchall(
            """
            SELECT id, content_hash, embedding FROM memories
            WHERE project_id = ?
              AND COALESCE(status, 'canonical') = 'canonical'
            """,
            (project_id,),
        )
        scanned = 0
        enqueued = 0
        seen_pairs: set[frozenset] = set()
        for row in rows:
            memory_id = str(row["id"])
            embedding_bytes = row["embedding"]
            if not embedding_bytes:
                continue
            scanned += 1
            try:
                vector = self.embedding_service.from_bytes(embedding_bytes)
                candidates = await self._find_reconcile_candidates(
                    vector, project_id, exclude_id=memory_id
                )
            except Exception as e:
                logger.warning(
                    "Project reconcile candidate scan failed for %s: %s", memory_id, e
                )
                continue
            # Drop candidates whose undirected pair was already handled from the
            # other side (avoids queuing both A→B and B→A).
            fresh = []
            for c in candidates or []:
                pair = frozenset((memory_id, c["id"]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                fresh.append(c)
            if not fresh:
                continue
            enqueued += await self._enqueue_reconcile(
                memory_id, str(row["content_hash"]), fresh, project_id
            )
        return {"scanned": scanned, "enqueued": enqueued}

    async def create_with_embedding(
        self,
        content: str,
        embedding: List[float],
        project_id: Optional[str] = None,
        category: str = "task",
        source: str = "unknown",
        tags: Optional[List[str]] = None,
        anchors: Optional[dict] = None,
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

        # 0. Redact secrets/PII before persisting (CLAUDE.md M4). The caller's
        # pre-computed embedding reflects the original text, but the *stored*
        # content must never contain a credential — this is a batch/migration
        # path so the minor embedding/content drift is acceptable.
        content = redact_secrets(content)

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
            anchors=json.dumps(anchors) if anchors else None,
            embedding=embedding_bytes,
        )

        try:
            async with self.db.transaction():
                await self.db.add_memory(memory.model_dump())
                await self._save_to_vector_index(memory.id, embedding_bytes)

            logger.info("Memory created with pre-computed embedding: %s", memory.id)
            response = AddResponse(
                id=memory.id, status="saved", created_at=memory.created_at
            )

        except Exception as e:
            logger.error("Failed to save memory with embedding: %s", e)
            raise DatabaseError(f"Failed to save memory: {e}") from e

        # Continuous relay sharing (best-effort) — also covers the batch/MCP
        # path (batch_tools → add_with_embedding) so subscribed projects share
        # batch-created memories too.
        await self._relay_auto_share(memory, event_type="create")
        return response

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

        # 2. Redact + quality gate (when content changes). Updates persist
        # content too, so they must redact at the same chokepoint (M4).
        if content is not None:
            content = redact_secrets(content)
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
            response = UpdateResponse(id=memory_id, status="updated")

        except Exception as e:
            logger.error("Failed to update memory %s: %s", memory_id, e)
            raise DatabaseError(f"Failed to update memory: {e}") from e

        # Continuous relay sharing (best-effort): re-share the refreshed memory.
        refreshed = None
        try:
            refreshed = await self.get(memory_id)
        except Exception:
            refreshed = None
        await self._relay_auto_share(refreshed, event_type="update")
        return response

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
            response = DeleteResponse(id=memory_id, status="deleted")

        except Exception as e:
            logger.error("Failed to delete memory %s: %s", memory_id, e)
            raise DatabaseError(f"Failed to delete memory: {e}") from e

        # Continuous relay sharing (best-effort): retract from the team hub.
        await self._relay_auto_share(existing_memory, event_type="retract")
        return response

    async def report_anchor_status(
        self,
        memory_id: str,
        status: str,
        detail: Optional[str] = None,
    ) -> dict:
        """Persist a client's local anchor-verification verdict (t12, strong signal).

        The server has no git access, so it cannot verify a memory's anchors
        itself. An agent that ran the check locally (file_paths exist, commit
        reachable via ``git cat-file -e``) reports the verdict here. A ``stale``
        memory is then excluded from auto-injection and ``fresh`` clears the weak
        aged-anchor warning.

        Args:
            memory_id: Memory whose anchors were verified.
            status: ``fresh`` (intact) or ``stale`` (files gone / commit gone).
            detail: Optional free-text note; not persisted beyond logs (kept off
                the row so no client payload can smuggle content into the store).

        Returns:
            dict: ``{memory_id, stale_status, stale_checked_at}``.

        Raises:
            InvalidAnchorStatusError: status is not ``fresh``/``stale``.
            MemoryNotFoundError: no memory with that id.
        """
        from ..errors import InvalidAnchorStatusError

        if status not in InvalidAnchorStatusError.VALID_STATUSES:
            raise InvalidAnchorStatusError(status)

        existing = await self.get(memory_id)
        if existing is None:
            raise MemoryNotFoundError(memory_id)

        # A verdict only makes sense for anchored memories — without this guard
        # any bearer could flip arbitrary (anchor-less) memories to stale and
        # silently drop them from injection (cross-vendor review F7).
        has_anchors = bool(
            existing.get_anchors()
            if hasattr(existing, "get_anchors")
            else getattr(existing, "anchors", None)
        )
        if not has_anchors:
            from ..errors import ValidationError

            raise ValidationError(
                "memory has no anchors — report_anchor_status applies only to "
                "anchored memories. Save anchors first via add(anchors={...}) "
                "or pin_promote(anchors={...})."
            )

        checked_at = datetime.utcnow().isoformat() + "Z"
        try:
            await self.db.execute(
                "UPDATE memories SET stale_status = ?, stale_checked_at = ? "
                "WHERE id = ?",
                (status, checked_at, memory_id),
            )
        except Exception as e:
            logger.error("Failed to record anchor status for %s: %s", memory_id, e)
            raise DatabaseError(f"Failed to record anchor status: {e}") from e

        logger.info(
            "Recorded anchor status: %s -> %s%s",
            memory_id,
            status,
            f" ({redact_secrets(detail)})" if detail else "",
        )
        return {
            "memory_id": memory_id,
            "stale_status": status,
            "stale_checked_at": checked_at,
        }

    async def _relay_auto_share(self, memory: Any, *, event_type: str) -> None:
        """Forward a memory write to relay auto-share, if a subscription exists.

        Imported lazily so the core memory service carries no hard dependency on
        the relay layer, and fully guarded so a relay problem can never change
        the outcome of the memory write that triggered it.
        """
        if memory is None:
            return
        try:
            from .relay import RelayService

            await RelayService(self.db).auto_share_on_write(
                memory, event_type=event_type
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Relay auto-share hook skipped: %s", exc)

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
                return await self.embedding_service.aembed(content)

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

        logger.error("Embedding generation failed after %d attempts", self.max_retries)
        raise EmbeddingError(
            f"Failed to generate embedding after {self.max_retries} attempts: {last_error}"
        )

    async def _save_to_vector_index(
        self, memory_id: str, embedding_bytes: bytes
    ) -> None:
        """벡터 인덱스에 저장"""
        try:
            tables = await self._write_vector_tables()

            if tables == ["memories_vec_fallback"]:
                await self.db.execute(
                    "INSERT INTO memories_vec_fallback (memory_id, embedding) VALUES (?, ?)",
                    (memory_id, embedding_bytes),
                )
                logger.debug("Saved to fallback table: %s", memory_id)
            else:
                embedding_json = self._embedding_to_json(embedding_bytes)
                # active (+ inactive during migration); table names from a fixed
                # slot allowlist, never user input — safe to interpolate.
                for table in tables:
                    await self.db.execute(
                        f"DELETE FROM {table} WHERE memory_id = ?", (memory_id,)
                    )
                    await self.db.execute(
                        f"INSERT INTO {table} (memory_id, embedding) VALUES (?, ?)",
                        (memory_id, embedding_json),
                    )
                logger.debug("Saved to vector table(s) %s: %s", tables, memory_id)

        except Exception as e:
            logger.error("Failed to save to vector index: %s", e)
            raise DatabaseError(f"Failed to save to vector index: {e}") from e

    async def _reconcile_enabled(self) -> bool:
        """Whether write-time reconcile (F1 enqueue) is on.

        True if env ``enable_conflict_detection`` is set, OR the dashboard
        app_config ``reconcile.enabled`` is truthy. Lets the reconcile pipeline
        be toggled from the dashboard without an env change.
        """
        from ..config import get_settings

        if get_settings().enable_conflict_detection:
            return True
        val = await self.db.get_app_config("reconcile.enabled")
        return str(val or "").strip().lower() in ("true", "1", "yes", "on")

    async def _find_reconcile_candidates(
        self,
        embedding_vector: List[float],
        project_id: Optional[str] = None,
        exclude_id: Optional[str] = None,
    ) -> list[dict] | None:
        """F1 sync gate: nearest-neighbor candidates for the async reconcile worker.

        Vector-only (Stage 1). The NLI contradiction judgment (former Stage 2) is
        moved to the async worker — a per-add CPU cross-encoder on the write path
        is the L1 system-stall risk. Returns up to 3 candidates above the scaled
        similarity threshold, each carrying a content_hash snapshot so the worker
        can revalidate at apply time and skip rows mutated in between (C2 TOCTOU).

        Returns None on no match or on any failure (graceful: never blocks save).
        Uses vector similarity thresholds from settings directly — no NLI model
        is loaded on the write path (the async worker loads NLI).
        """
        from ..config import get_settings

        settings = get_settings()

        try:
            embedding_bytes = self.embedding_service.to_bytes(embedding_vector)
            embedding_json = self._embedding_to_json(embedding_bytes)

            max_c = settings.conflict_max_candidates
            active_table = await self._resolve_vector_table()
            # Table name is from a fixed slot allowlist (_resolve_vector_table),
            # never user input — safe to interpolate.
            if active_table == "memories_vec_fallback":
                # vec0 unavailable → cosine brute scan (no MATCH kNN operator).
                cursor = await self.db.execute(
                    f"""
                    SELECT m.id, m.content_hash,
                           vec_distance_cosine(e.embedding, ?) AS distance
                    FROM {active_table} e
                    JOIN memories m ON m.id = e.memory_id
                    WHERE (m.project_id = ? OR ? IS NULL)
                      AND COALESCE(m.status, 'canonical') = 'canonical'
                      AND (? IS NULL OR m.id != ?)
                    ORDER BY distance ASC
                    LIMIT ?
                    """,
                    (
                        embedding_json,
                        project_id,
                        project_id,
                        exclude_id,
                        exclude_id,
                        max_c,
                    ),
                )
            else:
                # sqlite-vec vec0 MATCH kNN (indexed nearest-neighbor, no full
                # scan). Over-fetch the inner kNN so the project/status filter on
                # the outer join still yields up to max_c canonical candidates.
                inner_limit = max_c * 5 if project_id else max_c
                cursor = await self.db.execute(
                    f"""
                    SELECT m.id, m.content_hash, ve.distance
                    FROM memories m
                    JOIN (
                        SELECT memory_id, distance
                        FROM {active_table}
                        WHERE embedding MATCH ?
                        ORDER BY distance
                        LIMIT ?
                    ) ve ON m.id = ve.memory_id
                    WHERE (m.project_id = ? OR ? IS NULL)
                      AND COALESCE(m.status, 'canonical') = 'canonical'
                      AND (? IS NULL OR m.id != ?)
                    ORDER BY ve.distance ASC
                    LIMIT ?
                    """,
                    (
                        embedding_json,
                        inner_limit,
                        project_id,
                        project_id,
                        exclude_id,
                        exclude_id,
                        max_c,
                    ),
                )

            rows = cursor.fetchall()
            if not rows:
                return None

            threshold = self.embedding_service.scaled_threshold(
                settings.conflict_similarity_threshold
            )
            candidates: list[dict] = []
            for row in rows:
                # Convert cosine distance -> similarity
                similarity = max(0.0, min(1.0, 1.0 - (row[2] / 2.0)))
                if similarity >= threshold:
                    candidates.append(
                        {
                            "id": row[0],
                            "content_hash": row[1],
                            "similarity": similarity,
                        }
                    )

            return candidates[:3] or None

        except Exception as e:
            # Candidate scan failure does not block save (graceful degradation).
            logger.warning("Reconcile candidate scan failed (non-blocking): %s", e)
            return None

    async def _enqueue_reconcile(
        self,
        new_id: str,
        new_content_hash: str,
        candidates: list[dict],
        project_id: Optional[str],
    ) -> int:
        """Enqueue (new, old) conflict pairs for the async reconcile worker.

        One row per (new, old) pair: ``UNIQUE(new_memory_id, old_memory_id)``
        holds the 1:N conflict set (C1). ``INSERT OR IGNORE`` keeps a re-add
        idempotent. Called inside the save transaction (C2 atomicity). Returns
        the number of rows actually inserted (from each statement's rowcount) so
        callers don't need a separate COUNT.
        """
        now = datetime.utcnow().isoformat() + "Z"
        inserted = 0
        for c in candidates:
            cur = await self.db.execute(
                """
                INSERT OR IGNORE INTO reconcile_queue
                (id, new_memory_id, old_memory_id, project_id, similarity,
                 new_content_hash, old_content_hash, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    str(uuid4()),
                    new_id,
                    c["id"],
                    project_id,
                    c.get("similarity"),
                    new_content_hash,
                    c.get("content_hash"),
                    now,
                    now,
                ),
            )
            if cur.rowcount and cur.rowcount > 0:
                inserted += cur.rowcount
        return inserted

    async def _update_vector_index(
        self, memory_id: str, embedding_bytes: bytes
    ) -> None:
        """벡터 인덱스 업데이트"""
        try:
            tables = await self._write_vector_tables()

            if tables == ["memories_vec_fallback"]:
                await self.db.execute(
                    "UPDATE memories_vec_fallback SET embedding = ? WHERE memory_id = ?",
                    (embedding_bytes, memory_id),
                )
                logger.debug("Updated fallback table: %s", memory_id)
            else:
                embedding_json = self._embedding_to_json(embedding_bytes)
                # active (+ inactive during migration); DELETE+INSERT so a row
                # absent from a freshly created green slot is inserted, not missed.
                for table in tables:
                    await self.db.execute(
                        f"DELETE FROM {table} WHERE memory_id = ?", (memory_id,)
                    )
                    await self.db.execute(
                        f"INSERT INTO {table} (memory_id, embedding) VALUES (?, ?)",
                        (memory_id, embedding_json),
                    )
                logger.debug("Updated vector table(s) %s: %s", tables, memory_id)

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
            tables = await self._write_vector_tables()

            # Delete from every write target (active + inactive during migration,
            # else fallback) so a deletion can't survive a pointer swap.
            for table in tables:
                await self.db.execute(
                    f"DELETE FROM {table} WHERE memory_id = ?", (memory_id,)
                )
            logger.debug("Deleted from vector table(s) %s: %s", tables, memory_id)

        except Exception as e:
            logger.error("Failed to delete from vector index: %s", e)
            raise DatabaseError(f"Failed to delete from vector index: {e}") from e
