#!/usr/bin/env python3
"""
실시간 메모리 생성 테스트 - MCP를 통해 메모리를 생성하고 WebSocket 알림을 확인
"""

import asyncio
import websockets
import json
import aiohttp
from datetime import datetime

async def test_realtime_memory_creation():
    """실시간 메모리 생성 및 WebSocket 알림 테스트"""
    print("🧪 Testing realtime memory creation with WebSocket notifications...")
    
    # WebSocket 연결
    uri = "ws://127.0.0.1:8000/ws/realtime?client_id=test_realtime_client"
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ WebSocket connected")
            
            # 연결 확인 메시지 수신
            response = await websocket.recv()
            print(f"📨 Connection established: {json.loads(response)['data']['message']}")
            
            # 메모리 생성 API 호출
            print("📝 Creating memory via API...")
            
            memory_data = {
                "content": f"실시간 테스트 메모리 - {datetime.now().isoformat()}",
                "project_id": "realtime-test",
                "category": "task",
                "source": "websocket-test",
                "tags": ["realtime", "websocket", "test"]
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "http://127.0.0.1:8000/api/memories",
                    json=memory_data
                ) as response:
                    if response.status in [200, 201]:
                        created_memory = await response.json()
                        print(f"✅ Memory created: {created_memory['id']}")
                    else:
                        print(f"❌ Failed to create memory: {response.status}")
                        response_text = await response.text()
                        print(f"Response: {response_text}")
                        return
            
            # WebSocket 알림 수신 대기
            print("⏳ Waiting for WebSocket notification...")
            
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                print(f"📨 Received: {message}")
                
                # JSON 파싱
                data = json.loads(message)
                if data.get('type') == 'memory_created':
                    memory = data['data']['memory']
                    print(f"🎉 Memory created notification received!")
                    print(f"   ID: {memory['id']}")
                    print(f"   Status: {memory.get('status', 'N/A')}")
                    print(f"   Created: {memory.get('created_at', 'N/A')}")
                else:
                    print(f"⚠️ Unexpected message type: {data.get('type')}")
                    
            except asyncio.TimeoutError:
                print("⏰ Timeout waiting for notification")
                
            # 메모리 업데이트 테스트
            print("\n📝 Testing memory update...")
            
            update_data = {
                "content": f"업데이트된 실시간 테스트 메모리 - {datetime.now().isoformat()}",
                "tags": ["realtime", "websocket", "test", "updated"]
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    f"http://127.0.0.1:8000/api/memories/{created_memory['id']}",
                    json=update_data
                ) as response:
                    if response.status == 200:
                        print("✅ Memory updated")
                    else:
                        print(f"❌ Failed to update memory: {response.status}")
                        return
            
            # 업데이트 알림 수신 대기
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                print(f"📨 Update notification: {message}")
                
                data = json.loads(message)
                if data.get('type') == 'memory_updated':
                    print("🎉 Memory updated notification received!")
                else:
                    print(f"⚠️ Unexpected message type: {data.get('type')}")
                    
            except asyncio.TimeoutError:
                print("⏰ Timeout waiting for update notification")
                
    except Exception as e:
        print(f"❌ Test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_realtime_memory_creation())