#!/usr/bin/env python3
"""
MCP/SSE 프로토콜을 통한 메모리 검색 디버깅 스크립트

Usage:
    python scripts/debug_mcp_sse_search.py --category bug --limit 10
    python scripts/debug_mcp_sse_search.py --query "search query" --project mem-mesh
"""

import asyncio
import json
import sys
from typing import Optional
import httpx
import argparse


class MCPSSEClient:
    """MCP SSE 프로토콜 클라이언트"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.mcp_endpoint = f"{base_url}/mcp/sse"
        
    async def call_tool(
        self,
        tool_name: str,
        arguments: dict,
        timeout: float = 30.0
    ) -> dict:
        """MCP 도구 호출"""
        
        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        print(f"\n📤 Request to {self.mcp_endpoint}")
        print(f"Tool: {tool_name}")
        print(f"Arguments: {json.dumps(arguments, indent=2, ensure_ascii=False)}")
        print("-" * 80)
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(
                    self.mcp_endpoint,
                    json=request_data,
                    headers={"Content-Type": "application/json"}
                )
                
                print(f"📥 Response Status: {response.status_code}")
                
                if response.status_code != 200:
                    print(f"❌ Error: {response.text}")
                    return {"error": response.text}
                
                # 디버깅: raw 응답 출력
                print(f"\n🔍 Raw Response:")
                print(response.text[:500])  # 처음 500자만
                print("-" * 80)
                
                # 응답 파싱 (SSE 또는 일반 JSON-RPC)
                response_text = response.text.strip()
                
                # SSE 형식 체크
                if response_text.startswith('data: '):
                    # SSE 응답 파싱
                    lines = response_text.split('\n')
                    result = None
                    
                    for line in lines:
                        if line.startswith('data: '):
                            data = json.loads(line[6:])
                            if 'result' in data:
                                result = data['result']
                            elif 'error' in data:
                                print(f"❌ MCP Error: {data['error']}")
                                return data
                    
                    if result is None:
                        print(f"⚠️  Warning: No 'result' field found in SSE response")
                        return {"error": "No result in response", "raw": response_text}
                    
                    return result
                else:
                    # 일반 JSON-RPC 응답
                    try:
                        data = json.loads(response_text)
                        if 'result' in data:
                            return data['result']
                        elif 'error' in data:
                            print(f"❌ MCP Error: {data['error']}")
                            return data
                        else:
                            print(f"⚠️  Warning: No 'result' or 'error' field in response")
                            return {"error": "Invalid response format", "raw": response_text}
                    except json.JSONDecodeError as e:
                        print(f"❌ JSON Parse Error: {e}")
                        return {"error": f"JSON parse error: {e}", "raw": response_text}
                
            except Exception as e:
                print(f"❌ Exception: {e}")
                return {"error": str(e)}


async def search_memories(
    query: str,
    category: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: int = 10,
    base_url: str = "http://localhost:8000"
):
    """메모리 검색"""
    
    client = MCPSSEClient(base_url)
    
    arguments = {
        "query": query,
        "limit": limit,
        "response_format": "standard"
    }
    
    if category:
        arguments["category"] = category
    if project_id:
        arguments["project_id"] = project_id
    
    result = await client.call_tool("search", arguments)
    
    if result and "error" not in result:
        print("\n✅ Search Results:")
        print("=" * 80)
        
        # content 배열에서 결과 추출
        if isinstance(result, list) and len(result) > 0:
            content = result[0].get("content", [])
            
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        try:
                            data = json.loads(item.get("text", "{}"))
                            
                            if "results" in data:
                                results = data["results"]
                                print(f"\nFound {len(results)} results:")
                                print("-" * 80)
                                
                                for i, memory in enumerate(results, 1):
                                    print(f"\n{i}. Memory ID: {memory.get('id', 'N/A')}")
                                    print(f"   Category: {memory.get('category', 'N/A')}")
                                    print(f"   Project: {memory.get('project_id', 'N/A')}")
                                    print(f"   Score: {memory.get('score', 0):.4f}")
                                    print(f"   Created: {memory.get('created_at', 'N/A')}")
                                    
                                    content_text = memory.get('content', '')
                                    if len(content_text) > 200:
                                        content_text = content_text[:200] + "..."
                                    print(f"   Content: {content_text}")
                                    
                                    tags = memory.get('tags', [])
                                    if tags:
                                        print(f"   Tags: {', '.join(tags)}")
                            else:
                                print(json.dumps(data, indent=2, ensure_ascii=False))
                        except json.JSONDecodeError:
                            print(item.get("text", ""))
            else:
                print(json.dumps(content, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("\n❌ Search failed")
        if result:
            print(json.dumps(result, indent=2, ensure_ascii=False))


async def add_memory(
    content: str,
    category: str = "task",
    project_id: Optional[str] = None,
    tags: Optional[list] = None,
    base_url: str = "http://localhost:8000"
):
    """메모리 추가"""
    
    client = MCPSSEClient(base_url)
    
    arguments = {
        "content": content,
        "category": category
    }
    
    if project_id:
        arguments["project_id"] = project_id
    if tags:
        arguments["tags"] = tags
    
    result = await client.call_tool("add", arguments)
    
    if result and "error" not in result:
        print("\n✅ Memory Added:")
        print("=" * 80)
        
        # content 배열에서 결과 추출
        if isinstance(result, list) and len(result) > 0:
            content_item = result[0].get("content", [])
            
            if isinstance(content_item, list):
                for item in content_item:
                    if item.get("type") == "text":
                        try:
                            data = json.loads(item.get("text", "{}"))
                            print(f"Memory ID: {data.get('id', 'N/A')}")
                            print(f"Category: {data.get('category', 'N/A')}")
                            print(f"Project: {data.get('project_id', 'N/A')}")
                            print(f"Tags: {', '.join(data.get('tags', []))}")
                            print(f"Created: {data.get('created_at', 'N/A')}")
                        except json.JSONDecodeError:
                            print(item.get("text", ""))
            else:
                print(json.dumps(content_item, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("\n❌ Add memory failed")
        if result:
            print(json.dumps(result, indent=2, ensure_ascii=False))


async def get_stats(
    project_id: Optional[str] = None,
    base_url: str = "http://localhost:8000"
):
    """메모리 통계 조회"""
    
    client = MCPSSEClient(base_url)
    
    arguments = {}
    if project_id:
        arguments["project_id"] = project_id
    
    result = await client.call_tool("stats", arguments)
    
    if result and "error" not in result:
        print("\n✅ Statistics:")
        print("=" * 80)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("\n❌ Stats failed")


def main():
    parser = argparse.ArgumentParser(
        description="MCP/SSE 프로토콜을 통한 메모리 검색 디버깅"
    )
    
    # 서브커맨드 추가
    subparsers = parser.add_subparsers(dest="command", help="명령어")
    
    # search 서브커맨드
    search_parser = subparsers.add_parser("search", help="메모리 검색")
    search_parser.add_argument(
        "--query",
        type=str,
        default="bug error issue",
        help="검색 쿼리"
    )
    search_parser.add_argument(
        "--category",
        type=str,
        choices=["task", "bug", "idea", "decision", "incident", "code_snippet", "git-history"],
        help="카테고리 필터"
    )
    search_parser.add_argument(
        "--project",
        type=str,
        help="프로젝트 ID 필터"
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="결과 개수 제한 (기본: 10)"
    )
    
    # add 서브커맨드
    add_parser = subparsers.add_parser("add", help="메모리 추가")
    add_parser.add_argument(
        "--content",
        type=str,
        required=True,
        help="메모리 내용"
    )
    add_parser.add_argument(
        "--category",
        type=str,
        default="task",
        choices=["task", "bug", "idea", "decision", "incident", "code_snippet", "git-history"],
        help="카테고리 (기본: task)"
    )
    add_parser.add_argument(
        "--project",
        type=str,
        help="프로젝트 ID"
    )
    add_parser.add_argument(
        "--tags",
        type=str,
        help="태그 (쉼표로 구분)"
    )
    
    # stats 서브커맨드
    stats_parser = subparsers.add_parser("stats", help="통계 조회")
    stats_parser.add_argument(
        "--project",
        type=str,
        help="프로젝트 ID 필터"
    )
    
    # 공통 옵션
    parser.add_argument(
        "--url",
        type=str,
        default="http://localhost:8000",
        help="서버 URL (기본: http://localhost:8000)"
    )
    
    args = parser.parse_args()
    
    # 명령어가 없으면 search를 기본으로
    if not args.command:
        args.command = "search"
        args.query = "bug error issue"
        args.category = None
        args.project = None
        args.limit = 10
    
    if args.command == "search":
        asyncio.run(search_memories(
            query=args.query,
            category=args.category,
            project_id=args.project,
            limit=args.limit,
            base_url=args.url
        ))
    elif args.command == "add":
        tags = args.tags.split(",") if args.tags else None
        asyncio.run(add_memory(
            content=args.content,
            category=args.category,
            project_id=args.project,
            tags=tags,
            base_url=args.url
        ))
    elif args.command == "stats":
        asyncio.run(get_stats(
            project_id=args.project,
            base_url=args.url
        ))


if __name__ == "__main__":
    main()
