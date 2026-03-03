"""Bash hook script templates for all IDEs and profiles.

Templates are loaded from .sh files in the shell/ directory.
Each template contains __PLACEHOLDER__ tokens that are replaced
by the renderer at install time.
"""

from app.cli.hooks.renderer import _load_template

STOP_HOOK_TEMPLATE = _load_template("stop.sh")
STOP_DECIDE_HOOK_TEMPLATE = _load_template("stop-decide.sh")
SESSION_START_HOOK_TEMPLATE = _load_template("session-start.sh")
LOCAL_SESSION_START_HOOK_TEMPLATE = _load_template("local-session-start.sh")
KIRO_STOP_HOOK_TEMPLATE = _load_template("kiro-stop.sh")
CURSOR_SESSION_START_TEMPLATE = _load_template("cursor-session-start.sh")
CURSOR_STOP_TEMPLATE = _load_template("cursor-stop.sh")
LOCAL_STOP_HOOK_TEMPLATE = _load_template("local-stop.sh")
REFLECT_HOOK_TEMPLATE = _load_template("reflect.sh")
LOCAL_REFLECT_HOOK_TEMPLATE = _load_template("local-reflect.sh")
ENHANCED_STOP_HOOK_TEMPLATE = _load_template("enhanced-stop.sh")
LOCAL_ENHANCED_STOP_HOOK_TEMPLATE = _load_template("local-enhanced-stop.sh")

# SessionEnd / PreCompact hook templates
SESSION_END_HOOK_TEMPLATE = _load_template("session-end.sh")
LOCAL_SESSION_END_HOOK_TEMPLATE = _load_template("local-session-end.sh")
PRECOMPACT_HOOK_TEMPLATE = _load_template("precompact.sh")
LOCAL_PRECOMPACT_HOOK_TEMPLATE = _load_template("local-precompact.sh")
