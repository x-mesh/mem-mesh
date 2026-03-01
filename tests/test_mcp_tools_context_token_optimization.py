"""
MCP Tools 통합 테스트 - Context Token Optimization

작업 10.1과 10.2의 MCP 도구 핸들러 업데이트를 검증합니다.
- session_resume: 토큰 추적 정보 포함, expand/limit 파라미터 지원
- pin_add: ImportanceAnalyzer 통합, 자동 중요도 추정
"""

import os
import tempfile

import pytest

from app.core.database.base import Database
from app.core.storage.direct import DirectStorageBackend
from app.mcp_common.tools import MCPToolHandlers


@pytest.fixture
async def db():
    """테스트용 임시 데이터베이스"""
    # 임시 파일 생성
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Database 인스턴스 생성 및 연결
    database = Database(db_path)
    await database.connect()

    yield database

    # 정리
    await database.close()
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
async def storage(db):
    """테스트용 스토리지 백엔드"""
    # DirectStorageBackend는 db_path를 받아서 자체적으로 Database를 생성하므로
    # 이미 생성된 db의 경로를 사용
    backend = DirectStorageBackend(db.db_path)
    await backend.initialize()
    yield backend
    # 정리는 db fixture에서 처리


@pytest.fixture
async def tools(storage):
    """테스트용 MCP 도구 핸들러"""
    return MCPToolHandlers(storage, notifier=None, enable_compression=False)


class TestSessionResumeWithTokenTracking:
    """작업 10.1: session_resume 도구 업데이트 테스트"""

    async def test_resume_no_session_includes_token_info(self, tools):
        """세션이 없을 때도 token_info가 포함되어야 함"""
        result = await tools.session_resume(
            project_id="test-project", expand=False, limit=10
        )

        assert result["status"] == "no_session"
        assert "token_info" in result
        assert result["token_info"]["loaded_tokens"] == 0
        assert result["token_info"]["unloaded_tokens"] == 0
        assert result["token_info"]["estimated_total"] == 0

    async def test_resume_with_expand_false_includes_token_info(self, tools):
        """expand=false로 재개 시 토큰 정보가 포함되어야 함"""
        # 핀 추가 (세션 자동 생성)
        await tools.pin_add(
            content="Test pin 1", project_id="test-project", importance=3
        )
        await tools.pin_add(
            content="Test pin 2 with more content to increase token count",
            project_id="test-project",
            importance=4,
        )

        # 세션 재개 (expand=false)
        result = await tools.session_resume(
            project_id="test-project", expand=False, limit=10
        )

        assert result["status"] == "active"
        assert "token_info" in result
        assert result["token_info"]["loaded_tokens"] > 0
        # expand=false일 때 핀 내용이 로드되지 않으므로 unloaded_tokens가 있을 수 있음
        assert result["token_info"]["unloaded_tokens"] >= 0
        assert result["token_info"]["estimated_total"] > 0

        # expand=false에서도 핀 메타데이터는 반환됨 (content만 축소)
        assert "pins" in result

    async def test_resume_with_expand_true_includes_token_info(self, tools):
        """expand=true로 재개 시 토큰 정보가 포함되어야 함"""
        # 핀 추가
        await tools.pin_add(
            content="Test pin 1", project_id="test-project", importance=3
        )
        await tools.pin_add(
            content="Test pin 2", project_id="test-project", importance=4
        )

        # 세션 재개 (expand=true)
        result = await tools.session_resume(
            project_id="test-project", expand=True, limit=10
        )

        assert result["status"] == "active"
        assert "token_info" in result
        assert result["token_info"]["loaded_tokens"] > 0
        assert result["token_info"]["estimated_total"] > 0

        # 핀 내용이 포함되어야 함 (expand=true)
        assert len(result["pins"]) == 2

    async def test_resume_with_limit_parameter(self, tools):
        """limit 파라미터가 제대로 작동해야 함"""
        # 5개의 핀 추가
        for i in range(5):
            await tools.pin_add(
                content=f"Test pin {i+1}", project_id="test-project", importance=3
            )

        # limit=3으로 재개
        result = await tools.session_resume(
            project_id="test-project", expand=True, limit=3
        )

        assert result["status"] == "active"
        assert result["pins_count"] == 5  # 전체 핀 수
        assert len(result["pins"]) == 3  # limit에 따라 3개만 반환
        assert "token_info" in result

    async def test_resume_token_warning_when_over_100_tokens(self, tools):
        """expand=false일 때 100 토큰 초과 시 경고가 포함되어야 함"""
        # 긴 내용의 핀 추가
        long_content = "This is a very long content " * 50  # 약 150 단어
        await tools.pin_add(
            content=long_content, project_id="test-project", importance=3
        )

        # 세션 재개 (expand=false)
        result = await tools.session_resume(
            project_id="test-project", expand=False, limit=10
        )

        # 토큰 수가 100을 초과하면 경고가 있어야 함
        if result["token_info"]["loaded_tokens"] > 100:
            assert "token_warning" in result
            assert "100 토큰 이하를 권장" in result["token_warning"]


