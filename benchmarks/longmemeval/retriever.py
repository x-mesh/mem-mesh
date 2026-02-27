"""Retrieve relevant sessions from mem-mesh for each question."""

import logging
import time
from dataclasses import dataclass, field

from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.unified_search import UnifiedSearchService

from .config import BenchmarkConfig
from .dataset import LongMemEvalQuestion

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """Result of retrieval for a single question."""

    question_id: str
    retrieved_contents: list[str]
    retrieved_session_ids: list[str]
    retrieved_dates: list[str]
    scores: list[float]
    search_time_ms: float
    recall_any: float  # at least one answer session retrieved
    recall_all: float  # all answer sessions retrieved

    @property
    def sorted_contents_with_dates(self) -> list[tuple[str, str]]:
        """Return (content, date) pairs sorted chronologically (oldest first).

        This ensures the model sees the most recent information last,
        which is critical for knowledge-update questions.
        """
        items = list(zip(self.retrieved_contents, self.retrieved_dates))
        items.sort(key=lambda x: x[1] if x[1] else "")
        return items


def _extract_session_id_from_tags(tags: list[str] | None) -> str | None:
    """Extract session ID from memory tags.

    Tags are stored as [session_id, date] during indexing.
    """
    if tags and len(tags) >= 1:
        return tags[0]
    return None


def _extract_date_from_tags(tags: list[str] | None) -> str:
    """Extract date from memory tags.

    Tags are stored as [session_id, date] during indexing.
    """
    if tags and len(tags) >= 2:
        return tags[1]
    return ""


def _extract_date_from_content(content: str) -> str:
    """Fallback: extract date from content header."""
    # Content format: [Date: {date}] [Session: {session_id}]\n...
    if "[Date: " in content:
        start = content.index("[Date: ") + len("[Date: ")
        end = content.index("]", start)
        return content[start:end]
    return ""


def _extract_session_id_from_content(content: str) -> str | None:
    """Fallback: extract session ID from content header."""
    # Content format: [Date: ...] [Session: {session_id}]\n...
    if "[Session: " in content:
        start = content.index("[Session: ") + len("[Session: ")
        end = content.index("]", start)
        return content[start:end]
    return None


async def retrieve_for_question(
    question: LongMemEvalQuestion,
    embedding_service: EmbeddingService,
    config: BenchmarkConfig,
) -> RetrievalResult:
    """Retrieve relevant sessions for a question from its isolated DB."""
    start = time.time()
    db_path = config.db_path_for(question.question_id)
    project_id = f"lme-{question.question_id}"

    db = Database(str(db_path))
    await db.connect()

    try:
        search_service = UnifiedSearchService(
            db,
            embedding_service,
            enable_korean_optimization=config.enable_korean_optimization,
            enable_quality_features=False,
            enable_noise_filter=False,
        )

        response = await search_service.search(
            query=question.question,
            project_id=project_id,
            search_mode=config.search_mode,
            limit=config.topk,
            min_quality_score=0.0,
        )
    finally:
        await db.close()

    elapsed_ms = (time.time() - start) * 1000

    # Extract session IDs and dates from results
    retrieved_contents: list[str] = []
    retrieved_session_ids: list[str] = []
    retrieved_dates: list[str] = []
    scores: list[float] = []

    for result in response.results:
        retrieved_contents.append(result.content)
        scores.append(result.similarity_score)

        sid = _extract_session_id_from_tags(result.tags)
        if sid is None:
            sid = _extract_session_id_from_content(result.content)
        if sid:
            retrieved_session_ids.append(sid)

        date = _extract_date_from_tags(result.tags)
        if not date:
            date = _extract_date_from_content(result.content)
        retrieved_dates.append(date)

    # Compute recall metrics
    answer_set = set(question.answer_session_ids)
    retrieved_set = set(retrieved_session_ids)
    intersection = answer_set & retrieved_set

    recall_any = 1.0 if len(intersection) > 0 else 0.0
    recall_all = 1.0 if answer_set <= retrieved_set else 0.0

    result = RetrievalResult(
        question_id=question.question_id,
        retrieved_contents=retrieved_contents,
        retrieved_session_ids=retrieved_session_ids,
        retrieved_dates=retrieved_dates,
        scores=scores,
        search_time_ms=elapsed_ms,
        recall_any=recall_any,
        recall_all=recall_all,
    )

    logger.debug(
        "Retrieved %d results for %s (recall_any=%.1f, recall_all=%.1f) in %.0fms",
        len(retrieved_contents),
        question.question_id,
        recall_any,
        recall_all,
        elapsed_ms,
    )
    return result
