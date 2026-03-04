"""ANSI color utilities for CLI output (no emojis)."""

import os
import sys


def _supports_color() -> bool:
    """Check if the terminal supports ANSI color codes."""
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty"):
        return False
    return sys.stdout.isatty()


_COLOR = _supports_color()

# ANSI escape codes
BOLD = "\033[1m" if _COLOR else ""
DIM = "\033[2m" if _COLOR else ""
RED = "\033[31m" if _COLOR else ""
GREEN = "\033[32m" if _COLOR else ""
YELLOW = "\033[33m" if _COLOR else ""
CYAN = "\033[36m" if _COLOR else ""
RESET = "\033[0m" if _COLOR else ""


def ok(msg: str) -> str:
    """Green text for success."""
    return f"{GREEN}{msg}{RESET}"


def warn(msg: str) -> str:
    """Yellow text for warnings."""
    return f"{YELLOW}{msg}{RESET}"


def err(msg: str) -> str:
    """Red text for errors."""
    return f"{RED}{msg}{RESET}"


def info(msg: str) -> str:
    """Cyan text for informational messages."""
    return f"{CYAN}{msg}{RESET}"


def bold(msg: str) -> str:
    """Bold text."""
    return f"{BOLD}{msg}{RESET}"


def dim(msg: str) -> str:
    """Dimmed text."""
    return f"{DIM}{msg}{RESET}"


def header(msg: str) -> str:
    """Section header: bold cyan."""
    return f"{BOLD}{CYAN}{msg}{RESET}"
