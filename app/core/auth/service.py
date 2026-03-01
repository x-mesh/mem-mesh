"""OAuth Service - Client management, token issuance, and validation."""

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple

from app.core.database.base import Database
from .models import OAuthClient, OAuthToken, OAuthAuthorizationCode, _utc_now_iso
from .schemas import (
    OAuthClientCreate,
    OAuthClientUpdate,
    OAuthClientResponse,
    OAuthClientWithSecretResponse,
    OAuthTokenRequest,
    OAuthTokenResponse,
)
from .utils import (
    generate_client_id,
    generate_client_secret,
    generate_token,
    generate_authorization_code,
    hash_secret,
    verify_secret,
    verify_pkce,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

logger = logging.getLogger(__name__)


class OAuthError(Exception):
    """Base OAuth error."""

    def __init__(self, error: str, description: str = None):
        self.error = error
        self.description = description
        super().__init__(description or error)


class InvalidClientError(OAuthError):
    def __init__(self, description: str = "Invalid client"):
        super().__init__("invalid_client", description)


class InvalidGrantError(OAuthError):
    def __init__(self, description: str = "Invalid grant"):
        super().__init__("invalid_grant", description)


class InvalidTokenError(OAuthError):
    def __init__(self, description: str = "Invalid token"):
        super().__init__("invalid_token", description)


class InvalidRequestError(OAuthError):
    def __init__(self, description: str = "Invalid request"):
        super().__init__("invalid_request", description)


class OAuthService:
    """OAuth 2.1 Authorization Server service."""

    def __init__(self, db: Database):
        self.db = db

    # ========================================================================
    # Client Management
    # ========================================================================

    async def create_client(self, params: OAuthClientCreate) -> Tuple[OAuthClient, str]:
        """Create a new OAuth client. Returns (client, plain_secret)."""
        client_id = generate_client_id()
        plain_secret = generate_client_secret()
        secret_hash = hash_secret(plain_secret)

        client = OAuthClient(
            client_id=client_id,
            client_secret_hash=secret_hash,
            client_name=params.client_name,
            client_type=params.client_type,
            access_token_ttl=params.access_token_ttl,
            refresh_token_ttl=params.refresh_token_ttl,
        )
        client.set_redirect_uris(params.redirect_uris)
        client.set_scopes(params.scopes)
        client.set_grant_types(params.grant_types)

        await self.db.execute(
            """
            INSERT INTO oauth_clients (
                id, client_id, client_secret_hash, client_name, client_type,
                redirect_uris, scopes, grant_types,
                access_token_ttl, refresh_token_ttl, is_active,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client.id,
                client.client_id,
                client.client_secret_hash,
                client.client_name,
                client.client_type,
                client.redirect_uris,
                client.scopes,
                client.grant_types,
                client.access_token_ttl,
                client.refresh_token_ttl,
                client.is_active,
                client.created_at,
                client.updated_at,
            ),
        )

        logger.info(f"Created OAuth client: {client.client_id}")
        return client, plain_secret

    async def get_client(self, client_id: str) -> Optional[OAuthClient]:
        """Get client by client_id."""
        row = await self.db.fetchone(
            "SELECT * FROM oauth_clients WHERE client_id = ? AND is_active = 1",
            (client_id,),
        )
        if not row:
            return None
        return self._row_to_client(row)

    async def get_client_by_id(self, id: str) -> Optional[OAuthClient]:
        """Get client by internal ID."""
        row = await self.db.fetchone(
            "SELECT * FROM oauth_clients WHERE id = ?",
            (id,),
        )
        if not row:
            return None
        return self._row_to_client(row)

    async def list_clients(
        self, include_inactive: bool = False, limit: int = 50, offset: int = 0
    ) -> List[OAuthClient]:
        """List all OAuth clients."""
        query = "SELECT * FROM oauth_clients"
        params = []

        if not include_inactive:
            query += " WHERE is_active = 1"

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = await self.db.fetchall(query, tuple(params))
        return [self._row_to_client(row) for row in rows]

    async def update_client(
        self, client_id: str, params: OAuthClientUpdate
    ) -> Optional[OAuthClient]:
        """Update an OAuth client."""
        client = await self.get_client(client_id)
        if not client:
            return None

        updates = []
        values = []

        if params.client_name is not None:
            updates.append("client_name = ?")
            values.append(params.client_name)

        if params.redirect_uris is not None:
            updates.append("redirect_uris = ?")
            values.append(json.dumps(params.redirect_uris))

        if params.scopes is not None:
            updates.append("scopes = ?")
            values.append(json.dumps(params.scopes))

        if params.is_active is not None:
            updates.append("is_active = ?")
            values.append(params.is_active)

        if params.access_token_ttl is not None:
            updates.append("access_token_ttl = ?")
            values.append(params.access_token_ttl)

        if params.refresh_token_ttl is not None:
            updates.append("refresh_token_ttl = ?")
            values.append(params.refresh_token_ttl)

        if not updates:
            return client

        updates.append("updated_at = ?")
        values.append(_utc_now_iso())
        values.append(client_id)

        await self.db.execute(
            f"UPDATE oauth_clients SET {', '.join(updates)} WHERE client_id = ?",
            tuple(values),
        )

        return await self.get_client(client_id)

    async def delete_client(self, client_id: str) -> bool:
        """Soft delete an OAuth client."""
        cursor = await self.db.execute(
            "UPDATE oauth_clients SET is_active = 0, updated_at = ? WHERE client_id = ?",
            (_utc_now_iso(), client_id),
        )
        return cursor.rowcount > 0

    async def regenerate_client_secret(self, client_id: str) -> Optional[str]:
        """Regenerate client secret. Returns new plain secret."""
        client = await self.get_client(client_id)
        if not client:
            return None

        plain_secret = generate_client_secret()
        secret_hash = hash_secret(plain_secret)

        await self.db.execute(
            "UPDATE oauth_clients SET client_secret_hash = ?, updated_at = ? WHERE client_id = ?",
            (secret_hash, _utc_now_iso(), client_id),
        )

        logger.info(f"Regenerated secret for client: {client_id}")
        return plain_secret

    async def verify_client_credentials(
        self, client_id: str, client_secret: str
    ) -> Optional[OAuthClient]:
        """Verify client credentials."""
        client = await self.get_client(client_id)
        if not client:
            return None

        if not verify_secret(client_secret, client.client_secret_hash):
            return None

        return client

    # ========================================================================
    # Authorization Code
    # ========================================================================

    async def create_authorization_code(
        self,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
        scopes: List[str] = None,
        state: str = None,
    ) -> OAuthAuthorizationCode:
        """Create authorization code for PKCE flow."""
        client = await self.get_client(client_id)
        if not client:
            raise InvalidClientError("Client not found")

        valid_uris = client.get_redirect_uris()
        if valid_uris and redirect_uri not in valid_uris:
            raise InvalidRequestError("Invalid redirect_uri")

        code = generate_authorization_code()
        expires_at = (_utc_now() + timedelta(minutes=10)).isoformat() + "Z"

        auth_code = OAuthAuthorizationCode(
            code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scopes=json.dumps(scopes or ["read", "write"]),
            state=state,
            expires_at=expires_at,
        )

        await self.db.execute(
            """
            INSERT INTO oauth_authorization_codes (
                id, code, client_id, redirect_uri,
                code_challenge, code_challenge_method,
                scopes, state, expires_at, is_used, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                auth_code.id,
                auth_code.code,
                auth_code.client_id,
                auth_code.redirect_uri,
                auth_code.code_challenge,
                auth_code.code_challenge_method,
                auth_code.scopes,
                auth_code.state,
                auth_code.expires_at,
                auth_code.is_used,
                auth_code.created_at,
            ),
        )

        return auth_code

    async def validate_authorization_code(
        self, code: str, client_id: str, redirect_uri: str, code_verifier: str
    ) -> OAuthAuthorizationCode:
        """Validate and consume authorization code."""
        row = await self.db.fetchone(
            "SELECT * FROM oauth_authorization_codes WHERE code = ?",
            (code,),
        )

        if not row:
            raise InvalidGrantError("Authorization code not found")

        auth_code = self._row_to_auth_code(row)

        if auth_code.is_used:
            raise InvalidGrantError("Authorization code already used")

        if auth_code.is_expired():
            raise InvalidGrantError("Authorization code expired")

        if auth_code.client_id != client_id:
            raise InvalidGrantError("Client mismatch")

        if auth_code.redirect_uri != redirect_uri:
            raise InvalidGrantError("Redirect URI mismatch")

        if not verify_pkce(
            code_verifier, auth_code.code_challenge, auth_code.code_challenge_method
        ):
            raise InvalidGrantError("PKCE verification failed")

        await self.db.execute(
            "UPDATE oauth_authorization_codes SET is_used = 1, used_at = ? WHERE code = ?",
            (_utc_now_iso(), code),
        )

        return auth_code

    # ========================================================================
    # Token Management
    # ========================================================================

    async def issue_token(
        self, client: OAuthClient, scopes: List[str]
    ) -> Tuple[str, OAuthToken]:
        """Issue access and refresh tokens. Returns (plain_access_token, token_model)."""
        access_token = generate_token()
        refresh_token = generate_token()

        access_expires = (
            _utc_now() + timedelta(seconds=client.access_token_ttl)
        ).isoformat() + "Z"
        refresh_expires = (
            _utc_now() + timedelta(seconds=client.refresh_token_ttl)
        ).isoformat() + "Z"

        token = OAuthToken(
            client_id=client.client_id,
            access_token_hash=hash_secret(access_token),
            refresh_token=refresh_token,
            scopes=json.dumps(scopes),
            access_token_expires_at=access_expires,
            refresh_token_expires_at=refresh_expires,
        )

        await self.db.execute(
            """
            INSERT INTO oauth_tokens (
                id, client_id, access_token_hash, refresh_token,
                token_type, scopes,
                access_token_expires_at, refresh_token_expires_at,
                is_revoked, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token.id,
                token.client_id,
                token.access_token_hash,
                token.refresh_token,
                token.token_type,
                token.scopes,
                token.access_token_expires_at,
                token.refresh_token_expires_at,
                token.is_revoked,
                token.created_at,
            ),
        )

        return access_token, token

    async def validate_access_token(self, access_token: str) -> Optional[OAuthToken]:
        """Validate access token and return token info."""
        token_hash = hash_secret(access_token)

        row = await self.db.fetchone(
            "SELECT * FROM oauth_tokens WHERE access_token_hash = ? AND is_revoked = 0",
            (token_hash,),
        )

        if not row:
            return None

        token = self._row_to_token(row)

        if token.is_access_token_expired():
            return None

        return token

    async def refresh_access_token(
        self, refresh_token: str, client_id: str
    ) -> Tuple[str, OAuthToken]:
        """Refresh access token using refresh token."""
        row = await self.db.fetchone(
            "SELECT * FROM oauth_tokens WHERE refresh_token = ? AND is_revoked = 0",
            (refresh_token,),
        )

        if not row:
            raise InvalidGrantError("Invalid refresh token")

        token = self._row_to_token(row)

        if token.client_id != client_id:
            raise InvalidGrantError("Client mismatch")

        if token.is_refresh_token_expired():
            raise InvalidGrantError("Refresh token expired")

        await self.db.execute(
            "UPDATE oauth_tokens SET is_revoked = 1 WHERE id = ?",
            (token.id,),
        )

        client = await self.get_client(client_id)
        if not client:
            raise InvalidClientError()

        return await self.issue_token(client, token.get_scopes())

    async def revoke_token(self, token: str, token_type_hint: str = None) -> bool:
        """Revoke a token (access or refresh)."""
        if token_type_hint == "refresh_token" or token_type_hint is None:
            cursor = await self.db.execute(
                "UPDATE oauth_tokens SET is_revoked = 1 WHERE refresh_token = ?",
                (token,),
            )
            if cursor.rowcount > 0:
                return True

        if token_type_hint == "access_token" or token_type_hint is None:
            token_hash = hash_secret(token)
            cursor = await self.db.execute(
                "UPDATE oauth_tokens SET is_revoked = 1 WHERE access_token_hash = ?",
                (token_hash,),
            )
            if cursor.rowcount > 0:
                return True

        return False

    async def revoke_all_client_tokens(self, client_id: str) -> int:
        """Revoke all tokens for a client."""
        cursor = await self.db.execute(
            "UPDATE oauth_tokens SET is_revoked = 1 WHERE client_id = ?",
            (client_id,),
        )
        return cursor.rowcount

    # ========================================================================
    # Token Request Processing
    # ========================================================================

    async def process_token_request(
        self, request: OAuthTokenRequest
    ) -> OAuthTokenResponse:
        """Process token request (authorization_code or refresh_token grant)."""
        if request.grant_type == "authorization_code":
            return await self._handle_authorization_code_grant(request)
        elif request.grant_type == "refresh_token":
            return await self._handle_refresh_token_grant(request)
        else:
            raise InvalidRequestError(f"Unsupported grant_type: {request.grant_type}")

    async def _handle_authorization_code_grant(
        self, request: OAuthTokenRequest
    ) -> OAuthTokenResponse:
        if not all(
            [
                request.code,
                request.redirect_uri,
                request.code_verifier,
                request.client_id,
            ]
        ):
            raise InvalidRequestError("Missing required parameters")

        auth_code = await self.validate_authorization_code(
            request.code,
            request.client_id,
            request.redirect_uri,
            request.code_verifier,
        )

        client = await self.get_client(request.client_id)
        if not client:
            raise InvalidClientError()

        access_token, token = await self.issue_token(client, auth_code.get_scopes())

        return OAuthTokenResponse(
            access_token=access_token,
            token_type="Bearer",
            expires_in=client.access_token_ttl,
            refresh_token=token.refresh_token,
            scope=" ".join(auth_code.get_scopes()),
        )

    async def _handle_refresh_token_grant(
        self, request: OAuthTokenRequest
    ) -> OAuthTokenResponse:
        if not request.refresh_token or not request.client_id:
            raise InvalidRequestError("Missing required parameters")

        access_token, token = await self.refresh_access_token(
            request.refresh_token,
            request.client_id,
        )

        client = await self.get_client(request.client_id)

        return OAuthTokenResponse(
            access_token=access_token,
            token_type="Bearer",
            expires_in=client.access_token_ttl if client else 3600,
            refresh_token=token.refresh_token,
            scope=" ".join(token.get_scopes()),
        )

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _row_to_client(self, row) -> OAuthClient:
        return OAuthClient(
            id=row["id"],
            client_id=row["client_id"],
            client_secret_hash=row["client_secret_hash"],
            client_name=row["client_name"],
            client_type=row["client_type"],
            redirect_uris=row["redirect_uris"],
            scopes=row["scopes"],
            grant_types=row["grant_types"],
            access_token_ttl=row["access_token_ttl"],
            refresh_token_ttl=row["refresh_token_ttl"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_token(self, row) -> OAuthToken:
        return OAuthToken(
            id=row["id"],
            client_id=row["client_id"],
            access_token_hash=row["access_token_hash"],
            refresh_token=row["refresh_token"],
            token_type=row["token_type"],
            scopes=row["scopes"],
            access_token_expires_at=row["access_token_expires_at"],
            refresh_token_expires_at=row["refresh_token_expires_at"],
            is_revoked=bool(row["is_revoked"]),
            created_at=row["created_at"],
        )

    def _row_to_auth_code(self, row) -> OAuthAuthorizationCode:
        return OAuthAuthorizationCode(
            id=row["id"],
            code=row["code"],
            client_id=row["client_id"],
            redirect_uri=row["redirect_uri"],
            code_challenge=row["code_challenge"],
            code_challenge_method=row["code_challenge_method"],
            scopes=row["scopes"],
            state=row["state"],
            expires_at=row["expires_at"],
            is_used=bool(row["is_used"]),
            used_at=row["used_at"],
            created_at=row["created_at"],
        )

    def client_to_response(self, client: OAuthClient) -> OAuthClientResponse:
        return OAuthClientResponse(
            id=client.id,
            client_id=client.client_id,
            client_name=client.client_name,
            client_type=client.client_type,
            redirect_uris=client.get_redirect_uris(),
            scopes=client.get_scopes(),
            grant_types=client.get_grant_types(),
            access_token_ttl=client.access_token_ttl,
            refresh_token_ttl=client.refresh_token_ttl,
            is_active=client.is_active,
            created_at=client.created_at,
            updated_at=client.updated_at,
        )

    def client_to_response_with_secret(
        self, client: OAuthClient, plain_secret: str
    ) -> OAuthClientWithSecretResponse:
        return OAuthClientWithSecretResponse(
            id=client.id,
            client_id=client.client_id,
            client_secret=plain_secret,
            client_name=client.client_name,
            client_type=client.client_type,
            redirect_uris=client.get_redirect_uris(),
            scopes=client.get_scopes(),
            grant_types=client.get_grant_types(),
            access_token_ttl=client.access_token_ttl,
            refresh_token_ttl=client.refresh_token_ttl,
            is_active=client.is_active,
            created_at=client.created_at,
            updated_at=client.updated_at,
        )
