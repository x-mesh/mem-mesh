"""
Property-based tests for mem-mesh system
"""

import asyncio
import os
import re
import tempfile
from unittest.mock import Mock

import pytest
from hypothesis import HealthCheck, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from hypothesis.strategies import composite

from app.core.config import Settings
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.schemas.requests import AddParams, SearchParams, StatsParams, UpdateParams
from app.core.services.memory import MemoryService
from app.core.storage.direct import DirectStorageBackend


@composite
def valid_memory_content(draw):
    """Valid memory content generator"""
    return draw(st.text(min_size=10, max_size=1000).filter(lambda x: x.strip()))


@composite
def valid_project_id(draw):
    """Valid project ID generator"""
    return draw(
        st.one_of(
            st.none(),
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Ll", "Nd"), whitelist_characters="-_"
                ),
                min_size=1,
                max_size=20,
            ).filter(lambda x: x and re.match(r"^[a-z0-9_-]+$", x)),
        )
    )


@composite
def valid_category(draw):
    """Valid category generator"""
    return draw(
        st.sampled_from(["task", "bug", "idea", "decision", "incident", "code_snippet"])
    )


@composite
def valid_tags(draw):
    """Valid tags generator"""
    return draw(
        st.lists(
            st.text(min_size=1, max_size=20).filter(lambda x: x.isalnum()), max_size=5
        )
    )


