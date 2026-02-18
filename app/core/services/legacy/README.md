# Legacy Search Implementations

**Status**: DEPRECATED - Kept for reference only

## Active Implementation

Use `UnifiedSearchService` from `app.core.services.unified_search`

## Legacy Files

These files represent the evolution of the search system and are preserved for historical reference:

- **search.py** (872 lines) - Original base search implementation
- **enhanced_search.py** - Quality optimization extension
- **improved_search.py** - Korean optimization extension  
- **final_improved_search.py** - Standalone translation approach
- **simple_improved_search.py** - Lightweight standalone implementation

## Migration Guide

All code should use `UnifiedSearchService`. Example:

```python
from app.core.services.unified_search import UnifiedSearchService

# Initialize
search_service = UnifiedSearchService(db, embedding_service)

# Search
results = await search_service.search(
    query="your query",
    project_id="optional",
    limit=5
)
```

## Deprecation Timeline

These files will be removed in a future major version. No new code should reference these implementations.

## Configuration

Ensure `use_unified_search=True` in your configuration (this is the default).
