#!/usr/bin/env python3
"""간단한 MCP 서버 테스트"""

import json
import subprocess
import sys
import time
import threading
from queue import Queue, Empty

def read_output(pipe, queue):
    """백그라운드에서 출력을 읽는 함수"""
    try:
        for line in iter(pipe.readline, ''):
            if line:
                queue.put(line.strip())
    except Exception:
        pass

def test_mcp():
    """MCP 서버 간단 테스트"""
    
    print("🚀 MCP 서버 테스트 시작...")
    
    # MCP 서버 시작
    process = subprocess.Popen(
        [sys.executable, "-m", "app.mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0
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
        print("⏳ 서버 시작 대기 중...")
        time.sleep(3)
        
        # stderr에서 시작 로그 확인
        while True:
            try:
                stderr_line = stderr_queue.get_nowait()
                if "Starting MCP server" in stderr_line:
                    print(f"✅ 서버 시작됨: {stderr_line}")
                    break
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
                "clientInfo": {"name": "test-client", "version": "1.0"}
            }
        }
        
        process.stdin.write(json.dumps(init_msg) + "\n")
        process.stdin.flush()
        
        # 응답 대기
        time.sleep(1)
        try:
            response = stdout_queue.get(timeout=2)
            print(f"✅ 초기화 응답: {response}")
            
            # JSON 파싱 시도
            try:
                resp_data = json.loads(response)
                if resp_data.get("id") == 1:
                    print("✅ 초기화 성공!")
                else:
                    print(f"⚠️ 예상과 다른 응답: {resp_data}")
            except json.JSONDecodeError:
                print(f"⚠️ JSON 파싱 실패: {response}")
                
        except Empty:
            print("❌ 초기화 응답 없음")
            return
        
        # 2. 도구 목록 조회
        print("\n2️⃣ 도구 목록 조회...")
        tools_msg = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list"
        }
        
        process.stdin.write(json.dumps(tools_msg) + "\n")
        process.stdin.flush()
        
        time.sleep(1)
        try:
            response = stdout_queue.get(timeout=2)
            print(f"✅ 도구 목록 응답: {response}")
            
            try:
                resp_data = json.loads(response)
                if "result" in resp_data and "tools" in resp_data["result"]:
                    tools = resp_data["result"]["tools"]
                    print(f"✅ 사용 가능한 도구 수: {len(tools)}")
                    for tool in tools:
                        print(f"   - {tool.get('name', 'Unknown')}: {tool.get('description', 'No description')}")
                else:
                    print(f"⚠️ 예상과 다른 도구 목록 응답: {resp_data}")
            except json.JSONDecodeError:
                print(f"⚠️ JSON 파싱 실패: {response}")
                
        except Empty:
            print("❌ 도구 목록 응답 없음")
            return
        
        # 3. 메모리 추가 테스트
        print("\n3️⃣ 메모리 추가 테스트...")
        add_msg = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "add",
                "arguments": {
                    "content": "FastMCP 기반 MCP 서버 테스트 중입니다. 새로운 아키텍처가 잘 작동하는지 확인하고 있습니다.",
                    "project_id": "mcp-test",
                    "category": "task",
                    "tags": ["test", "fastmcp", "architecture"]
                }
            }
        }
        
        process.stdin.write(json.dumps(add_msg) + "\n")
        process.stdin.flush()
        
        time.sleep(1)
        try:
            response = stdout_queue.get(timeout=3)
            print(f"✅ 메모리 추가 응답: {response}")
            
            try:
                resp_data = json.loads(response)
                if "result" in resp_data:
                    result = resp_data["result"]
                    # FastMCP는 structuredContent에 실제 데이터를 반환
                    if "structuredContent" in result:
                        structured = result["structuredContent"]
                        if "id" in structured:
                            memory_id = structured["id"]
                            print(f"✅ 메모리 추가 성공! ID: {memory_id}")
                            
                            # 4. 메모리 검색 테스트
                            print("\n4️⃣ 메모리 검색 테스트...")
                            search_msg = {
                                "jsonrpc": "2.0",
                                "id": 4,
                                "method": "tools/call",
                                "params": {
                                    "name": "search",
                                    "arguments": {
                                        "query": "FastMCP 테스트",
                                        "limit": 5
                                    }
                                }
                            }
                            
                            process.stdin.write(json.dumps(search_msg) + "\n")
                            process.stdin.flush()
                            
                            time.sleep(1)
                            try:
                                search_response = stdout_queue.get(timeout=3)
                                print(f"✅ 검색 응답: {search_response}")
                                
                                try:
                                    search_data = json.loads(search_response)
                                    if "result" in search_data and "structuredContent" in search_data["result"]:
                                        search_result = search_data["result"]["structuredContent"]
                                        if "memories" in search_result:
                                            memories = search_result["memories"]
                                            print(f"✅ 검색 결과: {len(memories)}개 메모리 발견")
                                            for memory in memories:
                                                print(f"   - ID: {memory.get('id')}, 내용: {memory.get('content', '')[:50]}...")
                                        else:
                                            print(f"⚠️ 검색 결과에 memories가 없음: {search_result}")
                                    else:
                                        print(f"⚠️ 예상과 다른 검색 응답: {search_data}")
                                except json.JSONDecodeError:
                                    print(f"⚠️ 검색 응답 JSON 파싱 실패: {search_response}")
                                    
                            except Empty:
                                print("❌ 검색 응답 없음")
                            
                            # 5. 통계 조회 테스트
                            print("\n5️⃣ 통계 조회 테스트...")
                            stats_msg = {
                                "jsonrpc": "2.0",
                                "id": 5,
                                "method": "tools/call",
                                "params": {
                                    "name": "stats",
                                    "arguments": {}
                                }
                            }
                            
                            process.stdin.write(json.dumps(stats_msg) + "\n")
                            process.stdin.flush()
                            
                            time.sleep(1)
                            try:
                                stats_response = stdout_queue.get(timeout=3)
                                print(f"✅ 통계 응답: {stats_response}")
                                
                                try:
                                    stats_data = json.loads(stats_response)
                                    if "result" in stats_data and "structuredContent" in stats_data["result"]:
                                        stats = stats_data["result"]["structuredContent"]
                                        print("✅ 통계 조회 성공!")
                                        print(f"   - 총 메모리 수: {stats.get('total_memories', 0)}")
                                        print(f"   - 프로젝트 수: {stats.get('total_projects', 0)}")
                                    else:
                                        print(f"⚠️ 예상과 다른 통계 응답: {stats_data}")
                                except json.JSONDecodeError:
                                    print(f"⚠️ 통계 응답 JSON 파싱 실패: {stats_response}")
                                    
                            except Empty:
                                print("❌ 통계 응답 없음")
                                
                        else:
                            print(f"⚠️ structuredContent에 ID가 없음: {structured}")
                    else:
                        print(f"⚠️ result에 structuredContent가 없음: {result}")
                else:
                    print(f"⚠️ 예상과 다른 메모리 추가 응답: {resp_data}")
            except json.JSONDecodeError:
                print(f"⚠️ JSON 파싱 실패: {response}")
                
        except Empty:
            print("❌ 메모리 추가 응답 없음")
        
        print("\n🎉 MCP 서버 테스트 완료!")
        
    except Exception as e:
        print(f"❌ 테스트 중 오류 발생: {e}")
        
    finally:
        print("\n🛑 서버 종료 중...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

if __name__ == "__main__":
    test_mcp()