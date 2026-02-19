"""Database module for mem-mesh application.

This module provides database connection and models.
"""

from .base import Database, SQLITE_VEC_AVAILABLE
from .models import Memory
from .schema_migrator import SchemaMigrator, CURRENT_SCHEMA_VERSION

__all__ = ["Database", "Memory", "SQLITE_VEC_AVAILABLE", "SchemaMigrator", "CURRENT_SCHEMA_VERSION"]
