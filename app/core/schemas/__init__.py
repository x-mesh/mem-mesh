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
]
