#!/usr/bin/env python3
"""
Q&A 쌍 검색 스크립트
저장된 질문-답변 쌍을 효율적으로 검색
"""

import asyncio
import json
import sys
import os
from typing import List, Dict, Any

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import Settings
from app.core.storage.direct import DirectStorageBackend
from app.core.schemas.requests import SearchParams

async def search_qa_pairs(query: str, limit: int = 5, project_id: str = "kiro-conversations"):
    """Q&A 쌍 검색"""
    
    settings = Settings()
    storage = DirectStorageBackend(settings.database_path)
    await storage.initialize()
    
    try:
        # qa-pair 태그로 필터링하여 검색
        params = SearchParams(
            query=query,
            project_id=project_id,
            limit=limit,
            recency_weight=0.1  # 최신성도 약간 고려
        )
        
        result = await storage.search_memories(params)
        
        print(f"🔍 '{query}' 검색 결과: {len(result.results)}개 발견\n")
        
        for i, memory in enumerate(result.results, 1):
            print(f"--- {i}. 메모리 ID: {memory.id} ---")
            print(f"유사도: {memory.similarity_score:.3f}")
            print(f"생성일: {memory.created_at}")
            print(f"카테고리: {memory.category}")
            
            # JSON 구조인지 확인
            try:
                qa_data = json.loads(memory.content)
                if qa_data.get("type") == "qa_pair":
                    print(f"대화 ID: {qa_data.get('conversation_id', 'N/A')}")
                    print(f"질문: {qa_data.get('question', 'N/A')}")
                    print(f"답변: {qa_data.get('answer', 'N/A')[:200]}...")
                else:
                    print(f"내용: {memory.content[:200]}...")
            except json.JSONDecodeError:
                print(f"내용: {memory.content[:200]}...")
            
            print()
        
        return result.results
        
    except Exception as e:
        print(f"❌ 검색 실패: {e}")
        return []
    
    finally:
        await storage.shutdown()

async def list_recent_conversations(limit: int = 10, project_id: str = "kiro-conversations"):
    """최근 대화 목록 조회"""
    
    settings = Settings()
    storage = DirectStorageBackend(settings.database_path)
    await storage.initialize()
    
    try:
        # qa-pair 태그로 필터링
        params = SearchParams(
            query="qa-pair",
            project_id=project_id,
            limit=limit,
            recency_weight=1.0  # 최신성 우선
        )
        
        result = await storage.search_memories(params)
        
        print(f"📋 최근 대화 {len(result.results)}개:\n")
        
        for i, memory in enumerate(result.results, 1):
            try:
                qa_data = json.loads(memory.content)
                if qa_data.get("type") == "qa_pair":
                    print(f"{i}. [{memory.created_at[:16]}] {qa_data.get('conversation_id', 'N/A')}")
                    print(f"   Q: {qa_data.get('question', 'N/A')[:80]}...")
                    print(f"   A: {qa_data.get('answer', 'N/A')[:80]}...")
                    print()
            except json.JSONDecodeError:
                continue
        
        return result.results
        
    except Exception as e:
        print(f"❌ 대화 목록 조회 실패: {e}")
        return []
    
    finally:
        await storage.shutdown()

def search_qa_pairs_sync(query: str, limit: int = 5):
    """동기 래퍼 함수"""
    return asyncio.run(search_qa_pairs(query, limit))

def list_recent_conversations_sync(limit: int = 10):
    """동기 래퍼 함수"""
    return asyncio.run(list_recent_conversations(limit))

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        if sys.argv[1] == "--list":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            list_recent_conversations_sync(limit)
        else:
            query = sys.argv[1]
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
            search_qa_pairs_sync(query, limit)
    else:
        print("사용법:")
        print("  python search_qa_pairs.py '검색어' [개수]")
        print("  python search_qa_pairs.py --list [개수]")