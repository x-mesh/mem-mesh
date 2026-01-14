#!/usr/bin/env python3
"""
Work Tracking 테스트 결과를 메모리에 저장
"""

import asyncio
import os
from datetime import datetime, timezone

from app.core.database.base import Database
from app.core.services.memory import MemoryService
from app.core.embeddings.service import EmbeddingService
from app.core.config import get_settings


async def save_work_tracking_test_to_memory():
    """Work Tracking 테스트 결과를 메모리에 저장"""
    
    # 실제 데이터베이스 경로
    db_path = "./data/memories.db"

    # 설정 생성
    from app.core.config import create_settings
    settings = create_settings(database_path=db_path)

    # 데이터베이스 연결
    db = Database(db_path)
    await db.connect()

    # EmbeddingService 및 MemoryService 생성
    # EmbeddingService는 설정 객체 대신 모델 이름을 직접 받아야 함
    embedding_service = EmbeddingService(model_name=settings.embedding_model)
    memory_service = MemoryService(db, embedding_service)

    # 저장할 내용
    content = """
Work Tracking 기능 실제 DB 테스트 결과:

1. 프로젝트 생성:
   - real-db-test-project라는 프로젝트가 projects 테이블에 성공적으로 생성됨

2. 세션 생성 및 관리:
   - sessions 테이블에 세션이 생성되었으며, 활성 상태에서 시작하여 테스트 종료 시 완료 상태로 변경됨
   - 세션 요약도 함께 저장됨

3. 핀(Pin) 생성 및 상태 관리:
   - pins 테이블에 두 개의 핀이 생성됨
   - 하나는 중요도 4로 완료 상태(completed)로 변경됨
   - 다른 하나는 중요도 5로 열린 상태(open)로 유지됨
   - 태그도 함께 저장됨

4. 리드 타임 계산:
   - 완료된 핀에 대해 리드 타임이 계산되어 저장됨

5. 승격 제안 기능:
   - 중요도가 4 이상이고 완료된 핀에 대해 승격 제안이 적절히 판단됨

이 모든 데이터가 실제 ./data/memories.db SQLite 데이터베이스에 저장되어 있으며, 영구적으로 유지됩니다.
    """

    print("Work Tracking 테스트 결과를 메모리에 저장 중...")

    # 메모리 생성
    memory_response = await memory_service.create(
        content=content,
        project_id="work-tracking-tests",  # 관련 프로젝트 ID
        category="testing",  # 카테고리
        source="work_tracking_test",  # 소스
        tags=["work-tracking", "testing", "pin", "session", "project", "real-db"],  # 태그
    )

    print(f"메모리가 성공적으로 저장됨:")
    print(f"  ID: {memory_response.id}")
    print(f"  상태: {memory_response.status}")
    print(f"  생성 시간: {memory_response.created_at}")

    # 저장된 메모리 조회 확인
    # MemoryService.create는 AddResponse를 반환하므로, 실제 메모리 객체를 가져오기 위해 get 메서드 사용
    retrieved_memory = await memory_service.get(memory_response.id)
    print(f"\n저장된 메모리 내용 확인:")
    print(f"  ID: {retrieved_memory.id}")
    print(f"  프로젝트: {retrieved_memory.project_id}")
    print(f"  카테고리: {retrieved_memory.category}")
    print(f"  소스: {retrieved_memory.source}")
    print(f"  태그: {retrieved_memory.tags}")
    print(f"  길이: {len(retrieved_memory.content)} 문자")
    print(f"  미리보기: {retrieved_memory.content[:100]}...")

    # 정리
    await db.close()

    print("\n메모리 저장 테스트 완료!")


if __name__ == "__main__":
    asyncio.run(save_work_tracking_test_to_memory())