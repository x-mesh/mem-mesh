#!/usr/bin/env python3
"""
Work Tracking 기능 실제 DB 테스트
"""

import asyncio

from app.core.database.base import Database
from app.core.services.project import ProjectService
from app.core.services.session import SessionService
from app.core.services.pin import PinService


async def test_work_tracking_real_db():
    """실제 데이터베이스를 사용한 Work Tracking 테스트"""
    
    # 실제 데이터베이스 경로
    db_path = "./data/memories.db"

    # 데이터베이스 연결
    db = Database(db_path)
    await db.connect()

    # 서비스 생성
    project_service = ProjectService(db)
    session_service = SessionService(db, project_service)
    pin_service = PinService(db)

    print("1. 실제 DB에서 프로젝트 생성 테스트:")
    project = await project_service.get_or_create_project("real-db-test-project")
    print(f"   생성된 프로젝트: {project.id}")
    print(f"   이름: {project.name}")
    print(f"   생성 시간: {project.created_at}")

    print("\n2. 실제 DB에서 세션 생성 테스트:")
    session = await session_service.get_or_create_active_session("real-db-test-project", "test-user")
    print(f"   생성된 세션: {session.id}")
    print(f"   상태: {session.status}")

    print("\n3. 실제 DB에서 Pin 생성 테스트:")
    pin1 = await pin_service.create_pin(
        project_id="real-db-test-project",
        content="Real database test - Implement user authentication module",
        importance=4,
        tags=["auth", "security", "real-db"],
        user_id="test-user"
    )
    print(f"   생성된 Pin: {pin1.id}")
    print(f"   내용: {pin1.content}")
    print(f"   중요도: {pin1.importance}")
    print(f"   상태: {pin1.status}")

    pin2 = await pin_service.create_pin(
        project_id="real-db-test-project",
        content="Real database test - Fix memory leak in data processing",
        importance=5,
        tags=["bug", "performance", "real-db"],
        user_id="test-user"
    )
    print(f"   생성된 Pin: {pin2.id}")
    print(f"   내용: {pin2.content}")
    print(f"   중요도: {pin2.importance}")
    print(f"   상태: {pin2.status}")

    print("\n4. 실제 DB에서 Pin 상태 변경 테스트 (open → in_progress):")
    from app.core.schemas.pins import PinUpdate
    update_data = PinUpdate(status="in_progress")
    updated_pin = await pin_service.update_pin(pin1.id, update_data)
    print(f"   업데이트된 Pin 상태: {updated_pin.status}")

    print("\n5. 실제 DB에서 Pin 완료 처리 테스트:")
    completed_pin = await pin_service.complete_pin(pin1.id)
    print(f"   완료된 Pin 상태: {completed_pin.status}")
    print(f"   완료 시간: {completed_pin.completed_at}")
    print(f"   리드 타임: {completed_pin.lead_time_hours}시간")

    print("\n6. 실제 DB에서 세션 컨텍스트 로드 테스트:")
    session_context = await session_service.resume_last_session("real-db-test-project", "test-user", expand=True)
    print(f"   세션 ID: {session_context.session_id}")
    print(f"   상태: {session_context.status}")
    print(f"   총 Pin 수: {session_context.pins_count}")
    print(f"   열린 Pin 수: {session_context.open_pins}")
    print(f"   완료된 Pin 수: {session_context.completed_pins}")
    
    if session_context.pins:
        print("   Pin 목록:")
        for pin in session_context.pins:
            print(f"     - {pin.id}: {pin.content[:50]}... (상태: {pin.status})")

    print("\n7. 실제 DB에서 승격 제안 테스트:")
    should_promote = pin_service.should_suggest_promotion(completed_pin)
    print(f"   중요도 {completed_pin.importance}인 완료된 Pin에 대한 승격 제안: {should_promote}")

    print("\n8. 실제 DB에서 프로젝트 통계 조회 테스트:")
    projects_with_stats = await project_service.list_projects_with_stats()
    for proj in projects_with_stats:
        if proj.id == "real-db-test-project":
            print(f"   프로젝트: {proj.id}")
            print(f"   메모리 수: {proj.memory_count}")
            print(f"   핀 수: {proj.pin_count}")
            print(f"   평균 리드 타임: {proj.avg_lead_time_hours}시간")
            print(f"   활성 세션: {proj.active_session}")

    print("\n9. 실제 DB에서 세션 종료 테스트:")
    ended_session = await session_service.end_session(session.id, "Completed real database test tasks")
    print(f"   종료된 세션 상태: {ended_session.status}")
    print(f"   세션 요약: {ended_session.summary}")

    # 정리
    await db.close()

    print("\n실제 DB 테스트 완료!")
    print(f"데이터는 {db_path} 파일에 저장되었습니다.")


if __name__ == "__main__":
    asyncio.run(test_work_tracking_real_db())