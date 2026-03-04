"""Schemas module for mem-mesh application.

This module provides request and response schemas.
"""

from .optimization import (
    OptimizedSessionContext,
    PinStatistics,
    PromotionSuggestion,
    SessionStatistics,
    SessionStatRecord,
    TokenInfo,
    TokenSavingsReport,
    TokenUsageRecord,
)
from .pins import (
    PinCreate,
    PinListParams,
    PinResponse,
    PinUpdate,
)
from .projects import (
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    ProjectWithStats,
)
from .requests import (
    AddParams,
    ContextParams,
    DeleteParams,
    SearchParams,
    StatsParams,
    UpdateParams,
)
from .responses import (
    AddResponse,
    ContextResponse,
    DeleteResponse,
    ErrorResponse,
    RelatedMemory,
    SearchResponse,
    SearchResult,
    StatsResponse,
    UpdateResponse,
)
from .sessions import (
    SessionContext,
    SessionCreate,
    SessionEndParams,
    SessionResponse,
    SessionResumeParams,
)

__all__ = [
    # Requests
    "AddParams",
    "SearchParams",
    "ContextParams",
    "DeleteParams",
    "UpdateParams",
    "StatsParams",
    # Responses
    "AddResponse",
    "SearchResult",
    "SearchResponse",
    "RelatedMemory",
    "ContextResponse",
    "DeleteResponse",
    "UpdateResponse",
    "StatsResponse",
    "ErrorResponse",
    # Pins
    "PinCreate",
    "PinUpdate",
    "PinResponse",
    "PinListParams",
    # Sessions
    "SessionCreate",
    "SessionResponse",
    "SessionContext",
    "SessionResumeParams",
    "SessionEndParams",
    # Projects
    "ProjectCreate",
    "ProjectUpdate",
    "ProjectResponse",
    "ProjectWithStats",
    # Optimization
    "TokenInfo",
    "SessionStatistics",
    "PinStatistics",
    "OptimizedSessionContext",
    "SessionStatRecord",
    "TokenUsageRecord",
    "TokenSavingsReport",
    "PromotionSuggestion",
]
