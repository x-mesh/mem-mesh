"""ReconcileService (SSOT #3, F2) 테스트.

비동기 reconcile 워커: reconcile_queue claim → C2 revalidate → age pre-gate →
LLM 판정 → PROPOSED 관계 기록. LLM은 fake로 대체(모델 로드 없이 로직 검증).
"""

import json
import uuid
from dataclasses import dataclass

import pytest

from app.core.services.reconcile import ReconcileService

NOW = "2026-01-01T00:00:00Z"
LATER = "2026-01-20T00:00:00Z"  # 19 days on — clears the default 3-day gate
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


async def _add(db, mid, content_hash=None, created_at=NOW):
    await db.add_memory(
        {
            "id": mid,
            "content": f"{mid} content here",
            "content_hash": content_hash or f"h{mid}",
            "embedding": EMB,
            "source": "t",
            "created_at": created_at,
            "updated_at": created_at,
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
        await _add(temp_db, "new", created_at=LATER)
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
        await _add(temp_db, "new", created_at=LATER)
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
    async def test_same_day_pair_is_skipped_before_the_llm(self, temp_db):
        """Two memories written the same day are one job recorded twice."""
        await _add(temp_db, "new")
        await _add(temp_db, "old")  # same created_at
        await _enqueue(temp_db, "new", "old", "hnew", "hold")
        svc = ReconcileService(temp_db)

        called = []

        class _Spy(_FakeEnricher):
            async def reconcile(self, new_content, old_content):
                called.append(1)
                return await super().reconcile(new_content, old_content)

        r = await svc.process_next(worker_id="w", enricher=_Spy("supersede_old"))

        assert r.get("too_close") is True
        assert called == [], "the age gate must run before the paid LLM call"
        c = await temp_db.fetchone("SELECT COUNT(*) AS c FROM memory_relations")
        assert c["c"] == 0

    @pytest.mark.asyncio
    async def test_gap_threshold_is_configurable(self, temp_db):
        await _add(temp_db, "new", created_at="2026-01-06T00:00:00Z")  # 5 days
        await _add(temp_db, "old")
        await _enqueue(temp_db, "new", "old", "hnew", "hold")

        strict = ReconcileService(temp_db, min_age_gap_days=7.0)
        r = await strict.process_next(
            worker_id="w", enricher=_FakeEnricher("supersede_old")
        )
        assert r.get("too_close") is True

        await temp_db.execute("UPDATE reconcile_queue SET status='pending'")
        lenient = ReconcileService(temp_db, min_age_gap_days=3.0)
        r = await lenient.process_next(
            worker_id="w", enricher=_FakeEnricher("supersede_old")
        )
        assert r.get("verdict") == "supersede_old"

    @pytest.mark.asyncio
    async def test_relation_records_the_age_gap(self, temp_db):
        await _add(temp_db, "new", created_at=LATER)
        await _add(temp_db, "old")
        await _enqueue(temp_db, "new", "old", "hnew", "hold")
        svc = ReconcileService(temp_db)
        await svc.process_next(worker_id="w", enricher=_FakeEnricher("supersede_old"))

        row = await temp_db.fetchone(
            "SELECT metadata FROM memory_relations WHERE source_id='new'"
        )
        assert json.loads(row["metadata"])["age_gap_days"] == 19.0

    @pytest.mark.asyncio
    async def test_supersede_new_direction_c3(self, temp_db):
        await _add(temp_db, "new", created_at=LATER)
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
