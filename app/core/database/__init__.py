"""Database module for mem-mesh application.

This module provides database connection and models.
"""

from .base import SQLITE_VEC_AVAILABLE, Database
from .models import Memory
from .schema_migrator import CURRENT_SCHEMA_VERSION, SchemaMigrator

__all__ = [
    "Database",
    "Memory",
    "SQLITE_VEC_AVAILABLE",
    "SchemaMigrator",
    "CURRENT_SCHEMA_VERSION",
]
