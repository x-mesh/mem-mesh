"""Claude Code HTTP hook endpoints.

Claude Code (>= v2.1.105) can POST lifecycle events straight to an HTTP
endpoint instead of running a `bash + jq + curl` script. These routes are the
server-side replacement for the shell hooks under ``app/cli/hooks/shell/``:
the same work (session resume injection, keyword-matched saves, reminders)
runs here, driven by the event stream rather than the client-side transcript
file — which is unreachable when mem-mesh runs remotely or in Docker.

Design rules:
* **Never break the caller.** Every handler returns HTTP 200; failures degrade
  to an empty response. A hook must not stall the user's session.
* **Strict output schema.** Claude Code validates the response body against
  the command-hook stdout schema and rejects unknown root keys or a ``null``
  ``hookSpecificOutput``. So a "do nothing" reply is an *empty body* (the
  status is logged, never sent), and context injection emits *only*
  ``hookSpecificOutput``.
* Embedding-dependent services (memory/search) are fetched lazily so a
  loading model yields graceful degradation instead of a 503.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from app.cli.hooks.keywords import match_category
from app.core.config import get_settings, resolve_hook_token
from app.core.redaction import redact_secrets
from app.core.schemas.requests import normalize_project_id
from app.core.schemas.hooks import (
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
from ...oauth.middleware import is_loopback_host, verify_hook_token

logger = logging.getLogger(__name__)

# Every hook endpoint is guarded by the shared-secret hook token. The
# dependency is a no-op for local-dev (no token + loopback bind) and
# fail-closed for network-exposed servers without a token. Applied at router
# level so reads and writes are covered uniformly (the original report flagged
# only writes, but context-injection reads share the same exposure surface).
router = APIRouter(
    prefix="/hooks/claude",
    tags=["Claude Code Hooks"],
    dependencies=[Depends(verify_hook_token)],
)


def _warn_if_hook_endpoints_exposed() -> None:
    """Log a startup warning when hooks are reachable but will fail closed.

    Emitted at import (app construction) so operators see it before the first
    rejected hook call. Best-effort: never break import on a diagnostic.
    """
    try:
        settings = get_settings()
        if resolve_hook_token() is None and not is_loopback_host(settings.server_host):
            logger.warning(
                "Hook endpoints are exposed on non-loopback host %s without a "
                "hook token; hook write requests will be rejected with 401. "
                "Set MEM_MESH_HOOK_TOKEN or write ~/.mem-mesh/hook_token.",
                settings.server_host,
            )
    except Exception:  # noqa: BLE001 - diagnostic must not block startup
        pass


_warn_if_hook_endpoints_exposed()

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

# Non-substantive system artifacts that pollute memory if saved verbatim:
# task-notification envelopes, tool-use ids, injected reminders. A turn whose
# text is dominated by these is skipped; when only the *question* is noise we
# drop the Q and keep the answer.
_NOISE_MARKERS = (
    "<task-notification>",
    "</task-notification>",
    "<task-id>",
    "<tool-use-id>",
    "<system-reminder>",
)


def _ok(status: str) -> Response:
    """An empty 200 — the valid "do nothing" reply for a hook.

    Claude Code rejects unknown root keys in hook output JSON, so the status
    string is logged for observability and never put on the wire.
    """
    logger.debug("claude hook: %s", status)
    return Response(status_code=200)


def _context(event_name: str, additional_context: str) -> JSONResponse:
    """A 200 carrying only ``hookSpecificOutput`` for context injection."""
    return JSONResponse(
        {
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "additionalContext": additional_context,
            }
        }
    )


def _normalize_project_id(name: str) -> str:
    """Canonicalize a project id via the server-wide single source of truth.

    Delegates to :func:`app.core.schemas.requests.normalize_project_id` so the
    HTTP-hook path, the Pydantic-validated API/MCP path, and the work/search
    endpoints all converge on one id for the same repo. ``strict=False`` because
    a hook must never raise into the caller — an un-normalizable value degrades
    to ``"unknown"`` instead of a 422.

        ``term-mesh-wt-170638b5`` / ``term-mesh_wt_170638b5`` → ``term-mesh``
        ``/Users/me/work/oci-terraform`` → ``oci-terraform``
        ``oci_tools`` / ``OCI-Tools`` → ``oci-tools``
    """
    return normalize_project_id((name or "").strip() or None, strict=False) or "unknown"


def _project_id(cwd: Optional[str], explicit: Optional[str]) -> str:
    """Resolve the project id from an explicit value or the cwd basename.

    HTTP hooks cannot run ``git rev-parse`` client-side, so the cwd basename
    is the fallback. For repos checked out at their own directory name (the
    common case) this matches the shell hooks' ``git toplevel`` basename. The
    result is normalized so worktree / casing / separator variants of the same
    repo share one id.
    """
    if explicit:
        return _normalize_project_id(explicit)
    if cwd:
        name = Path(cwd).name
        if name:
            return _normalize_project_id(name)
    return "unknown"


def _save_marker_present(text: str) -> bool:
    return "mcp__mem-mesh__add" in text or "mcp__mem-mesh__pin_add" in text


def _is_noise(text: Optional[str]) -> bool:
    """True if the text is a system artifact (task notifications, tool-use
    envelopes, injected reminders) rather than substantive content."""
    if not text:
        return False
    return any(marker in text for marker in _NOISE_MARKERS)


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
        # Redact secrets/PII before persisting. Hook saves capture whole
        # assistant turns, so a leaked key/token/email could otherwise land in
        # long-term memory. Redact first, then truncate, so a secret near the
        # length boundary cannot survive as a partial. Both Q and A are covered
        # because the caller passes the combined "Q: …\n\nA: …" string here.
        safe_content = redact_secrets(content)[:_MAX_CONTENT]
        await memory_service.create(
            content=safe_content,
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


@router.post("/session-start")
async def session_start(
    payload: SessionStartPayload,
    hook_service: HookService = Depends(get_hook_service),
    session_service: SessionService = Depends(get_session_service),
) -> Response:
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

    return _context("SessionStart", context_str)


# ─────────────────────── UserPromptSubmit ────────────────────────


@router.post("/user-prompt-submit")
async def user_prompt_submit(
    payload: UserPromptSubmitPayload,
    hook_service: HookService = Depends(get_hook_service),
    pin_service: PinService = Depends(get_pin_service),
) -> Response:
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
        return _ok("user-prompt-submit: noop")

    return _context("UserPromptSubmit", "\n\n".join(parts))


# ───────────────────────────── Stop ──────────────────────────────


@router.post("/stop")
async def stop(
    payload: StopPayload,
    hook_service: HookService = Depends(get_hook_service),
) -> Response:
    """Keyword-matched structured save of the finished turn.

    The Q is paired from the event stream (the last recorded prompt for this
    session) so the saved memory keeps its question context without reading
    the transcript file.
    """
    if payload.stop_hook_active:
        return _ok("stop: skip (stop_hook_active)")

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
        return _ok("stop: skip (message too short)")
    if _save_marker_present(message):
        return _ok("stop: skip (already saved via MCP)")
    if _is_noise(message):
        return _ok("stop: skip (noise artifact)")

    category = match_category(message, os.getenv("MEM_MESH_HOOK_EXTRA_KEYWORDS", ""))
    if category not in _SAVE_CATEGORIES:
        return _ok(f"stop: skip (no keyword match: {category})")

    # Pair the question from the event stream. A noise-only question (task
    # notification / tool-use envelope) is dropped so it doesn't pollute the
    # saved memory; the answer is still kept on its own.
    content = message
    if ide_session_id:
        try:
            question = await hook_service.get_last_prompt(ide_session_id)
            if question and not _is_noise(question):
                content = f"Q: {question[:500]}\n\nA: {message[:_MAX_CONTENT]}"
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Q&A pairing failed: {e}")

    saved = await _save_memory(
        project_id,
        content,
        category,
        tags=["auto-save", "keyword", category],
    )
    return _ok(
        f"stop: saved memory as {category} (project={project_id})"
        if saved
        else f"stop: save skipped (category={category})"
    )


# ───────────────────────── SubagentStop ──────────────────────────


@router.post("/subagent-stop")
async def subagent_stop(
    payload: SubagentStopPayload,
    hook_service: HookService = Depends(get_hook_service),
) -> Response:
    """Keyword-matched save of a notable subagent result."""
    if payload.stop_hook_active:
        return _ok("subagent-stop: skip (stop_hook_active)")

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

    if len(message) < 100 or _save_marker_present(message) or _is_noise(message):
        return _ok("subagent-stop: skip")

    category = match_category(message, os.getenv("MEM_MESH_HOOK_EXTRA_KEYWORDS", ""))
    if category not in _SAVE_CATEGORIES:
        return _ok(f"subagent-stop: skip (no keyword match: {category})")

    agent_type = payload.agent_type or "unknown"
    saved = await _save_memory(
        project_id,
        f"[{agent_type} agent] {message}",
        category,
        tags=["auto-save", "subagent", category],
    )
    return _ok("subagent-stop: saved" if saved else "subagent-stop: save skipped")


# ───────────────────────── TaskCompleted ─────────────────────────


@router.post("/task-completed")
async def task_completed(
    payload: TaskCompletedPayload,
    hook_service: HookService = Depends(get_hook_service),
) -> Response:
    """Save a completed team task to mem-mesh."""
    if not payload.task_subject:
        return _ok("task-completed: skip (no task subject)")

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
    return _ok("task-completed: saved" if saved else "task-completed: save skipped")
