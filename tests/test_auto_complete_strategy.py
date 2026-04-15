"""auto_complete_pins 전략 패턴 테스트

전략별 검증:
- "none": pin 상태 변경 없음
- "in_progress": in_progress → completed, open 유지
- "all": open + in_progress 전부 completed
- True/False: 하위 호환성 (True → "all", False → "none")
- "true"/"false" 문자열: MCP 클라이언트 호환
- 알 수 없는 전략: "none"으로 기본 처리 + 경고
- 핀 완료 실패 시 복원력
"""

import pytest

from app.core.database.base import Database
from app.core.services.pin import PinService
from app.core.services.session import SessionService

PROJECT_ID = "test-strategy-project"
USER_ID = "default"


@pytest.fixture
async def services(tmp_path):
    """임시 DB로 서비스 초기화"""
    db_path = str(tmp_path / "test_strategy.db")
    db = Database(db_path=db_path)
    await db.connect()

    session_svc = SessionService(db)
    pin_svc = PinService(db)
    pin_svc._session_service = session_svc

    yield session_svc, pin_svc, db

    await db.close()


async def _create_pins_and_get_session(session_svc, pin_svc, db):
    """open 1개 + in_progress 2개 핀 생성 후 세션 ID 반환"""
    # pin_add로 세션 자동 생성 (기본 status: in_progress)
    pin_ip1 = await pin_svc.create_pin(
        project_id=PROJECT_ID,
        content="In-progress task 1",
        importance=3,
        user_id=USER_ID,
    )
    pin_ip2 = await pin_svc.create_pin(
        project_id=PROJECT_ID,
        content="In-progress task 2",
        importance=5,
        user_id=USER_ID,
    )
    pin_open = await pin_svc.create_pin(
        project_id=PROJECT_ID,
        content="Planned future task",
        importance=2,
        user_id=USER_ID,
    )
    # open 상태로 직접 변경
    await db.execute(
        "UPDATE pins SET status = 'open' WHERE id = ?", (pin_open.id,)
    )

    # 세션 ID 조회
    sessions = await session_svc.list_sessions(
        project_id=PROJECT_ID, status="active", limit=1
    )
    assert len(sessions) > 0
    session_id = sessions[0].id

    return session_id, pin_ip1.id, pin_ip2.id, pin_open.id


@pytest.mark.asyncio
async def test_strategy_none(services):
    """'none' 전략: 아무 핀도 완료하지 않음"""
    session_svc, pin_svc, db = services
    session_id, ip1, ip2, op = await _create_pins_and_get_session(
        session_svc, pin_svc, db
    )

    result = await session_svc.end_with_auto_promotion(
        session_id=session_id,
        auto_complete_pins="none",
    )

    assert result["auto_completed_pins"] == []

    # 핀 상태 확인 — 변경 없어야 함
    rows = await db.fetchall("SELECT id, status FROM pins ORDER BY created_at")
    status_map = {r["id"]: r["status"] for r in rows}
    assert status_map[ip1] == "in_progress"
    assert status_map[ip2] == "in_progress"
    assert status_map[op] == "open"


@pytest.mark.asyncio
async def test_strategy_in_progress(services):
    """'in_progress' 전략: in_progress만 완료, open 유지"""
    session_svc, pin_svc, db = services
    session_id, ip1, ip2, op = await _create_pins_and_get_session(
        session_svc, pin_svc, db
    )

    result = await session_svc.end_with_auto_promotion(
        session_id=session_id,
        auto_complete_pins="in_progress",
    )

    assert set(result["auto_completed_pins"]) == {ip1, ip2}

    rows = await db.fetchall("SELECT id, status FROM pins ORDER BY created_at")
    status_map = {r["id"]: r["status"] for r in rows}
    assert status_map[ip1] == "completed"
    assert status_map[ip2] == "completed"
    assert status_map[op] == "open"


