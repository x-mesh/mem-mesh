#!/usr/bin/env python3
"""
한국어 검색 문제와 해결책을 mem-mesh에 저장
"""

import asyncio
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.memory import MemoryService
from app.core.config import Settings


async def save_search_issue():
    """한국어 검색 문제와 해결책 저장"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(preload=False)
    memory_service = MemoryService(db, embedding_service)

    print("📝 한국어 검색 문제와 해결책을 mem-mesh에 저장합니다...")

    memory = {
        "content": """한국어 검색 품질 문제 진단 및 해결

        문제 현상:
        - "토큰"으로 검색 시 전혀 관련 없는 결과 출력
        - mem-mesh-optimization 프로젝트의 토큰 최적화 문서를 찾지 못함

        근본 원인:
        - 영어 전용 임베딩 모델 사용 (all-MiniLM-L6-v2)
        - 한국어 "토큰"과 영어 "token"의 벡터 유사도: 0.080 (거의 무관)
        - 한국어 콘텐츠에 영어 검색어 유사도: -0.145 (음수!)

        해결 방안:
        1. Query Expander 구현 (완료)
           - app/core/services/query_expander.py
           - 한국어→영어 자동 번역 사전 (300+ 용어)
           - "토큰" → "token tokenization tokenize 토큰 토큰화"

        2. 다국어 임베딩 모델 업그레이드 (권장)
           - sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
           - 50+ 언어 지원, 384 차원
           - upgrade_to_multilingual.py 스크립트 작성

        3. 검색 모드 자동 전환
           - 한국어 감지 시 text mode 사용
           - 벡터 검색 대신 텍스트 매칭

        테스트 결과:
        - Query Expansion 적용 후에도 개선 미미
        - 임베딩 모델 자체가 한국어를 이해 못함
        - 텍스트 모드에서는 정상 작동

        결론:
        다국어 모델로 전환이 필수적
        임시로는 Query Expander + 텍스트 모드 조합 사용""",
        "category": "bug",
        "project_id": "mem-mesh-search-issue",
        "source": "debugging",
        "tags": ["한국어", "검색", "임베딩", "버그", "해결책"]
    }

    try:
        result = await memory_service.create(**memory)
        print(f"✅ 한국어 검색 문제 분석 저장 완료: {result.id}")
    except Exception as e:
        print(f"❌ 저장 실패: {e}")


if __name__ == "__main__":
    asyncio.run(save_search_issue())