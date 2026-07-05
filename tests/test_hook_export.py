"""hook_events 장기 보관 export 테스트.

``HookService.prune_old_events``는 retention이 이벤트를 지우기 전에 replay(M2b
하네스)용으로 ``hook_events_archive``로 이동한다. 검증 대상:

* 이동 — retention을 넘긴 행이 archive로 옮겨지고 원본에서 삭제되는가
* 방어적 redaction — 아카이브 시점에 prompt/assistant_message가 재-redact되는가
  (t1 이전에 쌓인 미redact 행이 소급 정리 없이 넘어올 수 있다)
* 트랜잭션 — 이동 도중 실패 시 원본이 그대로 보존되는가 (부분 커밋 없음)
"""

import os
import tempfile
from datetime import datetime, timezone

import pytest

from app.core.database.base import Database
from app.core.services.hook import HookService

# retention(14일)보다 확실히 오래된 / 최신 타임스탬프.
OLD_TS = "2000-01-01T00:00:00+00:00"


def _recent_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
async def temp_db():
    """초기화된 임시 Database 인스턴스"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    db = Database(db_path)
    await db.connect()
    yield db
    await db.close()

    for ext in ["", "-wal", "-shm"]:
        path = db_path + ext
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture
async def hook_service(temp_db):
    return HookService(temp_db)


async def _insert_event(
    db,
    *,
    id: str,
    created_at: str,
    prompt=None,
    assistant_message=None,
    project_id: str = "p",
    ide_session_id: str = "s1",
    client_type=None,
    event_name: str = "UserPromptSubmit",
    turn_index: int = 0,
    saved_memory: int = 0,
) -> None:
    """created_at을 명시해 hook_events에 행을 직접 삽입한다.

    record_event는 created_at을 항상 now로 쓰므로, retention 경계를 넘긴 legacy
    행(및 미redact 행)을 재현하려면 직접 INSERT가 필요하다.
    """
    await db.execute(
        """
        INSERT INTO hook_events (
            id, project_id, ide_session_id, client_type, event_name,
            turn_index, prompt, assistant_message, saved_memory, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            id,
            project_id,
            ide_session_id,
            client_type,
            event_name,
            turn_index,
            prompt,
            assistant_message,
            saved_memory,
            created_at,
        ),
    )
    db.connection.commit()


class TestArchiveSchema:
    """hook_events_archive lazy schema 생성"""

    @pytest.mark.asyncio
    async def test_table_and_index_created(self, hook_service):
        await hook_service.ensure_archive_schema()

        tbl = await hook_service.db.fetchone(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='hook_events_archive'"
        )
        assert tbl is not None

        idx = await hook_service.db.fetchone(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_hook_events_archive_archived_at'"
        )
        assert idx is not None

    @pytest.mark.asyncio
    async def test_prune_creates_schema_lazily(self, hook_service):
        # 명시적 ensure 호출 없이 prune만으로 테이블이 생겨야 한다.
        await hook_service.prune_old_events(retention_days=14)
        tbl = await hook_service.db.fetchone(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='hook_events_archive'"
        )
        assert tbl is not None


class TestArchiveMove:
    """이동 — retention 초과 행만 archive로 옮기고 원본에서 제거"""

    @pytest.mark.asyncio
    async def test_old_events_moved_to_archive(self, hook_service):
        await _insert_event(
            hook_service.db, id="old-1", created_at=OLD_TS, prompt="ancient q"
        )
        await _insert_event(
            hook_service.db,
            id="old-2",
            created_at=OLD_TS,
            event_name="SessionStart",
            prompt=None,  # NULL prompt도 문제없이 아카이브돼야 한다
        )

        removed = await hook_service.prune_old_events(retention_days=14)
        assert removed == 2

        # 원본에서 삭제
        src = await hook_service.db.fetchall("SELECT id FROM hook_events")
        assert src == []

        # archive에 보존 (동일 컬럼 + archived_at)
        archived = await hook_service.db.fetchall(
            "SELECT id, prompt, created_at, archived_at "
            "FROM hook_events_archive ORDER BY id"
        )
        assert {r["id"] for r in archived} == {"old-1", "old-2"}
        assert all(r["created_at"] == OLD_TS for r in archived)
        assert all(r["archived_at"] for r in archived)

    @pytest.mark.asyncio
    async def test_recent_events_not_archived(self, hook_service):
        await _insert_event(
            hook_service.db, id="fresh-1", created_at=_recent_ts(), prompt="new q"
        )

        removed = await hook_service.prune_old_events(retention_days=14)
        assert removed == 0

        # 원본 유지, archive 비어있음
        src = await hook_service.db.fetchall("SELECT id FROM hook_events")
        assert {r["id"] for r in src} == {"fresh-1"}
        archived = await hook_service.db.fetchall("SELECT id FROM hook_events_archive")
        assert archived == []

    @pytest.mark.asyncio
    async def test_mixed_only_old_moved(self, hook_service):
        await _insert_event(
            hook_service.db, id="old-1", created_at=OLD_TS, prompt="old"
        )
        await _insert_event(
            hook_service.db, id="fresh-1", created_at=_recent_ts(), prompt="fresh"
        )

        removed = await hook_service.prune_old_events(retention_days=14)
        assert removed == 1

        src = {
            r["id"]
            for r in await hook_service.db.fetchall("SELECT id FROM hook_events")
        }
        archived = {
            r["id"]
            for r in await hook_service.db.fetchall(
                "SELECT id FROM hook_events_archive"
            )
        }
        assert src == {"fresh-1"}
        assert archived == {"old-1"}


