"""Relay federated RRF fusion tests."""

from app.core.services.relay_fusion import fuse_relay_results_rrf


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
