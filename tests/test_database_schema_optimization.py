"""데이터베이스 스키마 테스트: context-token-optimization

이 테스트는 context-token-optimization 기능을 위한 데이터베이스 스키마 변경을 검증합니다.

Requirements: 10.1, 10.2, 10.3
"""

import os
import tempfile

import pytest

from app.core.database.connection import DatabaseConnection
from app.core.database.initializer import DatabaseInitializer


@pytest.fixture
async def test_db():
    """테스트용 임시 데이터베이스 생성"""
    # 임시 파일 생성
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # 데이터베이스 연결 및 초기화
    connection = DatabaseConnection(db_path)
    await connection.connect()

    initializer = DatabaseInitializer(connection)
    await initializer.initialize_schema()

    yield connection

    # 정리
    await connection.close()
    for ext in ["", "-wal", "-shm"]:
        p = db_path + ext
        if os.path.exists(p):
            os.unlink(p)


@pytest.mark.asyncio
async def test_pins_table_has_optimization_columns(test_db):
    """pins 테이블에 토큰 최적화 컬럼이 존재하는지 확인

    Requirements: 10.1
    """
    cursor = await test_db.execute("PRAGMA table_info(pins)")
    columns = cursor.fetchall()
    column_names = [col["name"] for col in columns]

    # 새로운 컬럼 확인
    assert "estimated_tokens" in column_names, "pins.estimated_tokens 컬럼이 없습니다"
    assert (
        "promoted_to_memory_id" in column_names
    ), "pins.promoted_to_memory_id 컬럼이 없습니다"
    assert "auto_importance" in column_names, "pins.auto_importance 컬럼이 없습니다"


@pytest.mark.asyncio
async def test_sessions_table_has_optimization_columns(test_db):
    """sessions 테이블에 토큰 최적화 컬럼이 존재하는지 확인

    Requirements: 10.2
    """
    cursor = await test_db.execute("PRAGMA table_info(sessions)")
    columns = cursor.fetchall()
    column_names = [col["name"] for col in columns]

    # 새로운 컬럼 확인
    assert (
        "initial_context_tokens" in column_names
    ), "sessions.initial_context_tokens 컬럼이 없습니다"
    assert (
        "total_loaded_tokens" in column_names
    ), "sessions.total_loaded_tokens 컬럼이 없습니다"
    assert (
        "total_saved_tokens" in column_names
    ), "sessions.total_saved_tokens 컬럼이 없습니다"


@pytest.mark.asyncio
async def test_session_stats_table_exists(test_db):
    """session_stats 테이블이 존재하는지 확인

    Requirements: 10.1
    """
    cursor = await test_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='session_stats'"
    )
    result = cursor.fetchone()

    assert result is not None, "session_stats 테이블이 존재하지 않습니다"

    # 테이블 구조 확인
    cursor = await test_db.execute("PRAGMA table_info(session_stats)")
    columns = cursor.fetchall()
    column_names = [col["name"] for col in columns]

    expected_columns = [
        "id",
        "session_id",
        "timestamp",
        "event_type",
        "tokens_loaded",
        "tokens_saved",
        "context_depth",
        "created_at",
    ]

    for col in expected_columns:
        assert col in column_names, f"session_stats.{col} 컬럼이 없습니다"


@pytest.mark.asyncio
async def test_token_usage_table_exists(test_db):
    """token_usage 테이블이 존재하는지 확인

    Requirements: 10.1
    """
    cursor = await test_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='token_usage'"
    )
    result = cursor.fetchone()

    assert result is not None, "token_usage 테이블이 존재하지 않습니다"

    # 테이블 구조 확인
    cursor = await test_db.execute("PRAGMA table_info(token_usage)")
    columns = cursor.fetchall()
    column_names = [col["name"] for col in columns]

    expected_columns = [
        "id",
        "project_id",
        "session_id",
        "operation_type",
        "query",
        "tokens_used",
        "tokens_saved",
        "optimization_applied",
        "created_at",
    ]

    for col in expected_columns:
        assert col in column_names, f"token_usage.{col} 컬럼이 없습니다"


@pytest.mark.asyncio
async def test_optimization_indexes_exist(test_db):
    """토큰 최적화 관련 인덱스가 존재하는지 확인

    Requirements: 10.3
    """
    cursor = await test_db.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = cursor.fetchall()
    index_names = [idx["name"] for idx in indexes]

    # session_stats 인덱스
    assert (
        "idx_session_stats_session" in index_names
    ), "idx_session_stats_session 인덱스가 없습니다"
    assert (
        "idx_session_stats_timestamp" in index_names
    ), "idx_session_stats_timestamp 인덱스가 없습니다"
    assert (
        "idx_session_stats_event_type" in index_names
    ), "idx_session_stats_event_type 인덱스가 없습니다"

    # token_usage 인덱스
    assert (
        "idx_token_usage_project" in index_names
    ), "idx_token_usage_project 인덱스가 없습니다"
    assert (
        "idx_token_usage_session" in index_names
    ), "idx_token_usage_session 인덱스가 없습니다"
    assert (
        "idx_token_usage_created" in index_names
    ), "idx_token_usage_created 인덱스가 없습니다"
    assert (
        "idx_token_usage_operation" in index_names
    ), "idx_token_usage_operation 인덱스가 없습니다"

    # pins 테이블 추가 인덱스
    assert "idx_pins_promoted" in index_names, "idx_pins_promoted 인덱스가 없습니다"
    assert (
        "idx_pins_auto_importance" in index_names
    ), "idx_pins_auto_importance 인덱스가 없습니다"


