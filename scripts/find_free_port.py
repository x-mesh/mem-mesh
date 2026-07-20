#!/usr/bin/env python3
"""Print the first free TCP port on 127.0.0.1, starting from a base port.

Used by `make dev` in worktrees without a .env so multiple checkouts
(e.g. personal + team-hub) can run concurrently without a port clash.
"""

import socket
import sys


def find_free_port(base: int, limit: int = 100) -> int:
    for port in range(base, base + limit):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"no free port found in range [{base}, {base + limit})")


if __name__ == "__main__":
    base = int(sys.argv[1]) if len(sys.argv) > 1 else 8010
    print(find_free_port(base))
