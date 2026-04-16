"""
Configuration module for mem-mesh application.

This module provides configuration management using pydantic-settings
with support for environment variables and .env file loading.
Supports storage_mode for direct SQLite access or API mode.
"""

import os
import platform
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


def _default_data_dir() -> Path:
    """Return a stable per-user data directory.

    macOS:   ~/Library/Application Support/mem-mesh
    Linux:   $XDG_DATA_HOME/mem-mesh  (fallback: ~/.local/share/mem-mesh)
    Windows: %APPDATA%/mem-mesh        (fallback: ~/AppData/Roaming/mem-mesh)

    If a legacy ./data/memories.db exists in the CWD, prefer that for
    backwards compatibility with existing deployments.
    """
    legacy = Path.cwd() / "data" / "memories.db"
    if legacy.exists():
        import sys
        print(
            f"[mem-mesh] Using legacy database at {legacy} (found in CWD). "
            f"To use the standard per-user location instead, remove this file "
            f"or set MEM_MESH_DATABASE_PATH explicitly.",
            file=sys.stderr,
        )
        return legacy.parent

    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "mem-mesh"
    if system == "Windows":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "mem-mesh"
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "mem-mesh"


def _default_db_path() -> str:
    return str(_default_data_dir() / "memories.db")


class Settings(BaseSettings):
    """
    Application settings with environment variable support.

    All settings can be overridden via environment variables with MEM_MESH_ prefix.
    Command-line arguments take precedence over environment variables.

    Requirements: 1.1, 1.4, 1.5, 7.1, 7.2, 7.3, 7.4, 7.5
    """

    # Storage mode configuration (Requirements 1.1, 1.4, 1.5, 7.1)
    storage_mode: Literal["direct", "api"] = Field(
        default="direct",
        description="Storage mode: 'direct' for SQLite direct access, 'api' for FastAPI server",
    )

    # API settings for api mode (Requirements 7.2)
    api_base_url: str = Field(
        default="http://localhost:8000",
        description="FastAPI server base URL (used when storage_mode='api')",
    )

    # Database configuration
    database_path: str = Field(
        default_factory=lambda: _default_db_path(),
        description="Path to SQLite database file (default: XDG_DATA_HOME/mem-mesh/memories.db)",
    )

    # SQLite WAL settings (Requirements 7.3)
    busy_timeout: int = Field(
        default=5000, ge=1000, description="SQLite busy timeout in milliseconds"
    )

    # Embedding configuration
    embedding_model: str = Field(
        default="nlpai-lab/KURE-v1",
        description=(
            "Sentence-transformers model name. Default: nlpai-lab/KURE-v1 "
            "(Korean-tuned BGE-M3, 1024-dim). Override via MEM_MESH_EMBEDDING_MODEL."
        ),
    )
    embedding_dim: int = Field(default=1024, description="Embedding vector dimensions")

    # Search configuration
    search_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for search results",
    )

    # UnifiedSearchService feature flags
    use_unified_search: bool = Field(
        default=True,
        description="Use UnifiedSearchService instead of legacy SearchService",
    )
    enable_quality_features: bool = Field(
        default=True,
        description="Enable quality features (intent analysis, scoring, noise filter)",
    )
    enable_korean_optimization: bool = Field(
        default=True,
        description="Enable Korean language optimization (translation dict, query expansion)",
    )
    enable_noise_filter: bool = Field(
        default=True, description="Enable noise filtering for search queries"
    )
    enable_search_cache: bool = Field(
        default=True, description="Enable caching for embeddings and search results"
    )
    enable_score_normalization: bool = Field(
        default=True,
        description="Enable score normalization for better score distribution",
    )
    score_normalization_method: str = Field(
        default="sigmoid",
        description="Score normalization method (sigmoid/minmax/zscore/percentile)",
    )
    sigmoid_k: float = Field(
        default=10.0,
        ge=1.0,
        le=50.0,
        description="Sigmoid normalization steepness (higher = sharper cutoff)",
    )
    sigmoid_threshold: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        description="Sigmoid normalization center point (should match model's avg similarity score)",
    )
    rrf_vector_weight: float = Field(
        default=1.0,
        ge=0.0,
        description="RRF weight for vector search results",
    )
    rrf_text_weight: float = Field(
        default=1.2,
        ge=0.0,
        description="RRF weight for FTS text search results (higher = prefer keyword matches)",
    )
    enable_search_warmup: bool = Field(
        default=True, description="Enable search warmup on server startup"
    )

    # Reranking configuration
    enable_reranking: bool = Field(
        default=False,
        description="Enable cross-encoder reranking for search results (opt-in)",
    )
    reranking_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L6-v2",
        description="Cross-encoder model for reranking",
    )

    # Conflict detection configuration
    enable_conflict_detection: bool = Field(
        default=False,
        description="Enable conflict detection on memory add (opt-in)",
    )
    conflict_nli_model: str = Field(
        default="MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
        description="NLI cross-encoder model for contradiction detection",
    )
    conflict_contradiction_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum contradiction probability to flag as conflict",
    )
    conflict_similarity_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum vector similarity to consider as conflict candidate",
    )
    conflict_max_candidates: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of candidates to check for conflicts",
    )
    reranking_top_k_multiplier: int = Field(
        default=3,
        ge=2,
        le=10,
        description="Retrieve topk * multiplier candidates, rerank, return topk",
    )

    # Cache TTL settings (in seconds)
    cache_embedding_ttl: int = Field(
        default=86400,
        ge=60,
        description="Embedding cache TTL in seconds (default: 24 hours)",
    )
    cache_search_ttl: int = Field(
        default=3600,
        ge=60,
        description="Search results cache TTL in seconds (default: 1 hour)",
    )
    cache_context_ttl: int = Field(
        default=1800,
        ge=60,
        description="Context cache TTL in seconds (default: 30 minutes)",
    )

    # Token estimation settings
    enable_token_metadata: bool = Field(
        default=False,
        description="Include token estimation metadata (_meta) in MCP responses",
    )

    # OAuth/Authentication settings
    auth_enabled: bool = Field(
        default=False, description="Enable OAuth authentication globally"
    )
    mcp_auth_enabled: bool = Field(
        default=False, description="Enable OAuth authentication for MCP SSE endpoints"
    )
    web_auth_enabled: bool = Field(
        default=False,
        description="Enable OAuth authentication for Dashboard/Web API endpoints",
    )

    # Basic Auth for Web Dashboard (simpler alternative to OAuth for browser access)
    web_basic_auth_enabled: bool = Field(
        default=False,
        description="Enable Basic Auth for web dashboard (browser login)",
    )
    admin_username: str = Field(
        default="admin",
        description="Admin username for web dashboard Basic Auth",
    )
    admin_password: str = Field(
        default="",
        description="Admin password for web dashboard Basic Auth (required if basic_auth_enabled)",
    )
    oauth_issuer: str = Field(
        default="http://localhost:8000",
        description="OAuth issuer URL (used in metadata discovery)",
    )
    oauth_access_token_ttl: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Default access token TTL in seconds (1 hour)",
    )
    oauth_refresh_token_ttl: int = Field(
        default=604800,
        ge=3600,
        le=2592000,
        description="Default refresh token TTL in seconds (7 days)",
    )
    oauth_code_ttl: int = Field(
        default=600,
        ge=60,
        le=3600,
        description="Authorization code TTL in seconds (10 minutes)",
    )

    # CORS configuration
    cors_origins: str = Field(
        default="http://localhost:8000,http://127.0.0.1:8000",
        description="Comma-separated list of allowed CORS origins. Use '*' for development only.",
    )

    # Logging configuration
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    log_file: Optional[str] = Field(
        default=None, description="Log file path (None for console only)"
    )
    log_format: str = Field(default="text", description="Log format (text or json)")
    log_output: str = Field(
        default="console", description="Log output destination (console, file, or both)"
    )

    # Server configuration
    server_host: str = Field(default="127.0.0.1", description="Server host address")
    server_port: int = Field(
        default=8000, ge=1, le=65535, description="Server port number"
    )
    server_workers: int = Field(
        default=1, ge=1, le=32, description="Number of uvicorn worker processes"
    )

    # Content length settings
    max_content_length: int = Field(
        default=10000, ge=1, description="Maximum content length in characters"
    )
    min_content_length: int = Field(
        default=10, ge=1, description="Minimum content length in characters"
    )

    # Retry configuration
    max_embedding_retries: int = Field(
        default=3, ge=1, description="Maximum retries for embedding generation"
    )
    embedding_retry_delay: float = Field(
        default=0.1,
        ge=0.0,
        description="Base delay between embedding retries in seconds",
    )

    # API client settings
    api_timeout: float = Field(
        default=30.0, ge=1.0, description="API request timeout in seconds"
    )
    api_max_retries: int = Field(
        default=3, ge=1, description="Maximum retries for API requests"
    )

    @field_validator("storage_mode")
    @classmethod
    def validate_storage_mode(cls, v: str) -> str:
        """Validate storage_mode is one of the valid options (Requirement 1.5)."""
        if v not in ("direct", "api"):
            raise ValueError("storage_mode must be 'direct' or 'api'")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is one of the standard levels."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v.upper()

    @field_validator("embedding_model")
    @classmethod
    def validate_embedding_model(cls, v: str) -> str:
        """Validate embedding model name is not empty."""
        if not v.strip():
            raise ValueError("embedding_model cannot be empty")
        return v.strip()

    @model_validator(mode="after")
    def validate_basic_auth_password(self) -> "Settings":
        """Ensure admin_password is set when basic auth is enabled."""
        if self.web_basic_auth_enabled and not self.admin_password:
            raise ValueError(
                "admin_password must be set when web_basic_auth_enabled is True"
            )
        return self

    model_config = {
        "env_file": ".env",
        "env_prefix": "MEM_MESH_",
        "case_sensitive": False,
        "validate_assignment": True,
        "extra": "ignore",
    }


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    Get the global settings instance (lazy initialization).

    This function provides dependency injection support for FastAPI
    and allows for easy testing with different configurations.

    Returns:
        Settings: The global settings instance
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """
    Reload settings from environment and .env file.

    This is useful for testing or when configuration changes at runtime.

    Returns:
        Settings: New settings instance with reloaded values
    """
    global _settings
    _settings = Settings()
    return _settings


def create_settings(**kwargs) -> Settings:
    """
    Create a new Settings instance with custom values.

    Useful for testing or programmatic configuration.

    Args:
        **kwargs: Settings values to override

    Returns:
        Settings: New settings instance with provided values
    """
    return Settings(**kwargs)
