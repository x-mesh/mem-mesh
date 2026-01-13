#!/usr/bin/env python3
"""
대화 연결성 분석 도구
Q&A 쌍들 간의 관계와 패턴을 분석
"""

import asyncio
import json
import sys
import os
from collections import defaultdict, Counter
from datetime import datetime
from typing import List, Dict, Any

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import Settings
from app.core.storage.direct import DirectStorageBackend
from app.core.schemas.requests import SearchParams

async def analyze_conversation_patterns(project_id: str = "kiro-conversations"):
    """대화 패턴 분석"""
    
    settings = Settings()
    storage = DirectStorageBackend(settings.database_path)
    await storage.initialize()
    
    try:
        # 모든 Q&A 쌍 조회
        params = SearchParams(
            query="qa-pair",
            project_id=project_id,
            limit=20,  # 최대 20개
            recency_weight=0.0
        )
        
        result = await storage.search_memories(params)
        
        conversations = []
        question_keywords = Counter()
        answer_keywords = Counter()
        categories = Counter()
        daily_counts = defaultdict(int)
        
        print(f"📊 대화 패턴 분석 (총 {len(result.results)}개 Q&A 쌍)\n")
        
        for memory in result.results:
            try:
                qa_data = json.loads(memory.content)
                if qa_data.get("type") == "qa_pair":
                    conversations.append({
                        "id": memory.id,
                        "conversation_id": qa_data.get("conversation_id"),
                        "question": qa_data.get("question", ""),
                        "answer": qa_data.get("answer", ""),
                        "timestamp": qa_data.get("timestamp"),
                        "category": memory.category,
                        "created_at": memory.created_at
                    })
                    
                    # 키워드 추출
                    question = qa_data.get("question", "").lower()
                    answer = qa_data.get("answer", "").lower()
                    
                    # 간단한 키워드 추출 (공백 기준)
                    q_words = [w for w in question.split() if len(w) > 2]
                    a_words = [w for w in answer.split() if len(w) > 2]
                    
                    question_keywords.update(q_words[:5])  # 상위 5개만
                    answer_keywords.update(a_words[:5])
                    
                    categories[memory.category] += 1
                    
                    # 일별 통계
                    date = memory.created_at[:10]
                    daily_counts[date] += 1
                    
            except json.JSONDecodeError:
                continue
        
        # 분석 결과 출력
        print("🏷️ 카테고리별 분포:")
        for category, count in categories.most_common():
            print(f"  {category}: {count}개")
        
        print(f"\n📅 일별 대화 수:")
        for date, count in sorted(daily_counts.items()):
            print(f"  {date}: {count}개")
        
        print(f"\n❓ 자주 나오는 질문 키워드:")
        for word, count in question_keywords.most_common(10):
            print(f"  {word}: {count}회")
        
        print(f"\n💡 자주 나오는 답변 키워드:")
        for word, count in answer_keywords.most_common(10):
            print(f"  {word}: {count}회")
        
        # 최근 대화 트렌드
        recent_conversations = sorted(conversations, key=lambda x: x["created_at"], reverse=True)[:5]
        print(f"\n🔥 최근 대화 주제:")
        for i, conv in enumerate(recent_conversations, 1):
            print(f"  {i}. [{conv['created_at'][:16]}] {conv['question'][:60]}...")
        
        return {
            "total_conversations": len(conversations),
            "categories": dict(categories),
            "daily_counts": dict(daily_counts),
            "top_question_keywords": dict(question_keywords.most_common(10)),
            "top_answer_keywords": dict(answer_keywords.most_common(10))
        }
        
    except Exception as e:
        print(f"❌ 분석 실패: {e}")
        return {}
    
    finally:
        await storage.shutdown()

async def find_related_conversations(query: str, project_id: str = "kiro-conversations"):
    """관련 대화 찾기"""
    
    settings = Settings()
    storage = DirectStorageBackend(settings.database_path)
    await storage.initialize()
    
    try:
        params = SearchParams(
            query=query,
            project_id=project_id,
            limit=10
        )
        
        result = await storage.search_memories(params)
        
        print(f"🔗 '{query}'와 관련된 대화들:\n")
        
        related_conversations = []
        for memory in result.results:
            try:
                qa_data = json.loads(memory.content)
                if qa_data.get("type") == "qa_pair":
                    related_conversations.append({
                        "similarity": memory.similarity_score,
                        "question": qa_data.get("question", ""),
                        "answer": qa_data.get("answer", ""),
                        "conversation_id": qa_data.get("conversation_id")
                    })
            except json.JSONDecodeError:
                continue
        
        for i, conv in enumerate(related_conversations, 1):
            print(f"{i}. 유사도: {conv['similarity']:.3f}")
            print(f"   Q: {conv['question']}")
            print(f"   A: {conv['answer'][:100]}...")
            print(f"   대화 ID: {conv['conversation_id']}")
            print()
        
        return related_conversations
        
    except Exception as e:
        print(f"❌ 관련 대화 검색 실패: {e}")
        return []
    
    finally:
        await storage.shutdown()

def analyze_conversation_patterns_sync():
    """동기 래퍼 함수"""
    return asyncio.run(analyze_conversation_patterns())

def find_related_conversations_sync(query: str):
    """동기 래퍼 함수"""
    return asyncio.run(find_related_conversations(query))

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        if sys.argv[1] == "--analyze":
            analyze_conversation_patterns_sync()
        elif sys.argv[1] == "--related":
            if len(sys.argv) >= 3:
                find_related_conversations_sync(sys.argv[2])
            else:
                print("관련 대화 검색할 키워드를 입력하세요.")
    else:
        print("사용법:")
        print("  python analyze_conversations.py --analyze")
        print("  python analyze_conversations.py --related '키워드'")