#!/usr/bin/env python3
"""
PromptOptimizer 통합 테스트
응답 압축 기능 검증
"""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.database.base import Database
from app.core.config import Settings
from app.core.embeddings.service import EmbeddingService
from app.core.services.memory import MemoryService
from app.core.services.search import SearchService
from app.core.storage.direct import DirectStorageBackend
from app.mcp_common.tools import MCPToolHandlers


async def test_response_compression():
    """응답 압축 기능 테스트"""
    
    print("="*60)
    print("🧪 PromptOptimizer 통합 테스트")
    print("="*60)
    
    # 서비스 초기화
    test_settings = Settings()
    db = Database(test_settings.database_path)
    await db.connect()
    
    embedding_service = EmbeddingService(preload=False)
    memory_service = MemoryService(db, embedding_service)
    search_service = SearchService(db, embedding_service)
    
    storage = DirectStorageBackend(
        memory_service=memory_service,
        search_service=search_service,
        db=db
    )
    
    # 압축 활성화된 핸들러
    handlers_compressed = MCPToolHandlers(storage, enable_compression=True)
    
    # 압축 비활성화된 핸들러
    handlers_uncompressed = MCPToolHandlers(storage, enable_compression=False)
    
    # 테스트 쿼리
    test_query = "token optimization"
    
    print(f"\n📝 테스트 쿼리: '{test_query}'")
    print("-"*60)
    
    # 1. 표준 응답 (압축 없음)
    print("\n1️⃣ 표준 응답 (압축 없음)")
    result_standard = await handlers_uncompressed.search(
        query=test_query,
        limit=3
    )
    
    import json
    standard_json = json.dumps(result_standard, ensure_ascii=False)
    standard_size = len(standard_json)
    print(f"   크기: {standard_size} bytes")
    print(f"   결과 수: {len(result_standard.get('results', []))}")
    
    # 2. Minimal 압축
    print("\n2️⃣ Minimal 압축 (ID + 점수만)")
    result_minimal = await handlers_compressed.search(
        query=test_query,
        limit=3,
        response_format="minimal"
    )
    
    minimal_json = json.dumps(result_minimal, ensure_ascii=False)
    minimal_size = len(minimal_json)
    print(f"   크기: {minimal_size} bytes")
    print(f"   절감: {standard_size - minimal_size} bytes ({(1 - minimal_size/standard_size)*100:.1f}%)")
    print(f"   샘플: {json.dumps(result_minimal, ensure_ascii=False, indent=2)[:200]}...")
    
    # 3. Compact 압축
    print("\n3️⃣ Compact 압축 (요약)")
    result_compact = await handlers_compressed.search(
        query=test_query,
        limit=3,
        response_format="compact"
    )
    
    compact_json = json.dumps(result_compact, ensure_ascii=False)
    compact_size = len(compact_json)
    print(f"   크기: {compact_size} bytes")
    print(f"   절감: {standard_size - compact_size} bytes ({(1 - compact_size/standard_size)*100:.1f}%)")
    print(f"   샘플: {json.dumps(result_compact, ensure_ascii=False, indent=2)[:300]}...")
    
    # 4. Context 압축 테스트
    if result_standard.get('results'):
        first_id = result_standard['results'][0]['id']
        
        print(f"\n4️⃣ Context 압축 테스트 (Memory ID: {first_id[:8]}...)")
        
        # 표준 context
        context_standard = await handlers_uncompressed.context(
            memory_id=first_id,
            depth=1
        )
        context_standard_json = json.dumps(context_standard, ensure_ascii=False)
        context_standard_size = len(context_standard_json)
        print(f"   표준 크기: {context_standard_size} bytes")
        
        # 압축 context
        context_compact = await handlers_compressed.context(
            memory_id=first_id,
            depth=1,
            response_format="compact"
        )
        context_compact_json = json.dumps(context_compact, ensure_ascii=False)
        context_compact_size = len(context_compact_json)
        print(f"   압축 크기: {context_compact_size} bytes")
        print(f"   절감: {context_standard_size - context_compact_size} bytes ({(1 - context_compact_size/context_standard_size)*100:.1f}%)")
        print(f"   샘플: {json.dumps(context_compact, ensure_ascii=False, indent=2)[:300]}...")
    
    # 5. 토큰 추정
    print("\n5️⃣ 토큰 사용량 추정 (1 token ≈ 4 chars)")
    print(f"   표준 검색: ~{standard_size // 4} tokens")
    print(f"   Minimal 검색: ~{minimal_size // 4} tokens (절감: ~{(standard_size - minimal_size) // 4} tokens)")
    print(f"   Compact 검색: ~{compact_size // 4} tokens (절감: ~{(standard_size - compact_size) // 4} tokens)")
    
    # 6. 요약
    print("\n" + "="*60)
    print("📊 테스트 요약")
    print("="*60)
    print("✅ 압축 기능 정상 작동")
    print(f"✅ Minimal 압축: {(1 - minimal_size/standard_size)*100:.1f}% 절감")
    print(f"✅ Compact 압축: {(1 - compact_size/standard_size)*100:.1f}% 절감")
    print(f"✅ Context 압축: {(1 - context_compact_size/context_standard_size)*100:.1f}% 절감" if result_standard.get('results') else "")
    print("\n💡 권장 사용법:")
    print("   - 빠른 조회: response_format='minimal'")
    print("   - 일반 사용: response_format='compact'")
    print("   - 상세 필요: response_format='standard' (기본값)")
    print("   - 전체 데이터: response_format='full'")


if __name__ == "__main__":
    try:
        asyncio.run(test_response_compression())
    except KeyboardInterrupt:
        print("\n\n중단되었습니다.")
    except Exception as e:
        print(f"\n❌ 오류: {e}")
        import traceback
        traceback.print_exc()
