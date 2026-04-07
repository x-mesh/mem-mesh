#!/usr/bin/env python3
"""
Embedding regeneration script (non-interactive).
"""

import asyncio
import struct
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.config import Settings


async def regenerate_embeddings():
    """Regenerate all embeddings"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    # Initialize embedding service with multilingual model
    model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_service = EmbeddingService(model_name=model_name, preload=False)
    embedding_service.load_model()

    print("=" * 60)
    print("🔄 Starting embedding regeneration")
    print("=" * 60)
    print(f"Model: {embedding_service.model_name}")
    print(f"Dimensions: {embedding_service.dimension}")

    # Fetch all memories
    conn = db.connection
    cursor = conn.execute("""
        SELECT id, content, project_id, category, tags
        FROM memories
        ORDER BY created_at DESC
    """)
    memories = cursor.fetchall()

    print(f"Scheduled to process {len(memories)} memories in total")
    print()

    # Batch processing
    batch_size = 100
    updated_count = 0
    error_count = 0

    for i in range(0, len(memories), batch_size):
        batch = memories[i:i + batch_size]
        batch_texts = []
        batch_ids = []

        for memory in batch:
            memory_id = memory[0]
            content = memory[1]
            project_id = memory[2]
            category = memory[3]
            tags = memory[4]

            # Prepare text
            text_parts = [content]
            if category:
                text_parts.append(f"Category: {category}")
            if tags:
                text_parts.append(f"Tags: {tags}")
            if project_id:
                text_parts.append(f"Project: {project_id}")

            full_text = " ".join(text_parts)
            batch_texts.append(full_text)
            batch_ids.append(memory_id)

        # Generate batch embeddings
        try:
            embeddings = embedding_service.embed_batch(batch_texts)

            # Update database
            for memory_id, embedding in zip(batch_ids, embeddings):
                binary_embedding = struct.pack(f'{len(embedding)}f', *embedding)

                conn.execute("""
                    UPDATE memories
                    SET embedding = ?
                    WHERE id = ?
                """, (binary_embedding, memory_id))

            conn.commit()
            updated_count += len(batch)

            # Show progress
            progress = (i + len(batch)) / len(memories) * 100
            print(f"Progress: {progress:.1f}% ({updated_count}/{len(memories)})")

        except Exception as e:
            print(f"❌ Batch processing error: {e}")
            error_count += len(batch)

    # Done
    print()
    print("=" * 60)
    print("✅ Embedding regeneration complete")
    print("=" * 60)
    print(f"Succeeded: {updated_count}")
    print(f"Failed: {error_count}")
    print(f"Model: {model_name}")

    conn.close()


if __name__ == "__main__":
    asyncio.run(regenerate_embeddings())
