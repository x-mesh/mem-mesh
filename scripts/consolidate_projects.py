#!/usr/bin/env python3
"""
mem-mesh 프로젝트 통합 스크립트
모든 mem-mesh-* 프로젝트를 mem-mesh로 통합
"""

import sqlite3
import sys


def consolidate_projects(dry_run=True):
    """프로젝트 통합"""

    conn = sqlite3.connect('./data/memories.db')
    cursor = conn.cursor()

    # 현재 상태 확인
    print("=" * 60)
    print("📊 현재 프로젝트 상태")
    print("=" * 60)

    cursor.execute("""
        SELECT project_id, COUNT(*) as count
        FROM memories
        WHERE project_id LIKE 'mem-mesh%'
        GROUP BY project_id
        ORDER BY count DESC
    """)

    projects = cursor.fetchall()
    total_to_merge = 0

    for project, count in projects:
        print(f"  {project}: {count}개")
        if project != 'mem-mesh' and project.startswith('mem-mesh-'):
            total_to_merge += count

    print(f"\n통합 대상: {total_to_merge}개 메모리")

    # 통합할 프로젝트들
    projects_to_merge = [
        'mem-mesh-optimization',
        'mem-mesh-search-quality',
        'mem-mesh-core',
        'mem-mesh-search-issue',
        # thread-summary-kr은 별도로 유지 (한국어 요약 전용)
    ]

    if not dry_run:
        print("\n" + "=" * 60)
        print("🔄 프로젝트 통합 시작")
        print("=" * 60)

        for old_project in projects_to_merge:
            cursor.execute("""
                UPDATE memories
                SET project_id = 'mem-mesh'
                WHERE project_id = ?
            """, (old_project,))

            affected = cursor.rowcount
            print(f"  {old_project} → mem-mesh: {affected}개 업데이트")

        conn.commit()

        # 통합 후 상태
        print("\n" + "=" * 60)
        print("✅ 통합 완료")
        print("=" * 60)

        cursor.execute("""
            SELECT project_id, COUNT(*) as count
            FROM memories
            WHERE project_id LIKE 'mem-mesh%'
            GROUP BY project_id
            ORDER BY count DESC
        """)

        for project, count in cursor.fetchall():
            print(f"  {project}: {count}개")

    else:
        print("\n" + "=" * 60)
        print("⚠️ DRY RUN 모드")
        print("=" * 60)
        print("실제로 통합하려면 --execute 옵션을 사용하세요")
        print()
        print("통합될 프로젝트:")
        for project in projects_to_merge:
            print(f"  - {project} → mem-mesh")
        print()
        print("유지될 프로젝트:")
        print("  - mem-mesh (메인)")
        print("  - mem-mesh-thread-summary-kr (한국어 요약 전용)")
        print("  - mem-mesh-conversations (대화 기록)")

    conn.close()

    print("\n💡 통합 효과:")
    print("  1. 맥락 유지: 모든 mem-mesh 관련 메모리 통합 검색")
    print("  2. 단순화: 프로젝트 ID = 디렉토리명")
    print("  3. 자동 감지: 현재 디렉토리에서 자동 프로젝트 설정")


if __name__ == "__main__":
    # --execute 옵션이 있으면 실제 실행
    execute = '--execute' in sys.argv

    if execute:
        response = input("정말로 프로젝트를 통합하시겠습니까? (yes/no): ")
        if response.lower() == 'yes':
            consolidate_projects(dry_run=False)
        else:
            print("취소되었습니다.")
    else:
        consolidate_projects(dry_run=True)