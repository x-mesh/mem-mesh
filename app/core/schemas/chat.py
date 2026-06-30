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
    enabled: bool = True
    configured: bool = False
    available: bool = False


class ChatStatusResponse(BaseModel):
    """Lightweight availability check for the floating widget."""

    available: bool = False
    configured: bool = False
    enabled: bool = True
    provider: Optional[str] = None


class ChatSettingsUpdateRequest(BaseModel):
    llm_provider: Optional[str] = Field(default=None, max_length=20)
    llm_api_key: Optional[str] = Field(default=None, max_length=500)
    llm_model: Optional[str] = Field(default=None, max_length=200)
    llm_base_url: Optional[str] = Field(default=None, max_length=500)
    enabled: Optional[bool] = None

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


class ChatPageContext(BaseModel):
    """Where the user is in the dashboard when they open the assistant."""

    route: Optional[str] = Field(default=None, max_length=200)
    label: Optional[str] = Field(default=None, max_length=120)
    memory_id: Optional[str] = Field(default=None, max_length=100)
    project_id: Optional[str] = Field(default=None, max_length=100)


class ChatAgentRequest(BaseModel):
    messages: List[ChatMessageInput] = Field(min_length=1)
    page: Optional[ChatPageContext] = None
    max_steps: int = Field(default=5, ge=1, le=8)


class ChatStreamRequest(BaseModel):
    messages: List[ChatMessageInput] = Field(min_length=1)
    session_id: Optional[str] = Field(default=None, max_length=64)
    page: Optional[ChatPageContext] = None
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


class ChatRefineRequest(BaseModel):
    memory_id: str = Field(min_length=1, max_length=100)


class ChatRefinedMemory(BaseModel):
    content: str = ""
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    rationale: Optional[str] = None


class ChatRefineResponse(BaseModel):
    memory_id: str
    original: ChatRefinedMemory
    proposed: ChatRefinedMemory


class ChatRefineApplyRequest(BaseModel):
    memory_id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=10, max_length=50000)
    category: Optional[str] = Field(default=None, max_length=50)
    tags: Optional[List[str]] = None


class ChatRefineApplyResponse(BaseModel):
    memory_id: str
    updated: bool = True
    content: str = ""


SAVE_CATEGORIES = ("decision", "bug", "incident", "idea", "code_snippet")


class ChatSummarizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100000)


class ChatMemoryProposal(BaseModel):
    content: str = ""
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    summary: Optional[str] = None


class ChatSummarizeResponse(BaseModel):
    proposed: ChatMemoryProposal


class ChatSaveMemoryRequest(BaseModel):
    content: str = Field(min_length=10, max_length=50000)
    category: str = Field(default="idea", max_length=50)
    tags: Optional[List[str]] = None
    project_id: Optional[str] = Field(default=None, max_length=100)

    @field_validator("category")
    @classmethod
    def _valid_category(cls, value: str) -> str:
        normalized = (value or "idea").strip().lower()
        return normalized if normalized in SAVE_CATEGORIES else "idea"


class ChatSaveMemoryResponse(BaseModel):
    id: str
    category: str
    status: str = "saved"


class ChatEnrichRequest(BaseModel):
    memory_id: str = Field(min_length=1, max_length=100)


class ChatEnrichResponse(BaseModel):
    memory_id: str
    title: str = ""
    abstract: str = ""
    tags: List[str] = Field(default_factory=list)
    display_kind: str = ""
    model: str = ""
    merged_tags: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
