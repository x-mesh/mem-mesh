
import asyncio
import os
import logging
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.unified_search import UnifiedSearchService
from app.core.services.cache_manager import reset_cache_manager
from app.core.config import Settings

# Set logging to be quieter
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.basicConfig(level=logging.ERROR)  # Default to ERROR
logger = logging.getLogger("SearchVerifier")
logger.setLevel(logging.INFO)  # Only the verifier at INFO

async def verify_features():
    print("\n" + "="*60)
    print("🔍 RRF Hybrid Search & Smart Query Expansion Verification")
    print("="*60)

    # Reset cache
    reset_cache_manager()

    # Initialize
    settings = Settings()
    db = Database(settings.database_path)
    if hasattr(db, 'connect'):
        await db.connect()

    # Embedding service (preload=True triggers loading log)
    print("Loading embedding model...")
    embedding_service = EmbeddingService(preload=True)

    # Queries to test:
    # 1. dashboard: English -> not translated (check smart expansion) -> RRF text match boosting
    # 2. bug fix (Korean): Korean -> translated -> semantic search enhanced
    # 3. access log: English -> not translated -> RRF boosting
    queries = ["dashboard", "버그 수정", "Access Log"]

    # Create service instance once
    service = UnifiedSearchService(
        db=db,
        embedding_service=embedding_service,
        cache_search_ttl=0,
        enable_quality_features=True,
        enable_korean_optimization=True,
        enable_noise_filter=False,  # Noise filter off to inspect results (check RRF score distribution)
        enable_score_normalization=True
    )

    for query in queries:
        print(f"\n" + "-"*60)
        print(f"🧪 Query: '{query}'")
        print("-"*60)

        try:
            # Run search
            response = await service.search(query=query, limit=3)

            print(f"   Results: {len(response.results)}")
            for i, res in enumerate(response.results):
                title = res.content.split('\n')[0][:50]
                print(f"   [{i+1}] Score: {res.similarity_score:.4f} | {title}...")

            # Query expansion verification output
            is_korean = service._is_korean(query)
            expanded = service._expand_query(query)
            print(f"   [verify] Korean detected: {is_korean}")
            print(f"   [verify] Final query: '{expanded}'")

            if not is_korean and expanded == query:
                print("   ✅ Smart expansion succeeded (English query preserved)")
            elif is_korean and len(expanded) > len(query):
                print("   ✅ Smart expansion succeeded (Korean query translated)")

        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_features())
