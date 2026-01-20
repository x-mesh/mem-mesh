#!/usr/bin/env python3
"""
MCP 서버를 실행하는 스크립트
"""

import subprocess
import sys
import os
import signal
import time


def run_mcp_server():
    """MCP 서버 실행"""
    # 환경변수 설정
    env = os.environ.copy()
    env['MEM_MESH_STORAGE_MODE'] = 'direct'  # 직접 DB 접근
    env['MEM_MESH_IGNORE_SSL'] = 'true'

    # MCP 서버 시작
    print("🚀 MCP 서버 시작...")
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

    print("📡 Initialize 요청 전송...")
    process.stdin.write(__import__('json').dumps(init_request) + '\n')
    process.stdin.flush()

    # 응답 읽기
    response = process.stdout.readline()
    init_response = __import__('json').loads(response)
    print(f"✅ Initialize 응답: {init_response['result']['serverInfo']['name']}")

    print(f"MCP 서버가 실행 중입니다. PID: {process.pid}")
    print("이제 다른 프로그램에서 이 서버와 통신할 수 있습니다.")
    
    # 서버가 계속 실행되도록 유지
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n서버 종료 중...")
        process.terminate()
        process.wait()
        print("서버가 종료되었습니다.")


if __name__ == "__main__":
    run_mcp_server()