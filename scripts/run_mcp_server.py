#!/usr/bin/env python3
"""
Script to run the MCP server.
"""

import subprocess
import sys
import os
import signal
import time


def run_mcp_server():
    """Run the MCP server"""
    # Set environment variables
    env = os.environ.copy()
    env['MEM_MESH_STORAGE_MODE'] = 'direct'  # Direct DB access
    env['MEM_MESH_IGNORE_SSL'] = 'true'

    # Start MCP server
    print("🚀 Starting MCP server...")
    process = subprocess.Popen(
        [sys.executable, '-m', 'app.mcp_stdio_pure'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )

    # Initialize request
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

    print("📡 Sending initialize request...")
    process.stdin.write(__import__('json').dumps(init_request) + '\n')
    process.stdin.flush()

    # Read response
    response = process.stdout.readline()
    init_response = __import__('json').loads(response)
    print(f"✅ Initialize response: {init_response['result']['serverInfo']['name']}")

    print(f"MCP server is running. PID: {process.pid}")
    print("Other programs can now communicate with this server.")

    # Keep the server running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down server...")
        process.terminate()
        process.wait()
        print("Server has been shut down.")


if __name__ == "__main__":
    run_mcp_server()
