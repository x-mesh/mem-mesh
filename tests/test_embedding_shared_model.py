"""EmbeddingService shares one loaded model per model_name across instances, so
N concurrent workers (or repeated constructions) don't each load a ~2GB copy —
the root cause of the observed multi-GB memory blowup under parallelism.

Uses a fake SentenceTransformer so no real model is loaded (CLAUDE.md L1/L5)."""

import app.core.embeddings.service as svc_mod


class _FakeModel:
    def __init__(self, name):
        self.name = name


def test_model_loaded_once_and_shared_across_instances(monkeypatch):
    calls = {"n": 0}

    def _fake_ctor(name):
        calls["n"] += 1
        return _FakeModel(name)

    monkeypatch.setattr(svc_mod, "SentenceTransformer", _fake_ctor)
    svc_mod.EmbeddingService._MODEL_CACHE.clear()

    a = svc_mod.EmbeddingService._get_or_load_model("model-x")
    b = svc_mod.EmbeddingService._get_or_load_model("model-x")

    assert a is b  # same shared object, not two copies
    assert calls["n"] == 1  # constructed exactly once

    # A different model loads its own (still cached).
    c = svc_mod.EmbeddingService._get_or_load_model("model-y")
    assert c is not a
    assert calls["n"] == 2
    assert svc_mod.EmbeddingService._get_or_load_model("model-y") is c
    assert calls["n"] == 2


def test_cache_is_class_level_shared_state(monkeypatch):
    """Two EmbeddingService instances resolve to the same cached model."""

    def _fake_ctor(name):
        return _FakeModel(name)

    monkeypatch.setattr(svc_mod, "SentenceTransformer", _fake_ctor)
    svc_mod.EmbeddingService._MODEL_CACHE.clear()

    m1 = svc_mod.EmbeddingService._get_or_load_model("shared")
    m2 = svc_mod.EmbeddingService._get_or_load_model("shared")
    assert m1 is m2
    assert "shared" in svc_mod.EmbeddingService._MODEL_CACHE
