"""Conflict detection service for memory contradiction checking.

Uses a 2-stage hybrid approach:
  Stage 1: Vector similarity filtering (cosine >= threshold) to find candidates
  Stage 2: NLI (Natural Language Inference) model to classify contradiction

Follows the same lazy-load pattern as RerankerService.
"""

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import CrossEncoder as _CrossEncoder  # noqa: F811

    NLI_MODEL_AVAILABLE = True
except ImportError:
    NLI_MODEL_AVAILABLE = False
    logger.info("sentence_transformers not available — conflict detection (NLI) disabled")

DEFAULT_NLI_MODEL = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"

# NLI label indices (model-specific — mDeBERTa outputs [contradiction, neutral, entailment])
_LABEL_CONTRADICTION = 0
_LABEL_NEUTRAL = 1
_LABEL_ENTAILMENT = 2


@dataclass
class ConflictResult:
    """Single conflict detection result."""

    memory_id: str
    content_preview: str
    contradiction_score: float
    similarity_score: float


class ConflictDetectorService:
    """Hybrid conflict detector: vector similarity + NLI contradiction classification.

    Stage 1 (vector-only) works without NLI model — returns high-similarity warnings.
    Stage 2 (NLI) activates when model is loaded — returns precise contradiction scores.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_NLI_MODEL,
        preload: bool = False,
        contradiction_threshold: float = 0.7,
        similarity_threshold: float = 0.7,
        max_candidates: int = 10,
    ):
        self.model_name = model_name
        self._model: "CrossEncoder | None" = None
        self._model_load_failed: bool = False
        self.contradiction_threshold = contradiction_threshold
        self.similarity_threshold = similarity_threshold
        self.max_candidates = max_candidates

        if not NLI_MODEL_AVAILABLE:
            logger.warning(
                "CrossEncoder not available — NLI conflict detection will be skipped"
            )
            return

        if preload:
            self._load_model()

    def _load_model(self) -> None:
        """Lazy-load the NLI cross-encoder model."""
        if self._model is not None:
            return

        if self._model_load_failed:
            return

        if not NLI_MODEL_AVAILABLE:
            return

        try:
            start = time.time()
            self._model = _CrossEncoder(self.model_name)
            elapsed = time.time() - start
            logger.info("NLI model loaded: %s (%.1fs)", self.model_name, elapsed)
        except Exception as e:
            self._model_load_failed = True
            logger.error("NLI model load failed (will not retry): %s", e)

    @property
    def is_available(self) -> bool:
        """Check if NLI-based conflict detection is available."""
        return NLI_MODEL_AVAILABLE

    @property
    def nli_loaded(self) -> bool:
        """Check if the NLI model is actually loaded in memory."""
        return self._model is not None

    def detect_conflicts(
        self,
        new_content: str,
        candidates: list[dict],
    ) -> list[ConflictResult]:
        """Detect contradictions between new content and candidate memories.

        Args:
            new_content: The new memory content to check.
            candidates: List of dicts with keys: id, content, similarity_score.
                These should be pre-filtered by vector similarity (Stage 1).

        Returns:
            List of ConflictResult for memories that contradict the new content.
        """
        if not candidates:
            return []

        # If model loading previously failed, skip NLI entirely
        if self._model_load_failed:
            logger.debug("NLI model load previously failed — using vector-only fallback")
            filtered = [
                c
                for c in candidates
                if c.get("similarity_score", 0) >= self.similarity_threshold
            ]
            if not filtered:
                return []
            return self._vector_only_detect(filtered[: self.max_candidates])

        # Filter by similarity threshold (Stage 1 guard)
        filtered = [
            c for c in candidates if c.get("similarity_score", 0) >= self.similarity_threshold
        ]

        if not filtered:
            return []

        # Limit candidates
        filtered = filtered[: self.max_candidates]

        # Stage 2: NLI classification (if model available)
        if NLI_MODEL_AVAILABLE:
            if self._model is None:
                self._load_model()

            if self._model is not None:
                return self._nli_detect(new_content, filtered)

        # Fallback: vector-only mode (high similarity warning without NLI)
        logger.debug("NLI model not loaded — returning vector-only similarity warnings")
        return self._vector_only_detect(filtered)

    def _nli_detect(
        self,
        new_content: str,
        candidates: list[dict],
    ) -> list[ConflictResult]:
        """Stage 2: NLI-based contradiction detection."""
        assert self._model is not None

        pairs = [[new_content[:512], c["content"][:512]] for c in candidates]

        start = time.time()
        # predict returns shape (N, 3) for 3-class NLI
        scores = self._model.predict(pairs, apply_softmax=True)
        elapsed_ms = (time.time() - start) * 1000

        results: list[ConflictResult] = []
        for i, candidate in enumerate(candidates):
            contradiction_score = float(scores[i][_LABEL_CONTRADICTION])
            if contradiction_score >= self.contradiction_threshold:
                results.append(
                    ConflictResult(
                        memory_id=candidate["id"],
                        content_preview=candidate["content"][:200],
                        contradiction_score=contradiction_score,
                        similarity_score=candidate.get("similarity_score", 0.0),
                    )
                )

        logger.debug(
            "NLI conflict check: %d candidates, %d conflicts in %.0fms",
            len(candidates),
            len(results),
            elapsed_ms,
        )

        # Sort by contradiction score descending
        results.sort(key=lambda r: r.contradiction_score, reverse=True)
        return results

    def _vector_only_detect(
        self,
        candidates: list[dict],
    ) -> list[ConflictResult]:
        """Fallback: return high-similarity candidates as potential conflicts.

        Without NLI, we can only warn about topically similar memories.
        This is Stage 1 MVP behavior.
        """
        HIGH_SIMILARITY_THRESHOLD = 0.85
        results: list[ConflictResult] = []

        for candidate in candidates:
            sim = candidate.get("similarity_score", 0.0)
            if sim >= HIGH_SIMILARITY_THRESHOLD:
                results.append(
                    ConflictResult(
                        memory_id=candidate["id"],
                        content_preview=candidate["content"][:200],
                        contradiction_score=0.0,  # unknown without NLI
                        similarity_score=sim,
                    )
                )

        results.sort(key=lambda r: r.similarity_score, reverse=True)
        return results
