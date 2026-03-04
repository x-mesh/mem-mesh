"""Shared prompt definitions and IDE-specific renderers for mem-mesh hooks."""

from app.cli.prompts.behaviors import (
    CORE_RULES,
    PIN_CRITERIA,
    PROMPT_VERSION,
    SAVE_CRITERIA,
    SESSION_CONFIG,
    PinCriteria,
    Rule,
    SaveCriteria,
    SessionConfig,
)
from app.cli.prompts.renderers import (
    render_cursor_context,
    render_cursor_followup,
    render_kiro_auto_create_pin,
    render_kiro_auto_save,
    render_kiro_load_context,
    render_rules_text,
)

__all__ = [
    # Version
    "PROMPT_VERSION",
    # Data classes
    "Rule",
    "SaveCriteria",
    "PinCriteria",
    "SessionConfig",
    # Canonical definitions
    "CORE_RULES",
    "SAVE_CRITERIA",
    "PIN_CRITERIA",
    "SESSION_CONFIG",
    # Renderers
    "render_rules_text",
    "render_kiro_auto_save",
    "render_kiro_auto_create_pin",
    "render_kiro_load_context",
    "render_cursor_context",
    "render_cursor_followup",
]
