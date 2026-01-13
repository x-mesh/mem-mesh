#!/usr/bin/env python3
"""API 모드 MCP 서버 테스트"""

import asyncio
import json
import subprocess
import sys
import os

async def test_api_mcp():
    """API 모드로 MCP 서버 테스트"""
    
    # 환경변수 설정
    env = os.environ.copy()
    env['MEM_MESH_STORAGE_MODE'] = 'api'
    env['MEM_MESH_IGNORE_SSL'] = 'true'
    
    # MCP 서버 시작
    print("🚀 API 모드 MCP 서버 시작...")
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
        
        # API 모드로 메모리 추가
        add_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "add",
                "arguments": {
                    "content": "API 모드 테스트: 순수 MCP 서버가 API 스토리지 백엔드와 함께 정상 작동하는지 확인합니다.",
                    "project_id": "api-test",
                    "category": "task",
                    "source": "api-mcp-test",
                    "tags": ["api", "mcp", "storage-backend"]
                }
            }
        }
        
        print("📝 API 모드로 메모리 추가...")
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
        
        # 검색 테스트
        search_request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {
                    "query": "API 모드 테스트",
                    "project_id": "api-test",
                    "limit": 5
                }
            }
        }
        
        print("🔍 API 모드 검색 테스트...")
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
        
        print("\n🎉 API 모드 MCP 서버 테스트 성공!")
        return True
        
    except Exception as e:
        print(f"❌ 테스트 중 오류 발생: {e}")
        # stderr 출력 확인
        stderr_output = process.stderr.read()
        if stderr_output:
            print(f"서버 에러 로그:\n{stderr_output}")
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
        except:
            pass
        
        process.terminate()
        process.wait(timeout=5)

if __name__ == "__main__":
    success = asyncio.run(test_api_mcp())
    sys.exit(0 if success else 1)