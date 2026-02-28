"""Checkpoint and resume logic for benchmark runs."""

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .config import BenchmarkConfig

logger = logging.getLogger(__name__)


@dataclass
class QuestionResult:
    """Result for a single question."""

    question_id: str
    question_type: str
    is_abstention: bool

    # Retrieval
    retrieved_session_ids: list[str]
    recall_any: float
    recall_all: float
    search_time_ms: float

    # Generation
    generated_answer: str
    generation_time_s: float

    # Evaluation
    is_correct: bool
    judge_response: str
    eval_time_s: float

    # Timing
    total_time_s: float


@dataclass
class CheckpointData:
    """Checkpoint state for a benchmark run."""

    completed_ids: list[str] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    config_summary: dict[str, Any] = field(default_factory=dict)


def load_checkpoint(config: BenchmarkConfig) -> CheckpointData:
    """Load checkpoint from disk, or return empty if none exists."""
    path = config.checkpoint_path
    if not path.exists():
        logger.info("No checkpoint found at %s", path)
        return CheckpointData()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cp = CheckpointData(
            completed_ids=data.get("completed_ids", []),
            results=data.get("results", []),
            config_summary=data.get("config_summary", {}),
        )
        logger.info("Loaded checkpoint with %d completed questions", len(cp.completed_ids))
        return cp
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Corrupted checkpoint file, starting fresh: %s", e)
        return CheckpointData()


def save_checkpoint(
    config: BenchmarkConfig,
    checkpoint: CheckpointData,
) -> None:
    """Atomically save checkpoint to disk (write to tmp then rename)."""
    config.results_dir.mkdir(parents=True, exist_ok=True)
    path = config.checkpoint_path

    data = {
        "completed_ids": checkpoint.completed_ids,
        "results": checkpoint.results,
        "config_summary": checkpoint.config_summary,
    }

    # Atomic write: tmp file in same directory, then rename
    fd, tmp_path = tempfile.mkstemp(
        dir=str(config.results_dir), suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(path))
    except Exception:
        # Clean up tmp file on error
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    logger.debug("Checkpoint saved: %d completed", len(checkpoint.completed_ids))


def add_result(
    checkpoint: CheckpointData,
    result: QuestionResult,
) -> None:
    """Add a question result to the checkpoint."""
    checkpoint.completed_ids.append(result.question_id)
    checkpoint.results.append(asdict(result))


def update_result(
    checkpoint: CheckpointData,
    result: QuestionResult,
) -> None:
    """Replace an existing result in the checkpoint (for retry-failed)."""
    result_dict = asdict(result)
    for i, existing in enumerate(checkpoint.results):
        if existing["question_id"] == result.question_id:
            checkpoint.results[i] = result_dict
            return
    # If not found, add as new
    checkpoint.completed_ids.append(result.question_id)
    checkpoint.results.append(result_dict)


def get_failed_question_ids(checkpoint: CheckpointData) -> list[str]:
    """Return question IDs that had generation failures (including max turns errors)."""
    failed: list[str] = []
    for result in checkpoint.results:
        answer = result.get("generated_answer", "")
        if answer == "(generation failed)" or answer.startswith("Error: Reached max turns"):
            failed.append(result["question_id"])
    return failed
