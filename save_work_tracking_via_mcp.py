#!/usr/bin/env python3
"""
MCP를 사용하여 Work Tracking 테스트 결과를 메모리에 저장
"""

import asyncio
import json
import subprocess
import sys
import os


async def save_work_tracking_via_mcp():
    """MCP를 통해 Work Tracking 테스트 결과를 저장"""
    
    # 환경변수 설정
    env = os.environ.copy()
    env['MEM_MESH_STORAGE_MODE'] = 'direct'  # 직접 DB 접근
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

        # MCP를 통해 메모리 추가
        add_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "add",
                "arguments": {
                    "content": work_tracking_content,
                    "project_id": "mcp-work-tracking-tests",
                    "category": "testing",
                    "source": "mcp-test-script",
                    "tags": ["work-tracking", "testing", "mcp", "pin", "session", "project"]
                }
            }
        }

        print("📝 MCP를 통해 메모리 추가...")
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
            print(f"   상태: {result['status']}")
            print(f"   생성 시간: {result['created_at']}")

        # 검색 테스트
        search_request = {
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
            
            if result['results']:
                first_result = result['results'][0]
                print(f"   첫 번째 결과 ID: {first_result['id']}")
                print(f"   내용 미리보기: {first_result['content'][:100]}...")

        print("\n🎉 MCP를 통한 메모리 저장 테스트 성공!")
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
    success = asyncio.run(save_work_tracking_via_mcp())
    sys.exit(0 if success else 1)