"""Chat agent loop (M1b).

Drives a bounded multi-step tool-use conversation: ask the LLM with the tool
specs, run any tool calls it makes (read-only/safe tools auto-execute in M1;
mutating tools are rejected until the M2 approval gate), feed results back, and
repeat until the model answers or ``max_steps`` is hit. The loop builds a
provider-neutral message list; each adapter's ``_chat_payload`` serializes the
assistant tool-call and tool-result turns into the right wire shape.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from .chat_tools import READ_ONLY_TOOLS, REGISTRY, ChatTool, execute_tool, render_tools


class ChatAgentLoop:
    def __init__(
        self,
        *,
        enricher: Any,
        provider: str,
        handlers: Any,
        tools: Optional[List[ChatTool]] = None,
        max_steps: int = 5,
    ):
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.enricher = enricher
        self.provider = provider
        self.handlers = handlers
        self.tools = READ_ONLY_TOOLS if tools is None else tools
        self.max_steps = max_steps

    async def run_events(self, messages: List[dict]):
        """Async generator of progress events for SSE.

        Yields ``{"type": ...}`` dicts: ``tool_call`` / ``tool_result`` as they
        happen, then ``message`` (final text) and ``done`` (steps/truncated/
        full tool trace).
        """

        rendered = render_tools(self.tools, self.provider) if self.tools else None
        convo: List[dict] = list(messages)
        trace: List[dict] = []

        for step in range(1, self.max_steps + 1):
            result = await self.enricher.chat(convo, tools=rendered)
            if not result.tool_calls:
                yield {"type": "message", "text": result.text}
                yield {
                    "type": "done",
                    "steps": step,
                    "truncated": False,
                    "finish_reason": result.finish_reason,
                    "tool_calls": trace,
                }
                return

            convo.append(
                {
                    "role": "assistant",
                    "content": result.text,
                    "tool_calls": result.tool_calls,
                }
            )
            results: List[dict] = []
            for call in result.tool_calls:
                yield {
                    "type": "tool_call",
                    "name": call.get("name"),
                    "arguments": call.get("arguments") or {},
                }
                res = await self._run_one(call)
                trace.append(
                    {
                        "name": call.get("name"),
                        "arguments": call.get("arguments") or {},
                        "result": res,
                    }
                )
                yield {
                    "type": "tool_result",
                    "name": call.get("name"),
                    "ok": bool(res.get("ok")),
                }
                results.append(
                    {
                        "tool_call_id": call.get("id"),
                        "content": json.dumps(res, ensure_ascii=False),
                    }
                )
            convo.append({"role": "tool", "results": results})

        # Step budget exhausted while still calling tools — force a final answer
        # with no tools so the user always gets text rather than a dangling call.
        final = await self.enricher.chat(convo, tools=None)
        yield {"type": "message", "text": final.text}
        yield {
            "type": "done",
            "steps": self.max_steps,
            "truncated": True,
            "finish_reason": final.finish_reason,
            "tool_calls": trace,
        }

    async def run(self, messages: List[dict]) -> dict:
        text = ""
        done: dict = {}
        async for ev in self.run_events(messages):
            if ev["type"] == "message":
                text = ev["text"]
            elif ev["type"] == "done":
                done = ev
        return {
            "text": text,
            "tool_calls": done.get("tool_calls", []),
            "steps": done.get("steps", 0),
            "truncated": done.get("truncated", False),
            "finish_reason": done.get("finish_reason"),
        }

    async def _run_one(self, call: dict) -> dict:
        name = call.get("name")
        tool = REGISTRY.get(name)
        if tool is None:
            return {"ok": False, "error": f"unknown tool: {name}"}
        if tool.danger != "safe":
            return {
                "ok": False,
                "error": (
                    f"tool '{name}' is a mutating action and requires approval "
                    "(not available in read-only mode)"
                ),
            }
        return await execute_tool(self.handlers, name, call.get("arguments") or {})
