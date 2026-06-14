"""Regression tests for async embedding offload (red-team C4).

aembed/aembed_batch must run the blocking model.encode() on a worker thread so
the event loop stays responsive. The blocking-CPU encode used to be called
directly from async code, freezing every other request for its duration.
"""

import asyncio
import time

import numpy as np


def _make_service():
    """Build an EmbeddingService with a fake, deliberately-slow model without
    triggering the heavy real __init__ (model download)."""
    from app.core.embeddings.service import EmbeddingService

    svc = EmbeddingService.__new__(EmbeddingService)
    svc.metrics_collector = None
    svc.model_name = "fake"
    svc._defer_loading = False
    svc._status = "ready"
    svc._prepare_text = lambda text, is_query=False: text

    class _SlowModel:
        def encode(self, text, **kwargs):
            time.sleep(0.1)  # simulate blocking Torch inference
            if isinstance(text, list):
                return np.array([[0.1, 0.2, 0.3]] * len(text), dtype=np.float32)
            return np.array([0.1, 0.2, 0.3], dtype=np.float32)

    svc.model = _SlowModel()
    return svc


async def test_aembed_does_not_block_event_loop():
    svc = _make_service()

    ticks = 0

    async def ticker():
        nonlocal ticks
        for _ in range(20):
            await asyncio.sleep(0.01)
            ticks += 1

    tick_task = asyncio.create_task(ticker())
    result = await svc.aembed("hello")
    await tick_task

    assert result == [0.1, 0.2, 0.3] or len(result) == 3
    # During the 0.1s blocking encode (off-loaded to a thread) the loop kept
    # running the ticker. A synchronous on-loop encode would have frozen it.
    assert ticks >= 5, f"event loop appeared blocked (only {ticks} ticks)"


async def test_aembed_matches_sync_embed():
    svc = _make_service()
    assert await svc.aembed("x") == svc.embed("x")


async def test_aembed_batch_offloads_and_matches():
    svc = _make_service()
    out = await svc.aembed_batch(["a", "b"])
    assert len(out) == 2 and len(out[0]) == 3
    assert out == svc.embed_batch(["a", "b"])
