"""Schemas for Claude Code HTTP hook payloads.

Claude Code (>= v2.1.105) can POST hook events directly to an HTTP endpoint
instead of running a shell command. The request body is the same JSON a
command hook would receive on stdin. These models validate that payload and
shape the JSON response Claude Code reads back (the ``hookSpecificOutput``
schema, identical to command-hook stdout).

Unknown fields are allowed — Claude Code evolves the payload across versions
and the server should not reject events it merely does not recognise yet.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class HookEventBase(BaseModel):
    """Fields common to every Claude Code hook event."""

    model_config = ConfigDict(extra="allow")

    session_id: Optional[str] = Field(
        default=None, description="Claude Code native session id"
    )
    transcript_path: Optional[str] = Field(
        default=None, description="Client-side transcript path (not read by the server)"
    )
    cwd: Optional[str] = Field(default=None, description="Working directory")
    hook_event_name: Optional[str] = Field(default=None)
    project_id: Optional[str] = Field(
        default=None,
        description="Explicit project id; falls back to basename(cwd) when omitted",
    )


class SessionStartPayload(HookEventBase):
    source: Optional[str] = Field(
        default=None, description="startup | resume | clear | compact"
    )


class UserPromptSubmitPayload(HookEventBase):
    prompt: str = Field(default="", description="The user prompt being submitted")


class StopPayload(HookEventBase):
    stop_hook_active: bool = Field(default=False)
    last_assistant_message: str = Field(default="")


class SubagentStopPayload(HookEventBase):
    stop_hook_active: bool = Field(default=False)
    last_assistant_message: str = Field(default="")
    agent_type: Optional[str] = Field(default=None)


class TaskCompletedPayload(HookEventBase):
    task_subject: str = Field(default="")
    task_description: Optional[str] = Field(default=None)
    teammate_name: Optional[str] = Field(default=None)


class HookSpecificOutput(BaseModel):
    """The ``hookSpecificOutput`` block Claude Code parses from the response."""

    model_config = ConfigDict(extra="allow")

    hookEventName: str
    additionalContext: Optional[str] = None


class HookResponse(BaseModel):
    """Top-level JSON response body returned to Claude Code.

    Every field is optional: an empty response is a valid "do nothing" reply.
    """

    model_config = ConfigDict(extra="allow")

    hookSpecificOutput: Optional[HookSpecificOutput] = None
    # Plain status line surfaced for observability / debugging.
    status: Optional[str] = None
