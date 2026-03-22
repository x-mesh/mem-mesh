"""Tests for ConflictDetectorService."""

import pytest

from app.core.services.conflict_detector import (
    ConflictDetectorService,
    ConflictResult,
    NLI_MODEL_AVAILABLE,
)


class TestConflictDetectorService:
    """ConflictDetectorService unit tests (NLI model independent)."""

    def test_init_defaults(self):
        """Default initialization with no preload."""
        service = ConflictDetectorService(preload=False)
        assert service.contradiction_threshold == 0.7
        assert service.similarity_threshold == 0.7
        assert service.max_candidates == 10
        assert service.nli_loaded is False

    def test_is_available(self):
        """is_available reflects sentence_transformers availability."""
        service = ConflictDetectorService(preload=False)
        assert service.is_available == NLI_MODEL_AVAILABLE

    def test_detect_conflicts_empty_candidates(self):
        """Empty candidates should return empty list."""
        service = ConflictDetectorService(preload=False)
        result = service.detect_conflicts("new memory", [])
        assert result == []

    def test_detect_conflicts_below_similarity_threshold(self):
        """Candidates below similarity threshold should be filtered out."""
        service = ConflictDetectorService(
            preload=False, similarity_threshold=0.7
        )
        candidates = [
            {"id": "1", "content": "some content", "similarity_score": 0.5},
            {"id": "2", "content": "other content", "similarity_score": 0.3},
        ]
        result = service.detect_conflicts("new memory", candidates)
        assert result == []

    def test_vector_only_detect_high_similarity(self):
        """Vector-only mode should flag high similarity (>=0.85) candidates."""
        service = ConflictDetectorService(preload=False)
        candidates = [
            {"id": "1", "content": "Redis 캐시 사용 결정", "similarity_score": 0.90},
            {"id": "2", "content": "다른 주제", "similarity_score": 0.75},
        ]
        # Force vector-only mode by ensuring no model
        results = service._vector_only_detect(candidates)
        assert len(results) == 1
        assert results[0].memory_id == "1"
        assert results[0].similarity_score == 0.90
        assert results[0].contradiction_score == 0.0  # unknown without NLI

    def test_vector_only_detect_no_high_similarity(self):
        """Vector-only mode should return empty if no candidates >= 0.85."""
        service = ConflictDetectorService(preload=False)
        candidates = [
            {"id": "1", "content": "some content", "similarity_score": 0.80},
        ]
        results = service._vector_only_detect(candidates)
        assert results == []

    def test_max_candidates_limit(self):
        """Should limit candidates to max_candidates."""
        service = ConflictDetectorService(
            preload=False,
            max_candidates=2,
            similarity_threshold=0.5,
        )
        candidates = [
            {"id": str(i), "content": f"content {i}", "similarity_score": 0.9}
            for i in range(10)
        ]
        # Without NLI, falls through to vector_only_detect
        # But the method limits to max_candidates first
        # We test the filtering in detect_conflicts
        results = service.detect_conflicts("new", candidates)
        # vector_only_detect uses 0.85 threshold, all are 0.9 so all pass
        # but only max_candidates=2 should be checked
        assert len(results) <= 2

    def test_conflict_result_dataclass(self):
        """ConflictResult dataclass should hold all fields."""
        result = ConflictResult(
            memory_id="abc-123",
            content_preview="Redis 사용 결정",
            contradiction_score=0.85,
            similarity_score=0.92,
        )
        assert result.memory_id == "abc-123"
        assert result.contradiction_score == 0.85
        assert result.similarity_score == 0.92

    def test_content_preview_truncation(self):
        """ConflictResult preview should respect length passed in."""
        long_content = "A" * 500
        result = ConflictResult(
            memory_id="test",
            content_preview=long_content[:200],
            contradiction_score=0.8,
            similarity_score=0.9,
        )
        assert len(result.content_preview) == 200


