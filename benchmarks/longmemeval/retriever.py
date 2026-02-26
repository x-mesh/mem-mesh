"""LongMemEval 검색 래퍼 + 메트릭 수집"""

import logging
import math
import time
from typing import Dict, List, Set

from app.core.schemas.requests import SearchParams
from app.core.schemas.responses import SearchResult
from app.core.storage.direct import DirectStorageBackend

from .models import RetrievalMetrics

logger = logging.getLogger(__name__)


class Retriever:
    """mem-mesh 검색 래퍼"""

    def __init__(
        self,
        storage: DirectStorageBackend,
        top_k: int = 10,
        search_mode: str = "hybrid",
        recency_weight: float = 0.0,
    ):
        self.storage = storage
        self.top_k = min(top_k, 20)  # SearchParams limit ≤ 20
        self.search_mode = search_mode
        self.recency_weight = recency_weight

    async def retrieve(
        self,
        query: str,
        project_id: str,
        answer_session_ids: List[int],
    ) -> tuple[List[SearchResult], List[int], RetrievalMetrics]:
        """검색 수행 + 메트릭 계산

        Args:
            query: 검색 쿼리 (질문 텍스트)
            project_id: 질문별 격리용 project_id
            answer_session_ids: 정답 세션 ID 목록

        Returns:
            (검색 결과, 검색된 세션 ID 목록, 검색 메트릭)
        """
        params = SearchParams(
            query=query,
            project_id=project_id,
            limit=self.top_k,
            search_mode=self.search_mode,
            recency_weight=self.recency_weight,
        )

        start_time = time.time()
        response = await self.storage.search_memories(params)
        elapsed_ms = (time.time() - start_time) * 1000

        # 검색 결과에서 session ID 추출
        retrieved_session_ids = _extract_session_ids(response.results)

        # 메트릭 계산
        answer_set = set(answer_session_ids)
        metrics = _compute_metrics(
            retrieved_session_ids, answer_set, elapsed_ms
        )

        return response.results, retrieved_session_ids, metrics


def _extract_session_ids(results: List[SearchResult]) -> List[int]:
    """검색 결과의 tags에서 session ID 추출

    tags 형식: ["session_0", "session_3", ...]
    """
    session_ids: List[int] = []
    seen: Set[int] = set()

    for result in results:
        if not result.tags:
            continue
        for tag in result.tags:
            if tag.startswith("session_"):
                try:
                    sid = int(tag.split("_")[1])
                    if sid not in seen:
                        session_ids.append(sid)
                        seen.add(sid)
                except (ValueError, IndexError):
                    continue

    return session_ids


def _compute_metrics(
    retrieved_ids: List[int],
    answer_set: Set[int],
    elapsed_ms: float,
) -> RetrievalMetrics:
    """검색 메트릭 계산

    Args:
        retrieved_ids: 검색된 세션 ID 목록 (순서 유지)
        answer_set: 정답 세션 ID 집합
        elapsed_ms: 검색 소요 시간
    """
    ks = [1, 3, 5, 10]
    recall_any: Dict[int, float] = {}
    recall_all: Dict[int, float] = {}
    ndcg: Dict[int, float] = {}

    if not answer_set:
        # 정답 세션이 없으면 모든 메트릭 0
        for k in ks:
            recall_any[k] = 0.0
            recall_all[k] = 0.0
            ndcg[k] = 0.0
        return RetrievalMetrics(
            recall_any=recall_any,
            recall_all=recall_all,
            ndcg=ndcg,
            retrieval_time_ms=elapsed_ms,
        )

    for k in ks:
        top_k_ids = set(retrieved_ids[:k])

        # recall_any@k: 정답 세션 중 하나라도 top-k에 있는지
        hits = top_k_ids & answer_set
        recall_any[k] = 1.0 if len(hits) > 0 else 0.0

        # recall_all@k: 모든 정답 세션이 top-k에 있는지
        recall_all[k] = 1.0 if answer_set.issubset(top_k_ids) else 0.0

        # NDCG@k
        ndcg[k] = _ndcg_at_k(retrieved_ids, answer_set, k)

    return RetrievalMetrics(
        recall_any=recall_any,
        recall_all=recall_all,
        ndcg=ndcg,
        retrieval_time_ms=elapsed_ms,
    )


def _ndcg_at_k(
    retrieved_ids: List[int], answer_set: Set[int], k: int
) -> float:
    """NDCG@k 계산"""
    # DCG
    dcg = 0.0
    for i, sid in enumerate(retrieved_ids[:k]):
        rel = 1.0 if sid in answer_set else 0.0
        dcg += rel / math.log2(i + 2)  # i+2 because log2(1)=0

    # Ideal DCG
    ideal_rels = sorted(
        [1.0 if sid in answer_set else 0.0 for sid in retrieved_ids[:k]],
        reverse=True,
    )
    # Add remaining ideal hits if answer_set has more items
    remaining = len(answer_set) - sum(1 for r in ideal_rels if r > 0)
    if remaining > 0:
        ideal_rels = [1.0] * min(len(answer_set), k)
        ideal_rels.extend([0.0] * max(0, k - len(ideal_rels)))

    idcg = 0.0
    for i, rel in enumerate(ideal_rels[:k]):
        idcg += rel / math.log2(i + 2)

    if idcg == 0:
        return 0.0

    return dcg / idcg
