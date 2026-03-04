#!/usr/bin/env python3
"""
로컬 DB에서 리모트 MCP SSE 서버로 메모리 동기화

Usage:
    python scripts/sync_to_remote_mcp.py --since 2026-01-28 --dry-run
    python scripts/sync_to_remote_mcp.py --since 2026-01-28
    python scripts/sync_to_remote_mcp.py --since 2026-01-20 --limit 50
"""

import asyncio
import aiohttp
import sqlite3
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

ROOT_DIR = Path(__file__).parent.parent
LOCAL_DB = ROOT_DIR / "data" / "memories.db"
REMOTE_MCP_URL = "https://meme.24x365.online/mcp/sse"


async def get_remote_memory_ids(session: aiohttp.ClientSession) -> set:
    """리모트 서버에서 모든 메모리 ID를 가져옵니다 (MCP search 사용)."""
    print("📡 리모트 서버에서 메모리 ID 조회 중...")
    
    # MCP initialize
    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "sync-script", "version": "1.0.0"}
        }
    }
    
    async with session.post(REMOTE_MCP_URL, json=init_payload) as resp:
        if resp.status != 200:
            print(f"❌ MCP initialize 실패: {resp.status}")
            return set()
        result = await resp.json()
        session_id = resp.headers.get("Mcp-Session-Id")
    
    # 모든 메모리 검색 (빈 쿼리로 최대한 많이)
    # 여러 번 호출하여 모든 ID 수집
    all_ids = set()
    
    # stats로 총 개수 확인
    stats_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "stats",
            "arguments": {}
        }
    }
    
    headers = {"Mcp-Session-Id": session_id} if session_id else {}
    async with session.post(REMOTE_MCP_URL, json=stats_payload, headers=headers) as resp:
        if resp.status == 200:
            result = await resp.json()
            content = result.get("result", {}).get("content", [])
            if content:
                stats_text = content[0].get("text", "{}")
                stats = json.loads(stats_text)
                total = stats.get("total_memories", 0)
                print(f"   리모트 총 메모리: {total}")
    
    return all_ids


def get_local_memories(
    since: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """로컬 DB에서 메모리를 가져옵니다.
    
    Args:
        since: 이 날짜 이후의 메모리만 가져옴 (YYYY-MM-DD 형식)
        limit: 가져올 메모리 수 제한
        offset: 시작 위치
    """
    conn = sqlite3.connect(LOCAL_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = """
        SELECT id, content, project_id, category, source, tags, created_at, updated_at
        FROM memories
    """
    
    params = []
    
    if since:
        # YYYY-MM-DD 형식을 datetime으로 변환하여 시작 시점 설정
        try:
            since_date = datetime.strptime(since, "%Y-%m-%d")
            since_str = since_date.strftime("%Y-%m-%d 00:00:00")
            query += " WHERE created_at >= ?"
            params.append(since_str)
        except ValueError:
            print(f"⚠️  날짜 형식 오류: {since} (YYYY-MM-DD 형식 필요)")
    
    query += " ORDER BY created_at ASC"  # 오래된 것부터 동기화
    
    if limit:
        query += f" LIMIT {limit} OFFSET {offset}"
    
    cursor.execute(query, params)
    memories = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return memories


async def add_memory_to_remote(
    session: aiohttp.ClientSession,
    memory: Dict[str, Any],
    session_id: Optional[str] = None
) -> tuple[str, Optional[str]]:
    """리모트 서버에 메모리를 추가합니다.
    
    Returns:
        tuple: (status, memory_id)
        - status: "saved", "duplicate", "error"
        - memory_id: 생성/중복된 메모리 ID (에러 시 None)
    """
    
    # tags 파싱
    tags = memory.get("tags")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags) if tags else []
        except:
            tags = [t.strip() for t in tags.split(",") if t.strip()]
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "add",
            "arguments": {
                "content": memory["content"],
                "project_id": memory.get("project_id"),
                "category": memory.get("category", "task"),
                "tags": tags,
                "source": memory.get("source", "sync")
            }
        }
    }
    
    headers = {"Mcp-Session-Id": session_id} if session_id else {}
    
    try:
        async with session.post(REMOTE_MCP_URL, json=payload, headers=headers) as resp:
            if resp.status == 200:
                result = await resp.json()
                if "error" in result:
                    return ("error", None)
                
                # MCP 응답에서 결과 파싱
                content = result.get("result", {}).get("content", [])
                if content:
                    text = content[0].get("text", "{}")
                    data = json.loads(text)
                    status = data.get("status", "saved")
                    memory_id = data.get("id")
                    return (status, memory_id)
                
                return ("saved", None)
            return ("error", None)
    except Exception as e:
        print(f"   ❌ 에러: {e}")
        return ("error", None)


