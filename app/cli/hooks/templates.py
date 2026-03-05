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
CURSOR_PROJECT_SESSION_START_TEMPLATE = _load_template("cursor-project-session-start.sh")
CURSOR_PROJECT_AUTO_SAVE_TEMPLATE = _load_template("cursor-project-auto-save.sh")
CURSOR_PROJECT_SESSION_END_TEMPLATE = _load_template("cursor-project-session-end.sh")
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

# UserPromptSubmit / SubagentStart / SubagentStop / TaskCompleted hook templates
USER_PROMPT_SUBMIT_HOOK_TEMPLATE = _load_template("user-prompt-submit.sh")
LOCAL_USER_PROMPT_SUBMIT_HOOK_TEMPLATE = _load_template("local-user-prompt-submit.sh")
SUBAGENT_START_HOOK_TEMPLATE = _load_template("subagent-start.sh")
LOCAL_SUBAGENT_START_HOOK_TEMPLATE = _load_template("local-subagent-start.sh")
SUBAGENT_STOP_HOOK_TEMPLATE = _load_template("subagent-stop.sh")
LOCAL_SUBAGENT_STOP_HOOK_TEMPLATE = _load_template("local-subagent-stop.sh")
TASK_COMPLETED_HOOK_TEMPLATE = _load_template("task-completed.sh")
LOCAL_TASK_COMPLETED_HOOK_TEMPLATE = _load_template("local-task-completed.sh")
