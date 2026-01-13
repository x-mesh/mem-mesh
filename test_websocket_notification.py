#!/usr/bin/env python3
"""
WebSocket 실시간 알림 테스트
"""

import asyncio
import json
from app.mcp_common.tools import MCPToolHandlers
from app.core.storage.direct import DirectStorageBackend
from app.web.websocket.realtime import notifier

async def test_websocket_notification():
    """WebSocket 알림 테스트"""
    print("🧪 Testing WebSocket notification...")
    
    # 스토리지 초기화
    storage = DirectStorageBackend('./data/memories.db')
    await storage.initialize()
    
    # MCP 도구 핸들러 생성 (notifier 포함)
    handlers = MCPToolHandlers(storage, notifier)
    
    try:
        # 테스트 메모리 생성
        print("Creating test memory...")
        result = await handlers.add(
            content="WebSocket 알림 테스트 메모리입니다. 이 메모리가 생성되면 실시간으로 UI에 표시되어야 합니다.",
            project_id="websocket-test",
            category="task",
            source="test",
            tags=["websocket", "test", "realtime"]
        )
        
        print(f"✅ Memory created: {result['id']}")
        print(f"📡 WebSocket notification should have been sent")
        
        # 연결 통계 확인
        import requests
        stats_response = requests.get('http://127.0.0.1:8000/ws/stats')
        if stats_response.status_code == 200:
            stats = stats_response.json()
            print(f"📊 WebSocket connections: {stats}")
        
        return result['id']
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return None
    finally:
        await storage.shutdown()

if __name__ == "__main__":
    memory_id = asyncio.run(test_websocket_notification())
    if memory_id:
        print(f"\n🎯 Test completed. Check browser for real-time update of memory: {memory_id}")
    else:
        print("\n💥 Test failed")