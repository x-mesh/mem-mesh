"""Chat assistant API schemas (M0)."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .relay import RelaySettingValue


class ChatSettingsResponse(BaseModel):
    """Dashboard-facing chat LLM settings with masked secret + source."""

    generated_at: str
    llm_provider: RelaySettingValue
    llm_api_key: RelaySettingValue
    llm_model: RelaySettingValue
    llm_base_url: RelaySettingValue


class ChatSettingsUpdateRequest(BaseModel):
    llm_provider: Optional[str] = Field(default=None, max_length=20)
    llm_api_key: Optional[str] = Field(default=None, max_length=500)
    llm_model: Optional[str] = Field(default=None, max_length=200)
    llm_base_url: Optional[str] = Field(default=None, max_length=500)

    @field_validator("llm_provider")
    @classmethod
    def _validate_provider(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in ("anthropic", "openai"):
            raise ValueError("llm_provider must be 'anthropic' or 'openai'")
        return normalized


class ChatTestRequest(BaseModel):
    """Optional inline overrides so a key can be verified before saving.

    Any non-empty field overrides the stored/effective config for this one
    connectivity test; omitted fields fall back to the saved settings.
    """

    provider: Optional[str] = Field(default=None, max_length=20)
    api_key: Optional[str] = Field(default=None, max_length=500)
    model: Optional[str] = Field(default=None, max_length=200)
    base_url: Optional[str] = Field(default=None, max_length=500)

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in ("anthropic", "openai"):
            raise ValueError("provider must be 'anthropic' or 'openai'")
        return normalized


class ChatMessageInput(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=100000)


class ChatCompleteRequest(BaseModel):
    messages: List[ChatMessageInput] = Field(min_length=1)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=8192)


class ChatToolCall(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    arguments: dict = Field(default_factory=dict)


class ChatCompleteResponse(BaseModel):
    text: str = ""
    finish_reason: Optional[str] = None
    tool_calls: List[ChatToolCall] = Field(default_factory=list)


class ChatAgentRequest(BaseModel):
    messages: List[ChatMessageInput] = Field(min_length=1)
    project_id: Optional[str] = Field(default=None, max_length=100)
    page_memory_id: Optional[str] = Field(default=None, max_length=100)
    max_steps: int = Field(default=5, ge=1, le=8)


class ChatStreamRequest(BaseModel):
    messages: List[ChatMessageInput] = Field(min_length=1)
    session_id: Optional[str] = Field(default=None, max_length=64)
    project_id: Optional[str] = Field(default=None, max_length=100)
    page_memory_id: Optional[str] = Field(default=None, max_length=100)
    max_steps: int = Field(default=5, ge=1, le=8)


class ChatToolCallTrace(BaseModel):
    name: Optional[str] = None
    arguments: dict = Field(default_factory=dict)
    result: dict = Field(default_factory=dict)


class ChatAgentResponse(BaseModel):
    text: str = ""
    steps: int = 0
    truncated: bool = False
    tool_calls: List[ChatToolCallTrace] = Field(default_factory=list)


class ChatTestResponse(BaseModel):
    ok: bool
    provider: str
    model: str
    base_url: str
    sample: str = ""
