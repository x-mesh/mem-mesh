"""LLM routing settings API (dashboard).

Read/write the per-service LLM routing config that ``resolve_service_llm``
consumes: whether ``relay`` / ``reconcile`` bring their own LLM key or reuse the
shared ``chat`` LLM. Values live in DB app_config (``<svc>.llm_<field>`` and
``<svc>.use_own_llm``) with an env-backed Settings fallback.

API keys are never returned in plaintext — only a ``*_configured`` boolean.
"""

import logging

from fastapi import APIRouter, Body, Depends, HTTPException

from app.core.config import get_settings
from app.web.common.dependencies import get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["Settings"])

# Services that can opt into their own LLM (mirror llm_resolver._OWNABLE).
_SERVICES = ("relay", "reconcile")
# Truthy tokens for the use_own toggle (mirror llm_resolver._TRUE).
_TRUE = ("true", "1", "yes", "on")
# Public request field -> app_config field suffix (``<svc>.llm_<suffix>``).
_STR_FIELDS = {
    "provider": "provider",
    "api_key": "api_key",
    "model": "model",
    "base_url": "base_url",
}


async def _resolve_value(db, settings, namespace: str, field: str) -> str:
    """DB app_config ``<ns>.llm_<field>`` if set, else Settings ``<ns>_llm_<field>``."""
    db_value = await db.get_app_config(f"{namespace}.llm_{field}")
    if db_value is not None:
        return str(db_value)
    return str(getattr(settings, f"{namespace}_llm_{field}", "") or "")


async def _service_view(db, settings, service: str) -> dict:
    """Build the GET response block for one service."""
    toggle = await db.get_app_config(f"{service}.use_own_llm")
    if toggle is not None:
        use_own = str(toggle).strip().lower() in _TRUE
    else:
        use_own = None

    api_key = await _resolve_value(db, settings, service, "api_key")
    return {
        "use_own": use_own,
        "provider": await _resolve_value(db, settings, service, "provider"),
        "model": await _resolve_value(db, settings, service, "model"),
        "base_url": await _resolve_value(db, settings, service, "base_url"),
        "api_key_configured": bool(api_key.strip()),
    }


async def _build_response(db, settings) -> dict:
    """Assemble the full llm-routing response (shared by GET and PUT)."""
    chat_key = await _resolve_value(db, settings, "chat", "api_key")
    response = {"chat_configured": bool(chat_key.strip())}
    for service in _SERVICES:
        response[service] = await _service_view(db, settings, service)
    return response


@router.get("/llm-routing")
async def get_llm_routing(db=Depends(get_database)):
    """Return the effective LLM routing config (api keys as booleans only)."""
    try:
        return await _build_response(db, get_settings())
    except Exception as e:
        logger.exception("Get llm-routing failed")
        raise HTTPException(status_code=500, detail=str(e))


async def _apply_service(db, service: str, patch: dict) -> None:
    """Apply a partial per-service update to app_config."""
    if not isinstance(patch, dict):
        return

    if "use_own" in patch:
        use_own = patch["use_own"]
        if use_own is None:
            await db.delete_app_config(f"{service}.use_own_llm")
        else:
            await db.set_app_config(
                f"{service}.use_own_llm", "true" if use_own else "false"
            )

    for field, suffix in _STR_FIELDS.items():
        if field not in patch:
            continue
        key = f"{service}.llm_{suffix}"
        value = patch[field]
        if value is None or str(value) == "":
            await db.delete_app_config(key)
        else:
            await db.set_app_config(key, str(value))


@router.put("/llm-routing")
async def put_llm_routing(body: dict = Body(...), db=Depends(get_database)):
    """Partial-update LLM routing config, then return the effective config."""
    try:
        for service in _SERVICES:
            if service in body:
                await _apply_service(db, service, body[service])
        return await _build_response(db, get_settings())
    except Exception as e:
        logger.exception("Put llm-routing failed")
        raise HTTPException(status_code=500, detail=str(e))
