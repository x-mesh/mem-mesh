#!/usr/bin/env python3
"""
Pure MCP Server Entry Point

Usage: python -m app.pure_mcp
"""

import asyncio
from .server import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