class TestAddResponseConflicts:
    """Test AddResponse with conflicts field."""

    def test_add_response_without_conflicts(self):
        """AddResponse should work with conflicts=None (backward compat)."""
        from app.core.schemas.responses import AddResponse

        resp = AddResponse(
            id="test-id",
            status="saved",
            created_at="2026-01-01T00:00:00Z",
        )
        assert resp.conflicts is None

    def test_add_response_with_conflicts(self):
        """AddResponse should include conflict info when present."""
        from app.core.schemas.responses import AddResponse, ConflictInfo

        conflicts = [
            ConflictInfo(
                memory_id="old-123",
                content_preview="Redis 캐시 사용 결정",
                contradiction_score=0.85,
                similarity_score=0.92,
            )
        ]
        resp = AddResponse(
            id="new-id",
            status="saved",
            created_at="2026-01-01T00:00:00Z",
            conflicts=conflicts,
        )
        assert resp.conflicts is not None
        assert len(resp.conflicts) == 1
        assert resp.conflicts[0].memory_id == "old-123"
        assert resp.conflicts[0].contradiction_score == 0.85

    def test_add_response_json_serialization(self):
        """AddResponse with conflicts should serialize to JSON correctly."""
        from app.core.schemas.responses import AddResponse, ConflictInfo

        resp = AddResponse(
            id="new-id",
            status="saved",
            created_at="2026-01-01T00:00:00Z",
            conflicts=[
                ConflictInfo(
                    memory_id="old-123",
                    content_preview="기존 메모리",
                    contradiction_score=0.9,
                    similarity_score=0.88,
                )
            ],
        )
        data = resp.model_dump()
        assert "conflicts" in data
        assert data["conflicts"][0]["contradiction_score"] == 0.9


class TestConfigConflictDetection:
    """Test Settings conflict detection fields."""

    def test_default_conflict_detection_disabled(self):
        """Conflict detection should be disabled by default."""
        from app.core.config import Settings

        s = Settings()
        assert s.enable_conflict_detection is False

    def test_conflict_detection_settings(self):
        """Conflict detection settings should have correct defaults."""
        from app.core.config import Settings

        s = Settings()
        assert s.conflict_nli_model == "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
        assert s.conflict_contradiction_threshold == 0.7
        assert s.conflict_similarity_threshold == 0.7
        assert s.conflict_max_candidates == 10


class TestMemoryServiceWiring:
    """Test ConflictDetectorService auto-wiring in MemoryService."""

    def test_wiring_disabled_by_default(self):
        """MemoryService should NOT have conflict_detector when feature is disabled."""
        from unittest.mock import MagicMock

        from app.core.services.memory import MemoryService

        db = MagicMock()
        embedding = MagicMock()
        service = MemoryService(db, embedding)
        assert service.conflict_detector is None

    def test_wiring_with_explicit_detector(self):
        """MemoryService should use explicitly passed conflict_detector."""
        from unittest.mock import MagicMock

        from app.core.services.memory import MemoryService

        db = MagicMock()
        embedding = MagicMock()
        detector = MagicMock()
        service = MemoryService(db, embedding, conflict_detector=detector)
        assert service.conflict_detector is detector

    def test_wiring_auto_creates_when_enabled(self, monkeypatch):
        """MemoryService should auto-create ConflictDetectorService when enabled."""
        from unittest.mock import MagicMock

        from app.core.config import Settings
        from app.core.services.memory import MemoryService

        # Enable conflict detection via settings
        mock_settings = Settings()
        monkeypatch.setattr(
            "app.core.services.memory.get_settings",
            lambda: mock_settings,
            raising=False,
        )
        # Patch get_settings in the config module too (relative import)
        import app.core.config

        original_settings = app.core.config._settings
        app.core.config._settings = Settings(enable_conflict_detection=True)

        try:
            db = MagicMock()
            embedding = MagicMock()
            service = MemoryService(db, embedding)
            assert service.conflict_detector is not None
            assert hasattr(service.conflict_detector, "detect_conflicts")
        finally:
            app.core.config._settings = original_settings

    def test_wiring_graceful_on_import_error(self, monkeypatch):
        """MemoryService should gracefully handle ConflictDetectorService import failure."""
        from unittest.mock import MagicMock

        from app.core.config import Settings

        import app.core.config

        original_settings = app.core.config._settings
        app.core.config._settings = Settings(enable_conflict_detection=True)

        # Simulate import failure
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "conflict_detector" in name:
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        try:
            from app.core.services.memory import MemoryService

            db = MagicMock()
            embedding = MagicMock()
            service = MemoryService(db, embedding)
            # Should gracefully fall back to None
            assert service.conflict_detector is None
        finally:
            app.core.config._settings = original_settings