@pytest.mark.asyncio
async def test_wal_mode_enabled(test_db):
    """WAL 모드가 활성화되어 있는지 확인

    Requirements: 10.3
    """
    cursor = await test_db.execute("PRAGMA journal_mode")
    result = cursor.fetchone()

    assert result is not None, "journal_mode 조회 실패"
    assert result[0].lower() == "wal", f"WAL 모드가 활성화되지 않았습니다: {result[0]}"


@pytest.mark.asyncio
async def test_foreign_key_constraints(test_db):
    """외래 키 제약조건이 올바르게 설정되어 있는지 확인

    Requirements: 10.1
    """
    # session_stats의 외래 키 확인
    cursor = await test_db.execute("PRAGMA foreign_key_list(session_stats)")
    fks = cursor.fetchall()

    assert len(fks) > 0, "session_stats에 외래 키가 없습니다"
    assert any(
        fk["table"] == "sessions" for fk in fks
    ), "session_stats.session_id 외래 키가 sessions를 참조하지 않습니다"

    # token_usage의 외래 키 확인
    cursor = await test_db.execute("PRAGMA foreign_key_list(token_usage)")
    fks = cursor.fetchall()

    assert len(fks) > 0, "token_usage에 외래 키가 없습니다"
    assert any(
        fk["table"] == "sessions" for fk in fks
    ), "token_usage.session_id 외래 키가 sessions를 참조하지 않습니다"


@pytest.mark.asyncio
async def test_insert_session_stats_record(test_db):
    """session_stats 테이블에 레코드 삽입 테스트

    Requirements: 10.1
    """
    from datetime import datetime
    from uuid import uuid4

    # 먼저 프로젝트와 세션 생성
    project_id = str(uuid4())
    session_id = str(uuid4())
    now = datetime.utcnow().isoformat() + "Z"

    await test_db.execute(
        """INSERT INTO projects (id, name, created_at, updated_at)
           VALUES (?, ?, ?, ?)""",
        (project_id, "test-project", now, now),
    )

    await test_db.execute(
        """INSERT INTO sessions (id, project_id, user_id, started_at, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (session_id, project_id, "test-user", now, "active", now, now),
    )

    # session_stats 레코드 삽입
    stat_id = str(uuid4())
    await test_db.execute(
        """INSERT INTO session_stats 
           (id, session_id, timestamp, event_type, tokens_loaded, tokens_saved, context_depth, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (stat_id, session_id, now, "resume", 100, 500, 2, now),
    )

    test_db.commit()

    # 조회 확인
    cursor = await test_db.execute(
        "SELECT * FROM session_stats WHERE id = ?", (stat_id,)
    )
    result = cursor.fetchone()

    assert result is not None, "session_stats 레코드가 삽입되지 않았습니다"
    assert result["session_id"] == session_id
    assert result["event_type"] == "resume"
    assert result["tokens_loaded"] == 100
    assert result["tokens_saved"] == 500


@pytest.mark.asyncio
async def test_insert_token_usage_record(test_db):
    """token_usage 테이블에 레코드 삽입 테스트

    Requirements: 10.1
    """
    from datetime import datetime
    from uuid import uuid4

    # 프로젝트 생성
    project_id = str(uuid4())
    now = datetime.utcnow().isoformat() + "Z"

    await test_db.execute(
        """INSERT INTO projects (id, name, created_at, updated_at)
           VALUES (?, ?, ?, ?)""",
        (project_id, "test-project", now, now),
    )

    # token_usage 레코드 삽입
    usage_id = str(uuid4())
    await test_db.execute(
        """INSERT INTO token_usage 
           (id, project_id, session_id, operation_type, query, tokens_used, tokens_saved, optimization_applied, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (usage_id, project_id, None, "search", "test query", 200, 300, 1, now),
    )

    test_db.commit()

    # 조회 확인
    cursor = await test_db.execute(
        "SELECT * FROM token_usage WHERE id = ?", (usage_id,)
    )
    result = cursor.fetchone()

    assert result is not None, "token_usage 레코드가 삽입되지 않았습니다"
    assert result["project_id"] == project_id
    assert result["operation_type"] == "search"
    assert result["tokens_used"] == 200
    assert result["tokens_saved"] == 300
    assert result["optimization_applied"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
