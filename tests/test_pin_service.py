"""
Pin Service 테스트
"""

import pytest
import tempfile
import os
from unittest.mock import Mock, patch

from app.core.services.pin import (
    PinService,
    PinNotFoundError,
    PinAlreadyCompletedError,
    InvalidStatusTransitionError,
)
from app.core.services.session import SessionService
from app.core.services.project import ProjectService
from app.core.database.base import Database
from app.core.schemas.pins import PinUpdate


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
        path = db_path + ext
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture
async def pin_service(temp_db):
    """PinService 픽스처"""
    return PinService(temp_db)


class TestPinCRUD:
    """Pin CRUD 테스트"""

    @pytest.mark.asyncio
    async def test_create_pin(self, pin_service):
        """Pin 생성 테스트"""
        # Given
        project_id = "test-project"
        content = "Implement user authentication module"
        importance = 4
        tags = ["auth", "security"]
        user_id = "test-user"

        # When
        pin = await pin_service.create_pin(
            project_id=project_id,
            content=content,
            importance=importance,
            tags=tags,
            user_id=user_id,
        )

        # Then
        assert pin is not None
        assert pin.id is not None
        assert pin.project_id == project_id
        assert pin.content == content
        assert pin.importance == importance
        assert pin.tags == tags
        assert pin.status == "open"
        assert pin.completed_at is None

    @pytest.mark.asyncio
    async def test_get_pin(self, pin_service):
        """Pin 조회 테스트"""
        # Given
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Test pin content for retrieval",
            user_id="test-user",
        )

        # When
        retrieved_pin = await pin_service.get_pin(pin.id)

        # Then
        assert retrieved_pin is not None
        assert retrieved_pin.id == pin.id
        assert retrieved_pin.content == pin.content

    @pytest.mark.asyncio
    async def test_update_pin(self, pin_service):
        """Pin 업데이트 테스트"""
        # Given
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Original pin content for update",
            importance=3,
            user_id="test-user",
        )

        # When
        update_data = PinUpdate(
            content="Updated pin content for testing",
            importance=5,
            tags=["updated", "test"],
        )
        updated_pin = await pin_service.update_pin(pin.id, update_data)

        # Then
        assert updated_pin is not None
        assert updated_pin.content == "Updated pin content for testing"
        assert updated_pin.importance == 5
        assert updated_pin.tags == ["updated", "test"]

    @pytest.mark.asyncio
    async def test_delete_pin(self, pin_service):
        """Pin 삭제 테스트"""
        # Given
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Pin to be deleted for testing",
            user_id="test-user",
        )
        assert await pin_service.get_pin(pin.id) is not None

        # When
        result = await pin_service.delete_pin(pin.id)

        # Then
        assert result is True
        assert await pin_service.get_pin(pin.id) is None


class TestPinStatus:
    """Pin 상태 테스트"""

    @pytest.mark.asyncio
    async def test_complete_pin(self, pin_service):
        """Pin 완료 처리 테스트"""
        # Given
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Pin to be completed for testing",
            user_id="test-user",
        )
        assert pin.status == "open"

        # When
        completed_pin = await pin_service.complete_pin(pin.id)

        # Then
        assert completed_pin.status == "completed"
        assert completed_pin.completed_at is not None
        assert completed_pin.lead_time_hours is not None

    @pytest.mark.asyncio
    async def test_pin_status_transitions(self, pin_service):
        """Pin 상태 전이 테스트 (open → in_progress → completed)"""
        # Given
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Pin for status transition test",
            user_id="test-user",
        )
        assert pin.status == "open"

        # When - open → in_progress
        update_data = PinUpdate(status="in_progress")
        in_progress_pin = await pin_service.update_pin(pin.id, update_data)

        # Then
        assert in_progress_pin.status == "in_progress"

        # When - in_progress → completed
        completed_pin = await pin_service.complete_pin(pin.id)

        # Then
        assert completed_pin.status == "completed"

    @pytest.mark.asyncio
    async def test_complete_already_completed_pin_raises_error(self, pin_service):
        """이미 완료된 Pin 완료 시도 시 에러 테스트"""
        # Given
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Pin already completed for testing",
            user_id="test-user",
        )
        await pin_service.complete_pin(pin.id)

        # When & Then
        with pytest.raises(PinAlreadyCompletedError):
            await pin_service.complete_pin(pin.id)


