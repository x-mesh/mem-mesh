"""Relay federated RRF fusion tests."""

from app.core.services.relay_fusion import (
    fuse_relay_results_by_score,
    fuse_relay_results_rrf,
)


def test_fuse_relay_results_rrf_merges_local_and_hub_by_rank():
    local = [
        {"id": "local-a", "content": "A"},
        {"id": "shared-1", "content": "local copy"},
    ]
    hub = [
        {"id": "shared-1", "content": "hub copy"},
        {"id": "hub-b", "content": "B"},
    ]

    fused = fuse_relay_results_rrf(local, hub, limit=3, k=60)

    assert [item["id"] for item in fused] == ["shared-1", "local-a", "hub-b"]
    assert fused[0]["sources"] == ["local", "hub"]
    assert fused[0]["content"] == "local copy"
    assert fused[1]["sources"] == ["local"]
    assert fused[2]["sources"] == ["hub"]


def test_fuse_relay_results_rrf_accepts_custom_id_key_and_limits():
    local = [{"memory_id": "a"}, {"memory_id": "b"}]
    hub = [{"memory_id": "c"}, {"memory_id": "d"}]

    fused = fuse_relay_results_rrf(local, hub, id_key="memory_id", limit=2)

    assert [item["memory_id"] for item in fused] == ["a", "c"]


def test_fuse_relay_results_rrf_weights_rank_local_above_hub_at_equal_rank():
    local = [{"id": "local-a"}, {"id": "local-b"}]
    hub = [{"id": "hub-a"}, {"id": "hub-b"}]

    fused = fuse_relay_results_rrf(
        local, hub, limit=4, weights={"local": 1.0, "hub": 0.75}
    )

    # With k=60 a 0.75 hub weight ranks the whole local list above hub:
    # 1.0/61 > 1.0/62 > 0.75/61 > 0.75/62
    assert [item["id"] for item in fused] == ["local-a", "local-b", "hub-a", "hub-b"]
    assert fused[0]["rrf_score"] > fused[1]["rrf_score"] > fused[2]["rrf_score"]


def test_fuse_relay_results_rrf_weights_none_matches_default_behavior():
    local = [{"id": "a"}, {"id": "s"}]
    hub = [{"id": "s"}, {"id": "b"}]

    default = fuse_relay_results_rrf(local, hub, limit=3)
    explicit = fuse_relay_results_rrf(local, hub, limit=3, weights=None)

    assert [i["id"] for i in default] == [i["id"] for i in explicit]
    assert [i["rrf_score"] for i in default] == [i["rrf_score"] for i in explicit]


def test_fuse_by_score_surfaces_hub_when_it_scores_higher():
    """The regression RRF could not express: hub wins on relevance.

    Under RRF the local list's rank 10 outscores the hub's rank 1, so a hub
    result that is genuinely closer was always truncated away.
    """
    local = [{"id": f"L{i}", "similarity_score": 0.52 - i * 0.01} for i in range(1, 11)]
    hub = [{"id": f"H{i}", "similarity_score": 0.56 - i * 0.01} for i in range(1, 11)]

    fused = fuse_relay_results_by_score(local, hub, limit=10)

    assert fused[0]["id"] == "H1"
    assert fused[0]["sources"] == ["hub"]
    assert any(entry["sources"] == ["local"] for entry in fused)

    rrf = fuse_relay_results_rrf(
        local, hub, limit=10, weights={"local": 1.0, "hub": 0.75}
    )
    assert all(entry["sources"] == ["local"] for entry in rrf)


def test_fuse_by_score_keeps_local_when_local_scores_higher():
    """The other direction: a fix that always promotes hub is not a fix."""
    local = [{"id": "L1", "similarity_score": 0.99}]
    hub = [{"id": "H1", "similarity_score": 0.47}]

    fused = fuse_relay_results_by_score(local, hub, limit=5)

    assert [entry["id"] for entry in fused] == ["L1", "H1"]


def test_fuse_by_score_orders_strictly_by_similarity():
    local = [{"id": "L1", "similarity_score": 0.40}]
    hub = [
        {"id": "H1", "similarity_score": 0.90},
        {"id": "H2", "similarity_score": 0.10},
    ]

    fused = fuse_relay_results_by_score(local, hub, limit=3)

    assert [entry["id"] for entry in fused] == ["H1", "L1", "H2"]
    assert fused[0]["fusion_score"] == 0.90


def test_fuse_by_score_dedupes_shared_id_without_inflating_rank():
    """A memory in both corpora keeps its best score, not the sum.

    Summing would let a mediocre hit present on both sides outrank a strictly
    closer one that only exists in a single corpus.
    """
    local = [{"id": "same", "similarity_score": 0.50}]
    hub = [
        {"id": "same", "similarity_score": 0.55},
        {"id": "better", "similarity_score": 0.80},
    ]

    fused = fuse_relay_results_by_score(local, hub, limit=5)

    assert [entry["id"] for entry in fused] == ["better", "same"]
    shared = fused[1]
    assert shared["fusion_score"] == 0.55
    assert set(shared["sources"]) == {"local", "hub"}


def test_fuse_by_score_hub_penalty_breaks_near_ties_toward_local():
    local = [{"id": "L1", "similarity_score": 0.50}]
    hub = [{"id": "H1", "similarity_score": 0.52}]

    assert [e["id"] for e in fuse_relay_results_by_score(local, hub, limit=2)] == [
        "H1",
        "L1",
    ]
    penalised = fuse_relay_results_by_score(local, hub, limit=2, hub_penalty=0.05)
    assert [e["id"] for e in penalised] == ["L1", "H1"]


def test_fuse_by_score_treats_missing_score_as_zero():
    local = [{"id": "L1"}]
    hub = [{"id": "H1", "similarity_score": 0.30}]

    fused = fuse_relay_results_by_score(local, hub, limit=2)

    assert [entry["id"] for entry in fused] == ["H1", "L1"]
    assert fused[1]["fusion_score"] == 0.0
