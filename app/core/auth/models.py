"""
OAuth data models.

Database models for OAuth clients, tokens, and authorization codes.
"""

from datetime import datetime, timezone
from typing import Optional, List


def _utc_now() -> datetime:
    """Get current UTC time as naive datetime (backwards compatible)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_now_iso() -> str:
    """Get current UTC time as ISO format string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


from uuid import uuid4
from pydantic import BaseModel, Field
import json


class OAuthClient(BaseModel):
    """OAuth 2.1 Client model."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    client_id: str
    client_secret_hash: str  # Hashed secret
    client_name: str
    client_type: str = Field(default="public")  # "public" or "confidential"

    # Redirect URIs (JSON array)
    redirect_uris: str = Field(default="[]")

    # Scopes (JSON array)
    scopes: str = Field(default='["read", "write"]')

    # Grant types (JSON array)
    grant_types: str = Field(default='["authorization_code", "refresh_token"]')

    # Token settings
    access_token_ttl: int = Field(default=3600)  # 1 hour
    refresh_token_ttl: int = Field(default=604800)  # 7 days

    # Status
    is_active: bool = Field(default=True)

    # Timestamps
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)

    def get_redirect_uris(self) -> List[str]:
        """Get redirect URIs as list."""
        try:
            return json.loads(self.redirect_uris)
        except json.JSONDecodeError:
            return []

    def set_redirect_uris(self, uris: List[str]) -> None:
        """Set redirect URIs from list."""
        self.redirect_uris = json.dumps(uris)

    def get_scopes(self) -> List[str]:
        """Get scopes as list."""
        try:
            return json.loads(self.scopes)
        except json.JSONDecodeError:
            return ["read", "write"]

    def set_scopes(self, scopes: List[str]) -> None:
        """Set scopes from list."""
        self.scopes = json.dumps(scopes)

    def get_grant_types(self) -> List[str]:
        """Get grant types as list."""
        try:
            return json.loads(self.grant_types)
        except json.JSONDecodeError:
            return ["authorization_code", "refresh_token"]

    def set_grant_types(self, grant_types: List[str]) -> None:
        """Set grant types from list."""
        self.grant_types = json.dumps(grant_types)


class OAuthToken(BaseModel):
    """OAuth Access/Refresh Token model."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    client_id: str

    # Token values (hashed for access tokens, plain for refresh tokens in DB)
    access_token_hash: str
    refresh_token: Optional[str] = None

    # Token metadata
    token_type: str = Field(default="Bearer")
    scopes: str = Field(default='["read", "write"]')

    # Expiration
    access_token_expires_at: str
    refresh_token_expires_at: Optional[str] = None

    # Status
    is_revoked: bool = Field(default=False)

    # Timestamps
    created_at: str = Field(default_factory=_utc_now_iso)

    def get_scopes(self) -> List[str]:
        """Get scopes as list."""
        try:
            return json.loads(self.scopes)
        except json.JSONDecodeError:
            return ["read", "write"]

    def is_access_token_expired(self) -> bool:
        """Check if access token is expired."""
        expires_at = datetime.fromisoformat(self.access_token_expires_at.rstrip("Z"))
        return _utc_now() > expires_at

    def is_refresh_token_expired(self) -> bool:
        """Check if refresh token is expired."""
        if not self.refresh_token_expires_at:
            return True
        expires_at = datetime.fromisoformat(self.refresh_token_expires_at.rstrip("Z"))
        return _utc_now() > expires_at


class OAuthAuthorizationCode(BaseModel):
    """OAuth Authorization Code model (for PKCE flow)."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    code: str  # The authorization code
    client_id: str

    # PKCE
    code_challenge: str
    code_challenge_method: str = Field(default="S256")

    # Redirect URI used
    redirect_uri: str

    # Scopes requested
    scopes: str = Field(default='["read", "write"]')

    # State parameter (optional)
    state: Optional[str] = None

    # Expiration (short-lived, typically 10 minutes)
    expires_at: str

    # Usage tracking
    is_used: bool = Field(default=False)
    used_at: Optional[str] = None

    # Timestamps
    created_at: str = Field(default_factory=_utc_now_iso)

    def is_expired(self) -> bool:
        """Check if authorization code is expired."""
        expires_at = datetime.fromisoformat(self.expires_at.rstrip("Z"))
        return _utc_now() > expires_at

    def get_scopes(self) -> List[str]:
        """Get scopes as list."""
        try:
            return json.loads(self.scopes)
        except json.JSONDecodeError:
            return ["read", "write"]
