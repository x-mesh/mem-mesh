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
from .relay_worker import ChatResult


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
        """Async generator of progress events for SSE (token-streaming).

        Yields ``delta`` (streamed answer tokens), ``tool_call`` / ``tool_result``
        (as they happen), then ``message`` (final text) and ``done``.
        """

        rendered = render_tools(self.tools, self.provider) if self.tools else None
        convo: List[dict] = list(messages)
        trace: List[dict] = []

        for step in range(1, self.max_steps + 1):
            result = None
            async for ev in self.enricher.chat_stream(convo, tools=rendered):
                if ev.get("type") == "text_delta":
                    yield {"type": "delta", "text": ev.get("text", "")}
                elif ev.get("type") == "final":
                    result = ev.get("result")
            if result is None:
                result = ChatResult()

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

        # Step budget exhausted — stream one final answer with no tools.
        result = None
        async for ev in self.enricher.chat_stream(convo, tools=None):
            if ev.get("type") == "text_delta":
                yield {"type": "delta", "text": ev.get("text", "")}
            elif ev.get("type") == "final":
                result = ev.get("result")
        yield {"type": "message", "text": result.text if result else ""}
        yield {
            "type": "done",
            "steps": self.max_steps,
            "truncated": True,
            "finish_reason": result.finish_reason if result else None,
            "tool_calls": trace,
        }

    async def run(self, messages: List[dict]) -> dict:
        """Non-streaming variant (used by POST /agent and tests)."""

        rendered = render_tools(self.tools, self.provider) if self.tools else None
        convo: List[dict] = list(messages)
        trace: List[dict] = []

        for step in range(1, self.max_steps + 1):
            result = await self.enricher.chat(convo, tools=rendered)
            if not result.tool_calls:
                return {
                    "text": result.text,
                    "tool_calls": trace,
                    "steps": step,
                    "truncated": False,
                    "finish_reason": result.finish_reason,
                }
            convo.append(
                {
                    "role": "assistant",
                    "content": result.text,
                    "tool_calls": result.tool_calls,
                }
            )
            results = []
            for call in result.tool_calls:
                res = await self._run_one(call)
                trace.append(
                    {
                        "name": call.get("name"),
                        "arguments": call.get("arguments") or {},
                        "result": res,
                    }
                )
                results.append(
                    {
                        "tool_call_id": call.get("id"),
                        "content": json.dumps(res, ensure_ascii=False),
                    }
                )
            convo.append({"role": "tool", "results": results})

        final = await self.enricher.chat(convo, tools=None)
        return {
            "text": final.text,
            "tool_calls": trace,
            "steps": self.max_steps,
            "truncated": True,
            "finish_reason": final.finish_reason,
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
