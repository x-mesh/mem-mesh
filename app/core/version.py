"""
mem-mesh 버전 및 서버 정보 중앙 관리 모듈.

모든 모듈에서 이 파일을 import하여 일관된 버전 정보를 사용합니다.
버전의 단일 소스는 pyproject.toml — 여기서는 읽기만 한다.
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path


def _read_version() -> str:
    """pyproject.toml → importlib.metadata → fallback 순으로 버전을 읽는다."""
    # 1) Parse pyproject.toml directly (reflects make bump immediately in dev mode)
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text().splitlines():
            if line.strip().startswith("version"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    # 2) Installed package metadata (Docker/production, etc.)
    try:
        return _pkg_version("mem-mesh")
    except PackageNotFoundError:
        pass

    return "0.0.0"


__VERSION__ = _read_version()

# MCP protocol version (supports Streamable HTTP transport)
MCP_PROTOCOL_VERSION = "2025-03-26"

# Server basic info
SERVER_NAME = "mem-mesh"
SERVER_DESCRIPTION = "MCP server for mem-mesh memory management"

# Server info dictionary (for MCP protocol)
SERVER_INFO = {
    "name": SERVER_NAME,
    "version": __VERSION__,
    "description": SERVER_DESCRIPTION,
}


def get_server_info(transport: str = None) -> dict:
    """
    서버 정보 반환.

    Args:
        transport: transport 타입 (stdio, sse 등).
                   지정하면 description에 포함됨.

    Returns:
        서버 정보 딕셔너리
    """
    info = SERVER_INFO.copy()
    if transport:
        info["description"] = f"{SERVER_DESCRIPTION} ({transport})"
    return info
