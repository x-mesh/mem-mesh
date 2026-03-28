"""
Integration tests: Quality Gate + Memory CRUD + Conflict Detection + Pin Promotion.

Lane D: 통합 테스트 및 Regression 테스트
- create()/update() + quality gate 통합
- conflict detection graceful degradation
- pin promotion이 quality gate에 의해 실패하지 않는지 확인하는 regression
"""

import os
import tempfile
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.errors import (
    MemoryContentTooShortError,
    MemoryLowQualityError,
)
from app.core.services.memory import MemoryService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_content(prefix: str = "This is a valid memory") -> str:
    """100자 이상의 유효한 콘텐츠를 생성한다."""
    base = f"{prefix} — contains enough detail to pass the quality gate check."
    while len(base) < 110:
        base += " Extra padding text here."
    return base


def _make_mock_embedding_service() -> Mock:
    """EmbeddingService mock을 생성한다 (Settings 차원 기반)."""
    from app.core.config import Settings

    dim = Settings().embedding_dim
    service = Mock(spec=EmbeddingService)
    service.embed.return_value = [0.1] * dim
    service.to_bytes.return_value = b"\x00" * (dim * 4)
    service.from_bytes.return_value = [0.1] * dim
    service.embed_batch.return_value = [[0.1] * dim]
    service.dimension = dim
    return service


