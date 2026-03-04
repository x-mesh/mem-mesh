"""User identification utilities for mem-mesh.

Provides automatic user detection from system username or environment variables.
"""

import logging
import os
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

_cached_user: Optional[str] = None


def get_current_user() -> str:
    """
    현재 사용자명 자동 감지.

    우선순위:
    1. USER 환경변수
    2. whoami 명령어
    3. 기본값 "default"

    Returns:
        사용자명 문자열
    """
    global _cached_user

    if _cached_user is not None:
        return _cached_user

    # 1. USER 환경변수 확인
    user = os.environ.get("USER")
    if user:
        _cached_user = user
        logger.debug(f"User detected from USER env: {user}")
        return user

    # 2. whoami 명령어 시도
    try:
        result = subprocess.run(["whoami"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            user = result.stdout.strip()
            _cached_user = user
            logger.debug(f"User detected from whoami: {user}")
            return user
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.debug(f"whoami failed: {e}")

    # 3. 기본값 반환
    _cached_user = "default"
    logger.debug("Using default user")
    return _cached_user


def clear_user_cache() -> None:
    """사용자 캐시 초기화 (테스트용)"""
    global _cached_user
    _cached_user = None
