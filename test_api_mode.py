#!/usr/bin/env python3
"""API 모드 MCP 서버 테스트"""

import json
import subprocess
import sys
import time
import threading
from queue import Queue, Empty
import os

def read_output(pipe, queue):
    """백그라운드에서 출력을 읽는 함수"""
    try:
        for line in iter(pipe.readline, ''):
            if line:
                queue.put(line.strip())
    except:
        pass

def test_api_mode_mcp():
    """API 모드 MCP 서버 테스트"""
    
    print("🚀 API 모드 MCP 서버 테스트 시작...")
    
    # 환경변수 설정
    env = os.environ.copy()
    env['MEM_MESH_STORAGE_MODE'] = 'api'
    env['MEM_MESH_API_BASE_URL'] = 'http://localhost:8002'
    
    # MCP 서버 시작 (API 모드)
    process = subprocess.Popen(
        [sys.executable, "-m", "app.mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0,
        env=env
    )
    
    # 출력 읽기를 위한 큐와 스레드
    stdout_queue = Queue()
    stderr_queue = Queue()
    
    stdout_thread = threading.Thread(target=read_output, args=(process.stdout, stdout_queue))
    stderr_thread = threading.Thread(target=read_output, args=(process.stderr, stderr_queue))
    
    stdout_thread.daemon = True
    stderr_thread.daemon = True
    stdout_thread.start()
    stderr_thread.start()
    
    try:
        # 서버 시작 대기
        print("⏳ API 모드 서버 시작 대기 중...")
        time.sleep(3)
        
        # stderr에서 시작 로그 확인
        while True:
            try:
                stderr_line = stderr_queue.get_nowait()
                if "Starting MCP server" in stderr_line:
                    print(f"✅ 서버 시작됨: {stderr_line}")
                    break
                elif "api mode" in stderr_line.lower():
                    print(f"✅ API 모드 확인: {stderr_line}")
            except Empty:
                break
        
        # 1. 초기화
        print("\n1️⃣ 초기화 테스트...")
        init_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "api-test-client", "version": "1.0"}
            }
        }
        
        process.stdin.write(json.dumps(init_msg) + "\n")
        process.stdin.flush()
        
        # 응답 대기
        time.sleep(1)
        try:
            response = stdout_queue.get(timeout=3)
            print(f"✅ 초기화 응답: {response}")
            
            try:
                resp_data = json.loads(response)
                if resp_data.get("id") == 1:
                    print("✅ API 모드 초기화 성공!")
                else:
                    print(f"⚠️ 예상과 다른 응답: {resp_data}")
            except json.JSONDecodeError:
                print(f"⚠️ JSON 파싱 실패: {response}")
                
        except Empty:
            print("❌ 초기화 응답 없음")
            return
        
        # 2. API 모드에서 메모리 추가 테스트
        print("\n2️⃣ API 모드 메모리 추가 테스트...")
        add_msg = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "add",
                "arguments": {
                    "content": "API 모드에서 FastMCP 기반 MCP 서버 테스트 중입니다. FastAPI를 통해 데이터에 접근하고 있습니다.",
                    "project_id": "api-mode-test",
                    "category": "task",
                    "tags": ["api-mode", "fastmcp", "test"]
                }
            }
        }
        
        process.stdin.write(json.dumps(add_msg) + "\n")
        process.stdin.flush()
        
        time.sleep(2)
        try:
            response = stdout_queue.get(timeout=5)
            print(f"✅ API 모드 메모리 추가 응답: {response}")
            
            try:
                resp_data = json.loads(response)
                if "result" in resp_data and "structuredContent" in resp_data["result"]:
                    structured = resp_data["result"]["structuredContent"]
                    if "id" in structured:
                        memory_id = structured["id"]
                        print(f"✅ API 모드 메모리 추가 성공! ID: {memory_id}")
                    else:
                        print(f"⚠️ structuredContent에 ID가 없음: {structured}")
                else:
                    print(f"⚠️ 예상과 다른 응답: {resp_data}")
            except json.JSONDecodeError:
                print(f"⚠️ JSON 파싱 실패: {response}")
                
        except Empty:
            print("❌ API 모드 메모리 추가 응답 없음")
        
        # 3. API 모드에서 검색 테스트
        print("\n3️⃣ API 모드 검색 테스트...")
        search_msg = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {
                    "query": "API 모드 테스트",
                    "limit": 3
                }
            }
        }
        
        process.stdin.write(json.dumps(search_msg) + "\n")
        process.stdin.flush()
        
        time.sleep(2)
        try:
            response = stdout_queue.get(timeout=5)
            print(f"✅ API 모드 검색 응답: {response}")
            
            try:
                resp_data = json.loads(response)
                if "result" in resp_data and "structuredContent" in resp_data["result"]:
                    search_result = resp_data["result"]["structuredContent"]
                    if "memories" in search_result:
                        memories = search_result["memories"]
                        print(f"✅ API 모드 검색 결과: {len(memories)}개 메모리 발견")
                        for memory in memories:
                            print(f"   - ID: {memory.get('id')}, 내용: {memory.get('content', '')[:50]}...")
                    else:
                        print(f"⚠️ 검색 결과에 memories가 없음: {search_result}")
                else:
                    print(f"⚠️ 예상과 다른 검색 응답: {resp_data}")
            except json.JSONDecodeError:
                print(f"⚠️ JSON 파싱 실패: {response}")
                
        except Empty:
            print("❌ API 모드 검색 응답 없음")
        
        print("\n🎉 API 모드 MCP 서버 테스트 완료!")
        
    except Exception as e:
        print(f"❌ 테스트 중 오류 발생: {e}")
        
    finally:
        print("\n🛑 API 모드 서버 종료 중...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

if __name__ == "__main__":
    test_api_mode_mcp()