@pytest.mark.asyncio
async def test_strategy_all(services):
    """'all' 전략: open + in_progress 전부 완료"""
    session_svc, pin_svc, db = services
    session_id, ip1, ip2, op = await _create_pins_and_get_session(
        session_svc, pin_svc, db
    )

    result = await session_svc.end_with_auto_promotion(
        session_id=session_id,
        auto_complete_pins="all",
    )

    assert set(result["auto_completed_pins"]) == {ip1, ip2, op}

    rows = await db.fetchall("SELECT id, status FROM pins ORDER BY created_at")
    status_map = {r["id"]: r["status"] for r in rows}
    assert status_map[ip1] == "completed"
    assert status_map[ip2] == "completed"
    assert status_map[op] == "completed"


@pytest.mark.asyncio
async def test_backward_compat_true(services):
    """True → 'all' 하위 호환성"""
    session_svc, pin_svc, db = services
    session_id, ip1, ip2, op = await _create_pins_and_get_session(
        session_svc, pin_svc, db
    )

    result = await session_svc.end_with_auto_promotion(
        session_id=session_id,
        auto_complete_pins=True,
    )

    assert set(result["auto_completed_pins"]) == {ip1, ip2, op}


@pytest.mark.asyncio
async def test_backward_compat_false(services):
    """False → 'none' 하위 호환성"""
    session_svc, pin_svc, db = services
    session_id, ip1, ip2, op = await _create_pins_and_get_session(
        session_svc, pin_svc, db
    )

    result = await session_svc.end_with_auto_promotion(
        session_id=session_id,
        auto_complete_pins=False,
    )

    assert result["auto_completed_pins"] == []

    rows = await db.fetchall("SELECT id, status FROM pins ORDER BY created_at")
    status_map = {r["id"]: r["status"] for r in rows}
    assert status_map[ip1] == "in_progress"
    assert status_map[ip2] == "in_progress"
    assert status_map[op] == "open"


@pytest.mark.asyncio
async def test_string_true_maps_to_all(services):
    """문자열 'true' → 'all' 전략 (MCP 클라이언트 호환)"""
    session_svc, pin_svc, db = services
    session_id, ip1, ip2, op = await _create_pins_and_get_session(
        session_svc, pin_svc, db
    )

    result = await session_svc.end_with_auto_promotion(
        session_id=session_id,
        auto_complete_pins="true",
    )

    assert set(result["auto_completed_pins"]) == {ip1, ip2, op}


@pytest.mark.asyncio
async def test_string_false_maps_to_none(services):
    """문자열 'false' → 'none' 전략 (MCP 클라이언트 호환)"""
    session_svc, pin_svc, db = services
    session_id, ip1, ip2, op = await _create_pins_and_get_session(
        session_svc, pin_svc, db
    )

    result = await session_svc.end_with_auto_promotion(
        session_id=session_id,
        auto_complete_pins="false",
    )

    assert result["auto_completed_pins"] == []

    rows = await db.fetchall("SELECT id, status FROM pins ORDER BY created_at")
    status_map = {r["id"]: r["status"] for r in rows}
    assert status_map[ip1] == "in_progress"
    assert status_map[op] == "open"


@pytest.mark.asyncio
async def test_unknown_strategy_defaults_to_none(services):
    """알 수 없는 전략은 'none'으로 기본 처리"""
    session_svc, pin_svc, db = services
    session_id, ip1, ip2, op = await _create_pins_and_get_session(
        session_svc, pin_svc, db
    )

    result = await session_svc.end_with_auto_promotion(
        session_id=session_id,
        auto_complete_pins="invalid_strategy",
    )

    assert result["auto_completed_pins"] == []


@pytest.mark.asyncio
async def test_pin_completion_failure_resilience(services):
    """핀 완료 실패 시에도 session_end는 정상 완료"""
    session_svc, pin_svc, db = services
    session_id, ip1, ip2, op = await _create_pins_and_get_session(
        session_svc, pin_svc, db
    )

    # ip1을 삭제하여 complete_pin 실패 유도
    await db.execute("DELETE FROM pins WHERE id = ?", (ip1,))

    result = await session_svc.end_with_auto_promotion(
        session_id=session_id,
        auto_complete_pins="in_progress",
    )

    # 삭제된 핀은 auto_completed에 포함되지 않지만 세션은 종료됨
    assert ip1 not in result["auto_completed_pins"]
    # ip2는 여전히 in_progress이므로 완료되어야 함
    assert ip2 in result["auto_completed_pins"]
    assert "session" in result
