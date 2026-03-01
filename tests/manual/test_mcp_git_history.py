#!/usr/bin/env python3
"""MCP 서버를 통한 git-history 카테고리 테스트"""

import asyncio
import json
import subprocess
import sys
import os

async def test_mcp_git_history():
    """MCP 서버를 통해 git-history 카테고리 테스트"""
    
    # 환경변수 설정
    env = os.environ.copy()
    env['MEM_MESH_IGNORE_SSL'] = 'true'
    
    # MCP 서버 시작
    print("🚀 MCP 서버 시작...")
    process = subprocess.Popen(
        [sys.executable, '-m', 'app.pure_mcp'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )
    
    try:
        # Initialize 요청
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
        
        print("📡 Initialize 요청 전송...")
        process.stdin.write(json.dumps(init_request) + '\n')
        process.stdin.flush()
        
        # 응답 읽기
        response = process.stdout.readline()
        init_response = json.loads(response)
        print(f"✅ Initialize 응답: {init_response['result']['serverInfo']['name']}")
        
        # git-history 카테고리로 메모리 추가
        add_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "add",
                "arguments": {
                    "content": "MCP 테스트: git-history 카테고리로 메모리 추가 테스트 중입니다. SSL 검증 우회 기능과 함께 작동하는지 확인합니다.",
                    "project_id": "mcp-test",
                    "category": "git-history",
                    "source": "mcp-test",
                    "tags": ["mcp", "git-history", "test"]
                }
            }
        }
        
        print("📝 git-history 카테고리로 메모리 추가...")
        process.stdin.write(json.dumps(add_request) + '\n')
        process.stdin.flush()
        
        # 응답 읽기
        response = process.stdout.readline()
        add_response = json.loads(response)
        
        if 'error' in add_response:
            print(f"❌ 메모리 추가 실패: {add_response['error']}")
            return False
        else:
            result = json.loads(add_response['result']['content'][0]['text'])
            print(f"✅ 메모리 추가 성공: ID={result['id']}")
            result['id']
        
        # git-history 카테고리로 검색
        search_request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {
                    "query": "SSL 검증 우회",
                    "category": "git-history",
                    "limit": 5
                }
            }
        }
        
        print("🔍 git-history 카테고리 검색...")
        process.stdin.write(json.dumps(search_request) + '\n')
        process.stdin.flush()
        
        # 응답 읽기
        response = process.stdout.readline()
        search_response = json.loads(response)
        
        if 'error' in search_response:
            print(f"❌ 검색 실패: {search_response['error']}")
            return False
        else:
            result = json.loads(search_response['result']['content'][0]['text'])
            print(f"✅ 검색 성공: {len(result['results'])}개 결과 발견")
            
            for memory in result['results']:
                if memory['category'] == 'git-history':
                    print(f"  - ID: {memory['id']}")
                    print(f"    Category: {memory['category']}")
                    print(f"    Content: {memory['content'][:100]}...")
        
        print("\n🎉 MCP git-history 카테고리 테스트 성공!")
        return True
        
    except Exception as e:
        print(f"❌ 테스트 중 오류 발생: {e}")
        return False
    
    finally:
        # 서버 종료
        try:
            shutdown_request = {
                "jsonrpc": "2.0",
                "id": 999,
                "method": "shutdown"
            }
            process.stdin.write(json.dumps(shutdown_request) + '\n')
            process.stdin.flush()
        except Exception:
            pass
        
        process.terminate()
        process.wait(timeout=5)

if __name__ == "__main__":
    success = asyncio.run(test_mcp_git_history())
    sys.exit(0 if success else 1)