class TestPinPromotion:
    """Pin 승격 테스트"""

    @pytest.mark.asyncio
    async def test_promote_pin_to_memory(self, pin_service, temp_db):
        """Pin을 Memory로 승격 테스트"""
        # Given
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Critical security vulnerability needs immediate attention",
            importance=4,
            tags=["security", "critical"],
            user_id="test-user",
        )

        # When
        result = await pin_service.promote_to_memory(pin.id)

        # Then
        assert result is not None
        assert "memory_id" in result
        assert result["pin_deleted"] is True
        assert await pin_service.get_pin(pin.id) is None

    @pytest.mark.asyncio
    async def test_should_suggest_promotion_high_importance(self, pin_service):
        """중요도 높은 완료된 Pin 승격 제안 테스트"""
        # Given
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="High importance pin for promotion",
            importance=4,
            user_id="test-user",
        )
        completed_pin = await pin_service.complete_pin(pin.id)

        # When
        should_promote = pin_service.should_suggest_promotion(completed_pin)

        # Then
        assert should_promote is True

    @pytest.mark.asyncio
    async def test_should_not_suggest_promotion_low_importance(self, pin_service):
        """중요도 낮은 Pin 승격 제안 안함 테스트"""
        # Given
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Low importance pin for testing",
            importance=2,
            user_id="test-user",
        )
        completed_pin = await pin_service.complete_pin(pin.id)

        # When
        should_promote = pin_service.should_suggest_promotion(completed_pin)

        # Then
        assert should_promote is False


class TestPinQuery:
    """Pin 조회 테스트"""

    @pytest.mark.asyncio
    async def test_get_pins_by_session(self, pin_service):
        """세션별 Pin 조회 테스트"""
        # Given
        pin1 = await pin_service.create_pin(
            project_id="test-project",
            content="First pin in session for testing",
            importance=3,
            user_id="test-user",
        )
        pin2 = await pin_service.create_pin(
            project_id="test-project",
            content="Second pin in session for testing",
            importance=5,
            user_id="test-user",
        )

        # When
        pins = await pin_service.get_pins_by_session(
            session_id=pin1.session_id, limit=10
        )

        # Then
        assert len(pins) == 2
        assert pins[0].importance >= pins[1].importance

    @pytest.mark.asyncio
    async def test_get_pins_by_importance(self, pin_service):
        """중요도별 Pin 조회 테스트"""
        # Given
        await pin_service.create_pin(
            project_id="test-project",
            content="Low importance pin for filtering",
            importance=1,
            user_id="test-user",
        )
        await pin_service.create_pin(
            project_id="test-project",
            content="High importance pin for filtering",
            importance=5,
            user_id="test-user",
        )

        # When
        all_pins = await pin_service.get_pins_by_project(
            project_id="test-project", limit=10
        )

        # Then
        assert len(all_pins) == 2
        assert all_pins[0].importance == 5
        assert all_pins[1].importance == 1


class TestPinEdgeCases:
    """Pin 엣지 케이스 테스트"""

    @pytest.mark.asyncio
    async def test_get_pin_not_found(self, pin_service):
        """존재하지 않는 Pin 조회 테스트"""
        # Given
        non_existent_id = "non-existent-pin-id"

        # When
        pin = await pin_service.get_pin(non_existent_id)

        # Then
        assert pin is None

    @pytest.mark.asyncio
    async def test_delete_pin_not_found(self, pin_service):
        """존재하지 않는 Pin 삭제 테스트"""
        # Given
        non_existent_id = "non-existent-pin-id"

        # When
        result = await pin_service.delete_pin(non_existent_id)

        # Then
        assert result is False

    @pytest.mark.asyncio
    async def test_complete_pin_not_found(self, pin_service):
        """존재하지 않는 Pin 완료 시도 테스트"""
        # Given
        non_existent_id = "non-existent-pin-id"

        # When & Then
        with pytest.raises(PinNotFoundError):
            await pin_service.complete_pin(non_existent_id)

    @pytest.mark.asyncio
    async def test_promote_pin_not_found(self, pin_service):
        """존재하지 않는 Pin 승격 시도 테스트"""
        # Given
        non_existent_id = "non-existent-pin-id"

        # When & Then
        with pytest.raises(PinNotFoundError):
            await pin_service.promote_to_memory(non_existent_id)

    @pytest.mark.asyncio
    async def test_create_pin_default_importance(self, pin_service):
        """Pin 생성 시 기본 중요도 테스트"""
        # Given & When
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Pin without explicit importance",
            user_id="test-user",
        )

        # Then
        assert pin.importance == 3

    @pytest.mark.asyncio
    async def test_update_pin_not_found(self, pin_service):
        """존재하지 않는 Pin 업데이트 테스트"""
        # Given
        non_existent_id = "non-existent-pin-id"
        update_data = PinUpdate(content="Updated content for testing")

        # When
        result = await pin_service.update_pin(non_existent_id, update_data)

        # Then
        assert result is None