class TestArchiveRedaction:
    """방어적 redaction — 아카이브 시점에 secret/PII 재-redact"""

    @pytest.mark.asyncio
    async def test_secrets_redacted_on_archive(self, hook_service):
        # 미redact 상태로 쌓인 legacy 행(직접 INSERT로 redaction 우회).
        await _insert_event(
            hook_service.db,
            id="legacy-1",
            created_at=OLD_TS,
            prompt="my key is sk-ant-abcdefghij1234567890 do not leak",
            assistant_message="reach me at leak@example.com anytime",
        )

        await hook_service.prune_old_events(retention_days=14)

        row = await hook_service.db.fetchone(
            "SELECT prompt, assistant_message "
            "FROM hook_events_archive WHERE id='legacy-1'"
        )
        assert row is not None
        # secret은 마스킹되고 원문은 남지 않는다.
        assert "<REDACTED>" in row["prompt"]
        assert "sk-ant-abcdefghij1234567890" not in row["prompt"]
        assert "<REDACTED>" in row["assistant_message"]
        assert "leak@example.com" not in row["assistant_message"]

    @pytest.mark.asyncio
    async def test_clean_text_preserved(self, hook_service):
        # secret이 없는 본문은 그대로 보존돼야 한다(과도 redaction 방지).
        await _insert_event(
            hook_service.db,
            id="clean-1",
            created_at=OLD_TS,
            prompt="just a normal question about caching",
        )

        await hook_service.prune_old_events(retention_days=14)

        row = await hook_service.db.fetchone(
            "SELECT prompt FROM hook_events_archive WHERE id='clean-1'"
        )
        assert row["prompt"] == "just a normal question about caching"


class TestArchiveTransaction:
    """트랜잭션 — 부분 실패 시 원본 보존, 아카이브 누수 없음"""

    @pytest.mark.asyncio
    async def test_partial_failure_preserves_source(self, hook_service, monkeypatch):
        await _insert_event(hook_service.db, id="old-1", created_at=OLD_TS, prompt="a")
        await _insert_event(hook_service.db, id="old-2", created_at=OLD_TS, prompt="b")

        # archive INSERT는 성공시키되 원본 DELETE에서 실패를 주입한다.
        # 트랜잭션이 롤백되어 아카이브 INSERT까지 되돌려져야 한다.
        orig_execute = hook_service.db.execute

        async def failing_execute(query, params=()):
            if query.lstrip().upper().startswith("DELETE"):
                raise RuntimeError("simulated delete failure")
            return await orig_execute(query, params)

        monkeypatch.setattr(hook_service.db, "execute", failing_execute)

        with pytest.raises(RuntimeError, match="simulated delete failure"):
            await hook_service.prune_old_events(retention_days=14)

        monkeypatch.undo()

        # 원본 2행 그대로 보존 (부분 커밋 없음)
        src = {
            r["id"]
            for r in await hook_service.db.fetchall("SELECT id FROM hook_events")
        }
        assert src == {"old-1", "old-2"}

        # 아카이브 INSERT도 함께 롤백 — 누수 없음
        archived = await hook_service.db.fetchall("SELECT id FROM hook_events_archive")
        assert archived == []
