"""LongMemEval 인덱싱 전략

haystack_sessions를 mem-mesh 메모리로 변환하는 모듈.
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from app.core.schemas.requests import AddParams
from app.core.storage.direct import DirectStorageBackend

from .models import BenchmarkItem

logger = logging.getLogger(__name__)

# AddParams max_content_length is 10000
DEFAULT_MAX_CONTENT_LENGTH = 9500


class BaseIndexer(ABC):
    """인덱싱 전략 추상 베이스"""

    def __init__(
        self,
        include_date: bool = True,
        max_content_length: int = DEFAULT_MAX_CONTENT_LENGTH,
    ):
        self.include_date = include_date
        self.max_content_length = max_content_length

    @abstractmethod
    def build_chunks(
        self, item: BenchmarkItem
    ) -> List[dict]:
        """BenchmarkItem의 haystack_sessions를 청크로 분할

        Returns:
            List[dict]: 각 dict는 {"content": str, "tags": List[str], "session_ids": List[int]}
        """
        ...

    async def index(
        self,
        storage: DirectStorageBackend,
        item: BenchmarkItem,
        project_id: str,
    ) -> int:
        """BenchmarkItem을 mem-mesh에 인덱싱

        Args:
            storage: DirectStorageBackend 인스턴스
            item: 벤치마크 항목
            project_id: 질문별 격리용 project_id

        Returns:
            인덱싱된 메모리 수
        """
        chunks = self.build_chunks(item)
        count = 0

        for chunk in chunks:
            content = chunk["content"]
            tags = chunk["tags"]

            # content 길이 확인 (min 10, max 10000)
            if len(content) < 10:
                continue

            try:
                params = AddParams(
                    content=content,
                    project_id=project_id,
                    category="task",
                    source="longmemeval",
                    tags=tags,
                )
                await storage.add_memory(params)
                count += 1
            except Exception as e:
                logger.warning(
                    f"Failed to index chunk for {item.question_id}: {e}"
                )

        return count


class SessionIndexer(BaseIndexer):
    """1 세션 = 1 메모리 전략 (P0)

    각 세션 전체를 하나의 메모리로 저장.
    10K자 초과 시 분할.
    """

    def build_chunks(
        self, item: BenchmarkItem
    ) -> List[dict]:
        chunks: List[dict] = []

        for i, session in enumerate(item.haystack_sessions):
            date_str = (
                item.haystack_dates[i]
                if i < len(item.haystack_dates)
                else ""
            )

            # 세션 발화를 하나의 텍스트로 결합
            lines: List[str] = []
            if self.include_date and date_str:
                lines.append(f"[{date_str}]")

            for utterance in session:
                lines.append(utterance)

            content = "\n".join(lines)
            tags = [f"session_{i}"]
            if date_str:
                tags.append(f"date_{date_str.split()[0] if ' ' in date_str else date_str}")

            # 길이 초과 시 분할
            if len(content) > self.max_content_length:
                sub_chunks = self._split_content(
                    content, tags, i
                )
                chunks.extend(sub_chunks)
            else:
                chunks.append(
                    {
                        "content": content,
                        "tags": tags,
                        "session_ids": [i],
                    }
                )

        return chunks

    def _split_content(
        self, content: str, base_tags: List[str], session_id: int
    ) -> List[dict]:
        """긴 콘텐츠를 max_content_length 이하로 분할"""
        parts: List[dict] = []
        lines = content.split("\n")
        current_lines: List[str] = []
        current_len = 0
        part_idx = 0

        for line in lines:
            if current_len + len(line) + 1 > self.max_content_length and current_lines:
                parts.append(
                    {
                        "content": "\n".join(current_lines),
                        "tags": base_tags + [f"part_{part_idx}"],
                        "session_ids": [session_id],
                    }
                )
                current_lines = []
                current_len = 0
                part_idx += 1

            current_lines.append(line)
            current_len += len(line) + 1

        if current_lines:
            parts.append(
                {
                    "content": "\n".join(current_lines),
                    "tags": base_tags + [f"part_{part_idx}"] if part_idx > 0 else base_tags,
                    "session_ids": [session_id],
                }
            )

        return parts


class WindowIndexer(BaseIndexer):
    """슬라이딩 윈도우 전략 (P1)

    3-5턴 슬라이딩 윈도우로 세션을 분할.
    """

    def __init__(
        self,
        window_size: int = 5,
        overlap: int = 1,
        include_date: bool = True,
        max_content_length: int = DEFAULT_MAX_CONTENT_LENGTH,
    ):
        super().__init__(include_date, max_content_length)
        self.window_size = window_size
        self.overlap = overlap

    def build_chunks(
        self, item: BenchmarkItem
    ) -> List[dict]:
        chunks: List[dict] = []

        for i, session in enumerate(item.haystack_sessions):
            date_str = (
                item.haystack_dates[i]
                if i < len(item.haystack_dates)
                else ""
            )

            step = max(1, self.window_size - self.overlap)
            for w_start in range(0, len(session), step):
                w_end = min(w_start + self.window_size, len(session))
                window = session[w_start:w_end]

                lines: List[str] = []
                if self.include_date and date_str:
                    lines.append(f"[{date_str}]")

                for utterance in window:
                    lines.append(utterance)

                content = "\n".join(lines)
                if len(content) > self.max_content_length:
                    content = content[: self.max_content_length]

                tags = [
                    f"session_{i}",
                    f"window_{w_start}_{w_end}",
                ]
                if date_str:
                    tags.append(f"date_{date_str.split()[0] if ' ' in date_str else date_str}")

                chunks.append(
                    {
                        "content": content,
                        "tags": tags,
                        "session_ids": [i],
                    }
                )

        return chunks


class TurnIndexer(BaseIndexer):
    """턴 단위 전략 (P2)

    user+assistant 쌍을 1개 메모리로 저장.
    """

    def build_chunks(
        self, item: BenchmarkItem
    ) -> List[dict]:
        chunks: List[dict] = []

        for i, session in enumerate(item.haystack_sessions):
            date_str = (
                item.haystack_dates[i]
                if i < len(item.haystack_dates)
                else ""
            )

            # 발화를 2개씩 묶어 턴으로 처리
            for t in range(0, len(session), 2):
                turn_utterances = session[t : t + 2]

                lines: List[str] = []
                if self.include_date and date_str:
                    lines.append(f"[{date_str}]")

                for utterance in turn_utterances:
                    lines.append(utterance)

                content = "\n".join(lines)
                if len(content) > self.max_content_length:
                    content = content[: self.max_content_length]

                tags = [
                    f"session_{i}",
                    f"turn_{t // 2}",
                ]
                if date_str:
                    tags.append(f"date_{date_str.split()[0] if ' ' in date_str else date_str}")

                chunks.append(
                    {
                        "content": content,
                        "tags": tags,
                        "session_ids": [i],
                    }
                )

        return chunks


def create_indexer(
    strategy: str = "session",
    window_size: int = 5,
    window_overlap: int = 1,
    include_date: bool = True,
    max_content_length: int = DEFAULT_MAX_CONTENT_LENGTH,
) -> BaseIndexer:
    """인덱서 팩토리

    Args:
        strategy: session, window, turn
        window_size: WindowIndexer용 윈도우 크기
        window_overlap: WindowIndexer용 오버랩
        include_date: 날짜를 content에 포함할지
        max_content_length: 최대 콘텐츠 길이

    Returns:
        BaseIndexer 구현체
    """
    if strategy == "session":
        return SessionIndexer(
            include_date=include_date,
            max_content_length=max_content_length,
        )
    elif strategy == "window":
        return WindowIndexer(
            window_size=window_size,
            overlap=window_overlap,
            include_date=include_date,
            max_content_length=max_content_length,
        )
    elif strategy == "turn":
        return TurnIndexer(
            include_date=include_date,
            max_content_length=max_content_length,
        )
    else:
        raise ValueError(f"Unknown indexing strategy: {strategy}")
