"""Index LongMemEval sessions into per-question mem-mesh databases."""

import asyncio
import logging
import time
from pathlib import Path

from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.memory import MemoryService

from .config import BenchmarkConfig
from .dataset import LongMemEvalQuestion, Session

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 10_000


def _format_session_content(session: Session) -> str:
    """Format a session into a single memory content string."""
    lines = [f"[Date: {session.date}] [Session: {session.session_id}]"]
    for turn in session.turns:
        role = "User" if turn["role"] == "user" else "Assistant"
        lines.append(f"{role}: {turn['content']}")
    content = "\n".join(lines)
    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH]
    return content


async def index_question(
    question: LongMemEvalQuestion,
    embedding_service: EmbeddingService,
    config: BenchmarkConfig,
) -> float:
    """Index all sessions for a single question into an isolated DB.

    Returns indexing time in seconds.
    """
    start = time.time()
    db_path = config.db_path_for(question.question_id)

    # Skip if DB already exists (from previous run)
    if db_path.exists():
        logger.debug("DB already exists for %s, skipping", question.question_id)
        return 0.0

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(str(db_path), embedding_dim=embedding_service.dimension)
    await db.connect()

    try:
        memory_service = MemoryService(db, embedding_service)
        project_id = f"lme-{question.question_id}"

        # Prepare all session contents
        contents = [_format_session_content(s) for s in question.sessions]

        # Batch embed all sessions
        embeddings = embedding_service.embed_batch(contents, is_query=False)

        # Store each session as a memory
        for session, content, embedding in zip(
            question.sessions, contents, embeddings
        ):
            await memory_service.create_with_embedding(
                content=content,
                embedding=embedding,
                project_id=project_id,
                category="session",
                source="longmemeval",
                tags=[session.session_id, session.date],
            )
    finally:
        await db.close()

    elapsed = time.time() - start
    logger.debug(
        "Indexed %d sessions for %s in %.1fs",
        len(question.sessions),
        question.question_id,
        elapsed,
    )
    return elapsed
