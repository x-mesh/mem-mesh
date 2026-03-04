"""
OAuth 2.1 Authentication Module.

MCP 2025-03-26 스펙 준수 OAuth Provider 구현.
- OAuth 2.1 + PKCE
- Dynamic Client Registration
- Bearer Token Authentication
"""

from .models import OAuthAuthorizationCode, OAuthClient, OAuthToken
from .schemas import (
    OAuthAuthorizeRequest,
    OAuthClientCreate,
    OAuthClientRegistrationRequest,
    OAuthClientRegistrationResponse,
    OAuthClientResponse,
    OAuthMetadata,
    OAuthTokenRequest,
    OAuthTokenResponse,
)
from .service import OAuthService
from .utils import (
    generate_authorization_code,
    generate_client_id,
    generate_client_secret,
    generate_token,
    hash_secret,
    verify_pkce,
    verify_secret,
)

__all__ = [
    # Models
    "OAuthClient",
    "OAuthToken",
    "OAuthAuthorizationCode",
    # Schemas
    "OAuthClientCreate",
    "OAuthClientResponse",
    "OAuthTokenRequest",
    "OAuthTokenResponse",
    "OAuthAuthorizeRequest",
    "OAuthMetadata",
    "OAuthClientRegistrationRequest",
    "OAuthClientRegistrationResponse",
    # Service
    "OAuthService",
    # Utils
    "generate_client_id",
    "generate_client_secret",
    "generate_token",
    "generate_authorization_code",
    "verify_pkce",
    "hash_secret",
    "verify_secret",
]
