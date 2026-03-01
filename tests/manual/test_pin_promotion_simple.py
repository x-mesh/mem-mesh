#!/usr/bin/env python3
"""
Work Tracking - Pin 승격(Memory Promotion) 기능 단순화 테스트
"""

import asyncio
import os
import tempfile

from app.core.database.base import Database
from app.core.services.pin import PinService
from app.core.services.project import ProjectService
from app.core.services.session import SessionService


async def test_pin_promotion_simple():
    """Pin 승격 기능 단순화 테스트"""

    # 임시 데이터베이스 생성
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    try:
        # 데이터베이스 연결
        db = Database(db_path)
        await db.connect()

        # 서비스 생성
        project_service = ProjectService(db)
        session_service = SessionService(db, project_service)
        pin_service = PinService(db)

        print("1. 프로젝트 및 세션 생성:")
        project = await project_service.get_or_create_project("promotion-test-project")
        session = await session_service.get_or_create_active_session(
            "promotion-test-project", "test-user"
        )
        print(f"   프로젝트: {project.id}")
        print(f"   세션: {session.id}")

        print("\n2. 중요도가 높은 Pin 생성 (importance=4):")
        pin = await pin_service.create_pin(
            project_id="promotion-test-project",
            content="Critical security vulnerability needs to be addressed immediately",
            importance=4,
            tags=["security", "critical", "urgent"],
            user_id="test-user",
        )
        print(f"   생성된 Pin: {pin.id}")
        print(f"   내용: {pin.content}")
        print(f"   중요도: {pin.importance}")
        print(f"   상태: {pin.status}")

        print("\n3. Pin 완료 처리:")
        completed_pin = await pin_service.complete_pin(pin.id)
        print(f"   완료된 Pin 상태: {completed_pin.status}")

        print("\n4. 승격 제안 여부 확인:")
        should_promote = pin_service.should_suggest_promotion(completed_pin)
        print(f"   승격 제안 필요: {should_promote}")

        print("\n5. Pin 삭제 테스트 (승격 시 수행됨):")
        # 승격 기능을 직접 호출하지 않고, 삭제 기능만 테스트
        deletion_result = await pin_service.delete_pin(pin.id)
        print(f"   Pin 삭제 결과: {deletion_result}")

        print("\n6. 삭제 후 Pin 존재 여부 확인:")
        retrieved_pin = await pin_service.get_pin(pin.id)
        if retrieved_pin is None:
            print("   Pin이 성공적으로 삭제됨")
        else:
            print(f"   Pin 여전히 존재: {retrieved_pin.id}")

        # 정리
        await db.close()

        # 임시 파일 정리
        for ext in ["", "-wal", "-shm"]:
            path = db_path + ext
            if os.path.exists(path):
                os.unlink(path)

        print("\n승격 기능 단순화 테스트 완료!")

    except Exception as e:
        print(f"테스트 중 오류 발생: {e}")
        # 정리
        for ext in ["", "-wal", "-shm"]:
            path = db_path + ext
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    asyncio.run(test_pin_promotion_simple())
