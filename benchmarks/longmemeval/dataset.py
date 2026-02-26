"""LongMemEval 데이터셋 로더"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from .config import BenchmarkConfig
from .models import BenchmarkItem

logger = logging.getLogger(__name__)


def load_dataset(config: BenchmarkConfig) -> List[BenchmarkItem]:
    """HuggingFace 데이터셋 로드 또는 한국어 번역본 로드

    Args:
        config: 벤치마크 설정

    Returns:
        BenchmarkItem 리스트
    """
    if config.dataset.language == "ko":
        return _load_korean_dataset(config)
    return _load_hf_dataset(config)


def _load_hf_dataset(config: BenchmarkConfig) -> List[BenchmarkItem]:
    """HuggingFace 데이터셋 로드"""
    try:
        from datasets import load_dataset as hf_load
    except ImportError:
        raise ImportError(
            "datasets 패키지가 필요합니다: pip install datasets"
        )

    logger.info(f"Loading dataset: {config.dataset.name} ({config.dataset.split})")
    ds = hf_load(config.dataset.name, split=config.dataset.split)

    items: List[BenchmarkItem] = []
    for i, row in enumerate(ds):
        item = _row_to_item(row, i)
        if item is not None:
            items.append(item)

    if config.execution.max_questions is not None:
        items = items[: config.execution.max_questions]

    logger.info(f"Loaded {len(items)} benchmark items")
    return items


def _load_korean_dataset(config: BenchmarkConfig) -> List[BenchmarkItem]:
    """한국어 번역본 로드 (data/longmemeval_ko.json)"""
    ko_path = Path(__file__).parent / "data" / "longmemeval_ko.json"
    if not ko_path.exists():
        raise FileNotFoundError(
            f"한국어 데이터셋이 없습니다: {ko_path}\n"
            "먼저 번역을 실행하세요: python -m benchmarks.longmemeval translate"
        )

    logger.info(f"Loading Korean dataset from {ko_path}")
    with open(ko_path, encoding="utf-8") as f:
        data = json.load(f)

    items: List[BenchmarkItem] = []
    for row in data:
        item = BenchmarkItem(**row)
        items.append(item)

    if config.execution.max_questions is not None:
        items = items[: config.execution.max_questions]

    logger.info(f"Loaded {len(items)} Korean benchmark items")
    return items


def _row_to_item(row: dict, index: int) -> Optional[BenchmarkItem]:
    """HuggingFace 데이터셋 행을 BenchmarkItem으로 변환"""
    try:
        # LongMemEval 데이터셋 필드 매핑
        question_id = row.get("question_id", f"q_{index:03d}")
        question_type = row.get("question_type", "unknown")
        question = row.get("question", "")
        answer = row.get("answer", "")
        question_date = row.get("question_date")

        # haystack_sessions: 대화 세션 리스트
        haystack_sessions = row.get("haystack_sessions", [])
        haystack_dates = row.get("haystack_dates", [])
        answer_session_ids = row.get("answer_session_ids", [])

        if not question or not haystack_sessions:
            logger.warning(f"Skipping item {index}: missing question or sessions")
            return None

        return BenchmarkItem(
            question_id=question_id,
            question_type=question_type,
            question=question,
            answer=answer,
            question_date=question_date,
            haystack_sessions=haystack_sessions,
            haystack_dates=haystack_dates,
            answer_session_ids=answer_session_ids,
        )
    except Exception as e:
        logger.warning(f"Failed to parse item {index}: {e}")
        return None
