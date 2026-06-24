#!/usr/bin/env python3
import sys

from app.cli import main
from app.core.version import __VERSION__

if len(sys.argv) == 1:
    print(f"mem-mesh {__VERSION__}")

main.main()
