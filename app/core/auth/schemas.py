"""
OAuth Pydantic schemas for request/response validation.

MCP 2025-03-26 OAuth 스펙 준수.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


# ============================================================================
# Client Registration (RFC 7591 Dynamic Client Registration)
# ============================================================================


class OAuthClientRegistrationRequest(BaseModel):
    """Dynamic Client Registration request."""

    client_name: str = Field(..., description="Human-readable client name")
    redirect_uris: List[str] = Field(
        default_factory=list, description="Array of redirect URIs"
    )
    grant_types: List[str] = Field(
        default=["authorization_code", "refresh_token"], description="OAuth grant types"
    )
    token_endpoint_auth_method: str = Field(
        default="none",
        description="Token endpoint auth method (none for public clients)",
    )
    scope: Optional[str] = Field(
        default="read write", description="Space-separated list of scopes"
    )


class OAuthClientRegistrationResponse(BaseModel):
    """Dynamic Client Registration response."""

    client_id: str
    client_secret: Optional[str] = None  # Only for confidential clients
    client_id_issued_at: int
    client_secret_expires_at: int = Field(default=0)  # 0 = never expires

    # Echo back registration data
    client_name: str
    redirect_uris: List[str]
    grant_types: List[str]
    token_endpoint_auth_method: str
    scope: str


# ============================================================================
# Client Management (Dashboard API)
# ============================================================================


class OAuthClientCreate(BaseModel):
    """Create OAuth client request (Dashboard API)."""

    client_name: str = Field(..., min_length=1, max_length=255)
    redirect_uris: List[str] = Field(default_factory=list)
    scopes: List[str] = Field(default=["read", "write"])
    grant_types: List[str] = Field(default=["authorization_code", "refresh_token"])
    client_type: str = Field(default="public")  # "public" or "confidential"
    access_token_ttl: int = Field(default=3600, ge=60, le=86400)
    refresh_token_ttl: int = Field(default=604800, ge=3600, le=2592000)


class OAuthClientUpdate(BaseModel):
    """Update OAuth client request."""

    client_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    redirect_uris: Optional[List[str]] = None
    scopes: Optional[List[str]] = None
    is_active: Optional[bool] = None
    access_token_ttl: Optional[int] = Field(default=None, ge=60, le=86400)
    refresh_token_ttl: Optional[int] = Field(default=None, ge=3600, le=2592000)


class OAuthClientResponse(BaseModel):
    """OAuth client response (without secret)."""

    id: str
    client_id: str
    client_name: str
    client_type: str
    redirect_uris: List[str]
    scopes: List[str]
    grant_types: List[str]
    access_token_ttl: int
    refresh_token_ttl: int
    is_active: bool
    created_at: str
    updated_at: str


class OAuthClientWithSecretResponse(OAuthClientResponse):
    """OAuth client response with secret (only on creation)."""

    client_secret: str


# ============================================================================
# Authorization Endpoint
# ============================================================================


class OAuthAuthorizeRequest(BaseModel):
    """Authorization request parameters."""

    response_type: str = Field(default="code", description="Must be 'code'")
    client_id: str
    redirect_uri: str
    scope: Optional[str] = Field(default="read write")
    state: Optional[str] = None

    # PKCE (required by MCP 2025-03-26)
    code_challenge: str
    code_challenge_method: str = Field(default="S256")


class OAuthAuthorizeResponse(BaseModel):
    """Authorization response (redirect parameters)."""

    code: str
    state: Optional[str] = None


class OAuthAuthorizeError(BaseModel):
    """Authorization error response."""

    error: str
    error_description: Optional[str] = None
    state: Optional[str] = None


# ============================================================================
# Token Endpoint
# ============================================================================


class OAuthTokenRequest(BaseModel):
    """Token request parameters."""

    grant_type: str  # "authorization_code" or "refresh_token"

    # For authorization_code grant
    code: Optional[str] = None
    redirect_uri: Optional[str] = None
    code_verifier: Optional[str] = None  # PKCE

    # For refresh_token grant
    refresh_token: Optional[str] = None

    # Client authentication (for confidential clients)
    client_id: Optional[str] = None
    client_secret: Optional[str] = None

    # Scope (optional, for refresh)
    scope: Optional[str] = None


class OAuthTokenResponse(BaseModel):
    """Token response."""

    access_token: str
    token_type: str = Field(default="Bearer")
    expires_in: int  # seconds
    refresh_token: Optional[str] = None
    scope: str


class OAuthTokenError(BaseModel):
    """Token error response."""

    error: str
    error_description: Optional[str] = None


# ============================================================================
# Token Introspection / Revocation
# ============================================================================


class OAuthTokenRevokeRequest(BaseModel):
    """Token revocation request."""

    token: str
    token_type_hint: Optional[str] = None  # "access_token" or "refresh_token"


class OAuthTokenIntrospectResponse(BaseModel):
    """Token introspection response."""

    active: bool
    scope: Optional[str] = None
    client_id: Optional[str] = None
    exp: Optional[int] = None
    iat: Optional[int] = None


# ============================================================================
# OAuth Server Metadata (RFC 8414)
# ============================================================================


class OAuthMetadata(BaseModel):
    """OAuth Authorization Server Metadata.

    Per MCP 2025-03-26 spec:
    https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization
    """

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: Optional[str] = None
    revocation_endpoint: Optional[str] = None
    introspection_endpoint: Optional[str] = None

    # Supported features
    response_types_supported: List[str] = Field(default=["code"])
    grant_types_supported: List[str] = Field(
        default=["authorization_code", "refresh_token"]
    )
    token_endpoint_auth_methods_supported: List[str] = Field(
        default=["none", "client_secret_post"]
    )
    code_challenge_methods_supported: List[str] = Field(default=["S256"])
    scopes_supported: List[str] = Field(default=["read", "write"])

    # Service documentation
    service_documentation: Optional[str] = None
