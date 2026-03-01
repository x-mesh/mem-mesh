#!/usr/bin/env python3
"""
WebSocket 실시간 업데이트 테스트 - memories 페이지 통합 확인
"""

import asyncio
import json
import aiohttp

async def test_memory_creation_with_websocket():
    """메모리 생성 시 WebSocket 알림이 전송되는지 테스트"""
    print("🧪 Testing memory creation with WebSocket notifications...")
    
    # 테스트용 메모리 데이터
    test_memory = {
        "content": "WebSocket 테스트용 메모리입니다. 실시간 업데이트가 작동하는지 확인합니다.",
        "project_id": "websocket-test",
        "category": "task",
        "source": "test",
        "tags": ["websocket", "test", "realtime"]
    }
    
    try:
        # MCP SSE 엔드포인트를 통해 메모리 생성
        async with aiohttp.ClientSession() as session:
            # MCP 요청 생성
            mcp_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "add",
                    "arguments": test_memory
                }
            }
            
            print("📤 Sending memory creation request...")
            print(f"   Content: {test_memory['content'][:50]}...")
            print(f"   Project: {test_memory['project_id']}")
            print(f"   Category: {test_memory['category']}")
            
            # MCP SSE POST 엔드포인트로 요청
            async with session.post(
                'http://127.0.0.1:8000/mcp/sse',
                json=mcp_request,
                headers={'Content-Type': 'application/json'}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    print("✅ Memory creation request successful")
                    print(f"   Response: {result}")
                    
                    # 응답에서 메모리 ID 추출
                    if 'result' in result and 'content' in result['result']:
                        content_str = result['result']['content'][0]['text']
                        content_data = json.loads(content_str)
                        if 'id' in content_data:
                            memory_id = content_data['id']
                            print(f"   Created memory ID: {memory_id}")
                            return memory_id
                else:
                    print(f"❌ Memory creation failed: {response.status}")
                    error_text = await response.text()
                    print(f"   Error: {error_text}")
                    
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return None

async def test_websocket_connection():
    """WebSocket 연결 테스트"""
    print("🧪 Testing WebSocket connection...")
    
    try:
        async with aiohttp.ClientSession() as session:
            # WebSocket 통계 확인
            async with session.get('http://127.0.0.1:8000/ws/stats') as response:
                if response.status == 200:
                    stats = await response.json()
                    print("✅ WebSocket server is running")
                    print(f"   Total connections: {stats.get('total_connections', 0)}")
                    print(f"   Global subscribers: {stats.get('global_subscribers', 0)}")
                    print(f"   Project subscriptions: {stats.get('project_subscriptions', {})}")
                    return True
                else:
                    print(f"❌ WebSocket server not accessible: {response.status}")
                    return False
                    
    except Exception as e:
        print(f"❌ WebSocket connection test failed: {e}")
        return False

async def main():
    """메인 테스트 실행"""
    print("🚀 Starting WebSocket memories integration test...\n")
    
    # 1. WebSocket 서버 연결 테스트
    ws_ok = await test_websocket_connection()
    if not ws_ok:
        print("💥 WebSocket server is not running. Please start the server first:")
        print("   python -m app.web --reload")
        return 1
    
    print()
    
    # 2. 메모리 생성 및 WebSocket 알림 테스트
    memory_id = await test_memory_creation_with_websocket()
    if memory_id:
        print("\n🎉 Test completed successfully!")
        print(f"   Memory created with ID: {memory_id}")
        print("   WebSocket notifications should be sent to connected clients")
        print("\n📋 To verify real-time updates:")
        print("   1. Open http://127.0.0.1:8000/memories in your browser")
        print("   2. Open browser developer tools (F12)")
        print("   3. Check the Console tab for WebSocket messages")
        print("   4. The new memory should appear automatically in the list")
        return 0
    else:
        print("\n💥 Test failed - memory creation unsuccessful")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)