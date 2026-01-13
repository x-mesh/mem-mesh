#!/usr/bin/env python3
"""
WebSocket 직접 테스트 - 실제 WebSocket 연결을 통해 메시지 전송 확인
"""

import asyncio
import websockets
import json
from app.web.websocket.realtime import connection_manager, notifier

async def test_websocket_direct():
    """WebSocket 직접 연결 테스트"""
    print("🧪 Testing WebSocket direct connection...")
    
    try:
        # WebSocket 연결
        uri = "ws://127.0.0.1:8000/ws/realtime?client_id=test_client_debug"
        
        async with websockets.connect(uri) as websocket:
            print("✅ WebSocket connected")
            
            # 연결 확인 메시지 수신
            response = await websocket.recv()
            print(f"📨 Received: {response}")
            
            # 수동으로 메모리 생성 알림 전송 테스트
            print("📡 Sending test memory_created notification...")
            
            test_memory = {
                "id": "test-memory-123",
                "content": "Test memory for WebSocket notification",
                "project_id": "websocket-test",
                "category": "task",
                "created_at": "2026-01-14T00:48:00Z",
                "tags": ["test", "websocket"]
            }
            
            # 직접 알림 전송
            await notifier.notify_memory_created(test_memory)
            print("✅ Notification sent")
            
            # 메시지 수신 대기 (타임아웃 5초)
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                print(f"📨 Received notification: {message}")
                
                # JSON 파싱
                data = json.loads(message)
                if data.get('type') == 'memory_created':
                    print("🎉 Memory created notification received successfully!")
                else:
                    print(f"⚠️ Unexpected message type: {data.get('type')}")
                    
            except asyncio.TimeoutError:
                print("⏰ Timeout waiting for notification")
                
    except Exception as e:
        print(f"❌ WebSocket test failed: {e}")

async def test_connection_manager():
    """연결 관리자 상태 확인"""
    print("\n📊 Connection Manager Stats:")
    stats = connection_manager.get_stats()
    print(f"  Total connections: {stats['total_connections']}")
    print(f"  Global subscribers: {stats['global_subscribers']}")
    print(f"  Project subscriptions: {stats['project_subscriptions']}")

if __name__ == "__main__":
    asyncio.run(test_connection_manager())
    asyncio.run(test_websocket_direct())