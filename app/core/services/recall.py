"""세션 재개 시 큐레이션 메모리를 surface하는 헬퍼 (read-only).

``session_resume`` / ``SessionStart`` 훅은 그동안 pins만 반환했다. 저장된
17k+ 메모리 코퍼스가 정규 세션 루프에서 한 번도 읽히지 않아(운영 dead_ratio
≈0.999) 시스템이 "쓰기 전용 싱크"로 전락한 것이 핵심 문제였다.

이 헬퍼는 열린 작업(open/in_progress pin) 맥락을 쿼리로 관련 메모리를 검색해
세션 시작 시 함께 노출함으로써 읽기 루프를 닫는다.

설계 원칙:
- **read-only**: ``search(record_access=False)`` 로 호출해 access_count를
  올리지 않는다. 자동 surface가 recall 지표를 부풀리면 안 되기 때문이다.
  실제 recall은 에이전트가 직접 ``search`` 할 때만 집계된다.
- **큐레이션 우선**: 대화 덤프(Q:/A:)·노이즈를 피하려 가치 높은 카테고리만
  노출한다(``_SURFACE_CATEGORIES``). 미래에 source/importance 필터를 추가할
  수 있다.
- **best-effort**: 검색 실패는 절대 세션 재개를 깨뜨리지 않는다 — 빈 목록 반환.
"""

import logging
from typing import Any, List, Optional, Set

logger = logging.getLogger(__name__)

# 재사용 가치가 높은 카테고리만 surface (bug 50% 편향·대화 덤프 노이즈 회피).
_SURFACE_CATEGORIES: Set[str] = {"decision", "code_snippet", "incident"}


async def surface_relevant_memories(
    search_service: Any,
    project_id: str,
    *,
    query: str,
    limit: int = 3,
    min_score: float = 0.35,
    categories: Optional[Set[str]] = None,
) -> List[dict]:
    """열린 작업 맥락으로 관련 큐레이션 메모리를 read-only로 surface한다.

    Args:
        search_service: ``UnifiedSearchService`` (또는 ``search`` 시그니처 호환).
            None이면 빈 목록.
        project_id: 검색 스코프.
        query: 시드 쿼리 (보통 열린 pin 내용 결합). 비면 빈 목록.
        limit: 반환할 최대 메모리 수.
        min_score: 최소 유사도 (0~1). 약한 매치 컷오프.
        categories: surface 허용 카테고리. None이면 ``_SURFACE_CATEGORIES``.

    Returns:
        list[dict]: {id, category, content(≤240자), created_at(YYYY-MM-DD), score}
    """
    if search_service is None or not query or not query.strip():
        return []

    cats = categories if categories is not None else _SURFACE_CATEGORIES

    try:
        result = await search_service.search(
            query=query[:300],
            project_id=project_id,
            limit=max(limit * 3, 8),
            sort_by="relevance",
            sort_direction="desc",
            search_mode="hybrid",
            record_access=False,  # read-only: surfacing != genuine recall
        )
    except Exception as e:  # noqa: BLE001 — best-effort, never break resume
        logger.debug(f"surface_relevant_memories search failed: {e}")
        return []

    items = getattr(result, "results", None) or []
    out: List[dict] = []
    seen: Set[str] = set()
    for r in items:
        rid = getattr(r, "id", None) if not isinstance(r, dict) else r.get("id")
        if rid is None or rid in seen:
            continue
        cat = getattr(r, "category", None) if not isinstance(r, dict) else r.get("category")
        if cats and cat not in cats:
            continue
        score = (
            getattr(r, "similarity_score", 0.0)
            if not isinstance(r, dict)
            else r.get("similarity_score", 0.0)
        ) or 0.0
        if float(score) < min_score:
            continue
        content = (
            getattr(r, "content", "") if not isinstance(r, dict) else r.get("content", "")
        ) or ""
        created = (
            getattr(r, "created_at", "")
            if not isinstance(r, dict)
            else r.get("created_at", "")
        ) or ""
        seen.add(rid)
        out.append(
            {
                "id": rid,
                "category": cat,
                "content": content[:240],
                "created_at": str(created)[:10],
                "score": round(float(score), 3),
            }
        )
        if len(out) >= limit:
            break
    return out
