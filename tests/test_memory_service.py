"""
Memory Service 테스트
"""

import os
import tempfile
from unittest.mock import Mock

import pytest

from app.core.database.base import Database
from app.core.database.models import Memory
from app.core.embeddings.service import EmbeddingService
from app.core.errors import EmbeddingError, MemoryNotFoundError
from app.core.services.memory import MemoryService


@pytest.fixture
async def temp_db():
    """임시 데이터베이스 픽스처"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    db = Database(db_path)
    await db.connect()
    yield db
    await db.close()

    # 정리 (WAL/SHM 포함)
    for ext in ["", "-wal", "-shm"]:
        p = db_path + ext
        if os.path.exists(p):
            os.unlink(p)


@pytest.fixture
async def memory_service(temp_db, mock_embedding_service):
    """MemoryService 픽스처 (mock_embedding_service from conftest)"""
    return MemoryService(temp_db, mock_embedding_service)


class TestMemoryService:
    """MemoryService 테스트 클래스"""

    @pytest.mark.asyncio
    async def test_create_memory_success(self, memory_service):
        """메모리 생성 성공 테스트"""
        # Given
        content = "Test memory content for unit testing — this string is padded to exceed the 100-character quality gate minimum length requirement."
        project_id = "test-project"
        category = "task"
        source = "test"
        tags = ["test", "unit"]

        # When
        response = await memory_service.create(
            content=content,
            project_id=project_id,
            category=category,
            source=source,
            tags=tags,
        )

        # Then
        assert response.status == "saved"
        assert response.id is not None
        assert response.created_at is not None

        # 저장된 메모리 확인
        saved_memory = await memory_service.get(response.id)
        assert saved_memory is not None
        assert saved_memory.content == content
        assert saved_memory.project_id == project_id
        assert saved_memory.category == category
        assert saved_memory.source == source

    @pytest.mark.asyncio
    async def test_create_memory_duplicate(self, memory_service):
        """중복 메모리 생성 테스트"""
        # Given
        content = "Duplicate test content for testing — padded to exceed 100-character quality gate minimum length requirement here."
        project_id = "test-project"

        # When - 첫 번째 생성
        response1 = await memory_service.create(
            content=content, project_id=project_id, source="test"
        )

        # When - 두 번째 생성 (중복)
        response2 = await memory_service.create(
            content=content, project_id=project_id, source="test"
        )

        # Then
        assert response1.status == "saved"
        assert response2.status == "duplicate"
        assert response1.id == response2.id

    @pytest.mark.asyncio
    async def test_create_redacts_secrets_at_chokepoint(self, memory_service):
        """create() is the single save chokepoint for HTTP hook, command hook
        (POST /api/memories) and explicit MCP add; secrets/PII must be masked
        there so every path complies with CLAUDE.md M4 (no secret persisted)."""
        content = (
            "Deploying today. The key is sk-ant-abcdefghij1234567890 and the header "
            "was Authorization: Bearer abc.def.ghijklmnop — ping ops@example.com for "
            "the rollout. This body is padded comfortably past the hundred character "
            "quality-gate minimum so the create call is accepted by the service."
        )
        response = await memory_service.create(content=content, source="test")
        assert response.status == "saved"

        saved = await memory_service.get(response.id)
        assert "<REDACTED>" in saved.content
        assert "sk-ant-abcdefghij1234567890" not in saved.content
        assert "abc.def.ghijklmnop" not in saved.content
        assert "ops@example.com" not in saved.content
        # Hash must reflect the *stored* (redacted) content so dedup stays sound.
        assert saved.content_hash == Memory.compute_hash(saved.content)

    @pytest.mark.asyncio
    async def test_create_redaction_is_idempotent_for_dedup(self, memory_service):
        """A pre-redacted payload (e.g. from the HTTP hook) and a raw payload
        with the same secret collapse to one memory — redaction runs once."""
        raw = (
            "Rotated credential AKIAIOSFODNN7EXAMPLE today; document the change so "
            "the team knows. Padding this note beyond one hundred characters so the "
            "quality gate accepts the create call without raising on length."
        )
        from app.core.redaction import redact_secrets

        first = await memory_service.create(
            content=raw, project_id="redact-dedup", source="test"
        )
        second = await memory_service.create(
            content=redact_secrets(raw), project_id="redact-dedup", source="test"
        )
        assert first.status == "saved"
        assert second.status == "duplicate"
        assert first.id == second.id

    @pytest.mark.asyncio
    async def test_create_no_false_dedup_on_non_secret_config_values(
        self, memory_service
    ):
        """Two notes differing only in a non-secret config value (max_tokens)
        must remain two distinct memories.

        Regression: redaction runs before the dedup hash, so a false-positive on
        ``max_tokens=`` would mask both 4096 and 8192 to ``<REDACTED>`` and
        collapse them to one hash — silently dropping the second memory.
        """
        base = (
            "Tuning the generation config for the summarizer. We compared two "
            "settings to balance latency and completeness, recording the run here "
            "so the decision is traceable later: max_tokens={} was evaluated."
        )
        first = await memory_service.create(
            content=base.format(4096), project_id="cfg-dedup", source="test"
        )
        second = await memory_service.create(
            content=base.format(8192), project_id="cfg-dedup", source="test"
        )
        assert first.status == "saved"
        assert second.status == "saved"  # NOT "duplicate"
        assert first.id != second.id

        first_saved = await memory_service.get(first.id)
        second_saved = await memory_service.get(second.id)
        # The config values survive redaction and keep the hashes distinct.
        assert "max_tokens=4096" in first_saved.content
        assert "max_tokens=8192" in second_saved.content
        assert first_saved.content_hash != second_saved.content_hash

    @pytest.mark.asyncio
    async def test_update_redacts_secrets(self, memory_service):
        """update() also persists content, so it redacts at the same chokepoint."""
        clean = (
            "Initial note content padded well beyond the hundred character quality "
            "gate minimum so the create call is accepted by the service cleanly."
        )
        resp = await memory_service.create(content=clean, source="test")

        secret_update = (
            "Updated note: token ghp_0123456789abcdefghijABCDEFGHIJ0123 leaked and "
            "must never persist to long-term memory. Padding this line beyond one "
            "hundred characters so the quality gate accepts the update call fine."
        )
        upd = await memory_service.update(resp.id, content=secret_update)
        assert upd.status == "updated"

        saved = await memory_service.get(resp.id)
        assert "<REDACTED>" in saved.content
        assert "ghp_0123456789abcdefghijABCDEFGHIJ0123" not in saved.content

    @pytest.mark.asyncio
    async def test_get_memory_not_found(self, memory_service):
        """존재하지 않는 메모리 조회 테스트"""
        # Given
        non_existent_id = "non-existent-id"

        # When
        result = await memory_service.get(non_existent_id)

        # Then
        assert result is None

    @pytest.mark.asyncio
    async def test_update_memory_content(self, memory_service):
        """메모리 내용 업데이트 테스트"""
        # Given - 메모리 생성
        original_content = "Original content for update test — padded to exceed 100-character quality gate minimum length requirement here."
        response = await memory_service.create(content=original_content, source="test")
        memory_id = response.id

        # When - 내용 업데이트
        new_content = "Updated content for update test — padded to exceed 100-character quality gate minimum length requirement here."
        update_response = await memory_service.update(
            memory_id=memory_id, content=new_content
        )

        # Then
        assert update_response.status == "updated"
        assert update_response.id == memory_id

        # 업데이트된 메모리 확인
        updated_memory = await memory_service.get(memory_id)
        assert updated_memory.content == new_content
        assert updated_memory.content_hash == Memory.compute_hash(new_content)

    @pytest.mark.asyncio
    async def test_update_memory_metadata_only(self, memory_service):
        """메모리 메타데이터만 업데이트 테스트"""
        # Given - 메모리 생성
        content = "Content for metadata update test — padded to exceed 100-character quality gate minimum length requirement here."
        response = await memory_service.create(
            content=content, category="task", source="test"
        )
        memory_id = response.id
        original_memory = await memory_service.get(memory_id)

        # When - 메타데이터만 업데이트
        new_category = "bug"
        new_tags = ["updated", "metadata"]
        update_response = await memory_service.update(
            memory_id=memory_id, category=new_category, tags=new_tags
        )

        # Then
        assert update_response.status == "updated"

        # 업데이트된 메모리 확인
        updated_memory = await memory_service.get(memory_id)
        assert updated_memory.content == content  # 내용은 변경되지 않음
        assert (
            updated_memory.content_hash == original_memory.content_hash
        )  # 해시도 변경되지 않음
        assert updated_memory.category == new_category
        assert updated_memory.get_tags() == new_tags

    @pytest.mark.asyncio
    async def test_update_memory_not_found(self, memory_service):
        """존재하지 않는 메모리 업데이트 테스트"""
        # Given
        non_existent_id = "non-existent-id"

        # When & Then
        with pytest.raises(MemoryNotFoundError):
            await memory_service.update(
                memory_id=non_existent_id, content="New content"
            )

    @pytest.mark.asyncio
    async def test_delete_memory_success(self, memory_service):
        """메모리 삭제 성공 테스트"""
        # Given - 메모리 생성
        content = "Content to be deleted for testing — padded to exceed 100-character quality gate minimum length requirement here."
        response = await memory_service.create(content=content, source="test")
        memory_id = response.id

        # 메모리가 존재하는지 확인
        assert await memory_service.get(memory_id) is not None

        # When - 메모리 삭제
        delete_response = await memory_service.delete(memory_id)

        # Then
        assert delete_response.status == "deleted"
        assert delete_response.id == memory_id

        # 삭제된 메모리 확인
        assert await memory_service.get(memory_id) is None

    @pytest.mark.asyncio
    async def test_delete_memory_not_found(self, memory_service):
        """존재하지 않는 메모리 삭제 테스트"""
        # Given
        non_existent_id = "non-existent-id"

        # When & Then
        with pytest.raises(MemoryNotFoundError):
            await memory_service.delete(non_existent_id)

    @pytest.mark.asyncio
    async def test_embedding_retry_logic(self, temp_db):
        """임베딩 생성 재시도 로직 테스트"""
        # Given - 처음 두 번은 실패, 세 번째는 성공하는 Mock
        from app.core.config import Settings

        dim = Settings().embedding_dim
        mock_embedding_service = Mock(spec=EmbeddingService)
        mock_embedding_service.embed.side_effect = [
            Exception("First failure"),
            Exception("Second failure"),
            [0.1] * dim,  # 세 번째 시도에서 성공
        ]
        mock_embedding_service.to_bytes.return_value = b"\x00" * (dim * 4)

        memory_service = MemoryService(temp_db, mock_embedding_service)

        # When
        response = await memory_service.create(
            content="Test content for retry logic — padded to exceed 100-character quality gate minimum length requirement here.",
            source="test",
        )

        # Then
        assert response.status == "saved"
        assert mock_embedding_service.embed.call_count == 3

    @pytest.mark.asyncio
    async def test_embedding_max_retries_exceeded(self, temp_db):
        """임베딩 생성 최대 재시도 초과 테스트"""
        # Given - 모든 시도가 실패하는 Mock
        mock_embedding_service = Mock(spec=EmbeddingService)
        mock_embedding_service.embed.side_effect = Exception("Persistent failure")

        memory_service = MemoryService(temp_db, mock_embedding_service)

        # When & Then
        with pytest.raises(EmbeddingError):
            await memory_service.create(
                content="Test content for max retries — padded to exceed 100-character quality gate minimum length requirement here.",
                source="test",
            )

        assert mock_embedding_service.embed.call_count == 3  # max_retries
