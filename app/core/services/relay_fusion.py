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
