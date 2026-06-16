"""Schemas for Claude Code HTTP hook *payloads*.

Claude Code (>= v2.1.105) can POST hook events directly to an HTTP endpoint
instead of running a shell command. The request body is the same JSON a
command hook would receive on stdin; these models validate that payload.

The *response* side is intentionally not modelled here. Claude Code validates
hook output against the strict command-hook stdout schema and rejects unknown
root keys or a ``null`` ``hookSpecificOutput`` — so handlers return either an
empty body or a bare ``{"hookSpecificOutput": {...}}`` dict (see
``app/web/dashboard/route_modules/hooks.py``).

Unknown payload fields are allowed — Claude Code evolves the payload across
versions and the server should not reject events it merely does not
recognise yet.
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


class PostToolUsePayload(HookEventBase):
    """A PostToolUse event — fired after each tool call completes.

    Only the tool *name* is needed: the server records a write-signal when the
    tool was a file mutation (Edit/Write/...), which gates the pin/save
    reminders so they fire on real edits instead of on read-only turns.
    """

    tool_name: str = Field(default="", description="Name of the tool that just ran")
