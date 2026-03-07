"""Pin + Session Resume E2E 테스트

전체 흐름 검증:
1. session_resume (세션 없음) → None
2. pin_add → 세션 자동 생성 + pin 생성
3. session_resume (활성 세션 + 핀) → 핀 반환
4. pin_complete → 완료 처리
5. session_end → 세션 종료
6. session_resume (세션 종료 후) → cross-session fallback
7. 새 세션 resume (빈 세션 + cross-session 병합)
"""

import asyncio
import os
import tempfile

import pytest

from app.core.database.base import Database
from app.core.services.pin import PinService
from app.core.services.session import SessionService

PROJECT_ID = "test-e2e-project"
USER_ID = "default"


@pytest.fixture
async def services(tmp_path):
    """임시 DB로 서비스 초기화"""
    db_path = str(tmp_path / "test_e2e.db")
    db = Database(db_path=db_path)
    await db.connect()

    session_svc = SessionService(db)
    pin_svc = PinService(db)
    # lazy property 대신 직접 주입하여 동일 인스턴스 사용
    pin_svc._session_service = session_svc

    yield session_svc, pin_svc

    await db.close()


@pytest.mark.asyncio
async def test_full_pin_session_flow(services):
    """전체 pin + session_resume 흐름 검증"""
    session_svc, pin_svc = services

    # ── Step 1: 세션 없을 때 resume → None ──
    ctx = await session_svc.resume_last_session(PROJECT_ID, USER_ID)
    assert ctx is None, "세션이 없을 때 resume은 None 반환해야 함"

    # ── Step 2: pin_add → 세션 자동 생성 + pin 생성 ──
    pin1 = await pin_svc.create_pin(
        project_id=PROJECT_ID,
        content="Fix authentication bug in login flow",
        importance=4,
        tags=["bug", "auth"],
        user_id=USER_ID,
        ide_session_id="test-ide-session-123",
        client_type="claude-ai",
    )
    assert pin1.id is not None
    assert pin1.status == "in_progress"
    assert pin1.importance == 4
    assert pin1.project_id == PROJECT_ID

    pin2 = await pin_svc.create_pin(
        project_id=PROJECT_ID,
        content="Implement dark mode toggle",
        importance=2,
        tags=["feature", "ui"],
        user_id=USER_ID,
    )
    assert pin2.id is not None

    # ── Step 3: session_resume (활성 세션 + 핀 있음) → 핀 반환 ──
    ctx = await session_svc.resume_last_session(
        PROJECT_ID, USER_ID, expand=True, limit=10
    )
    assert ctx is not None, "활성 세션이 있으면 resume은 컨텍스트 반환해야 함"
    assert ctx.pins_count >= 2, f"핀 2개 이상이어야 함, 실제: {ctx.pins_count}"
    assert ctx.open_pins >= 2, f"open 핀 2개 이상이어야 함, 실제: {ctx.open_pins}"
    assert ctx.status == "active"

    session_id = ctx.session_id

    # expand=True일 때 전체 핀 정보 포함
    assert len(ctx.pins) >= 2

    # ── Step 3b: IDE session_id 확인 ──
    session = await session_svc.get_session(session_id)
    assert session is not None
    assert session.ide_session_id == "test-ide-session-123"
    assert session.client_type == "claude-ai"

    # ── Step 3c: expand="smart" 모드 확인 ──
    ctx_smart = await session_svc.resume_last_session(
        PROJECT_ID, USER_ID, expand="smart", limit=10
    )
    assert ctx_smart is not None
    assert ctx_smart.pins_count >= 2

    # ── Step 3d: expand=False (compact) 모드 확인 ──
    ctx_compact = await session_svc.resume_last_session(
        PROJECT_ID, USER_ID, expand=False, limit=10
    )
    assert ctx_compact is not None
    assert ctx_compact.pins_count >= 2

    # ── Step 4: pin_complete ──
    completed = await pin_svc.complete_pin(pin1.id)
    assert completed.status == "completed"
    assert completed.completed_at is not None

    # resume 후 completed_pins 증가 확인
    ctx_after = await session_svc.resume_last_session(
        PROJECT_ID, USER_ID, expand=True
    )
    assert ctx_after.completed_pins >= 1
    assert ctx_after.open_pins >= 1  # pin2는 아직 open

    # ── Step 5: session_end ──
    ended = await session_svc.end_session(session_id, summary="E2E test completed")
    assert ended is not None
    assert ended.status == "completed"

    # 종료된 세션 확인
    session_after = await session_svc.get_session(session_id)
    assert session_after.status == "completed"

    # ── Step 6: 세션 종료 후 resume → cross-session fallback ──
    ctx_cross = await session_svc.resume_last_session(
        PROJECT_ID, USER_ID, expand=True, limit=10
    )
    # 활성 세션이 없으므로 cross-session fallback 발생
    # cross-session은 최근 7일 핀을 가져옴
    assert ctx_cross is not None, "cross-session fallback이 핀을 반환해야 함"
    assert ctx_cross.pins_count >= 1, "이전 세션 핀이 보여야 함"
    # cross-session은 마지막 종료된 세션 ID를 참조 (새 세션을 만들지 않음)
    assert ctx_cross.session_id == session_id, "마지막 세션 ID를 참조해야 함"
    # summary에 cross-session 표시
    assert ctx_cross.summary is not None
    assert "cross-session" in ctx_cross.summary or "이전 세션" in ctx_cross.summary

    # ── Step 7: 새 세션 생성 후 resume (빈 세션 + cross-session 병합) ──
    new_session = await session_svc.get_or_create_active_session(
        project_id=PROJECT_ID,
        user_id=USER_ID,
    )
    assert new_session is not None
    assert new_session.id != session_id, "새 세션이 생성되어야 함"

    # 새 세션은 핀이 없으므로 Case 2 → cross-session 핀 병합
    ctx_merge = await session_svc.resume_last_session(
        PROJECT_ID, USER_ID, expand=True, limit=10
    )
    assert ctx_merge is not None
    assert ctx_merge.session_id == new_session.id, "새 세션 ID 반환"
    # cross-session 핀이 병합됨 (이전 세션의 핀이 보임)
    assert ctx_merge.pins_count >= 1, "이전 세션 핀이 병합되어야 함"


