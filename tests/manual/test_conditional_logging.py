#!/usr/bin/env python3
"""
조건부 로깅 기능 테스트 스크립트

이 스크립트는 새로 추가된 조건부 로깅 기능을 테스트합니다:
- info_debug(): 로그 레벨에 따라 다른 메시지 출력
- info_with_details(): DEBUG 레벨에서만 상세 정보 포함
"""

import os
import sys
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from app.core.utils.logger import get_logger, setup_logging


def test_info_debug():
    """info_debug 메서드 테스트"""
    print("\n=== info_debug() 메서드 테스트 ===")

    # INFO 레벨에서 테스트
    print("\n1. INFO 레벨에서 테스트:")
    os.environ["MCP_LOG_LEVEL"] = "INFO"
    setup_logging()
    logger = get_logger("test-info-debug")

    logger.info_debug(
        info_msg="Tool called with basic info",
        debug_msg="Tool called with detailed debug info",
        tool_name="add",
        user_id="test_user",
    )

    # DEBUG 레벨에서 테스트
    print("\n2. DEBUG 레벨에서 테스트:")
    os.environ["MCP_LOG_LEVEL"] = "DEBUG"
    setup_logging()
    logger = get_logger("test-info-debug-2")

    logger.info_debug(
        info_msg="Tool called with basic info",
        debug_msg="Tool called with detailed debug info",
        tool_name="add",
        user_id="test_user",
    )


def test_info_with_details():
    """info_with_details 메서드 테스트"""
    print("\n=== info_with_details() 메서드 테스트 ===")

    # INFO 레벨에서 테스트
    print("\n1. INFO 레벨에서 테스트 (details 숨김):")
    os.environ["MCP_LOG_LEVEL"] = "INFO"
    setup_logging()
    logger = get_logger("test-details-info")

    logger.info_with_details(
        base_msg="Tool add called",
        details={
            "content": "이것은 민감한 사용자 데이터입니다",
            "tags": ["private", "sensitive"],
            "source": "user_input",
        },
        project_id="test-project",
        category="task",
        content_length=25,
    )

    # DEBUG 레벨에서 테스트
    print("\n2. DEBUG 레벨에서 테스트 (details 포함):")
    os.environ["MCP_LOG_LEVEL"] = "DEBUG"
    setup_logging()
    logger = get_logger("test-details-debug")

    logger.info_with_details(
        base_msg="Tool add called",
        details={
            "content": "이것은 민감한 사용자 데이터입니다",
            "tags": ["private", "sensitive"],
            "source": "user_input",
        },
        project_id="test-project",
        category="task",
        content_length=25,
    )


def test_mcp_tools_logging():
    """MCP 도구에서 실제 사용되는 패턴 테스트"""
    print("\n=== MCP 도구 로깅 패턴 테스트 ===")

    # INFO 레벨에서 테스트
    print("\n1. INFO 레벨 - 메타데이터만:")
    os.environ["MCP_LOG_LEVEL"] = "INFO"
    setup_logging()
    logger = get_logger("mcp-tools")

    # add 도구 시뮬레이션
    content = "새로운 메모리 내용입니다. 이것은 사용자가 입력한 실제 데이터입니다."
    logger.info_with_details(
        "Tool add called",
        details={"content": content, "tags": ["test", "demo"], "source": "mcp"},
        project_id="demo-project",
        category="task",
        content_length=len(content),
    )

    # search 도구 시뮬레이션
    query = "메모리 검색 쿼리"
    logger.info_with_details(
        "Tool search called",
        details={"query_text": query, "recency_weight": 0.1},
        project_id="demo-project",
        category="task",
        limit=5,
        query_length=len(query),
    )

    # DEBUG 레벨에서 테스트
    print("\n2. DEBUG 레벨 - 상세 정보 포함:")
    os.environ["MCP_LOG_LEVEL"] = "DEBUG"
    setup_logging()
    logger = get_logger("mcp-tools-debug")

    # add 도구 시뮬레이션
    logger.info_with_details(
        "Tool add called",
        details={"content": content, "tags": ["test", "demo"], "source": "mcp"},
        project_id="demo-project",
        category="task",
        content_length=len(content),
    )

    # search 도구 시뮬레이션
    logger.info_with_details(
        "Tool search called",
        details={"query_text": query, "recency_weight": 0.1},
        project_id="demo-project",
        category="task",
        limit=5,
        query_length=len(query),
    )


def test_file_logging():
    """파일 로깅과 함께 조건부 로깅 테스트"""
    print("\n=== 파일 로깅 + 조건부 로깅 테스트 ===")

    log_file = "./logs/test-conditional.log"
    os.environ["MCP_LOG_FILE"] = log_file
    os.environ["MCP_LOG_LEVEL"] = "DEBUG"
    os.environ["MCP_LOG_FORMAT"] = "text"

    setup_logging()
    logger = get_logger("file-test")

    logger.info_with_details(
        "File logging test",
        details={
            "sensitive_data": "이 데이터는 DEBUG에서만 보입니다",
            "user_input": "사용자가 입력한 내용",
        },
        test_type="file_logging",
        timestamp="2024-01-13",
    )

    print(f"로그 파일 확인: {log_file}")
    if Path(log_file).exists():
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
            print("파일 내용:")
            print(content[-200:])  # 마지막 200자만 출력


def main():
    """모든 조건부 로깅 테스트 실행"""
    print("🧪 조건부 로깅 기능 테스트")
    print("=" * 50)

    # 로그 디렉토리 생성
    Path("./logs").mkdir(exist_ok=True)

    # 각종 테스트 실행
    test_info_debug()
    test_info_with_details()
    test_mcp_tools_logging()
    test_file_logging()

    print("\n✅ 모든 조건부 로깅 테스트 완료!")
    print("\n📋 사용법 요약:")
    print("1. logger.info_debug(info_msg, debug_msg, **kwargs)")
    print("   - INFO 레벨: info_msg 출력")
    print("   - DEBUG 레벨: debug_msg 출력")
    print("\n2. logger.info_with_details(base_msg, details={}, **kwargs)")
    print("   - INFO 레벨: base_msg + kwargs만 출력")
    print("   - DEBUG 레벨: base_msg + kwargs + details 모두 출력")
    print("\n3. MCP 도구에서 민감한 데이터 로깅:")
    print("   - content, query_text 등은 DEBUG에서만 출력")
    print("   - 메타데이터(길이, 카테고리 등)는 항상 출력")


if __name__ == "__main__":
    main()
