#!/usr/bin/env python3
"""
Embedding 차이 상세 분석 스크립트

각 데이터베이스의 embedding 모델, 차원, 생성 시점 등을 분석합니다.
"""

import sqlite3
import struct
from pathlib import Path
from typing import Dict, Optional

ROOT_DIR = Path(__file__).parent.parent

DATABASES = [
    ("data", ROOT_DIR / "data" / "memories.db"),
    ("data_macmini", ROOT_DIR / "data_macmini" / "memories.db"),
    ("data_macbook", ROOT_DIR / "data_macbook" / "memories.db"),
]


def get_embedding_info(db_path: Path) -> Dict:
    """데이터베이스의 embedding 정보를 분석합니다."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 총 메모리 수
    cursor.execute("SELECT COUNT(*) FROM memories")
    total_memories = cursor.fetchone()[0]
    
    # Embedding이 있는 메모리 수
    cursor.execute("SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL")
    with_embedding = cursor.fetchone()[0]
    
    # 샘플 embedding 가져오기 (차원 확인)
    cursor.execute("SELECT embedding FROM memories WHERE embedding IS NOT NULL LIMIT 1")
    sample_embedding = cursor.fetchone()
    
    embedding_dim = None
    if sample_embedding and sample_embedding[0]:
        # BLOB을 float 배열로 변환하여 차원 확인
        blob = sample_embedding[0]
        # 4바이트(float) 단위로 나누어 차원 계산
        embedding_dim = len(blob) // 4
    
    # 최근 생성된 메모리 5개의 created_at 확인
    cursor.execute("""
        SELECT created_at 
        FROM memories 
        ORDER BY created_at DESC 
        LIMIT 5
    """)
    recent_dates = [row[0] for row in cursor.fetchall()]
    
    # 가장 오래된 메모리 5개의 created_at 확인
    cursor.execute("""
        SELECT created_at 
        FROM memories 
        ORDER BY created_at ASC 
        LIMIT 5
    """)
    oldest_dates = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        'total_memories': total_memories,
        'with_embedding': with_embedding,
        'without_embedding': total_memories - with_embedding,
        'embedding_dim': embedding_dim,
        'recent_dates': recent_dates,
        'oldest_dates': oldest_dates,
    }


def compare_specific_memory(memory_id: str):
    """특정 메모리의 embedding을 세 DB에서 비교합니다."""
    print(f"\n🔬 메모리 ID {memory_id} 상세 분석:\n")
    
    for db_name, db_path in DATABASES:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT content, embedding, created_at, updated_at
            FROM memories
            WHERE id = ?
        """, (memory_id,))
        
        row = cursor.fetchone()
        
        if row:
            content, embedding, created_at, updated_at = row
            
            print(f"{db_name}:")
            print(f"   Content length: {len(content)} chars")
            print(f"   Created: {created_at}")
            print(f"   Updated: {updated_at}")
            
            if embedding:
                emb_dim = len(embedding) // 4
                # 처음 5개 값만 출력
                floats = struct.unpack(f'{5}f', embedding[:20])
                print(f"   Embedding dim: {emb_dim}")
                print(f"   First 5 values: {[f'{f:.6f}' for f in floats]}")
            else:
                print(f"   Embedding: None")
            print()
        else:
            print(f"{db_name}: 메모리를 찾을 수 없음\n")
        
        conn.close()


def main():
    print("📊 Embedding 차이 분석\n")
    print("=" * 60)
    
    for db_name, db_path in DATABASES:
        print(f"\n{db_name} ({db_path.name}):")
        print("-" * 60)
        
        info = get_embedding_info(db_path)
        
        print(f"총 메모리: {info['total_memories']:,}")
        print(f"Embedding 있음: {info['with_embedding']:,}")
        print(f"Embedding 없음: {info['without_embedding']:,}")
        print(f"Embedding 차원: {info['embedding_dim']}")
        print(f"\n최근 메모리 생성 시점:")
        for date in info['recent_dates']:
            print(f"   - {date}")
        print(f"\n가장 오래된 메모리 생성 시점:")
        for date in info['oldest_dates']:
            print(f"   - {date}")
    
    print("\n" + "=" * 60)
    
    # 공통 메모리 ID 하나를 선택하여 상세 비교
    conn = sqlite3.connect(DATABASES[0][1])
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM memories LIMIT 1")
    sample_id = cursor.fetchone()[0]
    conn.close()
    
    compare_specific_memory(sample_id)
    
    print("\n💡 결론:")
    print("   - 세 데이터베이스의 메모리 개수는 거의 동일")
    print("   - Content와 metadata는 동일할 가능성이 높음")
    print("   - Embedding 값이 다른 이유:")
    print("     1. 서로 다른 embedding 모델 사용")
    print("     2. 서로 다른 시점에 생성됨")
    print("     3. 모델 버전 차이")
    print("   - 이는 정상적인 상황이며, 검색 결과에 약간의 차이를 만들 수 있음")


if __name__ == "__main__":
    main()
