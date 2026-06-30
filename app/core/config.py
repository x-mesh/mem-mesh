"""
Configuration module for mem-mesh application.

This module provides configuration management using pydantic-settings
with support for environment variables and .env file loading.
Supports storage_mode for direct SQLite access or API mode.
"""

import os
import platform
import secrets
import tempfile
from pathlib import Path
from typing import Literal, Optional, Tuple

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
        default="dragonkue/snowflake-arctic-embed-l-v2.0-ko",
        description=(
            "Sentence-transformers model name. Default: "
            "dragonkue/snowflake-arctic-embed-l-v2.0-ko (Korean retrieval SOTA, "
            "MTEB-ko #1, 1024-dim). Override via MEM_MESH_EMBEDDING_MODEL."
        ),
    )
    embedding_dim: int = Field(default=1024, description="Embedding vector dimensions")

    # Minimum assistant-message length for a SubagentStop hook to attempt a save.
    # Below this the turn is treated as too thin to be worth persisting. Runtime-
    # overridable from the dashboard (see runtime_config). Env:
    # MEM_MESH_HOOK_MIN_MESSAGE_LENGTH.
    hook_min_message_length: int = Field(
        default=100,
        ge=0,
        description=(
            "Minimum assistant-message length (chars) for the SubagentStop hook "
            "to save a memory. Lower it to capture shorter subagent results. "
            "Override via MEM_MESH_HOOK_MIN_MESSAGE_LENGTH."
        ),
    )

    # Display timezone for API/MCP output. Storage stays UTC everywhere; only
    # the response boundary localizes timestamps. Runtime-overridable from the
    # dashboard (see runtime_config). Env: MEM_MESH_DISPLAY_TIMEZONE.
    display_timezone: str = Field(
        default="UTC",
        description=(
            "IANA timezone used to localize timestamps in API/MCP responses "
            "(e.g. Asia/Seoul). Storage is always UTC; default UTC returns "
            "timestamps unchanged. Override via MEM_MESH_DISPLAY_TIMEZONE."
        ),
    )

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
    enable_adaptive_hybrid: bool = Field(
        # OFF by default: self-retrieval eval can't measure RRF-weight tuning
        # (FTS exact-match dominates), so the wiki-mesh +15pp gain is unverified
        # on this corpus. Enable after a labeled query eval set confirms it.
        default=False,
        description="Adapt RRF vector/text weights to query length: short keyword "
        "queries favor FTS, long natural-language queries favor vector search",
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
    # None = inherit from auth_enabled (resolved in apply_auth_inheritance).
    # Set explicitly via MEM_MESH_MCP_AUTH_ENABLED / MEM_MESH_WEB_AUTH_ENABLED to
    # override the inherited value (e.g. auth_enabled=True but MCP left open).
    mcp_auth_enabled: Optional[bool] = Field(
        default=None,
        description=(
            "Enable OAuth auth for MCP SSE endpoints. None (default) inherits "
            "auth_enabled."
        ),
    )
    web_auth_enabled: Optional[bool] = Field(
        default=None,
        description=(
            "Enable OAuth auth for Dashboard/Web API endpoints. None (default) "
            "inherits auth_enabled."
        ),
    )

    # Hook endpoint authentication (independent of OAuth auth_enabled flags).
    # Guards POST /api/hooks/claude/* against unauthenticated remote memory
    # injection. Env: MEM_MESH_HOOK_TOKEN. File fallback: ~/.mem-mesh/hook_token.
    hook_token: Optional[str] = Field(
        default=None,
        description=(
            "Shared secret for hook endpoints. If unset, falls back to "
            "~/.mem-mesh/hook_token. When set, a matching "
            "'Authorization: Bearer <token>' is required on any bind host. When "
            "unset, hook writes are allowed; a non-loopback bind additionally "
            "logs a one-time warning (the firewall is the trust boundary — set "
            "this token to require authentication)."
        ),
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
    public_url: str = Field(
        default="",
        description=(
            "Public base URL (domain/proxy) advertised to clients in the /connect "
            "config. Shared by all dashboard users. Empty = fall back to the "
            "request origin. Env: MEM_MESH_PUBLIC_URL; also dashboard-settable."
        ),
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

    # Relay worker settings
    relay_hub_url: str = Field(
        default="",
        description="Default team hub URL used by relay share UI",
    )
    relay_source_node_id: str = Field(
        default="",
        description="Default source node id used by relay share UI",
    )
    relay_llm_provider: str = Field(
        default="anthropic",
        description="LLM provider for relay enrichment: 'anthropic' or 'openai'",
    )
    relay_llm_api_key: str = Field(
        default="",
        description="API key for relay LLM enrichment worker",
    )
    relay_llm_model: str = Field(
        default="",
        description=(
            "Model used by relay text enrichment and digest workers; empty uses "
            "the provider default (anthropic: claude-sonnet-4-6, openai: gpt-4o-mini)"
        ),
    )
    relay_llm_base_url: str = Field(
        default="",
        description=(
            "LLM endpoint for relay enrichment; empty uses the provider default "
            "(Anthropic Messages or OpenAI chat/completions)"
        ),
    )
    relay_llm_timeout: float = Field(
        default=30.0,
        ge=1.0,
        description="Timeout for relay LLM API calls in seconds",
    )
    relay_http_timeout: float = Field(
        default=10.0,
        ge=1.0,
        description="Timeout for relay S2S HTTP delivery in seconds",
    )
    relay_hub_token: str = Field(
        default="",
        description="Bearer token used by personal-node outbox delivery to hub",
    )
    relay_prompt_version: str = Field(
        default="relay-v1",
        description="Prompt version stamped on relay enrichment and digest outputs",
    )

    # Chat assistant LLM settings (separate namespace from relay_llm so the
    # dashboard chat assistant can use a different provider/model than relay
    # enrichment). Reuses the same provider adapters via build_chat_enricher.
    chat_llm_provider: str = Field(
        default="anthropic",
        description="LLM provider for the chat assistant: 'anthropic' or 'openai'",
    )
    chat_llm_api_key: str = Field(
        default="",
        description="API key for the chat assistant LLM",
    )
    chat_llm_model: str = Field(
        default="",
        description=(
            "Model used by the chat assistant; empty uses the provider default "
            "(anthropic: claude-sonnet-4-6, openai: gpt-4o-mini)"
        ),
    )
    chat_llm_base_url: str = Field(
        default="",
        description=(
            "LLM endpoint for the chat assistant; empty uses the provider default"
        ),
    )
    chat_llm_timeout: float = Field(
        default=60.0,
        ge=1.0,
        description="Timeout for chat assistant LLM calls in seconds",
    )
    chat_llm_max_tokens: int = Field(
        default=2048,
        ge=1,
        description="Max output tokens per chat assistant turn",
    )
    chat_enabled: bool = Field(
        default=True,
        description="Master toggle for the dashboard chat assistant widget",
    )
    chat_output_language: str = Field(
        default="auto",
        description=(
            "Language for 'Save as memory' summaries: 'auto' (match the input "
            "conversation language), 'korean', or 'english'. JSON keys and the "
            "category enum always stay in English."
        ),
    )

    @field_validator("storage_mode")
    @classmethod
    def validate_storage_mode(cls, v: str) -> str:
        """Validate storage_mode is one of the valid options (Requirement 1.5)."""
        if v not in ("direct", "api"):
            raise ValueError("storage_mode must be 'direct' or 'api'")
        return v

    @field_validator("relay_llm_provider")
    @classmethod
    def validate_relay_llm_provider(cls, v: str) -> str:
        """Validate relay LLM provider is one of the supported adapters."""
        normalized = (v or "anthropic").strip().lower()
        if normalized not in ("anthropic", "openai"):
            raise ValueError("relay_llm_provider must be 'anthropic' or 'openai'")
        return normalized

    @field_validator("chat_llm_provider")
    @classmethod
    def validate_chat_llm_provider(cls, v: str) -> str:
        """Validate chat assistant LLM provider is one of the supported adapters."""
        normalized = (v or "anthropic").strip().lower()
        if normalized not in ("anthropic", "openai"):
            raise ValueError("chat_llm_provider must be 'anthropic' or 'openai'")
        return normalized

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

    @field_validator("display_timezone")
    @classmethod
    def validate_display_timezone(cls, v: str) -> str:
        """Validate the display timezone is a known IANA name (or UTC)."""
        name = (v or "UTC").strip() or "UTC"
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(name)
        except Exception as exc:
            raise ValueError(f"invalid IANA timezone: {name!r}") from exc
        return name

    @model_validator(mode="after")
    def validate_basic_auth_password(self) -> "Settings":
        """Ensure admin_password is set when basic auth is enabled."""
        if self.web_basic_auth_enabled and not self.admin_password:
            raise ValueError(
                "admin_password must be set when web_basic_auth_enabled is True"
            )
        return self

    @model_validator(mode="after")
    def apply_auth_inheritance(self) -> "Settings":
        """Resolve auth sub-flags: ``None`` inherits ``auth_enabled``.

        Implements the inheritance the OAuth middleware already documents
        ("mcp/web auth defaults to auth_enabled") but never enforced — the
        sub-flags were static ``default=False``, so enabling ``auth_enabled``
        left ``/mcp`` and ``/api`` open. ``object.__setattr__`` bypasses the
        per-field validation that ``validate_assignment=True`` would otherwise
        re-trigger here.
        """
        if self.mcp_auth_enabled is None:
            object.__setattr__(self, "mcp_auth_enabled", self.auth_enabled)
        if self.web_auth_enabled is None:
            object.__setattr__(self, "web_auth_enabled", self.auth_enabled)
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


# Legacy on-disk hook-token fallback, written 0600 by the CLI installer
# (``app.cli.install_hooks._ensure_hook_token``). Kept for backwards
# compatibility; the server now prefers the data-dir token below.
HOOK_TOKEN_FILE = Path.home() / ".mem-mesh" / "hook_token"


def _data_dir_hook_token_file() -> Path:
    """Server-managed hook-token path inside the data directory.

    Sits next to the SQLite database (``database_path``), so when ``./data`` is
    a mounted Docker volume the auto-generated token survives container
    restarts. Preferred over ``~/.mem-mesh/hook_token`` because a container home
    directory is typically ephemeral.
    """
    db_path = getattr(get_settings(), "database_path", None) or _default_db_path()
    return Path(db_path).expanduser().resolve().parent / "hook_token"


def _read_token_file(path: Path) -> Optional[str]:
    """Return the trimmed contents of a token file, or None if absent/unreadable."""
    try:
        if path.exists():
            token = path.read_text(encoding="utf-8").strip()
            return token or None
    except OSError:
        # Unreadable token file degrades to "no token configured"; the
        # loopback/warning logic in verify_hook_token then applies.
        pass
    return None


def hook_token_source() -> str:
    """Report where the active hook token comes from.

    One of ``"env"`` (MEM_MESH_HOOK_TOKEN / .env), ``"data_file"``
    (``<data dir>/hook_token``), ``"legacy_file"`` (``~/.mem-mesh/hook_token``)
    or ``"none"``. Mirrors the precedence in :func:`resolve_hook_token` so the
    dashboard can warn that an env-pinned token overrides a rotated one.
    """
    if (get_settings().hook_token or "").strip():
        return "env"
    if _read_token_file(_data_dir_hook_token_file()):
        return "data_file"
    if _read_token_file(HOOK_TOKEN_FILE):
        return "legacy_file"
    return "none"


def resolve_hook_token() -> Optional[str]:
    """Resolve the hook auth token: env first, then on-disk fallbacks.

    Resolution order:
    1. ``settings.hook_token`` (from MEM_MESH_HOOK_TOKEN / .env)
    2. ``<data dir>/hook_token`` — server-managed, generated by
       :func:`bootstrap_hook_token`; persists on the mounted data volume.
    3. ``~/.mem-mesh/hook_token`` — legacy path written by the CLI installer.

    Returns None when none is configured. Read every call (no caching) so a
    token written/rotated after startup is picked up without a restart.
    """
    token = (get_settings().hook_token or "").strip()
    if token:
        return token
    return _read_token_file(_data_dir_hook_token_file()) or _read_token_file(
        HOOK_TOKEN_FILE
    )


def _atomic_write_token(path: Path, token: str) -> None:
    """Write ``token`` to ``path`` atomically with 0600 perms.

    Mirrors ``app.cli.hooks.json_ops._atomic_write_text`` but kept local so the
    core layer does not import the CLI layer. The content is written to a temp
    file in the same directory, chmod'd, then ``os.replace``'d into place so a
    crash mid-write can never truncate the original.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def bootstrap_hook_token() -> Tuple[str, bool]:
    """Ensure a hook auth token exists, generating one if none is configured.

    Returns ``(token, created)``. When a token already resolves (env or either
    on-disk fallback) it is returned with ``created=False``. Otherwise a fresh
    ``secrets.token_urlsafe(32)`` is written to ``<data dir>/hook_token`` (0600)
    and returned with ``created=True``.

    Called once at server startup so ``docker compose up`` succeeds without a
    pre-seeded MEM_MESH_HOOK_TOKEN, while hook writes still require
    authentication (a token always exists; unauthenticated writes are rejected).
    """
    existing = resolve_hook_token()
    if existing:
        return existing, False
    token = secrets.token_urlsafe(32)
    _atomic_write_token(_data_dir_hook_token_file(), token)
    return token, True


def rotate_hook_token() -> str:
    """Generate a new hook token in the data dir, replacing any existing one.

    Returns the new token. Unlike :func:`bootstrap_hook_token` this always
    writes a fresh value — used by the dashboard "regenerate" action. Note that
    an env-provided MEM_MESH_HOOK_TOKEN takes precedence in
    :func:`resolve_hook_token`, so rotation has no effect while that env var is
    set; callers should surface that to the operator.
    """
    token = secrets.token_urlsafe(32)
    _atomic_write_token(_data_dir_hook_token_file(), token)
    return token


# ---------------------------------------------------------------------------
# First-run setup token
# ---------------------------------------------------------------------------
# A one-time bootstrap secret that lets an operator configure dashboard auth from
# the web ``/setup`` page WITHOUT shell access, while preserving the loopback
# gate's security property: only someone who can read the server console (or the
# data-dir file) ever sees it. Generated at startup ONLY when no dashboard auth
# is configured yet, and consumed (deleted) the moment setup completes — so a
# network-exposed, still-unconfigured server cannot be hijacked remotely.


def _data_dir_setup_token_file() -> Path:
    """First-run setup-token path inside the data directory (next to the DB).

    Shares the data volume so the token survives a container restart mid-onboard,
    and is removed once auth is configured.
    """
    db_path = getattr(get_settings(), "database_path", None) or _default_db_path()
    return Path(db_path).expanduser().resolve().parent / "setup_token"


def read_setup_token() -> Optional[str]:
    """Return the pending first-run setup token, or None if none is active."""
    return _read_token_file(_data_dir_setup_token_file())


def ensure_setup_token() -> str:
    """Return the pending setup token, generating + persisting one if absent.

    The caller decides *whether* a token should exist (i.e. that no dashboard
    auth is configured yet); this only manages the file. Idempotent — repeated
    calls return the same token until it is cleared.
    """
    existing = read_setup_token()
    if existing:
        return existing
    token = secrets.token_urlsafe(32)
    _atomic_write_token(_data_dir_setup_token_file(), token)
    return token


def clear_setup_token() -> None:
    """Delete the setup-token file if present (idempotent).

    Called when setup completes, and at startup when auth is already configured
    so a stale token from an earlier state cannot linger as a live credential.
    """
    try:
        _data_dir_setup_token_file().unlink(missing_ok=True)
    except OSError:
        pass


def verify_setup_token(candidate: str) -> bool:
    """Constant-time check of ``candidate`` against the pending setup token."""
    token = read_setup_token()
    if not token or not candidate:
        return False
    return secrets.compare_digest(str(candidate), str(token))


# The host uvicorn actually binds to. ``settings.server_host`` is the *static*
# default (127.0.0.1) and does NOT reflect a ``--host`` / ``MEM_MESH_SERVER_HOST``
# override passed at launch, so hook-token loopback judgment must use this
# runtime value instead. Recorded once by the server start path
# (``create_uvicorn_config``); mirrored to an env var so uvicorn reload/worker
# subprocesses (which re-import the app instead of calling that function) still
# see it.
_EFFECTIVE_BIND_HOST_ENV = "MEM_MESH_EFFECTIVE_BIND_HOST"
_effective_bind_host: Optional[str] = None


def set_effective_bind_host(host: Optional[str]) -> None:
    """Record the host uvicorn is actually binding to (server start path)."""
    global _effective_bind_host
    _effective_bind_host = host
    if host:
        os.environ[_EFFECTIVE_BIND_HOST_ENV] = host


def get_effective_bind_host() -> str:
    """Effective uvicorn bind host: ``--host`` > ``MEM_MESH_SERVER_HOST`` > setting.

    Resolution order: the value recorded by :func:`set_effective_bind_host`
    (same process), then the ``MEM_MESH_EFFECTIVE_BIND_HOST`` env var (reload /
    worker subprocesses), then the static ``settings.server_host`` fallback for
    embedded / import-only / test usage where no server start path ran.
    """
    if _effective_bind_host:
        return _effective_bind_host
    env_host = os.environ.get(_EFFECTIVE_BIND_HOST_ENV)
    if env_host:
        return env_host
    return get_settings().server_host
