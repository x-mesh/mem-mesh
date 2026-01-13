#!/usr/bin/env python3
"""
threshold 검색 문제 해결 스크립트

1. 단순 "understood" 메모리들 정리
2. 검색 품질 개선 방안 제안
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from app.core.database.base import Database


async def fix_threshold_search():
    """threshold 검색 문제 해결"""
    print("🔧 threshold 검색 문제 해결 중...")
    
    db = Database("data/memories.db")
    await db.connect()
    
    try:
        # 1. 문제가 되는 "understood" 메모리들 확인
        print("\n1️⃣ 문제가 되는 'understood' 메모리들 확인")
        print("-" * 60)
        
        understood_memories = await db.fetchall(
            "SELECT id, content, project_id, created_at FROM memories WHERE content = 'understood'"
        )
        
        print(f"발견된 'understood' 메모리: {len(understood_memories)}개")
        
        for memory in understood_memories:
            print(f"  - ID: {memory['id'][:8]}... | 프로젝트: {memory['project_id']} | 생성일: {memory['created_at']}")
        
        # 2. 사용자 확인
        print(f"\n💡 해결 방안:")
        print(f"  1. 이 메모리들을 삭제 (내용이 너무 단순함)")
        print(f"  2. 내용을 더 의미있게 수정")
        print(f"  3. 검색 알고리즘 개선")
        
        choice = input(f"\n어떤 방법을 선택하시겠습니까? (1/2/3/skip): ").strip()
        
        if choice == "1":
            # 메모리 삭제
            print(f"\n🗑️ 'understood' 메모리들 삭제 중...")
            
            for memory in understood_memories:
                # 메모리 삭제
                await db.execute("DELETE FROM memories WHERE id = ?", (memory['id'],))
                
                # 벡터 테이블에서도 삭제
                await db.execute("DELETE FROM memory_embeddings WHERE memory_id = ?", (memory['id'],))
                
                print(f"  ✅ 삭제됨: {memory['id'][:8]}...")
            
            db.connection.commit()
            print(f"✅ {len(understood_memories)}개 메모리 삭제 완료")
            
        elif choice == "2":
            # 내용 수정
            print(f"\n✏️ 'understood' 메모리들 내용 수정 중...")
            
            for i, memory in enumerate(understood_memories, 1):
                new_content = input(f"메모리 {i} ({memory['id'][:8]}...) 새 내용: ").strip()
                
                if new_content:
                    await db.execute(
                        "UPDATE memories SET content = ?, updated_at = datetime('now') WHERE id = ?",
                        (new_content, memory['id'])
                    )
                    print(f"  ✅ 수정됨: {memory['id'][:8]}... -> '{new_content[:50]}...'")
            
            db.connection.commit()
            print(f"✅ 메모리 내용 수정 완료")
            
        elif choice == "3":
            # 검색 알고리즘 개선
            print(f"\n🔧 검색 알고리즘 개선 방안:")
            print(f"  1. 최소 콘텐츠 길이 필터 (예: 10자 이상)")
            print(f"  2. 콘텐츠 품질 점수 추가")
            print(f"  3. 하이브리드 검색 가중치 조정")
            print(f"  4. 정확한 단어 매칭 우선순위 증가")
            
            print(f"\n💡 이 방안들은 search.py 파일을 수정해야 합니다.")
            
        else:
            print(f"건너뛰기 선택됨")
        
        # 3. 수정 후 테스트
        if choice in ["1", "2"]:
            print(f"\n3️⃣ 수정 후 테스트")
            print("-" * 60)
            
            # 간단한 검색 테스트
            from app.core.storage.direct import DirectStorageBackend
            from app.core.schemas.requests import SearchParams
            
            storage = DirectStorageBackend("data/memories.db")
            await storage.initialize()
            
            # threshold 검색 테스트
            search_params = SearchParams(query="threshold", limit=3)
            result = await storage.search_memories(search_params)
            
            print(f"'threshold' 검색 결과 ({len(result.results)}개):")
            for i, res in enumerate(result.results, 1):
                content = res.content[:50] + "..." if len(res.content) > 50 else res.content
                print(f"  {i}. [{res.category}] {content}")
            
            await storage.shutdown()
    
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(fix_threshold_search())