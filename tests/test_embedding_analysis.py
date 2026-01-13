#!/usr/bin/env python3
"""
임베딩 벡터 분석 - threshold vs threshold1 vs understood
"""

import asyncio
import sys
import numpy as np
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from app.core.embeddings.service import EmbeddingService


async def analyze_embeddings():
    """임베딩 벡터 분석"""
    print("🔍 임베딩 벡터 분석: threshold vs threshold1 vs understood")
    
    # 임베딩 서비스 초기화
    embedding_service = EmbeddingService("intfloat/multilingual-e5-small", preload=True)
    
    # 테스트할 단어들
    test_words = [
        "threshold",
        "threshold1", 
        "threshold2",
        "thresh",
        "understood",
        "understand",
        "threshold_value",
        "search_threshold"
    ]
    
    print("\n📊 각 단어의 임베딩 벡터 생성 중...")
    embeddings = {}
    
    for word in test_words:
        embedding = embedding_service.embed(word)
        embeddings[word] = np.array(embedding)
        print(f"  {word}: {len(embedding)}차원 벡터")
    
    print("\n📈 코사인 유사도 매트릭스:")
    print("-" * 80)
    
    # 헤더 출력
    header = "단어".ljust(15)
    for word in test_words:
        header += word[:10].ljust(12)
    print(header)
    print("-" * 80)
    
    # 유사도 매트릭스 계산 및 출력
    for word1 in test_words:
        row = word1.ljust(15)
        for word2 in test_words:
            # 코사인 유사도 계산
            vec1 = embeddings[word1]
            vec2 = embeddings[word2]
            
            # 정규화
            vec1_norm = vec1 / np.linalg.norm(vec1)
            vec2_norm = vec2 / np.linalg.norm(vec2)
            
            # 코사인 유사도
            similarity = np.dot(vec1_norm, vec2_norm)
            
            row += f"{similarity:.4f}".ljust(12)
        print(row)
    
    print("\n🔍 특별 분석:")
    print("-" * 50)
    
    # threshold vs threshold1 유사도
    thresh_sim = np.dot(
        embeddings["threshold"] / np.linalg.norm(embeddings["threshold"]),
        embeddings["threshold1"] / np.linalg.norm(embeddings["threshold1"])
    )
    print(f"threshold ↔ threshold1 유사도: {thresh_sim:.6f}")
    
    # threshold vs understood 유사도
    understood_sim = np.dot(
        embeddings["threshold"] / np.linalg.norm(embeddings["threshold"]),
        embeddings["understood"] / np.linalg.norm(embeddings["understood"])
    )
    print(f"threshold ↔ understood 유사도: {understood_sim:.6f}")
    
    # threshold1 vs understood 유사도
    thresh1_understood_sim = np.dot(
        embeddings["threshold1"] / np.linalg.norm(embeddings["threshold1"]),
        embeddings["understood"] / np.linalg.norm(embeddings["understood"])
    )
    print(f"threshold1 ↔ understood 유사도: {thresh1_understood_sim:.6f}")
    
    print(f"\n💡 분석 결과:")
    if understood_sim > thresh_sim:
        print(f"  ❗ 'threshold'가 'understood'와 더 유사함! ({understood_sim:.6f} > {thresh_sim:.6f})")
        print(f"     이것이 검색 결과 이상 현상의 원인일 수 있습니다.")
    else:
        print(f"  ✅ 'threshold'가 'threshold1'과 더 유사함 ({thresh_sim:.6f} > {understood_sim:.6f})")
    
    # 벡터 거리 분석
    print(f"\n📏 유클리드 거리 분석:")
    thresh_thresh1_dist = np.linalg.norm(embeddings["threshold"] - embeddings["threshold1"])
    thresh_understood_dist = np.linalg.norm(embeddings["threshold"] - embeddings["understood"])
    
    print(f"  threshold ↔ threshold1 거리: {thresh_thresh1_dist:.6f}")
    print(f"  threshold ↔ understood 거리: {thresh_understood_dist:.6f}")
    
    if thresh_understood_dist < thresh_thresh1_dist:
        print(f"  ❗ 'threshold'가 'understood'와 더 가까움!")
    else:
        print(f"  ✅ 'threshold'가 'threshold1'과 더 가까움")


if __name__ == "__main__":
    asyncio.run(analyze_embeddings())