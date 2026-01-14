"""Schemas module for mem-mesh application.

This module provides request and response schemas.
"""

from .requests import (
    AddParams,
    SearchParams,
    ContextParams,
    DeleteParams,
    UpdateParams,
    StatsParams,
)
from .responses import (
    AddResponse,
    SearchResult,
    SearchResponse,
    RelatedMemory,
    ContextResponse,
    DeleteResponse,
    UpdateResponse,
    StatsResponse,
    ErrorResponse,
)
from .pins import (
    PinCreate,
    PinUpdate,
    PinResponse,
    PinListParams,
)
from .sessions import (
    SessionCreate,
    SessionResponse,
    SessionContext,
    SessionResumeParams,
    SessionEndParams,
)
from .projects import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectWithStats,
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
]
