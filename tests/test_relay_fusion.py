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