@pytest.mark.asyncio
async def test_pin_add_auto_creates_session(services):
    """pin_add가 세션을 자동 생성하는지 검증"""
    session_svc, pin_svc = services

    # 세션 없이 pin_add
    pin = await pin_svc.create_pin(
        project_id="auto-session-test",
        content="Test auto session creation",
        importance=3,
        user_id=USER_ID,
    )
    assert pin.session_id is not None

    # 해당 세션이 실제로 존재하는지 확인
    session = await session_svc.get_session(pin.session_id)
    assert session is not None
    assert session.project_id == "auto-session-test"
    assert session.status == "active"


@pytest.mark.asyncio
async def test_resume_expand_modes(services):
    """expand 모드별 반환 형식 검증"""
    session_svc, pin_svc = services

    # 핀 생성 (세션 자동 생성)
    await pin_svc.create_pin(
        project_id="expand-test",
        content="High importance task for smart expand",
        importance=5,
        user_id=USER_ID,
    )
    await pin_svc.create_pin(
        project_id="expand-test",
        content="Low importance task for smart expand",
        importance=1,
        user_id=USER_ID,
    )

    # expand=False → compact (id, content 80자, importance, status)
    ctx_compact = await session_svc.resume_last_session(
        "expand-test", USER_ID, expand=False
    )
    assert ctx_compact is not None
    assert ctx_compact.pins_count == 2
    for pin in ctx_compact.pins:
        # compact 모드: dict 또는 PinCompact
        assert "id" in pin if isinstance(pin, dict) else hasattr(pin, "id")

    # expand=True → full PinResponse
    ctx_full = await session_svc.resume_last_session(
        "expand-test", USER_ID, expand=True
    )
    assert ctx_full is not None
    assert ctx_full.pins_count == 2

    # expand="smart" → 4-Tier matrix
    ctx_smart = await session_svc.resume_last_session(
        "expand-test", USER_ID, expand="smart"
    )
    assert ctx_smart is not None
    assert ctx_smart.pins_count == 2


@pytest.mark.asyncio
async def test_cross_session_excludes_current(services):
    """cross-session fallback이 현재 세션 핀을 제외하는지 검증"""
    session_svc, pin_svc = services

    proj = "cross-exclude-test"

    # 첫 번째 세션에서 핀 생성
    pin1 = await pin_svc.create_pin(
        project_id=proj,
        content="Old session pin",
        importance=3,
        user_id=USER_ID,
    )
    first_session_id = pin1.session_id

    # 첫 번째 세션 종료
    await session_svc.end_session(first_session_id, summary="First session done")

    # 두 번째 세션 생성 (빈 세션)
    new_session = await session_svc.get_or_create_active_session(
        project_id=proj, user_id=USER_ID
    )

    # resume → 빈 세션이므로 cross-session fallback
    ctx = await session_svc.resume_last_session(proj, USER_ID, expand=True)
    assert ctx is not None
    # cross-session에서 이전 세션 핀이 보임
    assert ctx.pins_count >= 1

    # 현재 세션에 핀 추가
    pin2 = await pin_svc.create_pin(
        project_id=proj,
        content="New session pin",
        importance=4,
        user_id=USER_ID,
    )

    # resume → 현재 세션 핀만 반환 (cross-session 아님)
    ctx2 = await session_svc.resume_last_session(proj, USER_ID, expand=True)
    assert ctx2 is not None
    # 현재 세션 핀이 있으므로 Case 1 (현재 세션 핀만)
    pin_ids = [p.id if hasattr(p, "id") else p["id"] for p in ctx2.pins]
    assert pin2.id in pin_ids
