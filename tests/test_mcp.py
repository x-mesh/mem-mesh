#!/usr/bin/env python3
"""MCP 서버 테스트 스크립트"""

import asyncio
import json
import subprocess
import sys

async def test_mcp_server():
    """MCP 서버 테스트"""
    
    # MCP 서버 프로세스 시작
    process = subprocess.Popen(
        [sys.executable, "-m", "app.mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    try:
        # 1. 초기화
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"}
            }
        }
        
        print("🔄 Initializing MCP server...")
        process.stdin.write(json.dumps(init_request) + "\n")
        process.stdin.flush()
        
        # 응답 읽기
        response = process.stdout.readline()
        if response:
            init_response = json.loads(response)
            print("✅ Initialization successful!")
            print(f"   Server: {init_response['result']['serverInfo']['name']}")
            print(f"   Version: {init_response['result']['serverInfo']['version']}")
        
        # 2. 도구 목록 조회
        tools_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list"
        }
        
        print("\n🔄 Getting tools list...")
        process.stdin.write(json.dumps(tools_request) + "\n")
        process.stdin.flush()
        
        response = process.stdout.readline()
        if response:
            tools_response = json.loads(response)
            tools = tools_response['result']['tools']
            print(f"✅ Found {len(tools)} tools:")
            for tool in tools:
                print(f"   - {tool['name']}: {tool['description']}")
        
        # 3. 메모리 추가 테스트
        add_request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "add",
                "arguments": {
                    "content": "FastMCP 기반 MCP 서버 테스트 중입니다. 새로운 아키텍처가 잘 작동하는지 확인해보겠습니다.",
                    "project_id": "mem-mesh-test",
                    "category": "task",
                    "tags": ["test", "fastmcp", "architecture"]
                }
            }
        }
        
        print("\n🔄 Adding test memory...")
        process.stdin.write(json.dumps(add_request) + "\n")
        process.stdin.flush()
        
        response = process.stdout.readline()
        if response:
            add_response = json.loads(response)
            if 'result' in add_response:
                memory_id = add_response['result']['content']['id']
                print("✅ Memory added successfully!")
                print(f"   ID: {memory_id}")
                print(f"   Status: {add_response['result']['content']['status']}")
            else:
                print(f"❌ Error adding memory: {add_response.get('error', 'Unknown error')}")
        
        # 4. 검색 테스트
        search_request = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {
                    "query": "FastMCP 아키텍처",
                    "limit": 5
                }
            }
        }
        
        print("\n🔄 Searching memories...")
        process.stdin.write(json.dumps(search_request) + "\n")
        process.stdin.flush()
        
        response = process.stdout.readline()
        if response:
            search_response = json.loads(response)
            if 'result' in search_response:
                results = search_response['result']['content']['results']
                print(f"✅ Found {len(results)} memories:")
                for result in results:
                    print(f"   - {result['id']}: {result['content'][:50]}...")
            else:
                print(f"❌ Error searching: {search_response.get('error', 'Unknown error')}")
        
        # 5. 통계 조회
        stats_request = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "stats",
                "arguments": {}
            }
        }
        
        print("\n🔄 Getting statistics...")
        process.stdin.write(json.dumps(stats_request) + "\n")
        process.stdin.flush()
        
        response = process.stdout.readline()
        if response:
            stats_response = json.loads(response)
            if 'result' in stats_response:
                stats = stats_response['result']['content']
                print("✅ Statistics:")
                print(f"   Total memories: {stats['total_memories']}")
                print(f"   Unique projects: {stats['unique_projects']}")
                print(f"   Categories: {stats['categories_breakdown']}")
            else:
                print(f"❌ Error getting stats: {stats_response.get('error', 'Unknown error')}")
        
        print("\n🎉 All tests completed successfully!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
    finally:
        # 프로세스 종료
        process.terminate()
        process.wait()

if __name__ == "__main__":
    asyncio.run(test_mcp_server())