@pytest.fixture
async def temp_db_path():
    """임시 데이터베이스 경로 픽스처"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    yield db_path

    # 정리
    for ext in ["", "-wal", "-shm"]:
        path = db_path + ext
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture
def mock_embedding_service():
    """Mock 임베딩 서비스"""
    service = Mock(spec=EmbeddingService)
    service.embed.return_value = [0.1] * 384  # 384차원 벡터
    service.to_bytes.return_value = b"x" * (384 * 4)  # float32 * 384
    service.from_bytes.return_value = [0.1] * 384
    return service


class TestConcurrencyProperties:
    """동시성 관련 속성 기반 테스트"""

    @given(
        num_readers=st.integers(min_value=1, max_value=5),
        num_writers=st.integers(min_value=1, max_value=3),
        operations_per_task=st.integers(min_value=3, max_value=10),
    )
    @hyp_settings(
        max_examples=5,
        deadline=10000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_concurrent_database_access_stability(
        self,
        temp_db_path,
        mock_embedding_service,
        num_readers,
        num_writers,
        operations_per_task,
    ):
        """
        Feature: mcp-direct-sqlite, Property 5: Concurrent Database Access Stability

        For any set of concurrent read and write operations on the same database:
        - Read operations SHALL not be blocked by write operations (WAL mode)
        - Write conflicts SHALL be handled with retry logic
        - No data corruption SHALL occur

        **Validates: Requirements 4.2, 4.3**
        """
        # 데이터베이스 초기화
        db = Database(temp_db_path)
        await db.connect()

        memory_service = MemoryService(db, mock_embedding_service)

        # 초기 데이터 생성
        initial_memories = []
        for i in range(5):
            response = await memory_service.create(
                content=f"Initial memory {i} for concurrent test",
                source="test",
                category="task",
            )
            initial_memories.append(response.id)

        # 동시 작업 결과를 저장할 리스트
        reader_results = []
        writer_results = []
        errors = []

        async def reader_task(task_id: int):
            """읽기 작업"""
            try:
                results = []
                for i in range(operations_per_task):
                    # 기존 메모리 조회
                    if initial_memories:
                        memory_id = initial_memories[i % len(initial_memories)]
                        memory = await memory_service.get(memory_id)
                        if memory:
                            results.append(memory.id)

                reader_results.append((task_id, results))
            except Exception as e:
                errors.append(f"Reader {task_id}: {e}")

        async def writer_task(task_id: int):
            """쓰기 작업"""
            try:
                results = []
                for i in range(operations_per_task):
                    # 새 메모리 생성
                    response = await memory_service.create(
                        content=f"Concurrent memory from writer {task_id}, operation {i}",
                        source="concurrent_test",
                        category="task",
                    )
                    results.append(response.id)

                writer_results.append((task_id, results))
            except Exception as e:
                errors.append(f"Writer {task_id}: {e}")

        # 동시 작업 실행
        tasks = []

        # 읽기 작업들
        for i in range(num_readers):
            tasks.append(reader_task(i))

        # 쓰기 작업들
        for i in range(num_writers):
            tasks.append(writer_task(i))

        # 모든 작업 실행
        await asyncio.gather(*tasks, return_exceptions=True)

        # 검증
        assert len(errors) == 0, f"Concurrent operations failed: {errors}"

        # 읽기 작업이 성공적으로 완료되었는지 확인
        assert len(reader_results) == num_readers, "Not all readers completed"

        # 쓰기 작업이 성공적으로 완료되었는지 확인
        assert len(writer_results) == num_writers, "Not all writers completed"

        # 생성된 메모리들이 실제로 저장되었는지 확인
        for writer_id, created_ids in writer_results:
            for memory_id in created_ids:
                memory = await memory_service.get(memory_id)
                assert (
                    memory is not None
                ), f"Memory {memory_id} from writer {writer_id} was not saved"
                assert "concurrent_test" in memory.source

        await db.close()


class TestStorageBackendConsistency:
    """스토리지 백엔드 일관성 속성 기반 테스트"""

    @given(
        content=valid_memory_content(),
        project_id=valid_project_id(),
        category=valid_category(),
        tags=valid_tags(),
    )
    @hyp_settings(
        max_examples=5,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_storage_backend_interface_consistency(
        self, temp_db_path, mock_embedding_service, content, project_id, category, tags
    ):
        """
        Feature: mcp-direct-sqlite, Property 6: Storage Backend Interface Consistency

        For any StorageBackend implementation (DirectStorageBackend or APIStorageBackend),
        calling the same method with the same parameters SHALL produce equivalent results
        (given the same underlying data state).

        **Validates: Requirements 2.1-2.6, 3.1**
        """
        # DirectStorageBackend 테스트
        direct_storage = DirectStorageBackend(temp_db_path)
        await direct_storage.initialize()

        # 메모리 추가
        add_params = AddParams(
            content=content,
            project_id=project_id,
            category=category,
            source="property_test",
            tags=tags,
        )

        add_result = await direct_storage.add_memory(add_params)

        # 결과 검증
        assert add_result.id is not None
        assert add_result.status in ["saved", "duplicate"]

        # 검색 테스트
        search_params = SearchParams(
            query=content[:20] if len(content) >= 20 else content,
            project_id=project_id,
            category=category,
            limit=5,
        )

        search_result = await direct_storage.search_memories(search_params)

        # 검색 결과에 추가한 메모리가 포함되어야 함
        found_memory = None
        for memory in search_result.results:
            if memory.id == add_result.id:
                found_memory = memory
                break

        assert found_memory is not None, "Added memory not found in search results"
        assert found_memory.content == content
        assert found_memory.project_id == project_id
        assert found_memory.category == category

        # 컨텍스트 조회 테스트
        context_result = await direct_storage.get_context(
            memory_id=add_result.id, depth=2, project_id=project_id
        )

        assert context_result.primary_memory is not None
        assert context_result.primary_memory.id == add_result.id

        # 업데이트 테스트 (내용이 충분히 다른 경우에만)
        if len(content) > 20:
            new_content = content + " - updated for property test"
            update_params = UpdateParams(content=new_content)

            update_result = await direct_storage.update_memory(
                add_result.id, update_params
            )

            assert update_result.status == "updated"
            assert update_result.id == add_result.id

        # 통계 조회 테스트 - project_id 없이 전체 통계 조회
        stats_params = StatsParams(
            project_id=None,  # 전체 통계 조회
            start_date=None,
            end_date=None,
        )
        stats_result = await direct_storage.get_stats(stats_params)

        assert stats_result.total_memories >= 1

        # 프로젝트별 통계에서 해당 프로젝트가 포함되어야 함 (project_id가 있는 경우)
        if project_id:
            # 프로젝트별 통계 조회
            project_stats_params = StatsParams(
                project_id=project_id, start_date=None, end_date=None
            )
            project_stats_result = await direct_storage.get_stats(project_stats_params)
            assert project_stats_result.total_memories >= 1

        # 삭제 테스트
        delete_result = await direct_storage.delete_memory(add_result.id)
        assert delete_result.status == "deleted"
        assert delete_result.id == add_result.id

        await direct_storage.shutdown()


# 설정 관련 속성 기반 테스트
class TestSettingsProperties:
    """설정 관련 속성 기반 테스트"""

    @given(
        storage_mode=st.sampled_from(["direct", "api"]),
        api_base_url=st.text(min_size=10, max_size=50)
        .filter(lambda x: "\x00" not in x)
        .map(lambda x: "http://" + x.replace(" ", "")),
        database_path=st.text(min_size=1, max_size=100).filter(
            lambda x: "\x00" not in x
        ),
        busy_timeout=st.integers(min_value=1000, max_value=60000),
    )
    @hyp_settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_settings_configuration_round_trip(
        self, storage_mode, api_base_url, database_path, busy_timeout
    ):
        """
        Feature: mcp-direct-sqlite, Property 1: Settings Configuration Round-Trip

        For any valid settings configuration (storage_mode, api_base_url, database_path, busy_timeout),
        loading settings from environment variables and then reading them back
        SHALL produce the same values.

        **Validates: Requirements 1.1, 7.1, 7.2, 7.3, 7.4**
        """
        import os

        # 환경변수 설정
        original_env = {}
        env_vars = {
            "MEM_MESH_STORAGE_MODE": storage_mode,
            "MEM_MESH_API_BASE_URL": api_base_url,
            "MEM_MESH_DATABASE_PATH": database_path,
            "MEM_MESH_BUSY_TIMEOUT": str(busy_timeout),
        }

        # 기존 환경변수 백업 및 새 값 설정
        for key, value in env_vars.items():
            original_env[key] = os.environ.get(key)
            os.environ[key] = value

        try:
            # Settings 인스턴스 생성
            settings = Settings()

            # 값 검증
            assert settings.storage_mode == storage_mode
            assert settings.api_base_url == api_base_url
            assert settings.database_path == database_path
            assert settings.busy_timeout == busy_timeout

        finally:
            # 환경변수 복원
            for key, original_value in original_env.items():
                if original_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original_value

    @given(
        invalid_mode=st.text().filter(
            lambda x: x not in ("direct", "api") and len(x) > 0 and "\x00" not in x
        )
    )
    @hyp_settings(
        max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    def test_invalid_storage_mode_rejection(self, invalid_mode):
        """
        Feature: mcp-direct-sqlite, Property 2: Invalid Storage Mode Rejection

        For any storage_mode value that is not "direct" or "api",
        the Settings validation SHALL raise a ValueError with a descriptive message.

        **Validates: Requirements 1.5**
        """
        import os

        from pydantic import ValidationError

        # 환경변수 설정
        original_mode = os.environ.get("MEM_MESH_STORAGE_MODE")
        os.environ["MEM_MESH_STORAGE_MODE"] = invalid_mode

        try:
            # ValidationError가 발생해야 함
            with pytest.raises(ValidationError) as exc_info:
                Settings()

            # 에러 메시지에 storage_mode 관련 내용이 포함되어야 함
            error_str = str(exc_info.value).lower()
            assert "storage_mode" in error_str or "literal" in error_str

        finally:
            # 환경변수 복원
            if original_mode is None:
                os.environ.pop("MEM_MESH_STORAGE_MODE", None)
            else:
                os.environ["MEM_MESH_STORAGE_MODE"] = original_mode
