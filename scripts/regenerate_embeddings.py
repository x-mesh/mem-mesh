#!/usr/bin/env python3
"""
임베딩 재생성 스크립트 (비대화형)
"""

import asyncio
import struct
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.config import Settings


async def regenerate_embeddings():
    """모든 임베딩 재생성"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    # 다국어 모델로 임베딩 서비스 초기화
    model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_service = EmbeddingService(model_name=model_name, preload=False)
    embedding_service.load_model()

    print("=" * 60)
    print("🔄 임베딩 재생성 시작")
    print("=" * 60)
    print(f"모델: {embedding_service.model_name}")
    print(f"차원: {embedding_service.dimension}")

    # 모든 메모리 가져오기
    conn = db.connection
    cursor = conn.execute("""
        SELECT id, content, project_id, category, tags
        FROM memories
        ORDER BY created_at DESC
    """)
    memories = cursor.fetchall()

    print(f"총 {len(memories)}개의 메모리 처리 예정")
    print()

    # 배치 처리
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

            # 텍스트 준비
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

        # 배치 임베딩 생성
        try:
            embeddings = embedding_service.embed_batch(batch_texts)

            # 데이터베이스 업데이트
            for memory_id, embedding in zip(batch_ids, embeddings):
                binary_embedding = struct.pack(f'{len(embedding)}f', *embedding)

                conn.execute("""
                    UPDATE memories
                    SET embedding = ?
                    WHERE id = ?
                """, (binary_embedding, memory_id))

            conn.commit()
            updated_count += len(batch)

            # 진행상황 표시
            progress = (i + len(batch)) / len(memories) * 100
            print(f"진행: {progress:.1f}% ({updated_count}/{len(memories)})")

        except Exception as e:
            print(f"❌ 배치 처리 오류: {e}")
            error_count += len(batch)

    # 완료
    print()
    print("=" * 60)
    print("✅ 임베딩 재생성 완료")
    print("=" * 60)
    print(f"성공: {updated_count}개")
    print(f"실패: {error_count}개")
    print(f"모델: {model_name}")

    conn.close()


if __name__ == "__main__":
    asyncio.run(regenerate_embeddings())