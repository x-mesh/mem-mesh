#!/usr/bin/env python3
"""mem-mesh hooks installer — run directly without pip install.

Usage:
    python install-hooks.py                          # Interactive mode
    python install-hooks.py install --target cursor   # Direct install
    python install-hooks.py install --mode local      # Local storage mode
    python install-hooks.py status                    # Show status
    python install-hooks.py uninstall --target all    # Uninstall
"""

import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.cli.install_hooks import main  # noqa: E402

if __name__ == "__main__":
    main()
