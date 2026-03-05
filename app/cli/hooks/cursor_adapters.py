"""Cursor-specific hook script adapters.

These functions transform rendered hook scripts for Cursor compatibility.
Currently pass-through since Cursor supports the same hookSpecificOutput JSON
format as Claude Code. They serve as extension points for future Cursor-specific
adaptations (e.g. different stdin fields, output format changes).
"""


def adapt_cursor_before_submit_prompt(script: str) -> str:
    """Adapt UserPromptSubmit hook script for Cursor."""
    return script


def adapt_cursor_precompact(script: str) -> str:
    """Adapt PreCompact hook script for Cursor."""
    return script


def adapt_cursor_subagent_start(script: str) -> str:
    """Adapt SubagentStart hook script for Cursor."""
    return script


def adapt_cursor_subagent_stop(script: str) -> str:
    """Adapt SubagentStop hook script for Cursor."""
    return script
