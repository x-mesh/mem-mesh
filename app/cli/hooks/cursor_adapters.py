"""Thin adapters for Cursor hook payload/schema differences."""


def adapt_cursor_before_submit_prompt(script: str) -> str:
    """Adapt UserPromptSubmit script to Cursor beforeSubmitPrompt schema."""
    return (
        script.replace('hookEventName: "UserPromptSubmit"', 'hookEventName: "beforeSubmitPrompt"')
        .replace(".prompt // empty", ".prompt // .userPrompt // .text // empty")
        .replace(".transcript_path // empty", ".transcript_path // .transcriptPath // empty")
    )


def adapt_cursor_precompact(script: str) -> str:
    """Adapt PreCompact script to Cursor preCompact schema."""
    return (
        script.replace(".transcript_path // empty", ".transcript_path // .transcriptPath // empty")
        .replace(".session_id // empty", ".session_id // .sessionId // empty")
    )


def adapt_cursor_subagent_start(script: str) -> str:
    """Adapt SubagentStart script to Cursor subagentStart schema."""
    return script.replace(
        ".agent_type // empty", ".agent_type // .subagent_type // .agentType // empty"
    ).replace('hookEventName: "SubagentStart"', 'hookEventName: "subagentStart"')


def adapt_cursor_subagent_stop(script: str) -> str:
    """Adapt SubagentStop script to Cursor subagentStop schema."""
    return (
        script.replace(
            ".last_assistant_message // empty",
            ".last_assistant_message // .assistant_message // .result // empty",
        )
        .replace(".agent_type // \"unknown\"", ".agent_type // .subagent_type // .agentType // \"unknown\"")
        .replace(".stop_hook_active // false", ".stop_hook_active // .stopHookActive // false")
        .replace(
            "            source='hook-local',",
            "            source='hook-local',\n            client='cursor',",
        )
    )
