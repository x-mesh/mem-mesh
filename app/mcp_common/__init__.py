"""
MCP Common Module - MCP 서버 구현체들이 공유하는 공통 코드.

이 모듈은 다음을 제공합니다:
- tools: Tool handler 함수들 (비즈니스 로직)
- storage: Storage 초기화/종료 헬퍼
"""

__all__ = ["MCPToolHandlers", "StorageManager"]


def __getattr__(name: str):
    # Lazy export (PEP 562): storage/tools를 실제 접근 시점에만 import한다.
    # eager import 시 storage -> core.storage.api -> httpx 체인이 끌려와,
    # 같은 패키지의 가벼운 모듈(예: schemas)만 import하려는 경로(uvx mem-mesh
    # onboarding, base 의존성에 httpx 없음)를 ModuleNotFoundError로 깨뜨린다.
    if name == "StorageManager":
        from .storage import StorageManager

        return StorageManager
    if name == "MCPToolHandlers":
        from .tools import MCPToolHandlers

        return MCPToolHandlers
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
