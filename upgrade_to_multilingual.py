#!/usr/bin/env python3
"""
다국어 임베딩 모델로 업그레이드
한국어/영어 모두 지원하는 모델로 전환
"""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.memory import MemoryService
from app.core.config import Settings
from sentence_transformers import SentenceTransformer
import numpy as np


async def upgrade_embeddings():
    """모든 메모리의 임베딩을 다국어 모델로 재생성"""

    print("="*60)
    print("🌐 다국어 임베딩 모델 업그레이드")
    print("="*60)

    # 다국어 모델 옵션
    models = {
        "1": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",  # 384 차원, 빠름
        "2": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",   # 768 차원, 정확
        "3": "sentence-transformers/distiluse-base-multilingual-cased-v2"    # 512 차원, 균형
    }

    print("\n사용할 다국어 모델 선택:")
    for key, model in models.items():
        print(f"{key}. {model}")

    choice = input("\n선택 (1-3, Enter=1): ").strip() or "1"
    new_model_name = models.get(choice, models["1"])

    print(f"\n✅ 선택한 모델: {new_model_name}")

    # 모델 다운로드 및 테스트
    print("\n📥 모델 다운로드 중...")
    new_model = SentenceTransformer(new_model_name)
    new_dimension = new_model.get_sentence_embedding_dimension()
    print(f"   차원: {new_dimension}")

    # 한국어/영어 유사도 테스트
    print("\n🧪 다국어 성능 테스트:")
    test_pairs = [
        ("토큰", "token"),
        ("최적화", "optimization"),
        ("검색", "search")
    ]

    def cosine_similarity(a, b):
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

    for kor, eng in test_pairs:
        emb_kor = new_model.encode(kor)
        emb_eng = new_model.encode(eng)
        similarity = cosine_similarity(emb_kor, emb_eng)
        print(f"  {kor} vs {eng}: {similarity:.3f}")

    # 실제 업그레이드 확인
    proceed = input("\n⚠️ 모든 메모리의 임베딩을 재생성합니다. 계속하시겠습니까? (y/N): ")
    if proceed.lower() != 'y':
        print("취소되었습니다.")
        return

    # 데이터베이스 연결
    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    # 먼저 설정 업데이트
    print("\n📝 설정 업데이트 중...")

    # .env 파일 업데이트
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path, 'r') as f:
            lines = f.readlines()

        # EMBEDDING_MODEL 라인 찾아서 업데이트
        updated = False
        for i, line in enumerate(lines):
            if line.startswith("EMBEDDING_MODEL="):
                lines[i] = f"EMBEDDING_MODEL={new_model_name}\n"
                updated = True
                break

        if not updated:
            lines.append(f"\nEMBEDDING_MODEL={new_model_name}\n")

        with open(env_path, 'w') as f:
            f.writelines(lines)

        print(f"✅ .env 파일 업데이트 완료")

    # 모든 메모리 가져오기
    cursor = await db.execute("SELECT COUNT(*) FROM memories")
    total_count = cursor.fetchone()[0]
    print(f"\n🔄 재생성할 메모리: {total_count}개")

    # 배치로 처리
    batch_size = 100
    updated = 0

    cursor = await db.execute("SELECT id, content FROM memories")
    memories = cursor.fetchall()

    print("\n⏳ 임베딩 재생성 중...")
    for i in range(0, len(memories), batch_size):
        batch = memories[i:i+batch_size]
        contents = [mem[1] for mem in batch]
        ids = [mem[0] for mem in batch]

        # 배치 임베딩 생성
        embeddings = new_model.encode(contents, convert_to_tensor=False)

        # 업데이트
        for mem_id, embedding in zip(ids, embeddings):
            # bytes로 변환
            import struct
            embedding_bytes = struct.pack(f'{len(embedding)}f', *embedding)

            await db.execute(
                "UPDATE memories SET embedding = ? WHERE id = ?",
                (embedding_bytes, mem_id)
            )

        updated += len(batch)
        print(f"   {updated}/{total_count} 완료...")

    # embedding_metadata 업데이트
    await db.execute(
        """
        INSERT OR REPLACE INTO embedding_metadata (key, value, updated_at)
        VALUES ('model', ?, datetime('now'))
        """,
        (new_model_name,)
    )

    await db.execute(
        """
        INSERT OR REPLACE INTO embedding_metadata (key, value, updated_at)
        VALUES ('dimension', ?, datetime('now'))
        """,
        (str(new_dimension),)
    )

    print(f"\n✅ 완료! {updated}개 메모리의 임베딩이 업데이트되었습니다.")
    print(f"🌐 새 모델: {new_model_name} (차원: {new_dimension})")

    # 검증
    print("\n🔍 검증 테스트:")
    from app.core.services.search import SearchService

    # 새 임베딩 서비스 생성
    new_embedding_service = EmbeddingService(preload=False)
    new_embedding_service.model_name = new_model_name
    new_embedding_service.model = new_model
    new_embedding_service.dimension = new_dimension

    search_service = SearchService(db, new_embedding_service)

    test_queries = ["토큰", "token", "토큰 최적화"]
    for query in test_queries:
        results = await search_service.search(query, limit=2, search_mode='hybrid')
        print(f"\n'{query}' 검색 결과:")
        for r in results.results:
            print(f"  - [{r.category}] {r.content[:60]}...")
            print(f"    점수: {r.similarity_score:.3f}, 프로젝트: {r.project_id}")


if __name__ == "__main__":
    try:
        asyncio.run(upgrade_embeddings())
    except KeyboardInterrupt:
        print("\n취소되었습니다.")
    except Exception as e:
        print(f"\n❌ 오류: {e}")
        import traceback
        traceback.print_exc()