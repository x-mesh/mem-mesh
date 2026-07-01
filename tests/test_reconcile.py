"""ReconcileService (SSOT #3, F2) 테스트.

비동기 reconcile 워커: reconcile_queue claim → C2 revalidate → NLI pre-gate →
LLM 판정 → PROPOSED 관계 기록. NLI/LLM은 fake로 대체(모델 로드 없이 로직 검증).
"""

import json
import uuid
from dataclasses import dataclass

import pytest

from app.core.services.reconcile import ReconcileService

NOW = "2026-01-01T00:00:00Z"
EMB = b"\x00" * 16


@dataclass
class _FakeConflict:
    memory_id: str = "old"
    content_preview: str = "x"
    contradiction_score: float = 0.9
    similarity_score: float = 0.95


class _FakeCD:
    def __init__(self, conflicts):
        self._c = conflicts

    def detect_conflicts(self, content, candidates):
        return self._c


class _FakeEnricher:
    def __init__(self, verdict, merged_text=None):
        self.v = verdict
        self.m = merged_text

    async def reconcile(self, new_content, old_content):
        return {"verdict": self.v, "rationale": "r", "merged_text": self.m}


async def _add(db, mid, content_hash=None):
    await db.add_memory(
        {
            "id": mid,
            "content": f"{mid} content here",
            "content_hash": content_hash or f"h{mid}",
            "embedding": EMB,
            "source": "t",
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


async def _enqueue(db, new_id, old_id, new_hash, old_hash, sim=0.95):
    await db.execute(
        "INSERT INTO reconcile_queue (id, new_memory_id, old_memory_id, similarity, "
        "new_content_hash, old_content_hash, status, next_attempt_at, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)",
        (str(uuid.uuid4()), new_id, old_id, sim, new_hash, old_hash, NOW, NOW),
    )


class TestReconcileService:
    @pytest.mark.asyncio
    async def test_process_supersede_old(self, temp_db):
        await _add(temp_db, "new")
        await _add(temp_db, "old")
        await _enqueue(temp_db, "new", "old", "hnew", "hold")
        svc = ReconcileService(temp_db)
        r = await svc.process_next(
            worker_id="w",
            enricher=_FakeEnricher("supersede_old"),
            conflict_detector=_FakeCD([_FakeConflict()]),
        )
        assert r["verdict"] == "supersede_old"
        row = await temp_db.fetchone(
            "SELECT relation_type, metadata FROM memory_relations WHERE source_id='new'"
        )
        assert row["relation_type"] == "supersedes"
        assert json.loads(row["metadata"])["state"] == "proposed"
        q = await temp_db.fetchone(
            "SELECT status FROM reconcile_queue WHERE new_memory_id='new'"
        )
        assert q["status"] == "done"

    @pytest.mark.asyncio
    async def test_revalidate_stale_on_hash_drift(self, temp_db):
        await _add(temp_db, "new")
        await _add(temp_db, "old")
        # queued hash does not match current content_hash → stale (C2)
        await _enqueue(temp_db, "new", "old", "STALE", "hold")
        svc = ReconcileService(temp_db)
        r = await svc.process_next(
            worker_id="w",
            enricher=_FakeEnricher("supersede_old"),
            conflict_detector=_FakeCD([_FakeConflict()]),
        )
        assert r.get("stale") is True
        c = await temp_db.fetchone("SELECT COUNT(*) AS c FROM memory_relations")
        assert c["c"] == 0

    @pytest.mark.asyncio
    async def test_no_conflict_no_relation(self, temp_db):
        await _add(temp_db, "new")
        await _add(temp_db, "old")
        await _enqueue(temp_db, "new", "old", "hnew", "hold")
        svc = ReconcileService(temp_db)
        r = await svc.process_next(
            worker_id="w",
            enricher=_FakeEnricher("supersede_old"),
            conflict_detector=_FakeCD([]),  # NLI: no contradiction
        )
        assert r.get("no_conflict") is True
        c = await temp_db.fetchone("SELECT COUNT(*) AS c FROM memory_relations")
        assert c["c"] == 0

    @pytest.mark.asyncio
    async def test_supersede_new_direction_c3(self, temp_db):
        await _add(temp_db, "new")
        await _add(temp_db, "old")
        await _enqueue(temp_db, "new", "old", "hnew", "hold")
        svc = ReconcileService(temp_db)
        await svc.process_next(
            worker_id="w",
            enricher=_FakeEnricher("supersede_new"),
            conflict_detector=_FakeCD([_FakeConflict()]),
        )
        # old is correct → old supersedes new (new demoted on approval, C3)
        row = await temp_db.fetchone(
            "SELECT source_id, target_id FROM memory_relations "
            "WHERE relation_type='supersedes'"
        )
        assert row["source_id"] == "old"
        assert row["target_id"] == "new"

    @pytest.mark.asyncio
    async def test_empty_queue(self, temp_db):
        svc = ReconcileService(temp_db)
        r = await svc.process_next(
            worker_id="w",
            enricher=_FakeEnricher("supersede_old"),
            conflict_detector=_FakeCD([]),
        )
        assert r["job_id"] is None
