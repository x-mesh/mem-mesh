"""Evaluate answers using claude CLI as LLM judge."""

import logging
import os
import subprocess
import time

from .config import BenchmarkConfig
from .dataset import LongMemEvalQuestion
from .prompts import get_judge_prompt

logger = logging.getLogger(__name__)


def evaluate_answer(
    question: LongMemEvalQuestion,
    generated_answer: str,
    config: BenchmarkConfig,
) -> tuple[bool, str, float]:
    """Evaluate a generated answer using LLM judge.

    Returns (is_correct, raw_judge_response, eval_time_seconds).
    """
    judge_prompt = get_judge_prompt(
        question_id=question.question_id,
        question_type=question.question_type,
        question=question.question,
        answer=question.answer,
        response=generated_answer,
    )

    raw_response, elapsed = _call_judge(judge_prompt, config)

    # Determine correctness: check if "yes" appears in response
    is_correct = "yes" in raw_response.lower()

    logger.debug(
        "Judge for %s: %s (raw: %s) in %.1fs",
        question.question_id,
        "CORRECT" if is_correct else "WRONG",
        raw_response[:50],
        elapsed,
    )
    return is_correct, raw_response, elapsed


def _call_judge(
    prompt: str,
    config: BenchmarkConfig,
) -> tuple[str, float]:
    """Call claude CLI for judge evaluation.

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
                timeout=60,
                env=env,
            )

            if result.returncode == 0 and result.stdout.strip():
                elapsed = time.time() - start
                return result.stdout.strip(), elapsed

            logger.warning(
                "Judge CLI returned code %d (attempt %d/%d): %s",
                result.returncode,
                attempt + 1,
                max_attempts,
                result.stderr[:200] if result.stderr else "(no stderr)",
            )

        except subprocess.TimeoutExpired:
            logger.warning(
                "Judge CLI timed out (attempt %d/%d)",
                attempt + 1,
                max_attempts,
            )

        # Exponential backoff before retry (2s, 4s, 8s, ...)
        if attempt < max_attempts - 1:
            backoff = 2 ** (attempt + 1)
            logger.info("Backing off %ds before retry...", backoff)
            time.sleep(backoff)

    elapsed = time.time() - start
    return "no", elapsed
