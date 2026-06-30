"""Chat assistant REST API routes (M0).

Provides dashboard-managed chat LLM settings, a connectivity test, and a
single non-streaming completion. Tool-calling + SSE streaming arrive in M1.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import get_settings
from app.core.errors import ChatError
from app.core.schemas.chat import (
    ChatCompleteRequest,
    ChatCompleteResponse,
    ChatSettingsResponse,
    ChatSettingsUpdateRequest,
    ChatTestRequest,
    ChatTestResponse,
)
from app.core.services.chat import ChatService

from ...common.dependencies import get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat/v1", tags=["Chat"])


async def get_chat_service(db=Depends(get_database)) -> ChatService:
    return ChatService(db)


@router.get("/settings", response_model=ChatSettingsResponse)
async def get_chat_settings(
    service: ChatService = Depends(get_chat_service),
) -> ChatSettingsResponse:
    """Return dashboard-managed chat assistant settings (key masked)."""

    try:
        return await service.get_admin_settings(get_settings())
    except Exception as exc:
        logger.exception("Chat settings failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/settings", response_model=ChatSettingsResponse)
async def update_chat_settings(
    payload: ChatSettingsUpdateRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatSettingsResponse:
    """Persist chat assistant LLM provider/key/model/endpoint."""

    try:
        return await service.update_admin_settings(payload, get_settings())
    except Exception as exc:
        logger.exception("Chat settings update failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/test", response_model=ChatTestResponse)
async def test_chat(
    payload: ChatTestRequest | None = None,
    service: ChatService = Depends(get_chat_service),
) -> ChatTestResponse:
    """Validate connectivity. An optional body lets the dashboard verify a
    key/provider typed into the form before saving it."""

    overrides = None
    if payload is not None:
        overrides = {
            "llm_provider": payload.provider,
            "llm_api_key": payload.api_key,
            "llm_model": payload.model,
            "llm_base_url": payload.base_url,
        }
    try:
        out = await service.test_connection(get_settings(), overrides=overrides)
        return ChatTestResponse(**out)
    except ChatError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc))
    except Exception as exc:
        logger.exception("Chat test failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/complete", response_model=ChatCompleteResponse)
async def chat_complete(
    payload: ChatCompleteRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatCompleteResponse:
    """Run one non-streaming chat turn (no memory tools yet)."""

    try:
        result = await service.complete(
            [m.model_dump() for m in payload.messages],
            get_settings(),
            max_tokens=payload.max_tokens,
        )
        return ChatCompleteResponse(
            text=result.text,
            finish_reason=result.finish_reason,
            tool_calls=result.tool_calls,
        )
    except ChatError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc))
    except Exception as exc:
        logger.exception("Chat complete failed")
        raise HTTPException(status_code=500, detail=str(exc))
