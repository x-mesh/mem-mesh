#!/usr/bin/env python3
from app.cli import main
from app.core.version import __VERSION__

print(f"mem-mesh {__VERSION__}")

main.main()
