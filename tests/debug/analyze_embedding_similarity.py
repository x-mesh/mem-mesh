#!/usr/bin/env python3
"""
threshold와 understood의 임베딩 유사도가 높은 이유 분석

1. 토큰화 분석
2. 의미적 유사성 분석
3. 벡터 공간 시각화
4. 다양한 단어들과의 비교
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

from app.core.embeddings.service import EmbeddingService


def analyze_tokenization():
    """토큰화 분석"""
    print("=" * 80)
    print("1️⃣ 토큰화 분석")
    print("=" * 80)

    # SentenceTransformer의 토크나이저 확인
    embedding_service = EmbeddingService("intfloat/multilingual-e5-small", preload=True)

    # 토크나이저 접근
    tokenizer = embedding_service.model.tokenizer

    test_words = ["threshold", "threshold1", "understood", "understand", "thresh"]

    print("\n각 단어의 토큰화 결과:")
    print("-" * 60)

    for word in test_words:
        tokens = tokenizer.tokenize(word)
        token_ids = tokenizer.encode(word, add_special_tokens=False)
        print(f"  '{word}':")
        print(f"    토큰: {tokens}")
        print(f"    토큰 ID: {token_ids}")
        print()

    return embedding_service


def analyze_semantic_similarity(embedding_service):
    """의미적 유사성 분석"""
    print("=" * 80)
    print("2️⃣ 의미적 유사성 분석")
    print("=" * 80)

    # 다양한 카테고리의 단어들
    word_categories = {
        "기술 용어": [
            "threshold",
            "threshold1",
            "parameter",
            "variable",
            "config",
            "setting",
        ],
        "확인/이해": [
            "understood",
            "understand",
            "ok",
            "yes",
            "confirmed",
            "acknowledged",
        ],
        "숫자 관련": ["threshold1", "value1", "count1", "index1", "number1"],
        "임계값 관련": [
            "threshold",
            "limit",
            "boundary",
            "cutoff",
            "maximum",
            "minimum",
        ],
        "무작위": ["apple", "banana", "car", "house", "python", "javascript"],
    }

    # threshold와 각 단어의 유사도 계산
    threshold_embedding = np.array(embedding_service.embed("threshold"))
    threshold_norm = threshold_embedding / np.linalg.norm(threshold_embedding)

    print("\n'threshold'와 각 단어의 코사인 유사도:")
    print("-" * 60)

    all_similarities = []

    for category, words in word_categories.items():
        print(f"\n📂 {category}:")
        for word in words:
            word_embedding = np.array(embedding_service.embed(word))
            word_norm = word_embedding / np.linalg.norm(word_embedding)
            similarity = np.dot(threshold_norm, word_norm)
            all_similarities.append((word, similarity, category))
            print(f"    {word:<20} : {similarity:.4f}")

    # 유사도 순으로 정렬
    print("\n📊 유사도 순위 (높은 순):")
    print("-" * 60)
    all_similarities.sort(key=lambda x: x[1], reverse=True)
    for i, (word, sim, cat) in enumerate(all_similarities, 1):
        print(f"  {i:2d}. {word:<20} : {sim:.4f} ({cat})")


def analyze_vector_components(embedding_service):
    """벡터 성분 분석"""
    print("\n" + "=" * 80)
    print("3️⃣ 벡터 성분 분석")
    print("=" * 80)

    words = ["threshold", "understood", "threshold1", "limit", "ok"]
    embeddings = {}

    for word in words:
        embeddings[word] = np.array(embedding_service.embed(word))

    # 벡터 통계
    print("\n각 벡터의 통계:")
    print("-" * 60)
    for word, emb in embeddings.items():
        print(f"  '{word}':")
        print(f"    평균: {np.mean(emb):.6f}")
        print(f"    표준편차: {np.std(emb):.6f}")
        print(f"    최대값: {np.max(emb):.6f}")
        print(f"    최소값: {np.min(emb):.6f}")
        print(f"    L2 노름: {np.linalg.norm(emb):.6f}")
        print()

    # 벡터 차이 분석
    print("\n벡터 차이 분석:")
    print("-" * 60)

    thresh_emb = embeddings["threshold"]
    understood_emb = embeddings["understood"]
    thresh1_emb = embeddings["threshold1"]

    # 차이 벡터
    diff_understood = thresh_emb - understood_emb
    diff_thresh1 = thresh_emb - thresh1_emb

    print("  threshold - understood:")
    print(f"    L2 거리: {np.linalg.norm(diff_understood):.6f}")
    print(f"    평균 차이: {np.mean(np.abs(diff_understood)):.6f}")
    print(f"    최대 차이: {np.max(np.abs(diff_understood)):.6f}")

    print("\n  threshold - threshold1:")
    print(f"    L2 거리: {np.linalg.norm(diff_thresh1):.6f}")
    print(f"    평균 차이: {np.mean(np.abs(diff_thresh1)):.6f}")
    print(f"    최대 차이: {np.max(np.abs(diff_thresh1)):.6f}")

    # 가장 큰 차이가 나는 차원 분석
    print("\n가장 큰 차이가 나는 차원 (threshold vs understood):")
    top_diff_indices = np.argsort(np.abs(diff_understood))[-10:][::-1]
    for idx in top_diff_indices:
        print(
            f"    차원 {idx}: threshold={thresh_emb[idx]:.4f}, understood={understood_emb[idx]:.4f}, 차이={diff_understood[idx]:.4f}"
        )


def analyze_sentence_context(embedding_service):
    """문장 컨텍스트 분석"""
    print("\n" + "=" * 80)
    print("4️⃣ 문장 컨텍스트 분석")
    print("=" * 80)

    # 다양한 문장에서의 임베딩 비교
    sentences = {
        "threshold_tech": "The threshold value is set to 0.5",
        "threshold_simple": "threshold",
        "understood_response": "understood",
        "understood_sentence": "I understood the problem",
        "threshold1_code": "threshold1 = 0.5",
        "limit_tech": "The limit is reached",
        "ok_response": "ok",
    }

    print("\n각 문장의 임베딩과 'threshold'와의 유사도:")
    print("-" * 60)

    threshold_emb = np.array(embedding_service.embed("threshold"))
    threshold_norm = threshold_emb / np.linalg.norm(threshold_emb)

    for name, sentence in sentences.items():
        sent_emb = np.array(embedding_service.embed(sentence))
        sent_norm = sent_emb / np.linalg.norm(sent_emb)
        similarity = np.dot(threshold_norm, sent_norm)
        print(f"  {name:<25}: {similarity:.4f} - '{sentence}'")


def analyze_model_comparison():
    """다른 모델과의 비교"""
    print("\n" + "=" * 80)
    print("5️⃣ 다른 임베딩 모델과의 비교")
    print("=" * 80)

    models = [
        "intfloat/multilingual-e5-small",
        "all-MiniLM-L6-v2",
        "paraphrase-MiniLM-L6-v2",
    ]

    words = ["threshold", "understood", "threshold1", "limit"]

    print("\n각 모델에서 'threshold'와 다른 단어들의 유사도:")
    print("-" * 60)

    for model_name in models:
        print(f"\n🔧 모델: {model_name}")
        try:
            service = EmbeddingService(model_name, preload=True)

            threshold_emb = np.array(service.embed("threshold"))
            threshold_norm = threshold_emb / np.linalg.norm(threshold_emb)

            for word in words:
                if word == "threshold":
                    continue
                word_emb = np.array(service.embed(word))
                word_norm = word_emb / np.linalg.norm(word_emb)
                similarity = np.dot(threshold_norm, word_norm)
                print(f"    threshold ↔ {word:<15}: {similarity:.4f}")
        except Exception as e:
            print(f"    오류: {e}")


def main():
    print("🔬 threshold와 understood의 임베딩 유사도 분석")
    print("=" * 80)

    # 1. 토큰화 분석
    embedding_service = analyze_tokenization()

    # 2. 의미적 유사성 분석
    analyze_semantic_similarity(embedding_service)

    # 3. 벡터 성분 분석
    analyze_vector_components(embedding_service)

    # 4. 문장 컨텍스트 분석
    analyze_sentence_context(embedding_service)

    # 5. 다른 모델과의 비교
    analyze_model_comparison()

    print("\n" + "=" * 80)
    print("📝 분석 결론")
    print("=" * 80)
    print("""
    1. 토큰화: 두 단어가 어떻게 서브워드로 분해되는지 확인
    2. 의미적 유사성: 임베딩 모델이 학습한 의미 공간에서의 위치
    3. 벡터 성분: 실제 벡터 값의 차이 분석
    4. 문장 컨텍스트: 단독 단어 vs 문장에서의 임베딩 차이
    5. 모델 비교: 다른 모델에서도 동일한 패턴이 나타나는지 확인
    """)


if __name__ == "__main__":
    main()
