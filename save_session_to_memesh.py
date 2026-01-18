#!/usr/bin/env python3
"""
세션 요약을 mem-mesh에 저장
"""

import asyncio
import hashlib
from datetime import datetime
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.config import Settings
import struct
import json


async def save_session_summary():
    """세션 요약 저장"""

    # 요약 파일 읽기
    with open('session_summary.md', 'r', encoding='utf-8') as f:
        content = f.read()

    # 설정 및 연결
    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    # 임베딩 생성
    embedding_service = EmbeddingService(
        model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
        preload=False
    )
    embedding_service.load_model()

    # 임베딩 생성
    embedding = embedding_service.embed(content)
    binary_embedding = struct.pack(f'{len(embedding)}f', *embedding)

    # 해시 생성
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    # 메모리 저장
    conn = db.connection

    # 중복 확인
    cursor = conn.execute(
        "SELECT id FROM memories WHERE content_hash = ?",
        (content_hash,)
    )
    existing = cursor.fetchone()

    if existing:
        print(f"이미 저장된 메모리입니다: {existing[0]}")
        return existing[0]

    # 새로 저장
    import uuid
    memory_id = str(uuid.uuid4())

    cursor = conn.execute("""
        INSERT INTO memories (
            id, content, content_hash, project_id,
            category, source, embedding, tags,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        memory_id,
        content,
        content_hash,
        'mem-mesh',
        'decision',
        'session-2026-01-18',
        binary_embedding,
        json.dumps(['search-improvement', 'korean-support', 'auto-project', 'token-optimization']),
        datetime.now().isoformat(),
        datetime.now().isoformat()
    ))

    conn.commit()

    print(f"✅ mem-mesh에 저장 완료!")
    print(f"   ID: {memory_id}")
    print(f"   프로젝트: mem-mesh")
    print(f"   카테고리: decision")
    print(f"   태그: search-improvement, korean-support, auto-project, token-optimization")
    print(f"   크기: {len(content)} 문자")

    return memory_id


if __name__ == "__main__":
    asyncio.run(save_session_summary())