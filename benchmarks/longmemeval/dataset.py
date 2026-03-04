"""LongMemEval dataset download and parsing."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from huggingface_hub import hf_hub_download

from .config import BenchmarkConfig

logger = logging.getLogger(__name__)

HF_REPO_ID = "xiaowu0162/longmemeval-cleaned"


@dataclass
class Session:
    """A single conversation session from the haystack."""

    session_id: str
    date: str
    turns: list[dict[str, str]]  # [{"role": "user"/"assistant", "content": "..."}]


@dataclass
class LongMemEvalQuestion:
    """A single LongMemEval benchmark question."""

    question_id: str
    question_type: str
    question: str
    question_date: str
    answer: str  # always str (int answers converted)
    answer_session_ids: list[str]
    sessions: list[Session]

    @property
    def is_abstention(self) -> bool:
        return "_abs" in self.question_id


def download_dataset(config: BenchmarkConfig) -> Path:
    """Download the LongMemEval dataset from HuggingFace Hub."""
    if config.dataset_path.exists():
        logger.info("Dataset already exists at %s", config.dataset_path)
        return config.dataset_path

    config.data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s from %s ...", config.dataset_filename, HF_REPO_ID)

    downloaded = hf_hub_download(
        repo_id=HF_REPO_ID,
        filename=config.dataset_filename,
        repo_type="dataset",
        local_dir=str(config.data_dir),
    )
    logger.info("Downloaded to %s", downloaded)
    return Path(downloaded)


def _parse_sessions(
    haystack_session_ids: list[str],
    haystack_dates: list[str],
    haystack_sessions: list[list[dict[str, str]]],
) -> list[Session]:
    """Parse raw haystack data into Session objects."""
    sessions: list[Session] = []
    for sid, date, turns in zip(
        haystack_session_ids, haystack_dates, haystack_sessions
    ):
        # Strip has_answer field if present (oracle split)
        clean_turns = [
            {"role": t["role"], "content": t["content"]} for t in turns
        ]
        sessions.append(Session(session_id=sid, date=date, turns=clean_turns))
    return sessions


def load_questions(
    config: BenchmarkConfig,
) -> list[LongMemEvalQuestion]:
    """Load and parse questions from the dataset JSON file.

    Applies filtering by question_type, max_count, and question_ids.
    """
    path = config.dataset_path
    if not path.exists():
        path = download_dataset(config)

    logger.info("Loading questions from %s ...", path)
    with open(path, "r", encoding="utf-8") as f:
        raw_data: list[dict] = json.load(f)

    questions: list[LongMemEvalQuestion] = []
    for item in raw_data:
        q = LongMemEvalQuestion(
            question_id=item["question_id"],
            question_type=item["question_type"],
            question=item["question"],
            question_date=item["question_date"],
            answer=str(item["answer"]),  # int → str conversion
            answer_session_ids=item["answer_session_ids"],
            sessions=_parse_sessions(
                item["haystack_session_ids"],
                item["haystack_dates"],
                item["haystack_sessions"],
            ),
        )
        questions.append(q)

    # Apply filters
    if config.question_ids:
        id_set = set(config.question_ids)
        questions = [q for q in questions if q.question_id in id_set]

    if config.question_types:
        type_set = set(config.question_types)
        questions = [q for q in questions if q.question_type in type_set]

    if config.max_questions is not None:
        questions = questions[: config.max_questions]

    logger.info(
        "Loaded %d questions (filtered from %d total)", len(questions), len(raw_data)
    )
    return questions
