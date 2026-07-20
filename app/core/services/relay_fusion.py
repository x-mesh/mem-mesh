"""Federated relay search fusion utilities."""

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, Optional


def fuse_relay_results_rrf(
    local_results: Iterable[Mapping[str, Any]],
    hub_results: Iterable[Mapping[str, Any]],
    *,
    id_key: str = "id",
    limit: int = 10,
    k: int = 60,
    weights: Optional[Mapping[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Fuse local and hub search results with Reciprocal Rank Fusion.

    The first source occurrence is kept as the display payload. Duplicate ids
    accumulate score from both sources and expose a `sources` list.

    ``weights`` scales each source's rank contribution (missing source → 1.0),
    e.g. ``{"local": 1.0, "hub": 0.75}`` ranks local above hub at equal rank.
    """

    entries: Dict[str, Dict[str, Any]] = {}
    scores: Dict[str, float] = {}

    def add(source: str, results: Iterable[Mapping[str, Any]]) -> None:
        weight = (weights or {}).get(source, 1.0)
        for rank, item in enumerate(results, start=1):
            item_id = str(item[id_key])
            if item_id not in entries:
                entry = deepcopy(dict(item))
                entry["sources"] = [source]
                entries[item_id] = entry
            elif source not in entries[item_id]["sources"]:
                entries[item_id]["sources"].append(source)
            scores[item_id] = scores.get(item_id, 0.0) + weight / (k + rank)

    add("local", local_results)
    add("hub", hub_results)

    ordered_ids = sorted(scores, key=lambda item_id: scores[item_id], reverse=True)
    fused = []
    for item_id in ordered_ids[: max(0, limit)]:
        entry = entries[item_id]
        entry["rrf_score"] = scores[item_id]
        fused.append(entry)
    return fused


def fuse_relay_results_by_score(
    local_results: Iterable[Mapping[str, Any]],
    hub_results: Iterable[Mapping[str, Any]],
    *,
    id_key: str = "id",
    score_key: str = "similarity_score",
    limit: int = 10,
    hub_penalty: float = 0.0,
) -> List[Dict[str, Any]]:
    """Fuse local and hub results on raw similarity, not rank.

    Rank fusion (RRF) exists to combine rankers whose scores are not
    comparable. Both corpora here are scored by the SAME embedding model, so
    their cosine similarities *are* directly comparable — and converting them
    to ranks throws away the only signal that distinguishes "the hub has the
    answer" from "the hub has nothing relevant".

    Discarding it is not merely lossy, it is structurally fatal: under RRF the
    local list's rank N always outscores the hub's rank 1 for any N below the
    weight crossover (with hub weight 0.75 and k=60 that is local rank 22),
    which no reachable ``limit`` can cross. Hub results were therefore fetched,
    ranked, and then always truncated away.

    ``hub_penalty`` subtracts a flat margin from hub scores as a tie-breaker
    toward local memories; 0.0 keeps the comparison honest.
    """

    entries: Dict[str, Dict[str, Any]] = {}
    scores: Dict[str, float] = {}

    def add(source: str, results: Iterable[Mapping[str, Any]], penalty: float) -> None:
        for item in results:
            item_id = str(item[id_key])
            score = float(item.get(score_key) or 0.0) - penalty
            if item_id not in entries:
                entry = deepcopy(dict(item))
                entry["sources"] = [source]
                entries[item_id] = entry
            elif source not in entries[item_id]["sources"]:
                entries[item_id]["sources"].append(source)
            # A duplicate id keeps its best score rather than accumulating, so
            # appearing in both corpora cannot outrank a genuinely closer hit.
            scores[item_id] = max(scores.get(item_id, float("-inf")), score)

    add("local", local_results, 0.0)
    add("hub", hub_results, hub_penalty)

    ordered_ids = sorted(scores, key=lambda item_id: scores[item_id], reverse=True)
    fused = []
    for item_id in ordered_ids[: max(0, limit)]:
        entry = entries[item_id]
        entry["fusion_score"] = scores[item_id]
        fused.append(entry)
    return fused
