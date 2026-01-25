#!/usr/bin/env python3
"""
데이터베이스 정리 스크립트

mem-mesh 프로젝트만 남기고 나머지 프로젝트(특히 kiro-* 프로젝트) 삭제.
관련된 벡터 데이터도 함께 삭제.
"""

import asyncio
import sys
from pathlib import Path
from typing import List, Tuple

# mem-mesh 모듈 임포트
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.core.database.base import Database
from app.core.config import Settings


def get_database_path() -> Path:
    """데이터베이스 경로 반환"""
    settings = Settings()
    return Path(settings.database_path)


async def get_stats(db: Database) -> Tuple[int, int, int]:
    """현재 통계 조회"""
    # 전체 메모리 수
    total = await db.fetchone("SELECT COUNT(*) as count FROM memories")
    total = total["count"] if total else 0
    
    # mem-mesh 메모리 수
    mem_mesh = await db.fetchone(
        "SELECT COUNT(*) as count FROM memories WHERE project_id = ?",
        ("mem-mesh",)
    )
    mem_mesh = mem_mesh["count"] if mem_mesh else 0
    
    # kiro-* 메모리 수
    kiro = await db.fetchone(
        "SELECT COUNT(*) as count FROM memories WHERE project_id LIKE ?",
        ("kiro-%",)
    )
    kiro = kiro["count"] if kiro else 0
    
    return total, mem_mesh, kiro


async def get_project_summary(db: Database) -> List[Tuple[str, int]]:
    """프로젝트별 메모리 수 조회"""
    rows = await db.fetchall(
        """
        SELECT project_id, COUNT(*) as count 
        FROM memories 
        GROUP BY project_id 
        ORDER BY count DESC
        """
    )
    return [(row["project_id"], row["count"]) for row in rows]


async def get_ids_to_delete(db: Database, dry_run: bool = True) -> List[str]:
    """삭제할 메모리 ID 목록 조회"""
    # mem-mesh가 아닌 모든 메모리 ID 조회
    rows = await db.fetchall(
        """
        SELECT id FROM memories 
        WHERE project_id != ? OR project_id IS NULL
        """,
        ("mem-mesh",)
    )
    return [row["id"] for row in rows]


async def delete_memories(db: Database, ids: List[str], dry_run: bool = True) -> int:
    """메모리 및 벡터 데이터 삭제"""
    if not ids:
        return 0
    
    if dry_run:
        print(f"[DRY RUN] {len(ids)}개 메모리 삭제 예정")
        return len(ids)
    
    # 배치 크기 (SQLite 변수 제한 고려)
    batch_size = 500
    total_deleted = 0
    
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        placeholders = ','.join('?' * len(batch))
        
        # 벡터 데이터 삭제
        await db.execute(
            f"DELETE FROM memory_embeddings WHERE memory_id IN ({placeholders})",
            batch
        )
        
        # 메모리 데이터 삭제
        await db.execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})",
            batch
        )
        
        total_deleted += len(batch)
        print(f"  진행: {total_deleted}/{len(ids)} 삭제됨")
    
    print(f"  ✓ {total_deleted}개 메모리 삭제 완료")
    return total_deleted


async def vacuum_database(db: Database, dry_run: bool = True):
    """데이터베이스 최적화 (VACUUM)"""
    if dry_run:
        print("[DRY RUN] VACUUM 실행 예정")
        return
    
    print("데이터베이스 최적화 중 (VACUUM)...")
    await db.execute("VACUUM")
    print("  ✓ 최적화 완료")


async def main_async(dry_run: bool):
    """비동기 메인 함수"""
    if dry_run:
        print("=" * 60)
        print("  DRY RUN 모드 (실제 삭제 없음)")
        print("  실제 삭제하려면 --execute 옵션 사용")
        print("=" * 60)
        print()
    else:
        print("=" * 60)
        print("  ⚠️  실제 삭제 모드 ⚠️")
        print("=" * 60)
        print()
        response = input("정말로 삭제하시겠습니까? (yes/no): ")
        if response.lower() != "yes":
            print("취소되었습니다.")
            return
        print()
    
    db_path = get_database_path()
    if not db_path.exists():
        print(f"❌ 데이터베이스를 찾을 수 없습니다: {db_path}")
        sys.exit(1)
    
    # 데이터베이스 연결
    db = Database(str(db_path))
    await db.connect()
    
    try:
        # 현재 상태 출력
        print("📊 현재 상태:")
        print("-" * 60)
        total, mem_mesh, kiro = await get_stats(db)
        print(f"  전체 메모리:     {total:,}개")
        print(f"  mem-mesh:        {mem_mesh:,}개 (유지)")
        print(f"  kiro-* 프로젝트: {kiro:,}개 (삭제 대상)")
        print(f"  기타:            {total - mem_mesh - kiro:,}개 (삭제 대상)")
        print()
        
        # 프로젝트별 요약 (상위 10개)
        print("📋 프로젝트별 메모리 수 (상위 10개):")
        print("-" * 60)
        projects = await get_project_summary(db)
        for project_id, count in projects[:10]:
            status = "✓ 유지" if project_id == "mem-mesh" else "✗ 삭제"
            print(f"  {project_id:30s} {count:6,}개  {status}")
        if len(projects) > 10:
            print(f"  ... 외 {len(projects) - 10}개 프로젝트")
        print()
        
        # 삭제 대상 조회
        ids_to_delete = await get_ids_to_delete(db, dry_run)
        
        if not ids_to_delete:
            print("✓ 삭제할 데이터가 없습니다.")
            return
        
        print(f"🗑️  삭제 대상: {len(ids_to_delete):,}개 메모리")
        print()
        
        # 삭제 수행
        deleted = await delete_memories(db, ids_to_delete, dry_run)
        print()
        
        # VACUUM
        await vacuum_database(db, dry_run)
        print()
        
        # 최종 상태
        if not dry_run:
            print("📊 최종 상태:")
            print("-" * 60)
            total_after, mem_mesh_after, kiro_after = await get_stats(db)
            print(f"  전체 메모리:     {total_after:,}개")
            print(f"  mem-mesh:        {mem_mesh_after:,}개")
            print(f"  삭제된 메모리:   {total - total_after:,}개")
            print()
            print("✅ 정리 완료!")
        else:
            print("💡 실제 삭제하려면 다음 명령어를 실행하세요:")
            print(f"   python {sys.argv[0]} --execute")
    
    finally:
        await db.close()


def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="mem-mesh 데이터베이스 정리")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 삭제 없이 시뮬레이션만 수행"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제로 삭제 수행 (주의!)"
    )
    args = parser.parse_args()
    
    # 기본값은 dry-run
    dry_run = not args.execute
    
    # 비동기 실행
    asyncio.run(main_async(dry_run))


if __name__ == "__main__":
    main()