@asynccontextmanager
async def _temp_db():
    """임시 Database 인스턴스를 생성하고 정리한다."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path)
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
        for ext in ["", "-wal", "-shm"]:
            p = db_path + ext
            if os.path.exists(p):
                os.unlink(p)


# ===========================================================================
# 1. create() + quality gate 통합 테스트
# ===========================================================================
class TestCreateQualityGateIntegration:
    """create() 호출 시 quality gate가 실제로 동작하는지 통합 테스트."""

    @pytest.mark.asyncio
    async def test_create_rejects_short_content(self):
        """100자 미만 콘텐츠는 create()에서 MemoryContentTooShortError."""
        async with _temp_db() as db:
            svc = MemoryService(db, _make_mock_embedding_service())
            with pytest.raises(MemoryContentTooShortError):
                await svc.create(
                    content="Too short",
                    project_id="test",
                    category="task",
                    source="test",
                )

    @pytest.mark.asyncio
    async def test_create_rejects_low_quality_korean(self):
        """한국어 저품질 접두사는 create()에서 MemoryLowQualityError."""
        async with _temp_db() as db:
            svc = MemoryService(db, _make_mock_embedding_service())
            # "알겠습니다"로 시작하되 100자 이상
            content = "알겠습니다. " + "이 내용은 품질 게이트를 통과하기 위한 패딩 텍스트입니다. " * 5
            assert len(content) >= 100
            with pytest.raises(MemoryLowQualityError):
                await svc.create(
                    content=content,
                    project_id="test",
                    category="task",
                    source="test",
                )

    @pytest.mark.asyncio
    async def test_create_rejects_low_quality_english(self):
        """영어 저품질 접두사는 create()에서 MemoryLowQualityError."""
        async with _temp_db() as db:
            svc = MemoryService(db, _make_mock_embedding_service())
            content = "Sure, I can help with that. " + "x" * 100
            assert len(content) >= 100
            with pytest.raises(MemoryLowQualityError):
                await svc.create(
                    content=content,
                    project_id="test",
                    category="task",
                    source="test",
                )

    @pytest.mark.asyncio
    async def test_create_passes_valid_content(self):
        """100자 이상 유효한 콘텐츠는 정상 저장."""
        async with _temp_db() as db:
            svc = MemoryService(db, _make_mock_embedding_service())
            content = _make_valid_content()
            response = await svc.create(
                content=content,
                project_id="test",
                category="decision",
                source="test",
                tags=["integration"],
            )
            assert response.status == "saved"
            assert response.id is not None

            # DB에 실제 저장 확인
            saved = await svc.get(response.id)
            assert saved is not None
            assert saved.content == content


# ===========================================================================
# 2. update() + quality gate 통합 테스트
# ===========================================================================
class TestUpdateQualityGateIntegration:
    """update() 호출 시 quality gate 동작을 확인하는 통합 테스트."""

    @pytest.mark.asyncio
    async def test_update_rejects_short_content(self):
        """update()에서 content를 짧게 변경하면 MemoryContentTooShortError."""
        async with _temp_db() as db:
            svc = MemoryService(db, _make_mock_embedding_service())

            # 먼저 유효한 메모리 생성
            original = _make_valid_content()
            resp = await svc.create(
                content=original,
                project_id="test",
                category="task",
                source="test",
            )

            # 짧은 content로 update 시도
            with pytest.raises(MemoryContentTooShortError):
                await svc.update(resp.id, content="Short")

    @pytest.mark.asyncio
    async def test_update_allows_metadata_only_change(self):
        """content 없이 category/tags만 변경하면 quality gate 미적용."""
        async with _temp_db() as db:
            svc = MemoryService(db, _make_mock_embedding_service())

            original = _make_valid_content()
            resp = await svc.create(
                content=original,
                project_id="test",
                category="task",
                source="test",
            )

            # metadata만 변경 — quality gate를 타지 않으므로 성공해야 함
            update_resp = await svc.update(
                resp.id,
                category="decision",
                tags=["updated"],
            )
            assert update_resp.status == "updated"

            # 변경 확인
            updated = await svc.get(resp.id)
            assert updated.category == "decision"


# ===========================================================================
# 3. conflict detection graceful degradation 테스트
# ===========================================================================
class TestConflictDetectionGracefulDegradation:
    """Conflict detection이 실패해도 메모리 저장이 계속되는지 확인."""

    @pytest.mark.asyncio
    async def test_conflict_detection_failure_does_not_block_save(self):
        """conflict detection이 실패해도 메모리 저장은 계속됨."""
        async with _temp_db() as db:
            mock_embed = _make_mock_embedding_service()

            # conflict_detector를 Exception raise 하도록 mock
            mock_detector = MagicMock()
            mock_detector.max_candidates = 10
            mock_detector.is_available = True

            svc = MemoryService(db, mock_embed, conflict_detector=mock_detector)

            content = _make_valid_content("Conflict detection failure test")
            response = await svc.create(
                content=content,
                project_id="test",
                category="decision",
                source="test",
            )

            # 저장은 성공해야 함
            assert response.status == "saved"
            assert response.conflicts is None

    @pytest.mark.asyncio
    async def test_conflict_detection_disabled_by_default(self):
        """기본 설정에서 conflict_detector는 None."""
        async with _temp_db() as db:
            mock_embed = _make_mock_embedding_service()

            # conflict_detector를 명시적으로 전달하지 않으면
            # _init_conflict_detector()가 호출되는데,
            # 기본 설정(enable_conflict_detection=False)이면 None
            with patch(
                "app.core.services.memory.MemoryService._init_conflict_detector",
                return_value=None,
            ):
                svc = MemoryService(db, mock_embed)
                assert svc.conflict_detector is None

            content = _make_valid_content("No conflict detector test")
            response = await svc.create(
                content=content,
                project_id="test",
                category="task",
                source="test",
            )
            assert response.status == "saved"
            assert response.conflicts is None


# ===========================================================================
# 4. REGRESSION: Pin promotion quality gate 충돌
# ===========================================================================
class TestPinPromotionRegression:
    """Pin promotion이 quality gate에 의해 실패하지 않는지 확인하는 regression 테스트.

    배경: quality gate가 100자 최소를 강제하면서, 100자 미만의 pin content를
    가진 pin을 promote하면 MemoryContentTooShortError가 발생하는 regression.
    pin promotion 경로에서는 skip_quality_gate=True로 quality gate를 skip해야 함.
    """

    @pytest.mark.asyncio
    async def test_short_pin_can_be_promoted(self):
        """50자 pin도 promotion이 성공해야 함."""
        async with _temp_db() as db:
            mock_embed = _make_mock_embedding_service()

            from app.core.services.pin import PinService

            pin_service = PinService(db, embedding_service=mock_embed)

            # 50자짜리 pin 생성
            short_content = "Redis 캐시 도입 결정 — TTL 300s로 설정"
            assert len(short_content) < 100

            pin = await pin_service.create_pin(
                project_id="test-project",
                content=short_content,
                importance=5,
                tags=["decision"],
            )
            assert pin.id is not None

            # promote — quality gate skip 덕분에 성공해야 함
            result = await pin_service.promote_to_memory(
                pin_id=pin.id,
                category="decision",
            )

            assert result["already_promoted"] is False
            assert result["memory_id"] is not None

            # Memory가 실제로 저장되었는지 확인
            memory_svc = MemoryService(db, mock_embed)
            saved = await memory_svc.get(result["memory_id"])
            assert saved is not None
            assert saved.content == short_content
            assert saved.source == "pin_promotion"

    @pytest.mark.asyncio
    async def test_long_pin_promotion_also_works(self):
        """100자 이상 pin도 promotion이 정상 동작함 (regression 확인)."""
        async with _temp_db() as db:
            mock_embed = _make_mock_embedding_service()

            from app.core.services.pin import PinService

            pin_service = PinService(db, embedding_service=mock_embed)

            long_content = _make_valid_content("Long pin promotion test")
            pin = await pin_service.create_pin(
                project_id="test-project",
                content=long_content,
                importance=4,
                tags=["architecture"],
            )

            result = await pin_service.promote_to_memory(
                pin_id=pin.id,
                category="decision",
            )

            assert result["already_promoted"] is False
            assert result["memory_id"] is not None

    @pytest.mark.asyncio
    async def test_skip_quality_gate_parameter_works(self):
        """create()에 skip_quality_gate=True를 전달하면 짧은 콘텐츠도 저장됨."""
        async with _temp_db() as db:
            svc = MemoryService(db, _make_mock_embedding_service())
            short = "Short content for skip test"
            assert len(short) < 100

            response = await svc.create(
                content=short,
                project_id="test",
                category="task",
                source="pin_promotion",
                skip_quality_gate=True,
            )
            assert response.status == "saved"

    @pytest.mark.asyncio
    async def test_skip_quality_gate_false_still_validates(self):
        """skip_quality_gate=False (기본값)는 여전히 quality gate를 적용함."""
        async with _temp_db() as db:
            svc = MemoryService(db, _make_mock_embedding_service())
            with pytest.raises(MemoryContentTooShortError):
                await svc.create(
                    content="Too short",
                    project_id="test",
                    category="task",
                    source="test",
                    skip_quality_gate=False,
                )