async def sync_memories(
    dry_run: bool = False,
    limit: Optional[int] = None,
    batch_size: int = 10,
    since: Optional[str] = None
):
    """메모리를 리모트 서버로 동기화합니다.
    
    Args:
        dry_run: True면 실제 전송 없이 미리보기만
        limit: 전송할 메모리 수 제한
        batch_size: 배치 크기
        since: 이 날짜 이후의 메모리만 동기화 (YYYY-MM-DD)
    """
    
    print("🔄 로컬 → 리모트 메모리 동기화\n")
    print(f"   로컬 DB: {LOCAL_DB}")
    print(f"   리모트: {REMOTE_MCP_URL}")
    if since:
        print(f"   날짜 필터: {since} 이후")
    print()
    
    # 로컬 메모리 가져오기
    memories = get_local_memories(since=since, limit=limit)
    print(f"📊 로컬 메모리: {len(memories)}개")
    
    if dry_run:
        print(f"\n🔍 DRY RUN 모드 - 실제로 전송하지 않습니다.\n")
        print("샘플 메모리 (최대 5개):")
        for i, mem in enumerate(memories[:5], 1):
            print(f"\n{i}. Project: {mem.get('project_id', 'N/A')}")
            print(f"   Category: {mem.get('category', 'N/A')}")
            print(f"   Content: {mem['content'][:80]}...")
            print(f"   Created: {mem['created_at']}")
        
        if len(memories) > 5:
            print(f"\n... 그 외 {len(memories) - 5}개")
        return
    
    # MCP 세션 초기화
    async with aiohttp.ClientSession() as session:
        # Initialize
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "sync-script", "version": "1.0.0"}
            }
        }
        
        print("\n📡 MCP 세션 초기화 중...")
        async with session.post(REMOTE_MCP_URL, json=init_payload) as resp:
            if resp.status != 200:
                print(f"❌ MCP initialize 실패: {resp.status}")
                return
            session_id = resp.headers.get("Mcp-Session-Id")
            print(f"   세션 ID: {session_id}")
        
        # 메모리 전송
        print(f"\n💾 메모리 전송 중 (배치 크기: {batch_size})...")
        
        saved_count = 0
        duplicate_count = 0
        error_count = 0
        
        for i, memory in enumerate(memories, 1):
            status, memory_id = await add_memory_to_remote(session, memory, session_id)
            
            if status == "saved":
                saved_count += 1
            elif status == "duplicate":
                duplicate_count += 1
            else:
                error_count += 1
            
            if i % batch_size == 0:
                print(f"   진행: {i}/{len(memories)} (저장: {saved_count}, 중복스킵: {duplicate_count}, 실패: {error_count})")
                await asyncio.sleep(0.1)  # Rate limiting
        
        print(f"\n✅ 완료!")
        print(f"   새로 저장: {saved_count}")
        print(f"   중복 스킵: {duplicate_count}")
        print(f"   실패: {error_count}")


def main():
    parser = argparse.ArgumentParser(description="로컬 메모리를 리모트 MCP 서버로 동기화")
    parser.add_argument("--dry-run", action="store_true", help="실제로 전송하지 않고 미리보기")
    parser.add_argument("--limit", type=int, help="전송할 메모리 수 제한")
    parser.add_argument("--batch-size", type=int, default=10, help="배치 크기 (기본: 10)")
    parser.add_argument(
        "--since",
        type=str,
        help="이 날짜 이후의 메모리만 동기화 (YYYY-MM-DD 형식, 예: 2026-01-28)"
    )
    
    args = parser.parse_args()
    
    # --since 없이 실행하면 경고
    if not args.since and not args.dry_run:
        print("⚠️  경고: --since 옵션 없이 실행하면 모든 메모리가 동기화됩니다.")
        print("   특정 날짜 이후만 동기화하려면: --since YYYY-MM-DD")
        print("   미리보기: --dry-run")
        confirm = input("\n계속하시겠습니까? (y/N): ")
        if confirm.lower() != 'y':
            print("취소되었습니다.")
            return
    
    asyncio.run(sync_memories(
        dry_run=args.dry_run,
        limit=args.limit,
        batch_size=args.batch_size,
        since=args.since
    ))


if __name__ == "__main__":
    main()
