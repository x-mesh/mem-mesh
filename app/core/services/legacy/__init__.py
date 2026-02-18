"""
Legacy Search Implementations - DEPRECATED

This directory contains legacy search implementations that have been archived
for reference purposes. These implementations are no longer actively maintained
or used in the system.

ACTIVE IMPLEMENTATION:
- Use `app.core.services.unified_search.UnifiedSearchService` instead

ARCHIVED IMPLEMENTATIONS:
- search.py: Legacy base search implementation
- enhanced_search.py: Quality optimization extension
- improved_search.py: Korean optimization extension
- final_improved_search.py: Standalone translation implementation
- simple_improved_search.py: Lightweight standalone implementation

MIGRATION GUIDE:
If you need to use any of these legacy implementations, please:
1. Check if UnifiedSearchService meets your requirements
2. If not, file an issue with your use case
3. Do NOT import from this legacy directory in new code

DEPRECATION TIMELINE:
- v2.1: Archived to legacy/ directory
- v2.2+: May be removed in future versions

For more information, see:
- app/core/services/unified_search.py
- docs/unified-search-migration-guide.md
"""

__all__ = []
