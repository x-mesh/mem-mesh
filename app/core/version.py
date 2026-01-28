"""
mem-mesh 버전 및 서버 정보 중앙 관리 모듈.

모든 모듈에서 이 파일을 import하여 일관된 버전 정보를 사용합니다.
"""

# 버전 정보
__VERSION__ = "1.0.2"

# MCP 프로토콜 버전 (Streamable HTTP transport 지원)
MCP_PROTOCOL_VERSION = "2025-03-26"

# 서버 기본 정보
SERVER_NAME = "mem-mesh"
SERVER_DESCRIPTION = "MCP server for mem-mesh memory management"

# 서버 정보 딕셔너리 (MCP 프로토콜용)
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
