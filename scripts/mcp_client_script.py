#!/usr/bin/env python3
"""
MCP 서버에 연결하여 명령을 보내는 클라이언트 스크립트
"""

import subprocess
import sys
import os
import json
import time


def send_mcp_command(command):
    """MCP 서버에 명령을 보내고 응답을 받음"""
    # 환경변수 설정
    env = os.environ.copy()
    env['MEM_MESH_STORAGE_MODE'] = 'direct'  # 직접 DB 접근
    env['MEM_MESH_IGNORE_SSL'] = 'true'

    # MCP 서버에 명령 보내기
    process = subprocess.Popen(
        [sys.executable, '-m', 'app.mcp_stdio_pure'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )

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

    process.stdin.write(json.dumps(init_request) + '\n')
    process.stdin.flush()

    # 응답 읽기
    response = process.stdout.readline()
    init_response = json.loads(response)
    print(f"✅ Initialize 응답: {init_response['result']['serverInfo']['name']}")

    # 실제 명령 보내기
    process.stdin.write(json.dumps(command) + '\n')
    process.stdin.flush()

    # 응답 읽기
    response = process.stdout.readline()
    result = json.loads(response)

    # 서버 종료
    shutdown_request = {
        "jsonrpc": "2.0",
        "id": 999,
        "method": "shutdown"
    }
    process.stdin.write(json.dumps(shutdown_request) + '\n')
    process.stdin.flush()

    process.terminate()
    process.wait()

    return result


def save_work_tracking_via_mcp_client():
    """MCP 클라이언트를 통해 Work Tracking 테스트 결과 저장"""
    
    # Work Tracking 테스트 결과 내용
    work_tracking_content = """
Work Tracking 기능 실제 DB 테스트 결과:

1. 프로젝트 생성:
   - real-db-test-project라는 프로젝트가 projects 테이블에 성공적으로 생성됨

2. 세션 생성 및 관리:
   - sessions 테이블에 세션이 생성되었으며, 활성 상태에서 시작하여 테스트 종료 시 완료 상태로 변경됨
   - 세션 요약도 함께 저장됨

3. 핀(Pin) 생성 및 상태 관리:
   - pins 테이블에 두 개의 핀이 생성됨
   - 하나는 중요도 4로 완료 상태(completed)로 변경됨
   - 다른 하나는 중요도 5로 열린 상태(open)로 유지됨
   - 태그도 함께 저장됨

4. 리드 타임 계산:
   - 완료된 핀에 대해 리드 타임이 계산되어 저장됨

5. 승격 제안 기능:
   - 중요도가 4 이상이고 완료된 핀에 대해 승격 제안이 적절히 판단됨

이 모든 데이터가 실제 ./data/memories.db SQLite 데이터베이스에 저장되어 있으며, 영구적으로 유지됩니다.
    """

    # MCP를 통해 메모리 추가 명령
    add_command = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "add",
            "arguments": {
                "content": work_tracking_content,
                "project_id": "mcp-work-tracking-tests",
                "category": "task",
                "source": "mcp-client-script",
                "tags": ["work-tracking", "testing", "mcp", "pin", "session", "project"]
            }
        }
    }

    print("📝 MCP를 통해 메모리 추가...")
    result = send_mcp_command(add_command)

    if 'error' in result:
        print(f"❌ 메모리 추가 실패: {result['error']}")
        return False
    else:
        result_data = json.loads(result['result']['content'][0]['text'])
        print(f"✅ 메모리 추가 성공: {result_data}")
        # 응답 데이터 구조 확인
        if 'id' in result_data:
            print(f"   ID: {result_data['id']}")
        if 'status' in result_data:
            print(f"   상태: {result_data['status']}")
        if 'created_at' in result_data:
            print(f"   생성 시간: {result_data['created_at']}")

    # 검색 테스트 명령
    search_command = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "search",
            "arguments": {
                "query": "Work Tracking 테스트",
                "project_id": "mcp-work-tracking-tests",
                "limit": 5
            }
        }
    }

    print("🔍 MCP를 통해 검색 테스트...")
    result = send_mcp_command(search_command)

    if 'error' in result:
        print(f"❌ 검색 실패: {result['error']}")
        return False
    else:
        result_data = json.loads(result['result']['content'][0]['text'])
        print(f"✅ 검색 성공: {len(result_data['results'])}개 결과 발견")
        
        if result_data['results']:
            first_result = result_data['results'][0]
            print(f"   첫 번째 결과 ID: {first_result['id']}")
            print(f"   내용 미리보기: {first_result['content'][:100]}...")

    print("\n🎉 MCP 클라이언트를 통한 메모리 저장 테스트 성공!")
    return True


if __name__ == "__main__":
    success = save_work_tracking_via_mcp_client()
    sys.exit(0 if success else 1)