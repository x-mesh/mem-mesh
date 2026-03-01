#!/usr/bin/env python3
"""
mem-mesh 로깅 시스템 테스트 및 사용법 예제

파일 로깅을 활성화하려면 환경변수를 설정하세요:
export MCP_LOG_FILE="./logs/mem-mesh.log"
export MCP_LOG_LEVEL="INFO"
export MCP_LOG_FORMAT="text"  # 또는 "json"

그 다음 웹 서버를 실행하세요:
python -m app.web --reload
"""

import asyncio
import os
import sys
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from app.core.utils.logger import get_logger, setup_logging


def test_console_logging():
    """콘솔 로깅 테스트"""
    print("\n=== 콘솔 로깅 테스트 ===")

    # 환경변수 설정 (파일 로깅 비활성화)
    os.environ.pop("MCP_LOG_FILE", None)
    os.environ["MCP_LOG_LEVEL"] = "INFO"
    os.environ["MCP_LOG_FORMAT"] = "text"

    # 로거 초기화
    setup_logging()
    logger = get_logger("test-console")

    logger.info("콘솔 로깅 테스트", test_type="console")
    logger.warning("경고 메시지", component="test")
    logger.error("에러 메시지", error_code=500)


def test_file_logging():
    """파일 로깅 테스트"""
    print("\n=== 파일 로깅 테스트 ===")

    # 로그 파일 경로 설정
    log_file = "./logs/test-mem-mesh.log"

    # 환경변수 설정 (파일 로깅 활성화)
    os.environ["MCP_LOG_FILE"] = log_file
    os.environ["MCP_LOG_LEVEL"] = "DEBUG"
    os.environ["MCP_LOG_FORMAT"] = "text"

    # 로거 초기화
    setup_logging()
    logger = get_logger("test-file")

    logger.debug("디버그 메시지", test_type="file")
    logger.info("파일 로깅 테스트", log_file=log_file)
    logger.warning("파일에 기록됩니다", component="test")
    logger.error("에러도 파일에 기록", error_code=404)

    # 로그 파일 확인
    if Path(log_file).exists():
        print(f"✅ 로그 파일이 생성되었습니다: {log_file}")
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
            print(f"📄 로그 파일 내용 (마지막 200자):\n{content[-200:]}")
    else:
        print(f"❌ 로그 파일이 생성되지 않았습니다: {log_file}")


def test_json_logging():
    """JSON 로깅 테스트"""
    print("\n=== JSON 로깅 테스트 ===")

    # 환경변수 설정 (JSON 형식)
    os.environ["MCP_LOG_FILE"] = "./logs/test-mem-mesh-json.log"
    os.environ["MCP_LOG_LEVEL"] = "INFO"
    os.environ["MCP_LOG_FORMAT"] = "json"

    # 로거 초기화
    setup_logging()
    logger = get_logger("test-json")

    logger.info(
        "JSON 형식 로깅 테스트",
        format_type="json",
        structured_data={"key": "value", "number": 42},
    )
    logger.warning(
        "JSON 경고 메시지",
        component="test",
        metadata={"timestamp": "2024-01-01", "user": "test"},
    )


def test_mcp_server_logging():
    """MCP 서버용 간단한 로거 테스트"""
    print("\n=== MCP 서버 로깅 테스트 ===")

    # 환경변수 설정
    os.environ["MCP_LOG_FILE"] = "./logs/test-mcp-server.log"
    os.environ["MCP_LOG_LEVEL"] = "INFO"
    os.environ["MCP_LOG_FORMAT"] = "text"

    # MCP 서버용 간단한 로거
    log = setup_logging("test-mcp-server")

    log.info("MCP 서버 시작")
    log.info("도구 호출 처리 중")
    log.warning("느린 요청 감지")
    log.info("MCP 서버 종료")


async def test_web_server_logging():
    """웹 서버 로깅 테스트 (lifespan.py와 유사)"""
    print("\n=== 웹 서버 로깅 테스트 ===")

    # 환경변수 설정
    os.environ["MCP_LOG_FILE"] = "./logs/test-web-server.log"
    os.environ["MCP_LOG_LEVEL"] = "INFO"
    os.environ["MCP_LOG_FORMAT"] = "text"

    # 웹 서버용 로거
    setup_logging()
    logger = get_logger("mem-mesh-web")

    logger.info("Starting mem-mesh Web Server...")
    logger.info("Initializing database connection", database_path="./data/memories.db")
    logger.info("Database connected successfully")
    logger.info("Loading embedding model", model="all-MiniLM-L6-v2")
    logger.info("Initializing business services")
    logger.info("Initializing MCP SSE handlers")
    logger.info(
        "mem-mesh application initialized successfully",
        log_file="./logs/test-web-server.log",
        log_format="text",
    )


def main():
    """모든 로깅 테스트 실행"""
    print("🚀 mem-mesh 로깅 시스템 테스트")
    print("=" * 50)

    # 로그 디렉토리 생성
    Path("./logs").mkdir(exist_ok=True)

    # 각종 로깅 테스트
    test_console_logging()
    test_file_logging()
    test_json_logging()
    test_mcp_server_logging()

    # 비동기 테스트
    asyncio.run(test_web_server_logging())

    print("\n✅ 모든 로깅 테스트 완료!")
    print("\n📋 파일 로깅 사용법:")
    print("1. 환경변수 설정:")
    print("   export MCP_LOG_FILE='./logs/mem-mesh.log'")
    print("   export MCP_LOG_LEVEL='INFO'")
    print("   export MCP_LOG_FORMAT='text'")
    print("\n2. 웹 서버 실행:")
    print("   python -m app.web --reload")
    print("\n3. 로그 파일 확인:")
    print("   tail -f ./logs/mem-mesh.log")


if __name__ == "__main__":
    main()
