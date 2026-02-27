"""Cross-Encoder reranking service for search result refinement.

Uses a Cross-Encoder model to re-score query-document pairs for more
precise ranking than bi-encoder (embedding) similarity alone.
"""

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import CrossEncoder

    CROSS_ENCODER_AVAILABLE = True
except ImportError:
    CROSS_ENCODER_AVAILABLE = False
    logger.info("sentence_transformers not available — reranking disabled")

DEFAULT_RERANKING_MODEL = "cross-encoder/ms-marco-multilingual-MiniLM-L6-v2"


@dataclass
class RerankResult:
    """Single reranked item with original index and new score."""

    original_index: int
    score: float


class RerankerService:
    """Cross-Encoder based reranking service.

    Reranks candidate documents by jointly encoding (query, document) pairs,
    producing more accurate relevance scores than bi-encoder similarity.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_RERANKING_MODEL,
        preload: bool = True,
    ):
        self.model_name = model_name
        self._model: "CrossEncoder | None" = None

        if not CROSS_ENCODER_AVAILABLE:
            logger.warning("CrossEncoder not available — reranking will be skipped")
            return

        if preload:
            self._load_model()

    def _load_model(self) -> None:
        """Lazy-load the cross-encoder model."""
        if self._model is not None:
            return

        if not CROSS_ENCODER_AVAILABLE:
            return

        start = time.time()
        self._model = CrossEncoder(self.model_name)
        elapsed = time.time() - start
        logger.info(
            "CrossEncoder loaded: %s (%.1fs)", self.model_name, elapsed
        )

    @property
    def is_available(self) -> bool:
        """Check if reranking is available."""
        return CROSS_ENCODER_AVAILABLE

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[RerankResult]:
        """Rerank documents by relevance to query.

        Args:
            query: Search query string.
            documents: List of document texts to rerank.
            top_k: Return only top-K results. None = return all.

        Returns:
            List of RerankResult sorted by score descending.
        """
        if not documents:
            return []

        if not CROSS_ENCODER_AVAILABLE or self._model is None:
            self._load_model()
            if self._model is None:
                # Fallback: return original order with uniform scores
                results = [
                    RerankResult(original_index=i, score=1.0 - i * 0.01)
                    for i in range(len(documents))
                ]
                if top_k:
                    results = results[:top_k]
                return results

        start = time.time()

        # Cross-encoder expects list of [query, document] pairs
        pairs = [[query, doc] for doc in documents]
        scores = self._model.predict(pairs)

        # Normalize logits to 0-1 via sigmoid
        import numpy as np

        normalized_scores = 1 / (1 + np.exp(-scores))

        # Build results sorted by score descending
        results = [
            RerankResult(original_index=i, score=float(normalized_scores[i]))
            for i in range(len(documents))
        ]
        results.sort(key=lambda r: r.score, reverse=True)

        if top_k:
            results = results[:top_k]

        elapsed_ms = (time.time() - start) * 1000
        logger.debug(
            "Reranked %d documents in %.0fms (top score=%.3f)",
            len(documents),
            elapsed_ms,
            results[0].score if results else 0,
        )

        return results
