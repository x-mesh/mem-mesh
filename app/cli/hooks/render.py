"""Verbose rendering helpers — syntax-highlighted config with real line numbers.

The ``-v/--verbose`` surfaces show the *actual* installed config so the operator
can debug it directly. We render the real config file (at its real ``file:line``)
with a JSON/TOML lexer and a distinct background so the block stands out. When
``rich`` is unavailable we degrade to numbered plain lines so output is never
broken on a minimal install.
"""

import os
from pathlib import Path
from typing import Optional, Tuple

# Distinct background so the code block reads as a separate panel from the
# surrounding plain-text report (works on both light and dark terminals).
_CODE_BG = "#1b1d23"


def _rich_console() -> Optional[object]:
    """Return a rich Console, or None when rich is unavailable / color disabled."""
    if os.environ.get("NO_COLOR"):
        return None
    try:
        from rich.console import Console

        return Console()
    except Exception:
        return None


def _short_path(path: str) -> str:
    """Collapse the home directory to ``~`` for a compact, clickable path."""
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path


def _lexer_for(path: str) -> str:
    return "toml" if path.endswith(".toml") else "json"


def render_entry_source(
    config_path: str,
    entry_lines: Optional[Tuple[int, int]],
    fallback_json: str = "",
    indent: str = "  ",
) -> None:
    """Show an MCP entry from its real config file at the real ``file:line``.

    Prints a ``<path>:<start>`` header (clickable) then the actual file slice
    with its real line numbers. Falls back to ``fallback_json`` (a re-serialized
    entry numbered from 1) only when the real location is unknown.
    """
    if config_path and entry_lines:
        start, end = entry_lines
        print(f"{indent}{_short_path(config_path)}:{start}")
        if _render_file_slice(config_path, start, end, indent):
            return
    if fallback_json:
        render_json_block(fallback_json, indent)


def _render_file_slice(path: str, start: int, end: int, indent: str = "  ") -> bool:
    """Render lines [start, end] of ``path`` with their real line numbers.

    Returns True on success. rich path uses a JSON/TOML lexer, a distinct
    background, and ``line_range`` so the numbers reflect the actual file.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return False

    console = _rich_console()
    if console is not None:
        try:
            from rich.syntax import Syntax

            syntax = Syntax(
                text,
                _lexer_for(path),
                line_numbers=True,
                line_range=(start, end),
                theme="ansi_dark",
                background_color=_CODE_BG,
                word_wrap=False,
            )
            console.print(syntax)
            return True
        except Exception:
            pass

    # Plain fallback: real line numbers, no dependency.
    lines = text.splitlines()
    width = len(str(end))
    for n in range(start, end + 1):
        if 1 <= n <= len(lines):
            print(f"{indent}{str(n).rjust(width)} | {lines[n - 1]}")
    return True


def render_json_block(text: str, indent: str = "    ") -> None:
    """Print a JSON string with line numbers, syntax-highlighted when possible.

    Fallback for when the real file location is unknown (numbers start at 1).
    ``indent`` is prepended to each plain line so the block nests under a section.
    """
    if not text:
        return

    console = _rich_console()
    if console is not None:
        try:
            from rich.syntax import Syntax

            syntax = Syntax(
                text,
                "json",
                line_numbers=True,
                theme="ansi_dark",
                background_color=_CODE_BG,
                word_wrap=False,
            )
            console.print(syntax)
            return
        except Exception:
            pass

    lines = text.splitlines()
    width = len(str(len(lines)))
    for i, line in enumerate(lines, 1):
        print(f"{indent}{str(i).rjust(width)} | {line}")
