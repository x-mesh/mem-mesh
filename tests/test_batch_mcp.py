#!/usr/bin/env python3
"""Test MCP batch_operations via SSE endpoint."""

import json
import requests
import time

BASE_URL = "http://localhost:8000"
MCP_SSE_URL = f"{BASE_URL}/mcp/sse"

def test_batch_operations():
    """Test batch_operations tool via MCP SSE."""
    
    # Prepare batch operations request
    batch_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "batch_operations",
            "arguments": {
                "operations": [
                    {
                        "type": "add",
                        "content": "Batch test memory 1: Testing batch operations via MCP SSE",
                        "project_id": "test-batch",
                        "category": "task",
                        "tags": ["batch-test", "mcp-sse"]
                    },
                    {
                        "type": "add",
                        "content": "Batch test memory 2: Second item in batch operation",
                        "project_id": "test-batch",
                        "category": "task",
                        "tags": ["batch-test", "mcp-sse"]
                    },
                    {
                        "type": "search",
                        "query": "batch test",
                        "project_id": "test-batch",
                        "limit": 5
                    }
                ]
            }
        }
    }
    
    print("=" * 60)
    print("Testing MCP batch_operations via SSE")
    print("=" * 60)
    print(f"\nEndpoint: {MCP_SSE_URL}")
    print(f"\nRequest payload:")
    print(json.dumps(batch_request, indent=2))
    
    try:
        # Send request
        print("\n" + "-" * 60)
        print("Sending request...")
        response = requests.post(
            MCP_SSE_URL,
            json=batch_request,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            result = response.json()
            print("\n" + "-" * 60)
            print("Response:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
            # Parse results
            if "result" in result:
                batch_result = result["result"]
                if isinstance(batch_result, dict) and "results" in batch_result:
                    print("\n" + "=" * 60)
                    print("Batch Operation Results:")
                    print("=" * 60)
                    
                    for i, op_result in enumerate(batch_result["results"], 1):
                        print(f"\nOperation {i}:")
                        print(f"  Type: {op_result.get('type', 'unknown')}")
                        print(f"  Success: {op_result.get('success', False)}")
                        
                        if op_result.get("success"):
                            if op_result["type"] == "add":
                                print(f"  Memory ID: {op_result.get('memory_id', 'N/A')}")
                            elif op_result["type"] == "search":
                                results = op_result.get("results", [])
                                print(f"  Found: {len(results)} memories")
                                for mem in results[:3]:
                                    print(f"    - {mem.get('id', 'N/A')[:8]}... : {mem.get('content', '')[:50]}...")
                                    print(f"      Similarity: {mem.get('similarity_score', 0):.4f}")
                        else:
                            print(f"  Error: {op_result.get('error', 'Unknown error')}")
                    
                    print("\n" + "=" * 60)
                    print(f"✓ Batch operations completed successfully!")
                    print(f"  Total operations: {len(batch_result['results'])}")
                    print(f"  Successful: {sum(1 for r in batch_result['results'] if r.get('success'))}")
                    print(f"  Failed: {sum(1 for r in batch_result['results'] if not r.get('success'))}")
                    print(f"  Tokens saved: {batch_result.get('tokens_saved', 0)}")
                    print("=" * 60)
                    return True
        else:
            print(f"\n✗ Request failed with status {response.status_code}")
            print(f"Response: {response.text[:500]}")
            return False
            
    except requests.exceptions.Timeout:
        print("\n✗ Request timed out")
        return False
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_batch_operations()
    exit(0 if success else 1)
