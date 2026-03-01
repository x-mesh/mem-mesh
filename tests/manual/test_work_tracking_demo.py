#!/usr/bin/env python3
"""
Work Tracking 기능 데모 테스트
"""

import asyncio
import tempfile
import os

from app.core.database.base import Database
from app.core.services.project import ProjectService
from app.core.schemas.projects import ProjectUpdate


async def test_work_tracking():
    """Work Tracking 기능 테스트"""
    
    # 임시 데이터베이스 생성
    with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as f:
        db_path = f.name

    try:
        # 데이터베이스 연결
        db = Database(db_path)
        await db.connect()

        # 프로젝트 서비스 생성
        project_service = ProjectService(db)

        print("1. 새로운 프로젝트 생성 테스트:")
        project = await project_service.get_or_create_project("test-project-1")
        print(f"   생성된 프로젝트: {project.id}")
        print(f"   이름: {project.name}")
        print(f"   생성 시간: {project.created_at}")

        print("\n2. 프로젝트 업데이트 테스트:")
        update_data = ProjectUpdate(
            name="Test Project Updated",
            description="This is a test project for work tracking.",
            tech_stack="Python, FastAPI, SQLite"
        )
        updated_project = await project_service.update_project("test-project-1", update_data)
        print(f"   업데이트된 이름: {updated_project.name}")
        print(f"   설명: {updated_project.description}")
        print(f"   기술 스택: {updated_project.tech_stack}")

        print("\n3. 프로젝트 목록 조회 테스트:")
        projects = await project_service.list_projects()
        print(f"   전체 프로젝트 수: {len(projects)}")
        for proj in projects:
            print(f"   - {proj.id}: {proj.name}")

        print("\n4. 통계 포함 프로젝트 목록 조회 테스트:")
        projects_with_stats = await project_service.list_projects_with_stats()
        for proj in projects_with_stats:
            print(f"   - {proj.id}:")
            print(f"     메모리 수: {proj.memory_count}")
            print(f"     핀 수: {proj.pin_count}")
            print(f"     평균 리드 타임: {proj.avg_lead_time_hours}시간")
            print(f"     활성 세션: {proj.active_session}")

        print("\n5. 프로젝트 조회 테스트:")
        retrieved_project = await project_service.get_project("test-project-1")
        print(f"   조회된 프로젝트: {retrieved_project.name}")
        print(f"   설명: {retrieved_project.description}")

        # 정리
        await db.close()

        # 임시 파일 정리
        for ext in ['', '-wal', '-shm']:
            path = db_path + ext
            if os.path.exists(path):
                os.unlink(path)

        print("\n테스트 완료!")

    except Exception as e:
        print(f"테스트 중 오류 발생: {e}")
        # 정리
        for ext in ['', '-wal', '-shm']:
            path = db_path + ext
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    asyncio.run(test_work_tracking())