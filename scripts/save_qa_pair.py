#!/usr/bin/env python3
"""
Q&A 쌍 저장 스크립트
사용자 질문과 LLM 응답을 연결하여 mem-mesh에 저장
"""

import asyncio
import json
import sys
import os
import uuid
from datetime import datetime
from typing import Optional

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import Settings
from app.core.storage.direct import DirectStorageBackend
from app.core.schemas.requests import AddParams

async def save_conversation_pair(user_question: str, llm_response: str, project_id: str = "kiro-conversations"):
    """사용자 질문과 LLM 응답을 쌍으로 저장"""
    
    if not user_question.strip() or not llm_response.strip():
        print("빈 질문이나 응답은 저장하지 않습니다.")
        return
    
    # 설정 및 스토리지 초기화
    settings = Settings()
    storage = DirectStorageBackend(settings.database_path)
    await storage.initialize()
    
    try:
        # 대화 ID 생성
        conversation_id = f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
        
        # 방법 1: JSON 구조로 쌍 저장 (추천)
        qa_content = {
            "conversation_id": conversation_id,
            "question": user_question.strip(),
            "answer": llm_response.strip(),
            "timestamp": datetime.now().isoformat(),
            "type": "qa_pair"
        }
        
        # 질문에서 키워드 추출하여 태그 생성
        question_lower = user_question.lower()
        tags = ["qa-pair"]
        
        # 키워드 기반 태그 추가
        keyword_tags = {
            "검색": "search",
            "성능": "performance", 
            "최적화": "optimization",
            "버그": "bug",
            "에러": "error",
            "구현": "implementation",
            "설계": "design",
            "테스트": "test",
            "배포": "deployment",
            "설정": "configuration"
        }
        
        for keyword, tag in keyword_tags.items():
            if keyword in question_lower:
                tags.append(tag)
        
        # 카테고리 자동 분류
        category = "task"  # 기본값
        if any(word in question_lower for word in ["버그", "에러", "오류", "문제"]):
            category = "bug"
        elif any(word in question_lower for word in ["아이디어", "제안", "개선"]):
            category = "idea"
        elif any(word in question_lower for word in ["결정", "선택", "방향"]):
            category = "decision"
        
        # Q&A 쌍 저장
        params = AddParams(
            content=json.dumps(qa_content, ensure_ascii=False, indent=2),
            project_id=project_id,
            category=category,
            source="kiro-qa-hook",
            tags=tags
        )
        
        result = await storage.add_memory(params)
        print(f"✅ Q&A 쌍 저장 완료: {result.id}")
        print(f"   대화 ID: {conversation_id}")
        print(f"   카테고리: {category}")
        print(f"   태그: {', '.join(tags)}")
        
        # 방법 2: 개별 저장 (선택사항)
        # 질문과 답변을 각각 저장하되 conversation_id로 연결
        if os.environ.get("SAVE_INDIVIDUAL_QA", "false").lower() == "true":
            # 질문 저장
            question_params = AddParams(
                content=f"Q: {user_question.strip()}",
                project_id=project_id,
                category=category,
                source="kiro-qa-hook",
                tags=tags + ["question"]
            )
            
            question_result = await storage.add_memory(question_params)
            
            # 답변 저장 (질문 ID 참조)
            answer_params = AddParams(
                content=f"A: {llm_response.strip()}\n\n[관련 질문 ID: {question_result.id}]",
                project_id=project_id,
                category=category,
                source="kiro-qa-hook", 
                tags=tags + ["answer"]
            )
            
            answer_result = await storage.add_memory(answer_params)
            print(f"   개별 저장 - 질문: {question_result.id}, 답변: {answer_result.id}")
        
    except Exception as e:
        print(f"❌ Q&A 쌍 저장 실패: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await storage.shutdown()

def save_conversation_pair_sync(user_question: str, llm_response: str):
    """동기 래퍼 함수"""
    asyncio.run(save_conversation_pair(user_question, llm_response))

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        user_q = sys.argv[1]
        llm_resp = sys.argv[2]
        save_conversation_pair_sync(user_q, llm_resp)
    else:
        print("사용법: python save_qa_pair.py '사용자 질문' 'LLM 응답'")