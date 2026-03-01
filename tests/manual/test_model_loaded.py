#!/usr/bin/env python3
"""
실제로 어떤 모델이 로드되는지 확인
"""

import os

from app.core.config import Settings
from app.core.embeddings.service import EmbeddingService

# 환경변수 확인
print("=" * 60)
print("환경변수 확인")
print("=" * 60)
print(f"MEM_MESH_EMBEDDING_MODEL: {os.getenv('MEM_MESH_EMBEDDING_MODEL')}")
print(f"EMBEDDING_MODEL: {os.getenv('EMBEDDING_MODEL')}")

# 설정 확인
print("\n" + "=" * 60)
print("Settings 확인")
print("=" * 60)
settings = Settings()
print(f"settings.embedding_model: {settings.embedding_model}")

# EmbeddingService 확인
print("\n" + "=" * 60)
print("EmbeddingService 확인")
print("=" * 60)

# 1. 기본값으로 생성
service1 = EmbeddingService(preload=False)
print(f"EmbeddingService() -> model_name: {service1.model_name}")

# 2. 모델 로드
service1.load_model()
print(f"After load_model() -> model_name: {service1.model_name}")
print(f"Model dimension: {service1.dimension}")

# 3. 직접 모델 지정
service2 = EmbeddingService(
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    preload=False,
)
print(f"\nExplicit model -> model_name: {service2.model_name}")

# 임베딩 테스트
service2.load_model()
import numpy as np  # noqa: E402

test_pairs = [("토큰", "token"), ("최적화", "optimization")]

for kor, eng in test_pairs:
    emb_kor = service2.embed(kor)
    emb_eng = service2.embed(eng)

    def cosine_similarity(a, b):
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

    similarity = cosine_similarity(emb_kor, emb_eng)
    print(f"\n'{kor}' vs '{eng}' 유사도:")
    print("  영어 모델: Would be ~0.08")
    print(f"  다국어 모델: {similarity:.3f}")
