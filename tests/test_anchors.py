"""
Memory git-anchors (commit_hash / file_paths / branch) 왕복 및 검증 테스트 [R13].

anchors는 클라이언트(에이전트)가 수집해 전달하는 표시·수명 판단용 메타데이터로,
저장·조회 왕복이 보장되고 잘못된 값은 거부되어야 한다. 검색/임베딩에는 영향이 없다.
"""

import json
import os
import tempfile

import pytest
from pydantic import ValidationError

from app.core.database.base import Database
from app.core.schemas.requests import AddParams, validate_anchors
from app.core.services.memory import MemoryService
from app.core.services.pin import PinService
from app.core.services.search import SearchService

# 100자 이상: quality gate 통과용 본문
LONG = (
    "This memory documents the anchors feature and is padded well beyond the "
    "100-character quality-gate minimum so that create() accepts it in tests."
)

VALID_ANCHORS = {
    "commit_hash": "a1b2c3d",
    "file_paths": ["app/core/services/memory.py", "tests/test_anchors.py"],
    "branch": "develop",
}


@pytest.fixture
async def temp_db():
    """임시 데이터베이스 픽스처"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    db = Database(db_path)
    await db.connect()
    yield db
    await db.close()

    for ext in ["", "-wal", "-shm"]:
        p = db_path + ext
        if os.path.exists(p):
            os.unlink(p)


@pytest.fixture
async def memory_service(temp_db, mock_embedding_service):
    """MemoryService 픽스처 (mock 임베딩)"""
    return MemoryService(temp_db, mock_embedding_service)


@pytest.fixture
async def search_service(temp_db, mock_embedding_service):
    """SearchService 픽스처 (mock 임베딩)"""
    return SearchService(temp_db, mock_embedding_service)


@pytest.fixture
async def pin_service(temp_db, mock_embedding_service):
    """PinService 픽스처 (mock 임베딩 — promote 시 실제 모델 로드 방지)"""
    return PinService(temp_db, mock_embedding_service)


class TestAnchorsValidation:
    """validate_anchors / AddParams 스키마 검증"""

    def test_valid_anchors_accepted(self):
        assert validate_anchors(VALID_ANCHORS) == VALID_ANCHORS

    def test_none_returns_none(self):
        assert validate_anchors(None) is None

    def test_empty_dict_normalizes_to_none(self):
        assert validate_anchors({}) is None

    def test_partial_anchors_commit_only(self):
        assert validate_anchors({"commit_hash": "abcdef1"}) == {
            "commit_hash": "abcdef1"
        }

    def test_full_sha256_hash_accepted(self):
        h = "a" * 64
        assert validate_anchors({"commit_hash": h}) == {"commit_hash": h}

    @pytest.mark.parametrize(
        "bad",
        [
            {"commit_hash": "xyz"},  # non-hex
            {"commit_hash": "abc"},  # too short (<7)
            {"commit_hash": "a" * 65},  # too long (>64)
            {"file_paths": ["/etc/passwd"]},  # absolute (posix)
            {"file_paths": ["C:\\Windows\\x"]},  # absolute (windows)
            {"file_paths": ["../secret"]},  # traversal
            {"file_paths": ["app/../../x"]},  # traversal mid-path
            {"file_paths": ["ok/path"] * 21},  # >20 entries
            {"file_paths": [""]},  # empty path
            {"file_paths": "app/x.py"},  # not a list
            {"branch": ""},  # empty branch
            {"unknown_key": "value"},  # unknown key
            "not-a-dict",  # not an object
        ],
    )
    def test_invalid_anchors_rejected(self, bad):
        with pytest.raises(ValueError):
            validate_anchors(bad)

    def test_addparams_valid_anchors(self):
        params = AddParams(content=LONG, anchors=VALID_ANCHORS)
        assert params.anchors == VALID_ANCHORS

    def test_addparams_rejects_bad_anchors(self):
        with pytest.raises(ValidationError):
            AddParams(content=LONG, anchors={"commit_hash": "nothex"})

    def test_addparams_no_anchors_is_none(self):
        assert AddParams(content=LONG).anchors is None


class TestAnchorsRoundtrip:
    """create() → get() 왕복 및 기존 동작 무변화"""

    @pytest.mark.asyncio
    async def test_create_with_anchors_get_roundtrip(self, memory_service):
        resp = await memory_service.create(
            content=LONG,
            project_id="anchor-test",
            category="decision",
            source="test",
            anchors=VALID_ANCHORS,
        )
        assert resp.status == "saved"

        saved = await memory_service.get(resp.id)
        assert saved is not None
        # 저장은 JSON 문자열, get_anchors()로 dict 왕복
        assert saved.anchors == json.dumps(VALID_ANCHORS)
        assert saved.get_anchors() == VALID_ANCHORS

    @pytest.mark.asyncio
    async def test_create_without_anchors_unchanged(self, memory_service):
        """anchors 미전달 시 기존 동작 무변화 (NULL → None)"""
        resp = await memory_service.create(
            content=LONG + " no anchors variant",
            project_id="anchor-test",
            category="task",
            source="test",
        )
        saved = await memory_service.get(resp.id)
        assert saved is not None
        assert saved.anchors is None
        assert saved.get_anchors() is None

    @pytest.mark.asyncio
    async def test_empty_anchors_stored_as_none(self, memory_service):
        resp = await memory_service.create(
            content=LONG + " empty anchors variant",
            project_id="anchor-test",
            source="test",
            anchors=None,
        )
        saved = await memory_service.get(resp.id)
        assert saved.get_anchors() is None

    @pytest.mark.asyncio
    async def test_search_response_includes_anchors(
        self, memory_service, search_service
    ):
        """검색 결과(SearchResult)에 anchors가 포함된다."""
        unique = "anchortoken7231 hybrid retrieval marker"
        await memory_service.create(
            content=f"{unique}. {LONG}",
            project_id="anchor-search",
            category="decision",
            source="test",
            anchors=VALID_ANCHORS,
        )

        response = await search_service.search(
            "anchortoken7231", project_id="anchor-search", search_mode="exact"
        )
        assert response.results, "expected the anchored memory to be found"
        match = response.results[0]
        assert match.anchors == VALID_ANCHORS

    @pytest.mark.asyncio
    async def test_search_without_anchors_is_none(self, memory_service, search_service):
        unique = "plainmarker9911 no anchors here"
        await memory_service.create(
            content=f"{unique}. {LONG}",
            project_id="anchor-search",
            source="test",
        )
        response = await search_service.search(
            "plainmarker9911", project_id="anchor-search", search_mode="exact"
        )
        assert response.results
        assert response.results[0].anchors is None


class TestPinPromoteAnchors:
    """pin_promote 경로 왕복"""

    @pytest.mark.asyncio
    async def test_pin_promote_with_anchors_roundtrip(
        self, pin_service, memory_service
    ):
        pin = await pin_service.create_pin(
            project_id="anchor-pin",
            content="Investigate anchor promotion path end to end",
            importance=4,
        )
        result = await pin_service.promote_to_memory(
            pin.id, category="decision", anchors=VALID_ANCHORS
        )
        memory_id = result["memory_id"]

        saved = await memory_service.get(memory_id)
        assert saved is not None
        assert saved.get_anchors() == VALID_ANCHORS

    @pytest.mark.asyncio
    async def test_pin_promote_without_anchors(self, pin_service, memory_service):
        pin = await pin_service.create_pin(
            project_id="anchor-pin",
            content="Promotion without any anchors attached",
            importance=4,
        )
        result = await pin_service.promote_to_memory(pin.id, category="task")
        saved = await memory_service.get(result["memory_id"])
        assert saved.get_anchors() is None

    @pytest.mark.asyncio
    async def test_pin_promote_invalid_anchors_rejected(self, pin_service):
        pin = await pin_service.create_pin(
            project_id="anchor-pin",
            content="Promotion with invalid anchors should raise",
            importance=4,
        )
        with pytest.raises(ValueError):
            await pin_service.promote_to_memory(
                pin.id, category="task", anchors={"commit_hash": "not-hex!"}
            )


class TestReportAnchorStatus:
    """report_anchor_status: 클라이언트 검증 보고의 상태 전이 + 잘못된 보고 거부 [R14]"""

    @pytest.mark.asyncio
    async def test_unverified_memory_starts_null(self, memory_service):
        resp = await memory_service.create(
            content=LONG,
            project_id="anchor-stale",
            category="decision",
            source="test",
            anchors=VALID_ANCHORS,
        )
        saved = await memory_service.get(resp.id)
        assert saved.stale_status is None
        assert saved.stale_checked_at is None

    @pytest.mark.asyncio
    async def test_report_fresh_then_stale_transition(self, memory_service):
        resp = await memory_service.create(
            content=LONG + " transition variant",
            project_id="anchor-stale",
            category="decision",
            source="test",
            anchors=VALID_ANCHORS,
        )

        r1 = await memory_service.report_anchor_status(resp.id, "fresh")
        assert r1 == {
            "memory_id": resp.id,
            "stale_status": "fresh",
            "stale_checked_at": r1["stale_checked_at"],
        }
        assert r1["stale_checked_at"]
        saved = await memory_service.get(resp.id)
        assert saved.stale_status == "fresh"
        assert saved.stale_checked_at

        # A later verdict overwrites the earlier one (fresh → stale).
        r2 = await memory_service.report_anchor_status(
            resp.id, "stale", detail="app/core/services/memory.py removed"
        )
        assert r2["stale_status"] == "stale"
        saved = await memory_service.get(resp.id)
        assert saved.stale_status == "stale"

    @pytest.mark.asyncio
    async def test_report_invalid_status_rejected(self, memory_service):
        from app.core.errors import InvalidAnchorStatusError

        resp = await memory_service.create(
            content=LONG + " invalid status variant",
            project_id="anchor-stale",
            source="test",
            anchors=VALID_ANCHORS,
        )
        with pytest.raises(InvalidAnchorStatusError):
            await memory_service.report_anchor_status(resp.id, "rotten")
        # The rejected report must not have mutated the row.
        saved = await memory_service.get(resp.id)
        assert saved.stale_status is None

    @pytest.mark.asyncio
    async def test_report_rejected_for_anchorless_memory(self, memory_service):
        # cross-vendor review F7: without this guard any bearer could flip
        # arbitrary anchor-less memories to stale and drop them from injection.
        from app.core.errors import ValidationError

        resp = await memory_service.create(
            content=LONG + " anchorless variant",
            project_id="anchor-stale",
            category="decision",
            source="test",
        )
        with pytest.raises(ValidationError):
            await memory_service.report_anchor_status(resp.id, "stale")
        saved = await memory_service.get(resp.id)
        assert saved.stale_status is None

    @pytest.mark.asyncio
    async def test_report_nonexistent_memory_rejected(self, memory_service):
        from app.core.errors import MemoryNotFoundError

        with pytest.raises(MemoryNotFoundError):
            await memory_service.report_anchor_status(
                "00000000-0000-0000-0000-000000000000", "fresh"
            )


class TestMcpSchemaAnchors:
    """MCP tool 스키마에 anchors 노출 확인"""

    def test_add_and_pin_promote_schema_expose_anchors(self):
        from app.mcp_common.schemas import get_all_tool_schemas

        by_name = {t["name"]: t for t in get_all_tool_schemas()}
        for name in ("add", "pin_promote"):
            props = by_name[name]["inputSchema"]["properties"]
            assert "anchors" in props, f"{name} schema missing anchors"
            assert props["anchors"]["type"] == "object"

    def test_report_anchor_status_schema_exposed(self):
        from app.mcp_common.schemas import get_all_tool_schemas

        by_name = {t["name"]: t for t in get_all_tool_schemas()}
        assert "report_anchor_status" in by_name, "report_anchor_status not registered"
        schema = by_name["report_anchor_status"]["inputSchema"]
        assert schema["properties"]["status"]["enum"] == ["fresh", "stale"]
        assert set(schema["required"]) == {"memory_id", "status"}
