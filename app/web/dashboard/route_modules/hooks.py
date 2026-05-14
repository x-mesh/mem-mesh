"""Claude Code HTTP hook endpoints.

Claude Code (>= v2.1.105) can POST lifecycle events straight to an HTTP
endpoint instead of running a `bash + jq + curl` script. These routes are the
server-side replacement for the shell hooks under ``app/cli/hooks/shell/``:
the same work (session resume injection, keyword-matched saves, reminders)
runs here, driven by the event stream rather than the client-side transcript
file — which is unreachable when mem-mesh runs remotely or in Docker.

Design rules:
* **Never break the caller.** Every handler returns HTTP 200; failures degrade
  to an empty/partial response. A hook must not stall the user's session.
* Embedding-dependent services (memory/search) are fetched lazily so a
  loading model yields graceful degradation instead of a 503.
* Responses use the same ``hookSpecificOutput`` schema as command-hook stdout.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends

from app.cli.hooks.keywords import match_category
from app.core.schemas.hooks import (
    HookResponse,
    HookSpecificOutput,
    SessionStartPayload,
    StopPayload,
    SubagentStopPayload,
    TaskCompletedPayload,
    UserPromptSubmitPayload,
)
from app.core.services.hook import HookService
from app.core.services.pin import PinService
from app.core.services.session import SessionService

from ...common.dependencies import (
    get_hook_service,
    get_pin_service,
    get_session_service,
)
from ...lifespan import get_services

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hooks/claude", tags=["Claude Code Hooks"])

# Memory categories the keyword matcher is allowed to auto-save (mirrors the
# CLAUDE.md M3 rule). ``task`` / ``git-history`` stay system-only.
_SAVE_CATEGORIES = {"bug", "decision", "incident", "idea", "code_snippet"}

_MAX_CONTENT = 9500
_SEARCH_KEYWORDS = (
    "이전",
    "지난",
    "결정",
    "기존",
    "왜",
    "변경",
    "remember",
    "previous",
    "decided",
    "why did",
    "last time",
    "before",
)


def _project_id(cwd: Optional[str], explicit: Optional[str]) -> str:
    """Resolve the project id from an explicit value or the cwd basename.

    HTTP hooks cannot run ``git rev-parse`` client-side, so the cwd basename
    is the fallback. For repos checked out at their own directory name (the
    common case) this matches the shell hooks' ``git toplevel`` basename.
    """
    if explicit:
        return explicit
    if cwd:
        name = Path(cwd).name
        if name:
            return name
    return "unknown"


def _save_marker_present(text: str) -> bool:
    return "mcp__mem-mesh__add" in text or "mcp__mem-mesh__pin_add" in text


async def _record(
    hook_service: HookService,
    *,
    project_id: str,
    ide_session_id: Optional[str],
    event_name: str,
    client_type: Optional[str] = None,
    prompt: Optional[str] = None,
    assistant_message: Optional[str] = None,
) -> None:
    """Best-effort event recording — never raises into the handler."""
    if not ide_session_id:
        return
    try:
        await hook_service.record_event(
            project_id=project_id,
            ide_session_id=ide_session_id,
            event_name=event_name,
            client_type=client_type,
            prompt=prompt,
            assistant_message=assistant_message,
        )
    except Exception as e:  # noqa: BLE001 - hooks must not break the session
        logger.warning(f"hook event record failed ({event_name}): {e}")


async def _save_memory(
    project_id: str, content: str, category: str, *, tags: list[str]
) -> bool:
    """Save a memory via MemoryService if the embedding model is ready."""
    services = get_services()
    memory_service = services.get("memory_service")
    embedding_service = services.get("embedding_service")
    if (
        memory_service is None
        or embedding_service is None
        or not embedding_service.is_ready
    ):
        logger.info("hook save skipped: memory service / embedding model not ready")
        return False
    try:
        await memory_service.create(
            content=content[:_MAX_CONTENT],
            project_id=project_id,
            category=category,
            source="claude-code-http-hook",
            client="claude_code",
            tags=tags,
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"hook memory save failed: {e}")
        return False


# ───────────────────────── SessionStart ──────────────────────────


@router.post("/session-start", response_model=HookResponse)
async def session_start(
    payload: SessionStartPayload,
    hook_service: HookService = Depends(get_hook_service),
    session_service: SessionService = Depends(get_session_service),
) -> HookResponse:
    """Inject mem-mesh session context, transcript-file-free.

    Continuation (post-compaction) is detected from the event stream: a
    SessionStart for a ``session_id`` we have already recorded means the
    context was compacted and resumed.
    """
    project_id = _project_id(payload.cwd, payload.project_id)
    ide_session_id = payload.session_id

    is_continuation = False
    if ide_session_id:
        try:
            is_continuation = await hook_service.is_continuation(ide_session_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"continuation check failed: {e}")

    await _record(
        hook_service,
        project_id=project_id,
        ide_session_id=ide_session_id,
        event_name="SessionStart",
        client_type="claude-ai",
    )

    # Resume session context + correlate the IDE session id.
    summary_lines: list[str] = []
    try:
        context = await session_service.resume_last_session(
            project_id=project_id, expand="smart", limit=10
        )
        if ide_session_id:
            await session_service.get_or_create_active_session(
                project_id=project_id,
                ide_session_id=ide_session_id,
                client_type="claude-ai",
            )
        if context is not None:
            pins = getattr(context, "pins", None) or []
            for p in pins:
                pin = p if isinstance(p, dict) else p.dict()
                if pin.get("status") in ("open", "in_progress"):
                    content = str(pin.get("content", "?"))[:100]
                    client = pin.get("client") or ""
                    prefix = f"({client}) " if client else ""
                    summary_lines.append(f"- [pin] {prefix}{content}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"session resume failed: {e}")

    if not summary_lines:
        summary_lines.append("No recent activity.")

    continuation_block = ""
    if is_continuation:
        continuation_block = (
            "\n### [IMPORTANT] Context Continuation Detected\n"
            "This session was compacted and resumed. Previous context may be lost.\n"
            f'**You MUST call `session_resume(project_id="{project_id}", '
            'expand="smart")` immediately** to restore mem-mesh context.\n'
        )

    rules_text = ""
    try:
        from app.cli.prompts.renderers import render_rules_text

        rules_text = render_rules_text(project_id)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"rules text render skipped: {e}")

    context_str = (
        "## mem-mesh Session Context (Auto-injected)\n"
        f"{continuation_block}\n"
        f"### Recent Activity ({project_id})\n"
        + "\n".join(summary_lines)
        + (f"\n\n### Rules\n{rules_text}" if rules_text else "")
    )

    return HookResponse(
        hookSpecificOutput=HookSpecificOutput(
            hookEventName="SessionStart", additionalContext=context_str
        ),
        status="continuation" if is_continuation else "ok",
    )


# ─────────────────────── UserPromptSubmit ────────────────────────


@router.post("/user-prompt-submit", response_model=HookResponse)
async def user_prompt_submit(
    payload: UserPromptSubmitPayload,
    hook_service: HookService = Depends(get_hook_service),
    pin_service: PinService = Depends(get_pin_service),
) -> HookResponse:
    """Keyword-matched memory search + save/pin reminders.

    The "N turns since save" reminder is derived from the event stream's
    ``saved_memory`` flags instead of re-parsing the transcript.
    """
    project_id = _project_id(payload.cwd, payload.project_id)
    ide_session_id = payload.session_id
    prompt = payload.prompt or ""

    await _record(
        hook_service,
        project_id=project_id,
        ide_session_id=ide_session_id,
        event_name="UserPromptSubmit",
        client_type="claude-ai",
        prompt=prompt,
    )

    parts: list[str] = []

    # Part 1: keyword-filtered memory search.
    if len(prompt) >= 30 and any(kw in prompt.lower() for kw in _SEARCH_KEYWORDS):
        services = get_services()
        search_service = services.get("search_service")
        embedding_service = services.get("embedding_service")
        if (
            search_service is not None
            and embedding_service is not None
            and embedding_service.is_ready
        ):
            try:
                threshold = float(os.getenv("MEM_MESH_SEARCH_THRESHOLD", "0.75"))
                limit = int(os.getenv("MEM_MESH_SEARCH_LIMIT", "3"))
                result = await search_service.search(
                    query=prompt[:200],
                    project_id=project_id,
                    category=None,
                    source=None,
                    tag=None,
                    limit=limit,
                    offset=0,
                    sort_by="relevance",
                    sort_direction="desc",
                    recency_weight=0.0,
                    search_mode="hybrid",
                )
                results = getattr(result, "results", None) or []
                relevant = [
                    r
                    for r in results
                    if (getattr(r, "similarity_score", 0) or 0) > threshold
                ]
                if relevant:
                    lines = ["## Related Memories (auto-retrieved)", ""]
                    for r in relevant[:limit]:
                        cat = getattr(r, "category", "unknown")
                        content = (getattr(r, "content", "") or "")[:300]
                        created = (getattr(r, "created_at", "") or "")[:10]
                        lines.append(f"- [{cat}] ({created}) {content}")
                    parts.append("\n".join(lines))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"hook memory search failed: {e}")

    # Part 2: save reminder driven by the event stream.
    if ide_session_id:
        try:
            interval = int(os.getenv("MEM_MESH_SAVE_REMINDER_TURNS", "5"))
            since = await hook_service.turns_since_save(ide_session_id)
            if since >= interval:
                parts.append(
                    f"mem-mesh에 {since}턴 동안 저장하지 않았습니다. 중요한 결정/"
                    "버그 수정/설계 변경이 있었다면 mcp__mem-mesh__add로 저장하세요."
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"turns-since-save check failed: {e}")

    # Part 3: pin tracking reminder.
    if len(prompt) >= 15:
        try:
            open_pins = await pin_service.get_pins(
                project_id=project_id, status="open", limit=1
            )
            if not open_pins:
                parts.append(
                    "현재 추적 중인 pin이 없습니다. 작업 요청이라면 pin_add를 호출하세요."
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"pin reminder check failed: {e}")

    if not parts:
        return HookResponse(status="noop")

    return HookResponse(
        hookSpecificOutput=HookSpecificOutput(
            hookEventName="UserPromptSubmit",
            additionalContext="\n\n".join(parts),
        ),
        status="ok",
    )


# ───────────────────────────── Stop ──────────────────────────────


@router.post("/stop", response_model=HookResponse)
async def stop(
    payload: StopPayload,
    hook_service: HookService = Depends(get_hook_service),
) -> HookResponse:
    """Keyword-matched structured save of the finished turn.

    The Q is paired from the event stream (the last recorded prompt for this
    session) so the saved memory keeps its question context without reading
    the transcript file.
    """
    if payload.stop_hook_active:
        return HookResponse(status="skip: stop_hook_active")

    message = payload.last_assistant_message or ""
    project_id = _project_id(payload.cwd, payload.project_id)
    ide_session_id = payload.session_id

    await _record(
        hook_service,
        project_id=project_id,
        ide_session_id=ide_session_id,
        event_name="Stop",
        client_type="claude-ai",
        assistant_message=message,
    )

    if len(message) < 50:
        return HookResponse(status="skip: message too short")
    if _save_marker_present(message):
        return HookResponse(status="skip: already saved via MCP")

    category = match_category(message, os.getenv("MEM_MESH_HOOK_EXTRA_KEYWORDS", ""))
    if category not in _SAVE_CATEGORIES:
        return HookResponse(status=f"skip: no keyword match ({category})")

    # Pair the question from the event stream.
    content = message
    if ide_session_id:
        try:
            question = await hook_service.get_last_prompt(ide_session_id)
            if question:
                content = f"Q: {question[:500]}\n\nA: {message[:_MAX_CONTENT]}"
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Q&A pairing failed: {e}")

    saved = await _save_memory(
        project_id,
        content,
        category,
        tags=["auto-save", "keyword", category],
    )
    return HookResponse(
        status=(
            f"saved memory as {category} (project={project_id})"
            if saved
            else f"save skipped (category={category})"
        )
    )


# ───────────────────────── SubagentStop ──────────────────────────


@router.post("/subagent-stop", response_model=HookResponse)
async def subagent_stop(
    payload: SubagentStopPayload,
    hook_service: HookService = Depends(get_hook_service),
) -> HookResponse:
    """Keyword-matched save of a notable subagent result."""
    if payload.stop_hook_active:
        return HookResponse(status="skip: stop_hook_active")

    message = payload.last_assistant_message or ""
    project_id = _project_id(payload.cwd, payload.project_id)

    await _record(
        hook_service,
        project_id=project_id,
        ide_session_id=payload.session_id,
        event_name="SubagentStop",
        client_type="claude-ai",
        assistant_message=message,
    )

    if len(message) < 100 or _save_marker_present(message):
        return HookResponse(status="skip")

    category = match_category(message, os.getenv("MEM_MESH_HOOK_EXTRA_KEYWORDS", ""))
    if category not in _SAVE_CATEGORIES:
        return HookResponse(status=f"skip: no keyword match ({category})")

    agent_type = payload.agent_type or "unknown"
    saved = await _save_memory(
        project_id,
        f"[{agent_type} agent] {message}",
        category,
        tags=["auto-save", "subagent", category],
    )
    return HookResponse(status="saved" if saved else "save skipped")


# ───────────────────────── TaskCompleted ─────────────────────────


@router.post("/task-completed", response_model=HookResponse)
async def task_completed(
    payload: TaskCompletedPayload,
    hook_service: HookService = Depends(get_hook_service),
) -> HookResponse:
    """Save a completed team task to mem-mesh."""
    if not payload.task_subject:
        return HookResponse(status="skip: no task subject")

    project_id = _project_id(payload.cwd, payload.project_id)

    await _record(
        hook_service,
        project_id=project_id,
        ide_session_id=payload.session_id,
        event_name="TaskCompleted",
        client_type="claude-ai",
    )

    lines = [f"## Task Completed: {payload.task_subject}"]
    if payload.task_description:
        lines.append(f"\n{payload.task_description}")
    if payload.teammate_name:
        lines.append(f"\nCompleted by: {payload.teammate_name}")

    saved = await _save_memory(
        project_id,
        "\n".join(lines)[:5000],
        "task",
        tags=["auto-save", "task-completed"],
    )
    return HookResponse(status="saved" if saved else "save skipped")
