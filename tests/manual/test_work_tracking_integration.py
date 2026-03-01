#!/usr/bin/env python3
"""
Work Tracking 기능 통합 테스트
"""

import asyncio
import tempfile
import os

from app.core.database.base import Database
from app.core.services.project import ProjectService
from app.core.services.session import SessionService
from app.core.services.pin import PinService


async def test_work_tracking_integration():
    """Work Tracking 통합 테스트"""
    
    # 임시 데이터베이스 생성
    with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as f:
        db_path = f.name

    try:
        # 데이터베이스 연결
        db = Database(db_path)
        await db.connect()

        # 서비스 생성
        project_service = ProjectService(db)
        session_service = SessionService(db, project_service)
        pin_service = PinService(db)

        print("1. 프로젝트 생성 테스트:")
        project = await project_service.get_or_create_project("integration-test-project")
        print(f"   생성된 프로젝트: {project.id}")

        print("\n2. 세션 생성 테스트:")
        session = await session_service.get_or_create_active_session("integration-test-project", "test-user")
        print(f"   생성된 세션: {session.id}")
        print(f"   상태: {session.status}")

        print("\n3. Pin 생성 테스트:")
        pin1 = await pin_service.create_pin(
            project_id="integration-test-project",
            content="Implement user authentication module",
            importance=4,
            tags=["auth", "security"],
            user_id="test-user"
        )
        print(f"   생성된 Pin: {pin1.id}")
        print(f"   내용: {pin1.content}")
        print(f"   중요도: {pin1.importance}")
        print(f"   상태: {pin1.status}")

        pin2 = await pin_service.create_pin(
            project_id="integration-test-project",
            content="Fix memory leak in data processing",
            importance=5,
            tags=["bug", "performance"],
            user_id="test-user"
        )
        print(f"   생성된 Pin: {pin2.id}")
        print(f"   내용: {pin2.content}")
        print(f"   중요도: {pin2.importance}")
        print(f"   상태: {pin2.status}")

        print("\n4. Pin 상태 변경 테스트 (open → in_progress):")
        from app.core.schemas.pins import PinUpdate
        update_data = PinUpdate(status="in_progress")
        updated_pin = await pin_service.update_pin(pin1.id, update_data)
        print(f"   업데이트된 Pin 상태: {updated_pin.status}")

        print("\n5. Pin 완료 처리 테스트:")
        completed_pin = await pin_service.complete_pin(pin1.id)
        print(f"   완료된 Pin 상태: {completed_pin.status}")
        print(f"   완료 시간: {completed_pin.completed_at}")
        print(f"   리드 타임: {completed_pin.lead_time_hours}시간")

        print("\n6. 세션 컨텍스트 로드 테스트:")
        session_context = await session_service.resume_last_session("integration-test-project", "test-user", expand=True)
        print(f"   세션 ID: {session_context.session_id}")
        print(f"   상태: {session_context.status}")
        print(f"   총 Pin 수: {session_context.pins_count}")
        print(f"   열린 Pin 수: {session_context.open_pins}")
        print(f"   완료된 Pin 수: {session_context.completed_pins}")
        
        if session_context.pins:
            print("   Pin 목록:")
            for pin in session_context.pins:
                print(f"     - {pin.id}: {pin.content[:50]}... (상태: {pin.status})")

        print("\n7. 승격 제안 테스트:")
        should_promote = pin_service.should_suggest_promotion(completed_pin)
        print(f"   중요도 {completed_pin.importance}인 완료된 Pin에 대한 승격 제안: {should_promote}")

        print("\n8. 프로젝트 통계 조회 테스트:")
        projects_with_stats = await project_service.list_projects_with_stats()
        for proj in projects_with_stats:
            if proj.id == "integration-test-project":
                print(f"   프로젝트: {proj.id}")
                print(f"   메모리 수: {proj.memory_count}")
                print(f"   핀 수: {proj.pin_count}")
                print(f"   평균 리드 타임: {proj.avg_lead_time_hours}시간")
                print(f"   활성 세션: {proj.active_session}")

        print("\n9. 세션 종료 테스트:")
        ended_session = await session_service.end_session(session.id, "Completed initial development tasks")
        print(f"   종료된 세션 상태: {ended_session.status}")
        print(f"   세션 요약: {ended_session.summary}")

        # 정리
        await db.close()

        # 임시 파일 정리
        for ext in ['', '-wal', '-shm']:
            path = db_path + ext
            if os.path.exists(path):
                os.unlink(path)

        print("\n통합 테스트 완료!")

    except Exception as e:
        print(f"테스트 중 오류 발생: {e}")
        # 정리
        for ext in ['', '-wal', '-shm']:
            path = db_path + ext
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    asyncio.run(test_work_tracking_integration())