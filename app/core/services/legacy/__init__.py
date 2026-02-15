"""
Legacy Search Implementation - DEPRECATED

search.py의 SearchService는 일부 모듈에서 아직 참조 중이므로 유지합니다.
새 코드에서는 반드시 UnifiedSearchService를 사용하세요.

ACTIVE IMPLEMENTATION:
- app.core.services.unified_search.UnifiedSearchService

REMAINING LEGACY:
- search.py: 기본 SearchService (batch_tools, storage, mcp_stdio에서 참조)

REMOVED (v1.0.4):
- enhanced_search.py, improved_search.py, final_improved_search.py, simple_improved_search.py
"""

__all__ = []
