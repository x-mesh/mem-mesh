#!/usr/bin/env python3
"""
두 데이터베이스 간 메모리 동기화 스크립트 (범용)

Usage:
    python scripts/sync_memories.py <source_db> <target_db> [--dry-run]
    
Examples:
    python scripts/sync_memories.py data_macmini/memories.db data/memories.db --dry-run
    python scripts/sync_memories.py data_macbook/memories.db data/memories.db
"""

import sqlite3
import sys
import argparse
from pathlib import Path
from datetime import datetime

# 프로젝트 루트 경로
ROOT_DIR = Path(__file__).parent.parent


def get_memory_ids(db_path: Path) -> set:
    """데이터베이스에서 모든 메모리 ID를 가져옵니다."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM memories")
    ids = {row[0] for row in cursor.fetchall()}
    
    conn.close()
    return ids


def get_missing_memories(source_db: Path, target_db: Path) -> list:
    """source_db에는 있지만 target_db에는 없는 메모리를 찾습니다."""
    print(f"📊 데이터베이스 분석 중...")
    
    source_ids = get_memory_ids(source_db)
    target_ids = get_memory_ids(target_db)
    
    missing_ids = source_ids - target_ids
    
    print(f"   Source DB ({source_db.name}): {len(source_ids):,} memories")
    print(f"   Target DB ({target_db.name}): {len(target_ids):,} memories")
    print(f"   Missing in target: {len(missing_ids):,} memories")
    
    if not missing_ids:
        return []
    
    # 누락된 메모리의 전체 데이터 가져오기
    conn = sqlite3.connect(source_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    placeholders = ','.join('?' * len(missing_ids))
    query = f"""
        SELECT 
            id, content, content_hash, project_id, category, source, 
            embedding, tags, created_at, updated_at
        FROM memories 
        WHERE id IN ({placeholders})
        ORDER BY created_at
    """
    
    cursor.execute(query, list(missing_ids))
    memories = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return memories


def check_schema_version(db_path: Path) -> str:
    """데이터베이스 스키마 버전 확인 (구 스키마 vs 신 스키마)"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # memory_embeddings 테이블이 있는지 확인
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='memory_embeddings'
    """)
    
    has_embeddings_table = cursor.fetchone() is not None
    conn.close()
    
    return "new" if has_embeddings_table else "old"


def insert_memories(target_db: Path, memories: list, dry_run: bool = False):
    """메모리를 target_db에 삽입합니다."""
    if dry_run:
        print(f"\n🔍 DRY RUN 모드 - 실제로 데이터를 삽입하지 않습니다.")
        print(f"\n삽입될 메모리 샘플 (최대 5개):")
        for i, memory in enumerate(memories[:5], 1):
            print(f"\n{i}. ID: {memory['id']}")
            print(f"   Project: {memory['project_id']}")
            print(f"   Category: {memory['category']}")
            print(f"   Content: {memory['content'][:100]}...")
            print(f"   Created: {memory['created_at']}")
            has_embedding = memory.get('embedding') is not None
            print(f"   Has embedding: {'✅' if has_embedding else '❌'}")
        
        if len(memories) > 5:
            print(f"\n... 그 외 {len(memories) - 5}개 메모리")
        
        return
    
    print(f"\n💾 메모리 삽입 중...")
    
    conn = sqlite3.connect(target_db)
    cursor = conn.cursor()
    
    # 메모리 삽입
    inserted_count = 0
    
    for memory in memories:
        try:
            cursor.execute("""
                INSERT INTO memories (
                    id, content, content_hash, project_id, category, source,
                    embedding, tags, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                memory['id'],
                memory['content'],
                memory['content_hash'],
                memory['project_id'],
                memory['category'],
                memory['source'],
                memory['embedding'],
                memory['tags'],
                memory['created_at'],
                memory['updated_at']
            ))
            
            inserted_count += 1
            
            if inserted_count % 100 == 0:
                print(f"   진행: {inserted_count}/{len(memories)} memories...")
                conn.commit()
        
        except sqlite3.IntegrityError as e:
            print(f"   ⚠️  중복 또는 제약 조건 위반 (ID: {memory['id']}): {e}")
            continue
        except Exception as e:
            print(f"   ❌ 삽입 실패 (ID: {memory['id']}): {e}")
            continue
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ 완료!")
    print(f"   삽입된 메모리: {inserted_count:,}")


def main():
    parser = argparse.ArgumentParser(
        description="두 데이터베이스 간 메모리 동기화",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/sync_memories.py data_macmini/memories.db data/memories.db --dry-run
  python scripts/sync_memories.py data_macbook/memories.db data/memories.db
        """
    )
    parser.add_argument(
        'source_db',
        type=str,
        help='Source 데이터베이스 경로 (예: data_macmini/memories.db)'
    )
    parser.add_argument(
        'target_db',
        type=str,
        help='Target 데이터베이스 경로 (예: data/memories.db)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='실제로 삽입하지 않고 미리보기만 표시'
    )
    
    args = parser.parse_args()
    
    # 경로 처리
    source_db = ROOT_DIR / args.source_db
    target_db = ROOT_DIR / args.target_db
    
    print("🔄 메모리 동기화 시작\n")
    print(f"Source: {source_db}")
    print(f"Target: {target_db}\n")
    
    # 데이터베이스 파일 존재 확인
    if not source_db.exists():
        print(f"❌ Source 데이터베이스를 찾을 수 없습니다: {source_db}")
        return 1
    
    if not target_db.exists():
        print(f"❌ Target 데이터베이스를 찾을 수 없습니다: {target_db}")
        return 1
    
    # 스키마 버전 확인
    source_schema = check_schema_version(source_db)
    target_schema = check_schema_version(target_db)
    print(f"Schema versions:")
    print(f"   Source: {source_schema}")
    print(f"   Target: {target_schema}")
    
    if source_schema != target_schema:
        print(f"\n⚠️  경고: 스키마 버전이 다릅니다. 마이그레이션이 필요할 수 있습니다.")
    
    # 누락된 메모리 찾기
    missing_memories = get_missing_memories(source_db, target_db)
    
    if not missing_memories:
        print("\n✅ 동기화할 메모리가 없습니다. 모든 데이터가 이미 동기화되어 있습니다.")
        return 0
    
    # 메모리 삽입
    insert_memories(target_db, missing_memories, dry_run=args.dry_run)
    
    if args.dry_run:
        print(f"\n💡 실제로 삽입하려면 --dry-run 옵션 없이 실행하세요:")
        print(f"   python scripts/sync_memories.py {args.source_db} {args.target_db}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
