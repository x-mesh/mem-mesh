"""Chat assistant tool registry (M1a, read-only).

A single Pydantic definition per tool renders to BOTH Anthropic ``tool_use``
and OpenAI function-calling shapes, and the executor dispatches to the shared
``MCPToolHandlers`` — the same business logic the MCP endpoints use — so chat
tool-calls run through the identical validation/permission path as MCP clients.

M1a exposes read-only (``danger="safe"``) tools only; mutating tools + the
human-in-the-loop approval gate arrive in M2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List, Optional, Type

from pydantic import BaseModel, Field, ValidationError

# ----- per-tool input schemas (single source of truth) ----------------------


class SearchToolInput(BaseModel):
    query: str = Field(
        description="Natural-language query over the user's stored memories"
    )
    limit: int = Field(default=5, ge=1, le=25)
    category: Optional[str] = Field(
        default=None,
        description="Filter by category: bug|decision|incident|idea|code_snippet|task",
    )
    recency_weight: float = Field(
        default=0.0, ge=0.0, le=1.0, description="0..1 boost toward recent memories"
    )
    project_id: Optional[str] = Field(default=None, description="Restrict to a project")


class ContextToolInput(BaseModel):
    memory_id: str = Field(description="Memory id to fetch with its related memories")
    depth: int = Field(default=1, ge=0, le=3, description="Relationship hops to expand")
    project_id: Optional[str] = Field(default=None)


class StatsToolInput(BaseModel):
    project_id: Optional[str] = Field(default=None, description="Restrict to a project")


class PinListToolInput(BaseModel):
    project_id: str = Field(description="Project whose work pins to list")
    status: Optional[str] = Field(
        default=None, description="Filter: open|in_progress|completed"
    )
    limit: int = Field(default=10, ge=1, le=50)


class WeeklyReviewToolInput(BaseModel):
    project_id: str = Field(description="Project to review")
    days: int = Field(default=7, ge=1, le=90, description="Look-back window in days")


# ----- tool spec + provider rendering ---------------------------------------


@dataclass
class ChatTool:
    name: str
    description: str
    input_model: Type[BaseModel]
    danger: str  # "safe" | "mutating" | "critical"
    handler: Callable[[Any, BaseModel], Awaitable[Any]]

    def json_schema(self) -> dict:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return schema

    def to_anthropic(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.json_schema(),
        }

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.json_schema(),
            },
        }


# ----- handlers (dispatch to the shared MCPToolHandlers) --------------------


async def _search(handlers: Any, m: SearchToolInput) -> Any:
    return await handlers.search(**m.model_dump(exclude_none=True))


async def _context(handlers: Any, m: ContextToolInput) -> Any:
    return await handlers.context(**m.model_dump(exclude_none=True))


async def _stats(handlers: Any, m: StatsToolInput) -> Any:
    return await handlers.stats(**m.model_dump(exclude_none=True))


async def _pin_list(handlers: Any, m: PinListToolInput) -> Any:
    return await handlers.pin_list(**m.model_dump(exclude_none=True))


async def _weekly_review(handlers: Any, m: WeeklyReviewToolInput) -> Any:
    return await handlers.weekly_review(**m.model_dump(exclude_none=True))


READ_ONLY_TOOLS: List[ChatTool] = [
    ChatTool(
        name="search_memories",
        description=(
            "Search the user's memories (hybrid vector + keyword). Use this for "
            "any question about what is stored. Returns matching memories with ids."
        ),
        input_model=SearchToolInput,
        danger="safe",
        handler=_search,
    ),
    ChatTool(
        name="get_memory_context",
        description=(
            "Fetch one memory by id together with its related memories and "
            "timeline. Use to look deeper at a specific memory."
        ),
        input_model=ContextToolInput,
        danger="safe",
        handler=_context,
    ),
    ChatTool(
        name="memory_stats",
        description="Overall counts: totals, categories, projects, sources.",
        input_model=StatsToolInput,
        danger="safe",
        handler=_stats,
    ),
    ChatTool(
        name="list_pins",
        description=(
            "List work pins for a project, optionally filtered by status "
            "(open|in_progress|completed). Use for 'what am I working on'."
        ),
        input_model=PinListToolInput,
        danger="safe",
        handler=_pin_list,
    ),
    ChatTool(
        name="weekly_review",
        description=(
            "Summarize recent activity for a project: incomplete pins, recent "
            "memories, sessions, and zero-result searches."
        ),
        input_model=WeeklyReviewToolInput,
        danger="safe",
        handler=_weekly_review,
    ),
]

REGISTRY = {tool.name: tool for tool in READ_ONLY_TOOLS}


def render_tools(tools: List[ChatTool], provider: str) -> list:
    """Render tool specs in the given provider's tool shape."""

    key = (provider or "anthropic").strip().lower()
    if key == "openai":
        return [tool.to_openai() for tool in tools]
    return [tool.to_anthropic() for tool in tools]


async def execute_tool(handlers: Any, name: str, raw_args: Optional[dict]) -> dict:
    """Validate args against the tool schema and dispatch to ``handlers``.

    Returns a normalized envelope ``{ok, data}`` or ``{ok: False, error}`` so the
    result can be fed back to the model as a tool result regardless of provider.
    """

    tool = REGISTRY.get(name)
    if tool is None:
        return {"ok": False, "error": f"unknown tool: {name}"}
    try:
        model = tool.input_model(**(raw_args or {}))
    except ValidationError as exc:
        return {"ok": False, "error": f"invalid arguments for {name}: {exc}"}
    try:
        data = await tool.handler(handlers, model)
    except Exception as exc:  # service failure surfaced back to the model
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "data": data}
