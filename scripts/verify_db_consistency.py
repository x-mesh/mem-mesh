#!/usr/bin/env python3
"""
여러 데이터베이스 간 메모리 내용 일관성 검증 스크립트

동일한 ID를 가진 메모리들의 content, content_hash, embedding 등이 
실제로 같은지 확인합니다.

Usage:
    python scripts/verify_db_consistency.py
"""

import sqlite3
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Set

# 프로젝트 루트 경로
ROOT_DIR = Path(__file__).parent.parent

# 검증할 데이터베이스 목록
DATABASES = [
    ROOT_DIR / "data" / "memories.db",
    ROOT_DIR / "data_macmini" / "memories.db",
    ROOT_DIR / "data_macbook" / "memories.db",
]


def get_memory_data(db_path: Path) -> Dict[str, Dict]:
    """데이터베이스에서 모든 메모리 데이터를 가져옵니다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, content, content_hash, project_id, category, 
               source, embedding, tags, created_at, updated_at
        FROM memories
    """)
    
    memories = {}
    for row in cursor.fetchall():
        memory_id = row['id']
        memories[memory_id] = {
            'content': row['content'],
            'content_hash': row['content_hash'],
            'project_id': row['project_id'],
            'category': row['category'],
            'source': row['source'],
            'embedding': row['embedding'],
            'tags': row['tags'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
        }
    
    conn.close()
    return memories


def compare_memories(db_memories: List[Tuple[str, Dict[str, Dict]]]) -> Dict:
    """여러 데이터베이스의 메모리를 비교합니다."""
    
    # 모든 데이터베이스에 공통으로 있는 ID 찾기
    all_ids = [set(memories.keys()) for _, memories in db_memories]
    common_ids = set.intersection(*all_ids)
    
    print(f"📊 메모리 ID 분석:")
    for db_name, memories in db_memories:
        print(f"   {db_name}: {len(memories):,} memories")
    print(f"   공통 ID: {len(common_ids):,} memories")
    
    # 각 데이터베이스에만 있는 ID
    for i, (db_name, memories) in enumerate(db_memories):
        unique_ids = set(memories.keys())
        for j, (other_name, other_memories) in enumerate(db_memories):
            if i != j:
                unique_ids -= set(other_memories.keys())
        
        if unique_ids:
            print(f"   {db_name}에만 있음: {len(unique_ids):,} memories")
    
    print()
    
    # 공통 ID에 대해 내용 비교
    inconsistencies = {
        'content_mismatch': [],
        'content_hash_mismatch': [],
        'embedding_mismatch': [],
        'metadata_mismatch': [],
    }
    
    print(f"🔍 내용 일관성 검증 중... (샘플: 처음 1000개)")
    
    # 샘플링: 처음 1000개만 검증 (전체 검증은 시간이 오래 걸림)
    sample_ids = list(common_ids)[:1000]
    
    for idx, memory_id in enumerate(sample_ids):
        if (idx + 1) % 100 == 0:
            print(f"   진행: {idx + 1}/{len(sample_ids)}")
        
        # 첫 번째 DB를 기준으로 삼음
        base_db_name, base_memories = db_memories[0]
        base_memory = base_memories[memory_id]
        
        # 다른 DB들과 비교
        for db_name, memories in db_memories[1:]:
            memory = memories[memory_id]
            
            # Content 비교
            if base_memory['content'] != memory['content']:
                inconsistencies['content_mismatch'].append({
                    'id': memory_id,
                    'base_db': base_db_name,
                    'compare_db': db_name,
                    'base_content_len': len(base_memory['content']),
                    'compare_content_len': len(memory['content']),
                })
            
            # Content hash 비교
            if base_memory['content_hash'] != memory['content_hash']:
                inconsistencies['content_hash_mismatch'].append({
                    'id': memory_id,
                    'base_db': base_db_name,
                    'compare_db': db_name,
                    'base_hash': base_memory['content_hash'],
                    'compare_hash': memory['content_hash'],
                })
            
            # Embedding 비교 (None 체크)
            base_emb = base_memory['embedding']
            comp_emb = memory['embedding']
            
            if (base_emb is None) != (comp_emb is None):
                inconsistencies['embedding_mismatch'].append({
                    'id': memory_id,
                    'base_db': base_db_name,
                    'compare_db': db_name,
                    'issue': 'one_is_null',
                })
            elif base_emb is not None and comp_emb is not None:
                if base_emb != comp_emb:
                    inconsistencies['embedding_mismatch'].append({
                        'id': memory_id,
                        'base_db': base_db_name,
                        'compare_db': db_name,
                        'issue': 'different_values',
                    })
            
            # Metadata 비교 (project_id, category, source, tags)
            metadata_fields = ['project_id', 'category', 'source', 'tags']
            for field in metadata_fields:
                if base_memory[field] != memory[field]:
                    inconsistencies['metadata_mismatch'].append({
                        'id': memory_id,
                        'base_db': base_db_name,
                        'compare_db': db_name,
                        'field': field,
                        'base_value': base_memory[field],
                        'compare_value': memory[field],
                    })
    
    return inconsistencies


def print_inconsistencies(inconsistencies: Dict):
    """불일치 사항을 출력합니다."""
    print(f"\n📋 검증 결과:\n")
    
    total_issues = sum(len(issues) for issues in inconsistencies.values())
    
    if total_issues == 0:
        print("✅ 모든 메모리가 일관성 있게 동기화되어 있습니다!")
        return
    
    print(f"⚠️  총 {total_issues}개의 불일치 발견\n")
    
    # Content 불일치
    if inconsistencies['content_mismatch']:
        print(f"❌ Content 불일치: {len(inconsistencies['content_mismatch'])}개")
        for issue in inconsistencies['content_mismatch'][:5]:
            print(f"   ID: {issue['id']}")
            print(f"   {issue['base_db']}: {issue['base_content_len']} chars")
            print(f"   {issue['compare_db']}: {issue['compare_content_len']} chars")
            print()
        
        if len(inconsistencies['content_mismatch']) > 5:
            print(f"   ... 그 외 {len(inconsistencies['content_mismatch']) - 5}개\n")
    
    # Content hash 불일치
    if inconsistencies['content_hash_mismatch']:
        print(f"❌ Content Hash 불일치: {len(inconsistencies['content_hash_mismatch'])}개")
        for issue in inconsistencies['content_hash_mismatch'][:5]:
            print(f"   ID: {issue['id']}")
            print(f"   {issue['base_db']}: {issue['base_hash']}")
            print(f"   {issue['compare_db']}: {issue['compare_hash']}")
            print()
        
        if len(inconsistencies['content_hash_mismatch']) > 5:
            print(f"   ... 그 외 {len(inconsistencies['content_hash_mismatch']) - 5}개\n")
    
    # Embedding 불일치
    if inconsistencies['embedding_mismatch']:
        print(f"❌ Embedding 불일치: {len(inconsistencies['embedding_mismatch'])}개")
        for issue in inconsistencies['embedding_mismatch'][:5]:
            print(f"   ID: {issue['id']}")
            print(f"   {issue['base_db']} vs {issue['compare_db']}")
            print(f"   Issue: {issue['issue']}")
            print()
        
        if len(inconsistencies['embedding_mismatch']) > 5:
            print(f"   ... 그 외 {len(inconsistencies['embedding_mismatch']) - 5}개\n")
    
    # Metadata 불일치
    if inconsistencies['metadata_mismatch']:
        print(f"❌ Metadata 불일치: {len(inconsistencies['metadata_mismatch'])}개")
        for issue in inconsistencies['metadata_mismatch'][:5]:
            print(f"   ID: {issue['id']}")
            print(f"   Field: {issue['field']}")
            print(f"   {issue['base_db']}: {issue['base_value']}")
            print(f"   {issue['compare_db']}: {issue['compare_value']}")
            print()
        
        if len(inconsistencies['metadata_mismatch']) > 5:
            print(f"   ... 그 외 {len(inconsistencies['metadata_mismatch']) - 5}개\n")


def main():
    print("🔍 데이터베이스 일관성 검증 시작\n")
    
    # 데이터베이스 존재 확인
    for db_path in DATABASES:
        if not db_path.exists():
            print(f"❌ 데이터베이스를 찾을 수 없습니다: {db_path}")
            return 1
    
    print(f"검증할 데이터베이스:")
    for db_path in DATABASES:
        print(f"   - {db_path}")
    print()
    
    # 각 데이터베이스에서 메모리 데이터 가져오기
    db_memories = []
    for db_path in DATABASES:
        print(f"📥 {db_path.name} 로딩 중...")
        memories = get_memory_data(db_path)
        db_memories.append((db_path.name, memories))
    
    print()
    
    # 메모리 비교
    inconsistencies = compare_memories(db_memories)
    
    # 결과 출력
    print_inconsistencies(inconsistencies)
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