class TestPinAddWithImportanceAnalyzer:
    """작업 10.2: pin_add 도구 업데이트 테스트"""

    async def test_pin_add_with_explicit_importance(self, tools):
        """명시적 importance가 제공되면 그대로 사용해야 함"""
        result = await tools.pin_add(
            content="Test pin", project_id="test-project", importance=5, tags=["test"]
        )

        assert result["importance"] == 5
        assert result["auto_importance"] is False
        assert "importance_note" not in result

    async def test_pin_add_without_importance_auto_determines(self, tools):
        """importance가 없으면 자동으로 추정해야 함"""
        result = await tools.pin_add(
            content="Fix typo in README",
            project_id="test-project",
            tags=["documentation"],
        )

        assert "importance" in result
        assert result["importance"] in range(1, 6)  # 1-5 범위
        assert result["auto_importance"] is True
        assert "importance_note" in result
        assert "자동으로" in result["importance_note"]

    async def test_pin_add_auto_importance_critical(self, tools):
        """critical 키워드가 있으면 높은 중요도로 추정해야 함"""
        result = await tools.pin_add(
            content="Critical security vulnerability in authentication",
            project_id="test-project",
            tags=["security", "critical"],
        )

        assert result["importance"] >= 4  # 4 또는 5
        assert result["auto_importance"] is True

    async def test_pin_add_auto_importance_typo(self, tools):
        """typo 키워드가 있으면 낮은 중요도로 추정해야 함"""
        result = await tools.pin_add(
            content="Fix typo in variable name",
            project_id="test-project",
            tags=["style"],
        )

        assert result["importance"] <= 2  # 1 또는 2
        assert result["auto_importance"] is True

    async def test_pin_add_auto_importance_feature(self, tools):
        """feature 키워드가 있으면 중간-높은 중요도로 추정해야 함"""
        result = await tools.pin_add(
            content="Implement new user authentication feature",
            project_id="test-project",
            tags=["feature", "authentication"],
        )

        assert result["importance"] >= 3  # 3, 4, 또는 5
        assert result["auto_importance"] is True

    async def test_pin_add_auto_importance_korean(self, tools):
        """한국어 키워드도 제대로 분석해야 함"""
        result = await tools.pin_add(
            content="아키텍처 설계 변경", project_id="test-project", tags=["설계"]
        )

        assert result["importance"] >= 4  # 4 또는 5
        assert result["auto_importance"] is True

    async def test_pin_add_auto_importance_default_for_no_keywords(self, tools):
        """키워드가 없으면 기본값(3)으로 설정해야 함"""
        result = await tools.pin_add(
            content="Some random task without specific keywords",
            project_id="test-project",
        )

        assert result["importance"] == 3  # 기본값
        assert result["auto_importance"] is True


class TestIntegrationWorkflow:
    """통합 워크플로우 테스트"""

    async def test_full_workflow_with_token_tracking_and_auto_importance(self, tools):
        """전체 워크플로우: 핀 추가 (자동 중요도) → 세션 재개 (토큰 추적)"""
        # 1. 다양한 중요도의 핀 추가 (자동 추정)
        pin1 = await tools.pin_add(
            content="Critical security fix",
            project_id="test-project",
            tags=["security"],
        )
        assert pin1["auto_importance"] is True
        assert pin1["importance"] >= 4

        pin2 = await tools.pin_add(
            content="Fix typo in comment", project_id="test-project"
        )
        assert pin2["auto_importance"] is True
        assert pin2["importance"] <= 2

        pin3 = await tools.pin_add(
            content="Implement new feature",
            project_id="test-project",
            importance=4,  # 명시적 지정
        )
        assert pin3["auto_importance"] is False
        assert pin3["importance"] == 4

        # 2. 세션 재개 (expand=false, 토큰 추적)
        resume_result = await tools.session_resume(
            project_id="test-project", expand=False, limit=10
        )

        assert resume_result["status"] == "active"
        assert resume_result["pins_count"] == 3
        assert "token_info" in resume_result
        assert resume_result["token_info"]["loaded_tokens"] > 0

        # 3. 세션 재개 (expand=true, 전체 내용 로드)
        resume_expanded = await tools.session_resume(
            project_id="test-project", expand=True, limit=10
        )

        assert len(resume_expanded["pins"]) == 3
        assert (
            resume_expanded["token_info"]["loaded_tokens"]
            > resume_result["token_info"]["loaded_tokens"]
        )

        # 4. 핀 완료
        complete_result = await tools.pin_complete(pin1["id"])
        assert complete_result["status"] == "completed"
        assert complete_result["suggest_promotion"] is True  # importance >= 4

        # 5. 세션 종료
        end_result = await tools.session_end(
            project_id="test-project", summary="Test session completed"
        )

        assert end_result["status"] == "completed"
        assert end_result["summary"] == "Test session completed"
