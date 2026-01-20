#!/usr/bin/env python3
"""
메모리 실시간 업데이트 테스트 스크립트

서버가 실행 중일 때 이 스크립트를 실행하면:
1. 새 메모리를 생성합니다
2. WebSocket을 통해 실시간 알림이 전송되는지 확인합니다
3. 브라우저에서 실시간으로 메모리가 업데이트되는지 확인할 수 있습니다
"""

import asyncio
import json
import aiohttp
from datetime import datetime, timezone

async def create_test_memory(content: str, project_id: str = "kiro-conversations"):
    """테스트용 메모리 생성"""
    test_memory = {
        "content": content,
        "project_id": project_id,
        "category": "task",
        "source": "realtime-test",
        "tags": ["realtime", "test", "websocket"]
    }
    
    try:
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
            
            print(f"📤 Creating memory...")
            print(f"   Content: {content[:50]}...")
            print(f"   Project: {project_id}")
            
            # MCP SSE POST 엔드포인트로 요청
            async with session.post(
                'http://127.0.0.1:8000/mcp/sse',
                json=mcp_request,
                headers={'Content-Type': 'application/json'}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✅ Memory created successfully")
                    
                    # 응답에서 메모리 ID 추출
                    if 'result' in result and 'content' in result['result']:
                        content_str = result['result']['content'][0]['text']
                        content_data = json.loads(content_str)
                        if 'id' in content_data:
                            memory_id = content_data['id']
                            print(f"   Memory ID: {memory_id}")
                            return memory_id
                else:
                    print(f"❌ Memory creation failed: {response.status}")
                    error_text = await response.text()
                    print(f"   Error: {error_text}")
                    
    except Exception as e:
        print(f"❌ Error creating memory: {e}")
        return None

async def check_websocket_stats():
    """WebSocket 연결 상태 확인"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('http://127.0.0.1:8000/ws/stats') as response:
                if response.status == 200:
                    stats = await response.json()
                    print(f"📊 WebSocket Stats:")
                    print(f"   Total connections: {stats.get('total_connections', 0)}")
                    print(f"   Global subscribers: {stats.get('global_subscribers', 0)}")
                    
                    project_subs = stats.get('project_subscriptions', {})
                    if project_subs:
                        print(f"   Project subscriptions:")
                        for project, count in project_subs.items():
                            print(f"     - {project}: {count} subscribers")
                    else:
                        print(f"   No project subscriptions")
                    
                    return stats.get('total_connections', 0) > 0
                else:
                    print(f"❌ Cannot access WebSocket stats: {response.status}")
                    return False
                    
    except Exception as e:
        print(f"❌ Error checking WebSocket stats: {e}")
        return False

async def main():
    """메인 테스트 실행"""
    print("🚀 메모리 실시간 업데이트 테스트 시작\n")
    
    # 1. WebSocket 상태 확인
    print("1️⃣ WebSocket 연결 상태 확인...")
    has_connections = await check_websocket_stats()
    
    if not has_connections:
        print("\n⚠️  현재 WebSocket 연결이 없습니다.")
        print("   브라우저에서 http://127.0.0.1:8000/memories 를 열어주세요.")
        print("   그러면 WebSocket 연결이 생성됩니다.\n")
    
    # 2. 사용자 메시지 저장
    print("2️⃣ 사용자 메시지를 메모리로 저장...")
    user_message = "서버는 내가 시작할게 - 메모리 실시간 업데이트 테스트 요청"
    memory_id = await create_test_memory(user_message, "kiro-conversations")
    
    if memory_id:
        print(f"\n✅ 메모리가 성공적으로 생성되었습니다!")
        print(f"   Memory ID: {memory_id}")
        
        if has_connections:
            print(f"\n🎉 WebSocket 연결이 있으므로 실시간 알림이 전송되었습니다!")
            print(f"   브라우저에서 새 메모리가 자동으로 나타나는지 확인해보세요.")
        else:
            print(f"\n📝 WebSocket 연결이 없어서 실시간 알림은 전송되지 않았습니다.")
            print(f"   브라우저를 새로고침하면 새 메모리를 볼 수 있습니다.")
        
        print(f"\n📋 실시간 업데이트 확인 방법:")
        print(f"   1. 브라우저에서 http://127.0.0.1:8000/memories 열기")
        print(f"   2. 개발자 도구(F12) → Console 탭에서 WebSocket 메시지 확인")
        print(f"   3. 이 스크립트를 다시 실행하여 새 메모리 생성")
        print(f"   4. 브라우저에서 자동으로 새 메모리가 나타나는지 확인")
        
        return 0
    else:
        print(f"\n❌ 메모리 생성에 실패했습니다.")
        print(f"   서버가 실행 중인지 확인해주세요: python -m app.web --reload")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)