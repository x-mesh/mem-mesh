"""CurationService (SSOT #3, F4) 테스트.

사람 게이트: PROPOSED 관계 조회 + 승인/거부/dismiss/merge. 승인 시에만 status가
flip된다(불변식: new는 승인 전까지 canonical). merge는 fake memory_service로
새 canonical 생성 경로를 검증.
"""

import json
import uuid

import pytest

from app.core.services.curation import CurationService

NOW = "2026-01-01T00:00:00Z"
EMB = b"\x00" * 16


async def _add(db, mid, project="p1"):
    await db.add_memory(
        {
            "id": mid,
            "content": f"{mid} original content",
            "content_hash": f"h{mid}",
            "embedding": EMB,
            "source": "t",
            "project_id": project,
            "category": "idea",
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


async def _rel(db, rid, src, tgt, rtype, state, verdict="supersede_old", merged=None):
    meta = {"state": state, "verdict": verdict}
    if merged:
        meta["merged_text"] = merged
    await db.execute(
        "INSERT INTO memory_relations (id, source_id, target_id, relation_type, "
        "strength, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, 1.0, ?, ?, ?)",
        (rid, src, tgt, rtype, json.dumps(meta), NOW, NOW),
    )


class _FakeMemSvc:
    def __init__(self, db):
        self.db = db

    async def create(self, *, content, project_id, category, source, skip_quality_gate):
        mid = "m_" + uuid.uuid4().hex[:6]
        await self.db.add_memory(
            {
                "id": mid,
                "content": content,
                "content_hash": f"h{mid}",
                "embedding": EMB,
                "source": source,
                "project_id": project_id,
                "category": category,
                "created_at": NOW,
                "updated_at": NOW,
            }
        )

        class _R:
            pass

        r = _R()
        r.id = mid
        return r


class TestCurationActivity:
    @pytest.mark.asyncio
    async def test_activity_annotates_reconcile_pair_with_titles(self, temp_db):
        await _add(temp_db, "new1")
        await _add(temp_db, "old1")
        await temp_db.execute(
            "INSERT INTO reconcile_queue (id, new_memory_id, old_memory_id, "
            "project_id, status, created_at, updated_at) "
            "VALUES ('rq1', 'new1', 'old1', 'p1', 'done', ?, ?)",
            (NOW, NOW),
        )
        svc = CurationService(temp_db)
        activity = await svc.list_activity()
        reconcile = next(w for w in activity["workers"] if w["key"] == "reconcile")
        assert reconcile["counts"] == {"done": 1}
        row = reconcile["recent"][0]
        subject_ids = {s["memory_id"] for s in row["subjects"]}
        assert subject_ids == {"new1", "old1"}
        # First content line becomes the title.
        by_id = {s["memory_id"]: s for s in row["subjects"]}
        assert by_id["new1"]["title"] == "new1 original content"
        assert by_id["new1"]["exists"] is True

    @pytest.mark.asyncio
    async def test_activity_maintenance_shows_operation_and_memory(self, temp_db):
        from app.core.services.maintenance import MaintenanceService

        await _add(temp_db, "mm1")
        mnt = MaintenanceService(temp_db)
        await mnt.enqueue_project(
            project_id="p1", operations=["improve"], force=False
        )
        svc = CurationService(temp_db)
        activity = await svc.list_activity()
        # Maintenance is split into per-operation cards.
        maint = next(
            w for w in activity["workers"] if w["key"] == "maintenance:improve"
        )
        assert maint["counts"].get("pending") == 1
        row = maint["recent"][0]
        assert row["operation"] == "improve"
        assert row["subjects"][0]["memory_id"] == "mm1"

    @pytest.mark.asyncio
    async def test_activity_splits_maintenance_into_enrich_and_improve(self, temp_db):
        from app.core.services.maintenance import MaintenanceService

        await _add(temp_db, "mm1")
        await MaintenanceService(temp_db).enqueue_project(
            project_id="p1", operations=["enrich", "improve"], force=False
        )
        svc = CurationService(temp_db)
        keys = {w["key"] for w in (await svc.list_activity())["workers"]}
        assert "maintenance:enrich" in keys
        assert "maintenance:improve" in keys
        assert "maintenance" not in keys  # never a merged card

    @pytest.mark.asyncio
    async def test_activity_flags_deleted_subject(self, temp_db):
        from app.core.services.maintenance import MaintenanceService

        await _add(temp_db, "gone1")
        mnt = MaintenanceService(temp_db)
        await mnt.enqueue_project(
            project_id="p1", operations=["enrich"], force=False
        )
        # Memory deleted after the job was queued (maintenance_queue has no FK).
        await temp_db.execute("DELETE FROM memories WHERE id = 'gone1'")

        svc = CurationService(temp_db)
        activity = await svc.list_activity()
        maint = next(
            w for w in activity["workers"] if w["key"] == "maintenance:enrich"
        )
        row = maint["recent"][0]
        assert row["subjects"][0]["memory_id"] == "gone1"
        assert row["subjects"][0]["exists"] is False


class TestCurationService:
    @pytest.mark.asyncio
    async def test_list_queue_only_proposed(self, temp_db):
        await _add(temp_db, "a")
        await _add(temp_db, "b")
        await _rel(temp_db, "r1", "a", "b", "supersedes", "proposed")
        await _rel(temp_db, "r2", "a", "b", "supersedes", "approved")
        svc = CurationService(temp_db)
        items = await svc.list_queue()
        assert len(items) == 1
        assert items[0]["id"] == "r1"

    @pytest.mark.asyncio
    async def test_approve_supersede_deprecates_loser(self, temp_db):
        await _add(temp_db, "win")
        await _add(temp_db, "lose")
        await _rel(temp_db, "r", "win", "lose", "supersedes", "proposed")
        svc = CurationService(temp_db)
        await svc.approve_supersede("r")
        lose = await temp_db.fetchone("SELECT status FROM memories WHERE id='lose'")
        win = await temp_db.fetchone("SELECT status FROM memories WHERE id='win'")
        assert lose["status"] == "deprecated"
        assert win["status"] == "canonical"

    @pytest.mark.asyncio
    async def test_cycle_guard(self, temp_db):
        await _add(temp_db, "a")
        await _add(temp_db, "b")
        await _rel(temp_db, "r_ab", "a", "b", "supersedes", "approved")  # a→b
        await _rel(temp_db, "r_ba", "b", "a", "supersedes", "proposed")  # b→a = cycle
        svc = CurationService(temp_db)
        with pytest.raises(ValueError, match="cycle"):
            await svc.approve_supersede("r_ba")

    @pytest.mark.asyncio
    async def test_reject_new_c3(self, temp_db):
        await _add(temp_db, "n")
        svc = CurationService(temp_db)
        await svc.reject_new("n")
        row = await temp_db.fetchone("SELECT status FROM memories WHERE id='n'")
        assert row["status"] == "deprecated"

    @pytest.mark.asyncio
    async def test_dismiss(self, temp_db):
        await _add(temp_db, "a")
        await _add(temp_db, "b")
        await _rel(temp_db, "r", "a", "b", "conflicts", "proposed", "conflict")
        svc = CurationService(temp_db)
        await svc.dismiss("r")
        row = await temp_db.fetchone("SELECT metadata FROM memory_relations WHERE id='r'")
        assert json.loads(row["metadata"])["state"] == "dismissed"

    @pytest.mark.asyncio
    async def test_approve_merge(self, temp_db):
        await _add(temp_db, "new")
        await _add(temp_db, "old")
        await _rel(
            temp_db, "rm", "new", "old", "conflicts", "proposed", "merge",
            "merged combined content",
        )
        svc = CurationService(temp_db, memory_service=_FakeMemSvc(temp_db))
        res = await svc.approve_merge("rm")
        assert res["merged_id"].startswith("m_")
        for mid in ("new", "old"):
            row = await temp_db.fetchone(
                "SELECT status FROM memories WHERE id=?", (mid,)
            )
            assert row["status"] == "deprecated"
        merged = await temp_db.fetchone(
            "SELECT status FROM memories WHERE id=?", (res["merged_id"],)
        )
        assert merged["status"] == "canonical"
        cur = await temp_db.execute(
            "SELECT target_id FROM memory_relations WHERE source_id=? "
            "AND relation_type='supersedes'",
            (res["merged_id"],),
        )
        assert sorted(r[0] for r in cur.fetchall()) == ["new", "old"]

    @pytest.mark.asyncio
    async def test_approve_merge_requires_memory_service(self, temp_db):
        await _add(temp_db, "new")
        await _add(temp_db, "old")
        await _rel(
            temp_db, "rm", "new", "old", "conflicts", "proposed", "merge",
            "merged text long enough",
        )
        svc = CurationService(temp_db)  # no memory_service
        with pytest.raises(ValueError, match="memory_service"):
            await svc.approve_merge("rm")
