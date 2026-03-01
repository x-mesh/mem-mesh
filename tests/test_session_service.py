"""
Session Service 테스트
"""

import os
import tempfile

import pytest

from app.core.database.base import Database
from app.core.services.project import ProjectService
from app.core.services.session import SessionService


@pytest.fixture
async def temp_db():
    """임시 데이터베이스 픽스처"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    db = Database(db_path)
    await db.connect()
    yield db
    await db.close()

    # 정리
    for ext in ["", "-wal", "-shm"]:
        path = db_path + ext
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture
async def project_service(temp_db):
    """ProjectService 픽스처"""
    return ProjectService(temp_db)


@pytest.fixture
async def session_service(temp_db, project_service):
    """SessionService 픽스처"""
    return SessionService(temp_db, project_service)


class TestSessionLifecycle:
    """세션 생명주기 테스트"""

    @pytest.mark.asyncio
    async def test_get_or_create_active_session_creates_new(self, session_service):
        """새 세션 생성 테스트"""
        # Given
        project_id = "test-project"
        user_id = "test-user"

        # When
        session = await session_service.get_or_create_active_session(
            project_id=project_id, user_id=user_id
        )

        # Then
        assert session is not None
        assert session.id is not None
        assert session.project_id == project_id
        assert session.user_id == user_id
        assert session.status == "active"
        assert session.started_at is not None
        assert session.ended_at is None

    @pytest.mark.asyncio
    async def test_resume_existing_session(self, session_service):
        """기존 활성 세션 재개 테스트"""
        # Given - 세션 생성
        project_id = "test-project"
        user_id = "test-user"
        original_session = await session_service.get_or_create_active_session(
            project_id=project_id, user_id=user_id
        )

        # When - 같은 프로젝트/사용자로 다시 요청
        resumed_session = await session_service.get_or_create_active_session(
            project_id=project_id, user_id=user_id
        )

        # Then - 같은 세션이 반환되어야 함
        assert resumed_session.id == original_session.id
        assert resumed_session.status == "active"

    @pytest.mark.asyncio
    async def test_end_session(self, session_service):
        """세션 종료 테스트"""
        # Given - 세션 생성
        project_id = "test-project"
        user_id = "test-user"
        session = await session_service.get_or_create_active_session(
            project_id=project_id, user_id=user_id
        )

        # When - 세션 종료
        summary = "Test session completed successfully"
        ended_session = await session_service.end_session(
            session_id=session.id, summary=summary
        )

        # Then
        assert ended_session is not None
        assert ended_session.status == "completed"
        assert ended_session.ended_at is not None
        assert ended_session.summary == summary


class TestSessionState:
    """세션 상태 테스트"""

    @pytest.mark.asyncio
    async def test_session_status_transitions(self, session_service):
        """세션 상태 전이 테스트 (active → completed)"""
        # Given - 활성 세션 생성
        project_id = "test-project"
        user_id = "test-user"
        session = await session_service.get_or_create_active_session(
            project_id=project_id, user_id=user_id
        )
        assert session.status == "active"

        # When - 세션 종료
        ended_session = await session_service.end_session(session_id=session.id)

        # Then
        assert ended_session.status == "completed"

        # When - 이미 완료된 세션 다시 종료 시도
        re_ended_session = await session_service.end_session(session_id=session.id)

        # Then - 이미 완료된 상태 유지
        assert re_ended_session.status == "completed"

    @pytest.mark.asyncio
    async def test_multiple_sessions_per_project(self, session_service):
        """프로젝트별 다중 세션 격리 테스트"""
        # Given
        project_id = "test-project"
        user1 = "user-1"
        user2 = "user-2"

        # When - 다른 사용자로 세션 생성
        session1 = await session_service.get_or_create_active_session(
            project_id=project_id, user_id=user1
        )
        session2 = await session_service.get_or_create_active_session(
            project_id=project_id, user_id=user2
        )

        # Then - 서로 다른 세션이어야 함
        assert session1.id != session2.id
        assert session1.user_id == user1
        assert session2.user_id == user2


class TestSessionQuery:
    """세션 조회 테스트"""

    @pytest.mark.asyncio
    async def test_get_sessions_by_project(self, session_service):
        """프로젝트별 세션 조회 테스트"""
        # Given - 여러 프로젝트에 세션 생성
        project1 = "project-1"
        project2 = "project-2"
        user_id = "test-user"

        await session_service.get_or_create_active_session(
            project_id=project1, user_id=user_id
        )
        await session_service.get_or_create_active_session(
            project_id=project2, user_id=user_id
        )

        # When - 프로젝트별 세션 조회
        sessions_p1 = await session_service.list_sessions(project_id=project1)
        sessions_p2 = await session_service.list_sessions(project_id=project2)

        # Then
        assert len(sessions_p1) == 1
        assert sessions_p1[0].project_id == project1
        assert len(sessions_p2) == 1
        assert sessions_p2[0].project_id == project2

    @pytest.mark.asyncio
    async def test_get_sessions_by_user(self, session_service):
        """사용자별 세션 조회 테스트"""
        # Given - 여러 사용자로 세션 생성
        project_id = "test-project"
        user1 = "user-1"
        user2 = "user-2"

        await session_service.get_or_create_active_session(
            project_id=project_id, user_id=user1
        )
        await session_service.get_or_create_active_session(
            project_id=project_id, user_id=user2
        )

        # When - 사용자별 세션 조회
        sessions_u1 = await session_service.list_sessions(user_id=user1)
        sessions_u2 = await session_service.list_sessions(user_id=user2)

        # Then
        assert len(sessions_u1) == 1
        assert sessions_u1[0].user_id == user1
        assert len(sessions_u2) == 1
        assert sessions_u2[0].user_id == user2


class TestSessionEdgeCases:
    """세션 엣지 케이스 테스트"""

    @pytest.mark.asyncio
    async def test_session_without_project(self, session_service):
        """프로젝트 자동 생성 테스트"""
        # Given - 존재하지 않는 프로젝트 ID
        project_id = "non-existent-project"
        user_id = "test-user"

        # When - 세션 생성 (프로젝트 자동 생성됨)
        session = await session_service.get_or_create_active_session(
            project_id=project_id, user_id=user_id
        )

        # Then - 세션이 정상적으로 생성됨
        assert session is not None
        assert session.project_id == project_id

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, session_service):
        """존재하지 않는 세션 조회 테스트"""
        # Given
        non_existent_id = "non-existent-session-id"

        # When
        session = await session_service.get_session(non_existent_id)

        # Then
        assert session is None

    @pytest.mark.asyncio
    async def test_end_session_not_found(self, session_service):
        """존재하지 않는 세션 종료 테스트"""
        # Given
        non_existent_id = "non-existent-session-id"

        # When
        result = await session_service.end_session(session_id=non_existent_id)

        # Then
        assert result is None

    @pytest.mark.asyncio
    async def test_end_session_auto_summary(self, session_service, temp_db):
        """세션 종료 시 자동 요약 생성 테스트"""
        # Given - 세션 생성
        project_id = "test-project"
        user_id = "test-user"
        session = await session_service.get_or_create_active_session(
            project_id=project_id, user_id=user_id
        )

        # When - 요약 없이 세션 종료
        ended_session = await session_service.end_session(session_id=session.id)

        # Then - 자동 요약이 생성됨
        assert ended_session.summary is not None
        assert "세션 완료" in ended_session.summary

    @pytest.mark.asyncio
    async def test_resume_last_session_context(self, session_service):
        """마지막 세션 컨텍스트 로드 테스트"""
        # Given - 세션 생성
        project_id = "test-project"
        user_id = "test-user"
        await session_service.get_or_create_active_session(
            project_id=project_id, user_id=user_id
        )

        # When - 세션 컨텍스트 로드
        context = await session_service.resume_last_session(
            project_id=project_id, user_id=user_id, expand=False
        )

        # Then
        assert context is not None
        assert context.project_id == project_id
        assert context.user_id == user_id
        assert context.status == "active"
        assert context.pins_count == 0
        assert context.open_pins == 0
        assert context.completed_pins == 0

    @pytest.mark.asyncio
    async def test_resume_last_session_not_found(self, session_service):
        """존재하지 않는 세션 컨텍스트 로드 테스트"""
        # Given
        project_id = "non-existent-project"
        user_id = "test-user"

        # When
        context = await session_service.resume_last_session(
            project_id=project_id, user_id=user_id
        )

        # Then
        assert context is None
