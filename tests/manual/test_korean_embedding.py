#!/usr/bin/env python3
"""
한국어/영어 임베딩 문제 진단
"""

import asyncio
import numpy as np
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.search import SearchService
from app.core.config import Settings


async def diagnose_korean_embedding():
    """한국어/영어 임베딩 문제 진단"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(preload=False)
    embedding_service.load_model()

    print("="*60)
    print("한국어/영어 임베딩 진단")
    print("="*60)

    # 테스트할 단어 쌍
    test_pairs = [
        ("토큰", "token"),
        ("최적화", "optimization"),
        ("검색", "search"),
        ("품질", "quality"),
        ("캐시", "cache"),
        ("메모리", "memory")
    ]

    print("\n1️⃣ 임베딩 벡터 비교")
    print("-"*40)

    def cosine_similarity(a, b):
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

    for kor, eng in test_pairs:
        emb_kor = embedding_service.embed(kor)
        emb_eng = embedding_service.embed(eng)
        similarity = cosine_similarity(emb_kor, emb_eng)
        print(f"{kor:6} vs {eng:12} = 유사도: {similarity:.3f}")

    # 실제 저장된 내용과 비교
    print("\n2️⃣ 실제 저장된 내용과의 유사도")
    print("-"*40)

    # mem-mesh-optimization 프로젝트에서 토큰 관련 내용 가져오기
    cursor = await db.execute(
        """
        SELECT content, embedding
        FROM memories
        WHERE project_id = 'mem-mesh-optimization'
        AND content LIKE '%Token Optimization%'
        LIMIT 1
        """
    )
    row = cursor.fetchone()

    if row:
        stored_content = row[0]
        stored_embedding = embedding_service.from_bytes(row[1])

        print(f"저장된 내용 (일부): {stored_content[:100]}...")

        # 여러 검색어로 테스트
        test_queries = ["토큰", "token", "토큰 최적화", "token optimization"]

        for query in test_queries:
            query_embedding = embedding_service.embed(query)
            similarity = cosine_similarity(query_embedding, stored_embedding)
            print(f"  '{query}' 유사도: {similarity:.3f}")

    # 한국어 내용과 비교
    cursor = await db.execute(
        """
        SELECT content, embedding
        FROM memories
        WHERE project_id = 'mem-mesh-thread-summary-kr'
        AND content LIKE '%토큰%'
        LIMIT 1
        """
    )
    row = cursor.fetchone()

    if row:
        print(f"\n한국어 저장 내용 (일부): {row[0][:100]}...")
        stored_embedding = embedding_service.from_bytes(row[1])

        for query in test_queries:
            query_embedding = embedding_service.embed(query)
            similarity = cosine_similarity(query_embedding, stored_embedding)
            print(f"  '{query}' 유사도: {similarity:.3f}")

    # 모델 정보 확인
    print("\n3️⃣ 임베딩 모델 정보")
    print("-"*40)
    print(f"모델 이름: {embedding_service.model_name}")
    print(f"차원: {embedding_service.dimension}")

    # 다국어 모델 추천
    print("\n💡 해결 방안")
    print("-"*40)
    print("현재 모델이 영어에 최적화되어 있어 한국어 검색 성능이 떨어집니다.")
    print("\n추천 다국어 모델:")
    print("1. sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
    print("   - 50+ 언어 지원, 768 차원")
    print("2. sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    print("   - 50+ 언어 지원, 384 차원, 더 빠름")
    print("3. intfloat/multilingual-e5-large")
    print("   - 최신 모델, 높은 성능")

    # 검색어 확장 제안
    print("\n또 다른 해결책: 검색어 확장")
    print("-"*40)
    print("검색 시 한국어와 영어를 모두 사용:")

    search_service = SearchService(db, embedding_service)

    # 한국어만 검색
    kor_results = await search_service.search("토큰 최적화", limit=3, search_mode='hybrid')
    print(f"\n'토큰 최적화' 검색 결과: {len(kor_results.results)}개")
    if kor_results.results:
        print(f"  Top1: {kor_results.results[0].content[:80]}...")

    # 영어만 검색
    eng_results = await search_service.search("token optimization", limit=3, search_mode='hybrid')
    print(f"\n'token optimization' 검색 결과: {len(eng_results.results)}개")
    if eng_results.results:
        print(f"  Top1: {eng_results.results[0].content[:80]}...")

    # 혼합 검색 (OR 조건으로)
    mixed_results = await search_service.search("토큰 token 최적화 optimization", limit=3, search_mode='hybrid')
    print(f"\n'토큰 token 최적화 optimization' 검색 결과: {len(mixed_results.results)}개")
    if mixed_results.results:
        print(f"  Top1: {mixed_results.results[0].content[:80]}...")


if __name__ == "__main__":
    asyncio.run(diagnose_korean_embedding())