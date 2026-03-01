#!/usr/bin/env python3
"""
벡터 검색 디버깅 - 실제 데이터베이스 검색 과정 분석
"""

import asyncio
import sys
from pathlib import Path

import numpy as np

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService


async def debug_vector_search():
    """벡터 검색 디버깅"""
    print("🔍 벡터 검색 디버깅 - threshold vs threshold1")

    # 데이터베이스 연결
    db = Database("data/memories.db")
    await db.connect()

    # 임베딩 서비스 초기화
    embedding_service = EmbeddingService("intfloat/multilingual-e5-small", preload=True)

    try:
        # 1. 검색할 단어들의 임베딩 생성
        queries = ["threshold", "threshold1", "understood"]

        for query in queries:
            print(f"\n{'='*80}")
            print(f"🔍 검색어: '{query}'")
            print(f"{'='*80}")

            # 임베딩 생성
            query_embedding_list = embedding_service.embed(query)
            query_embedding = embedding_service.to_bytes(query_embedding_list)

            print(f"임베딩 차원: {len(query_embedding_list)}")
            print(f"임베딩 바이트 크기: {len(query_embedding)}")

            # 벡터 검색 실행 (상위 10개)
            raw_results = await db.vector_search(
                embedding=query_embedding, limit=10, filters=None
            )

            print(f"검색 결과: {len(raw_results)}개")

            if raw_results:
                print("\n상위 결과들:")
                for i, row in enumerate(raw_results, 1):
                    content = (
                        row["content"][:50] + "..."
                        if len(row["content"]) > 50
                        else row["content"]
                    )
                    distance = row["distance"] if "distance" in row.keys() else "N/A"
                    print(f"  {i}. [{row['category']}] {content}")
                    print(f"     거리: {distance}, ID: {row['id'][:8]}...")

                    # 첫 번째 결과의 임베딩과 비교
                    if i == 1:
                        # 해당 메모리의 실제 임베딩 가져오기
                        memory_embedding_row = await db.fetchone(
                            "SELECT embedding FROM memories WHERE id = ?", (row["id"],)
                        )

                        if memory_embedding_row:
                            memory_embedding_bytes = memory_embedding_row["embedding"]
                            memory_embedding_array = np.frombuffer(
                                memory_embedding_bytes, dtype=np.float32
                            )

                            # 코사인 유사도 직접 계산
                            query_array = np.array(
                                query_embedding_list, dtype=np.float32
                            )

                            # 정규화
                            query_norm = query_array / np.linalg.norm(query_array)
                            memory_norm = memory_embedding_array / np.linalg.norm(
                                memory_embedding_array
                            )

                            # 코사인 유사도
                            cosine_sim = np.dot(query_norm, memory_norm)

                            print(f"     직접 계산한 코사인 유사도: {cosine_sim:.6f}")
                            print(f"     sqlite-vec 거리와 비교: {distance}")
            else:
                print("검색 결과 없음")

        # 2. "understood" 메모리들의 임베딩 분석
        print(f"\n{'='*80}")
        print("🔍 'understood' 메모리들의 임베딩 분석")
        print(f"{'='*80}")

        understood_memories = await db.fetchall(
            "SELECT id, content, embedding FROM memories WHERE content = 'understood' LIMIT 3"
        )

        if understood_memories:
            threshold_embedding = np.array(
                embedding_service.embed("threshold"), dtype=np.float32
            )
            threshold1_embedding = np.array(
                embedding_service.embed("threshold1"), dtype=np.float32
            )

            print(f"발견된 'understood' 메모리: {len(understood_memories)}개")

            for i, memory in enumerate(understood_memories, 1):
                memory_embedding = np.frombuffer(memory["embedding"], dtype=np.float32)

                # 정규화
                threshold_norm = threshold_embedding / np.linalg.norm(
                    threshold_embedding
                )
                threshold1_norm = threshold1_embedding / np.linalg.norm(
                    threshold1_embedding
                )
                memory_norm = memory_embedding / np.linalg.norm(memory_embedding)

                # 유사도 계산
                thresh_sim = np.dot(threshold_norm, memory_norm)
                thresh1_sim = np.dot(threshold1_norm, memory_norm)

                print(f"\n  {i}. 메모리 ID: {memory['id'][:8]}...")
                print(f"     'threshold' 유사도: {thresh_sim:.6f}")
                print(f"     'threshold1' 유사도: {thresh1_sim:.6f}")
                print(f"     차이: {thresh_sim - thresh1_sim:.6f}")

        # 3. 벡터 테이블 상태 확인
        print(f"\n{'='*80}")
        print("🔍 벡터 테이블 상태 확인")
        print(f"{'='*80}")

        # 벡터 테이블 존재 확인
        vector_table_exists = await db.fetchone("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='memory_embeddings'
        """)

        if vector_table_exists:
            print("✅ memory_embeddings 테이블 존재")

            # 벡터 테이블 레코드 수
            vector_count = await db.fetchone(
                "SELECT COUNT(*) as count FROM memory_embeddings"
            )
            print(f"벡터 테이블 레코드 수: {vector_count['count']}")

            # 일반 테이블 레코드 수
            memory_count = await db.fetchone("SELECT COUNT(*) as count FROM memories")
            print(f"일반 테이블 레코드 수: {memory_count['count']}")

            if vector_count["count"] != memory_count["count"]:
                print("⚠️ 벡터 테이블과 일반 테이블의 레코드 수가 다름!")
        else:
            print("❌ memory_embeddings 테이블이 존재하지 않음")

    except Exception as e:
        print(f"❌ 디버깅 실패: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(debug_vector_search())
