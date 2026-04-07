#!/usr/bin/env python3
"""
Verify that database embeddings have been correctly updated to the multilingual model.
"""

import asyncio
import numpy as np
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.config import Settings


async def verify_embeddings():
    """Verify embeddings"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(preload=False)
    embedding_service.load_model()

    print(f"Model: {embedding_service.model_name}")
    print(f"Dimensions: {embedding_service.dimension}")
    print("="*60)

    # Generate embedding for a Korean query
    query_emb = embedding_service.embed("토큰")

    # Fetch a specific memory from the database
    cursor = await db.execute(
        """
        SELECT id, content, embedding
        FROM memories
        WHERE project_id = 'mem-mesh-optimization'
        AND content LIKE '%Token Optimization Strategy%'
        LIMIT 1
        """
    )
    row = cursor.fetchone()

    if row:
        memory_id = row[0]
        content = row[1]
        stored_emb = embedding_service.from_bytes(row[2])

        print(f"Memory ID: {memory_id}")
        print(f"Content: {content[:100]}...")
        print(f"Stored embedding dimensions: {len(stored_emb)}")
        print(f"Query embedding dimensions: {len(query_emb)}")

        # Compute cosine similarity
        def cosine_similarity(a, b):
            return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

        # Test with various queries
        test_queries = [
            "토큰",
            "token",
            "토큰 최적화",
            "Token Optimization"
        ]

        print("\nSimilarity tests:")
        for q in test_queries:
            q_emb = embedding_service.embed(q)
            sim = cosine_similarity(q_emb, stored_emb)
            print(f"  '{q}' → {sim:.3f}")

        # Compare stored embedding against freshly generated one
        print("\nEmbedding regeneration comparison:")
        new_emb = embedding_service.embed(content)
        sim_new = cosine_similarity(stored_emb, new_emb)
        print(f"  Stored embedding vs newly generated embedding: {sim_new:.3f}")

        if sim_new < 0.99:
            print("  ⚠️ Embeddings do not match! Regeneration may be needed.")
        else:
            print("  ✅ Embeddings match.")

    # Korean memory test
    cursor = await db.execute(
        """
        SELECT id, content, embedding
        FROM memories
        WHERE project_id = 'mem-mesh-thread-summary-kr'
        AND content LIKE '%토큰%'
        LIMIT 1
        """
    )
    row = cursor.fetchone()

    if row:
        print("\n" + "="*60)
        print("Korean memory test:")
        content = row[1]
        stored_emb = embedding_service.from_bytes(row[2])

        print(f"Content: {content[:100]}...")

        for q in ["토큰", "token", "최적화", "optimization"]:
            q_emb = embedding_service.embed(q)
            sim = cosine_similarity(q_emb, stored_emb)
            print(f"  '{q}' → {sim:.3f}")


if __name__ == "__main__":
    asyncio.run(verify_embeddings())
