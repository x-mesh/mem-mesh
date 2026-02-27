"""Generate answers using claude CLI."""

import logging
import os
import subprocess
import time

from .config import BenchmarkConfig
from .dataset import LongMemEvalQuestion
from .prompts import get_generation_prompt
from .retriever import RetrievalResult

logger = logging.getLogger(__name__)


def generate_answer(
    question: LongMemEvalQuestion,
    retrieval: RetrievalResult,
    config: BenchmarkConfig,
) -> tuple[str, float]:
    """Generate an answer using claude CLI.

    Returns (answer_text, generation_time_seconds).
    """
    # Build context from retrieved contents (chronologically sorted)
    sorted_items = retrieval.sorted_contents_with_dates
    context_parts: list[str] = []
    for i, (content, date) in enumerate(sorted_items, 1):
        date_label = f" ({date})" if date else ""
        context_parts.append(f"--- Excerpt {i}{date_label} ---\n{content}")
    context = "\n\n".join(context_parts) if context_parts else "(No relevant context found)"

    prompt = get_generation_prompt(
        question=question.question,
        question_date=question.question_date,
        context=context,
        use_cot=config.use_cot,
    )

    return _call_claude(prompt, config)


def _call_claude(
    prompt: str,
    config: BenchmarkConfig,
) -> tuple[str, float]:
    """Call claude CLI and return (response_text, elapsed_seconds).

    Uses stdin pipe for prompt delivery and exponential backoff on retries.
    """
    start = time.time()

    # Remove CLAUDECODE env var to avoid nested session restriction
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    max_attempts = 1 + config.generation_retries
    for attempt in range(max_attempts):
        try:
            result = subprocess.run(
                [
                    "claude",
                    "-p",
                    "-",
                    "--model",
                    config.claude_model,
                    "--output-format",
                    "text",
                    "--max-turns",
                    "1",
                ],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=config.generation_timeout,
                env=env,
            )

            if result.returncode == 0 and result.stdout.strip():
                elapsed = time.time() - start
                response = result.stdout.strip()
                logger.debug(
                    "Claude response (%d chars) in %.1fs",
                    len(response),
                    elapsed,
                )
                return response, elapsed

            logger.warning(
                "Claude CLI returned code %d (attempt %d/%d): %s",
                result.returncode,
                attempt + 1,
                max_attempts,
                result.stderr[:200] if result.stderr else "(no stderr)",
            )

        except subprocess.TimeoutExpired:
            logger.warning(
                "Claude CLI timed out after %ds (attempt %d/%d)",
                config.generation_timeout,
                attempt + 1,
                max_attempts,
            )

        # Exponential backoff before retry (2s, 4s, 8s, ...)
        if attempt < max_attempts - 1:
            backoff = 2 ** (attempt + 1)
            logger.info("Backing off %ds before retry...", backoff)
            time.sleep(backoff)

    elapsed = time.time() - start
    return "(generation failed)", elapsed
