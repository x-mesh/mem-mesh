"""Hook installation constants and path definitions."""

from pathlib import Path

DEFAULT_URL = "http://localhost:8000"

HOOK_PROFILES = {
    "standard": {
        "description": "Keyword matching + structured save (no LLM, no API key, 요약+원본)",
        "hooks": [
            "session-start",
            "stop-decide",
            "user-prompt-submit",
            "subagent-start",
            "subagent-stop",
            "task-completed",
            "session-end",
            "precompact",
        ],
    },
    "enhanced": {
        "description": "Haiku API decision + structured analysis (requires ANTHROPIC_API_KEY)",
        "hooks": [
            "session-start",
            "stop-enhanced",
            "user-prompt-submit",
            "subagent-start",
            "subagent-stop",
            "task-completed",
            "session-end",
            "precompact",
        ],
    },
    "minimal": {
        "description": "Simple truncated save (async, no LLM, no decision making)",
        "hooks": ["session-start", "stop", "session-end", "precompact"],
    },
}

HOME = Path.home()

CLAUDE_HOOKS_DIR = HOME / ".claude" / "hooks"
CLAUDE_SETTINGS = HOME / ".claude" / "settings.json"

KIRO_HOOKS_DIR = HOME / ".kiro" / "hooks"
KIRO_SETTINGS = HOME / ".kiro" / "settings" / "hooks.json"

CURSOR_HOOKS_DIR = HOME / ".cursor" / "hooks"
CURSOR_SETTINGS = HOME / ".cursor" / "hooks.json"
