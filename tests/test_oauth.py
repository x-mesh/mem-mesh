"""
OAuth 2.1 + PKCE Tests

Comprehensive tests for OAuth service, endpoints, and PKCE flow.
"""

import pytest
import tempfile
import os
from datetime import datetime, timedelta, timezone


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.core.database.base import Database
from app.core.config import Settings
from app.core.auth import OAuthService
from app.core.auth.models import OAuthClient, OAuthToken, OAuthAuthorizationCode
from app.core.auth.schemas import OAuthClientCreate, OAuthClientUpdate
from app.core.auth.utils import (
    generate_client_id,
    generate_client_secret,
    generate_token,
    generate_authorization_code,
    hash_secret,
    verify_secret,
    generate_code_verifier,
    generate_code_challenge,
    verify_pkce,
    parse_bearer_token,
    generate_state,
)
from app.core.auth.service import (
    OAuthError,
    InvalidClientError,
    InvalidGrantError,
    InvalidTokenError,
    InvalidRequestError,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def test_settings(temp_db, monkeypatch):
    """Test settings with temporary database."""
    monkeypatch.setenv("MEM_MESH_DATABASE_PATH", temp_db)
    return Settings()


@pytest.fixture
async def db(test_settings):
    """Initialize and yield a test database."""
    database = Database(test_settings.database_path)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def oauth_service(db):
    """Initialize OAuth service."""
    return OAuthService(db)


@pytest.fixture
def pkce_pair():
    """Generate a PKCE code verifier and challenge pair."""
    verifier = generate_code_verifier()
    challenge = generate_code_challenge(verifier, "S256")
    return {"verifier": verifier, "challenge": challenge}


# =============================================================================
# Utils Tests
# =============================================================================


class TestOAuthUtils:
    """Tests for OAuth utility functions."""

    def test_generate_client_id(self):
        """Test client ID generation."""
        client_id = generate_client_id()
        assert client_id.startswith("mem_")
        assert len(client_id) == 36  # "mem_" + 32 hex chars

    def test_generate_client_id_custom_prefix(self):
        """Test client ID generation with custom prefix."""
        client_id = generate_client_id(prefix="test_")
        assert client_id.startswith("test_")

    def test_generate_client_secret(self):
        """Test client secret generation."""
        secret = generate_client_secret()
        assert len(secret) == 64  # Base64 URL-safe

    def test_generate_token(self):
        """Test token generation."""
        token = generate_token()
        assert len(token) == 64

    def test_generate_authorization_code(self):
        """Test authorization code generation."""
        code = generate_authorization_code()
        assert len(code) == 32

    def test_hash_secret(self):
        """Test secret hashing."""
        secret = "test_secret"
        hashed = hash_secret(secret)
        assert hashed != secret
        assert len(hashed) == 64  # SHA-256 hex

    def test_verify_secret_correct(self):
        """Test secret verification with correct secret."""
        secret = "test_secret"
        hashed = hash_secret(secret)
        assert verify_secret(secret, hashed) is True

    def test_verify_secret_wrong(self):
        """Test secret verification with wrong secret."""
        secret = "test_secret"
        hashed = hash_secret(secret)
        assert verify_secret("wrong_secret", hashed) is False

    def test_generate_code_verifier(self):
        """Test PKCE code verifier generation."""
        verifier = generate_code_verifier()
        assert 43 <= len(verifier) <= 128

    def test_generate_code_challenge_s256(self):
        """Test PKCE code challenge generation with S256."""
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        challenge = generate_code_challenge(verifier, "S256")
        assert challenge is not None
        assert challenge != verifier

    def test_generate_code_challenge_plain(self):
        """Test PKCE code challenge generation with plain method."""
        verifier = "test_verifier"
        challenge = generate_code_challenge(verifier, "plain")
        assert challenge == verifier

    def test_generate_code_challenge_unsupported(self):
        """Test PKCE code challenge with unsupported method."""
        with pytest.raises(ValueError, match="Unsupported code challenge method"):
            generate_code_challenge("verifier", "unsupported")

    def test_verify_pkce_s256(self):
        """Test PKCE verification with S256."""
        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier, "S256")
        assert verify_pkce(verifier, challenge, "S256") is True

    def test_verify_pkce_wrong_verifier(self):
        """Test PKCE verification with wrong verifier."""
        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier, "S256")
        assert verify_pkce("wrong_verifier", challenge, "S256") is False

    def test_parse_bearer_token_valid(self):
        """Test Bearer token parsing with valid header."""
        token = parse_bearer_token("Bearer abc123")
        assert token == "abc123"

    def test_parse_bearer_token_none(self):
        """Test Bearer token parsing with None."""
        assert parse_bearer_token(None) is None

    def test_parse_bearer_token_invalid_scheme(self):
        """Test Bearer token parsing with invalid scheme."""
        assert parse_bearer_token("Basic abc123") is None

    def test_parse_bearer_token_malformed(self):
        """Test Bearer token parsing with malformed header."""
        assert parse_bearer_token("Bearer") is None
        assert parse_bearer_token("Bearer a b c") is None

    def test_generate_state(self):
        """Test state parameter generation."""
        state = generate_state()
        assert len(state) >= 32


# =============================================================================
# Model Tests
# =============================================================================


class TestOAuthModels:
    """Tests for OAuth data models."""

    def test_oauth_client_creation(self):
        """Test OAuthClient model creation."""
        client = OAuthClient(
            client_id="test_client_id",
            client_secret_hash="hashed_secret",
            client_name="Test Client",
        )
        assert client.client_id == "test_client_id"
        assert client.client_name == "Test Client"
        assert client.is_active is True
        assert client.id is not None

    def test_oauth_client_redirect_uris(self):
        """Test OAuthClient redirect URIs handling."""
        client = OAuthClient(
            client_id="test",
            client_secret_hash="hash",
            client_name="Test",
        )
        uris = ["http://localhost/callback", "http://example.com/callback"]
        client.set_redirect_uris(uris)
        assert client.get_redirect_uris() == uris

    def test_oauth_client_scopes(self):
        """Test OAuthClient scopes handling."""
        client = OAuthClient(
            client_id="test",
            client_secret_hash="hash",
            client_name="Test",
        )
        scopes = ["read", "write"]
        client.set_scopes(scopes)
        assert client.get_scopes() == scopes

    def test_oauth_token_expiry(self):
        """Test OAuthToken expiry checks."""
        # Expired token
        expired_token = OAuthToken(
            client_id="test",
            access_token_hash="hash",
            refresh_token="refresh",
            access_token_expires_at=(_utc_now() - timedelta(hours=1)).isoformat() + "Z",
            refresh_token_expires_at=(_utc_now() + timedelta(days=7)).isoformat() + "Z",
        )
        assert expired_token.is_access_token_expired() is True
        assert expired_token.is_refresh_token_expired() is False

        # Valid token
        valid_token = OAuthToken(
            client_id="test",
            access_token_hash="hash",
            refresh_token="refresh",
            access_token_expires_at=(_utc_now() + timedelta(hours=1)).isoformat() + "Z",
            refresh_token_expires_at=(_utc_now() + timedelta(days=7)).isoformat() + "Z",
        )
        assert valid_token.is_access_token_expired() is False
        assert valid_token.is_refresh_token_expired() is False

    def test_oauth_authorization_code_expiry(self):
        """Test OAuthAuthorizationCode expiry."""
        expired_code = OAuthAuthorizationCode(
            code="test_code",
            client_id="test",
            redirect_uri="http://localhost/callback",
            code_challenge="challenge",
            expires_at=(_utc_now() - timedelta(minutes=1)).isoformat() + "Z",
        )
        assert expired_code.is_expired() is True

        valid_code = OAuthAuthorizationCode(
            code="test_code",
            client_id="test",
            redirect_uri="http://localhost/callback",
            code_challenge="challenge",
            expires_at=(_utc_now() + timedelta(minutes=5)).isoformat() + "Z",
        )
        assert valid_code.is_expired() is False


# =============================================================================
# Service Tests
# =============================================================================


class TestOAuthService:
    """Tests for OAuth service."""

    @pytest.mark.asyncio
    async def test_create_client(self, oauth_service):
        """Test client creation."""
        params = OAuthClientCreate(
            client_name="Test Client",
            redirect_uris=["http://localhost:8080/callback"],
            scopes=["read", "write"],
        )

        client, secret = await oauth_service.create_client(params)

        assert client.client_name == "Test Client"
        assert client.client_id.startswith("mem_")
        assert client.is_active is True
        assert secret is not None
        assert len(secret) == 64

    @pytest.mark.asyncio
    async def test_get_client(self, oauth_service):
        """Test getting a client by client_id."""
        params = OAuthClientCreate(client_name="Test Client")
        created, _ = await oauth_service.create_client(params)

        fetched = await oauth_service.get_client(created.client_id)
        assert fetched is not None
        assert fetched.client_id == created.client_id
        assert fetched.client_name == "Test Client"

    @pytest.mark.asyncio
    async def test_get_client_not_found(self, oauth_service):
        """Test getting a non-existent client."""
        client = await oauth_service.get_client("non_existent")
        assert client is None

    @pytest.mark.asyncio
    async def test_list_clients(self, oauth_service):
        """Test listing clients."""
        # Create multiple clients
        for i in range(3):
            params = OAuthClientCreate(client_name=f"Client {i}")
            await oauth_service.create_client(params)

        clients = await oauth_service.list_clients()
        assert len(clients) >= 3

    @pytest.mark.asyncio
    async def test_update_client(self, oauth_service):
        """Test updating a client."""
        params = OAuthClientCreate(client_name="Original Name")
        client, _ = await oauth_service.create_client(params)

        update_params = OAuthClientUpdate(client_name="Updated Name")
        updated = await oauth_service.update_client(client.client_id, update_params)

        assert updated is not None
        assert updated.client_name == "Updated Name"

    @pytest.mark.asyncio
    async def test_delete_client(self, oauth_service):
        """Test soft deleting a client."""
        params = OAuthClientCreate(client_name="To Delete")
        client, _ = await oauth_service.create_client(params)

        result = await oauth_service.delete_client(client.client_id)
        assert result is True

        # Client should not be found (soft deleted)
        fetched = await oauth_service.get_client(client.client_id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_regenerate_client_secret(self, oauth_service):
        """Test regenerating client secret."""
        params = OAuthClientCreate(client_name="Test Client")
        client, original_secret = await oauth_service.create_client(params)

        new_secret = await oauth_service.regenerate_client_secret(client.client_id)
        assert new_secret is not None
        assert new_secret != original_secret

    @pytest.mark.asyncio
    async def test_verify_client_credentials(self, oauth_service):
        """Test client credential verification."""
        params = OAuthClientCreate(client_name="Test Client")
        client, secret = await oauth_service.create_client(params)

        # Correct credentials
        verified = await oauth_service.verify_client_credentials(
            client.client_id, secret
        )
        assert verified is not None
        assert verified.client_id == client.client_id

        # Wrong credentials
        wrong = await oauth_service.verify_client_credentials(client.client_id, "wrong")
        assert wrong is None

    @pytest.mark.asyncio
    async def test_create_authorization_code(self, oauth_service, pkce_pair):
        """Test authorization code creation."""
        params = OAuthClientCreate(
            client_name="Test Client",
            redirect_uris=["http://localhost:8080/callback"],
        )
        client, _ = await oauth_service.create_client(params)

        auth_code = await oauth_service.create_authorization_code(
            client_id=client.client_id,
            redirect_uri="http://localhost:8080/callback",
            code_challenge=pkce_pair["challenge"],
            code_challenge_method="S256",
            scopes=["read", "write"],
        )

        assert auth_code is not None
        assert auth_code.code is not None
        assert auth_code.client_id == client.client_id

    @pytest.mark.asyncio
    async def test_create_authorization_code_invalid_client(
        self, oauth_service, pkce_pair
    ):
        """Test authorization code creation with invalid client."""
        with pytest.raises(InvalidClientError):
            await oauth_service.create_authorization_code(
                client_id="non_existent",
                redirect_uri="http://localhost/callback",
                code_challenge=pkce_pair["challenge"],
            )

    @pytest.mark.asyncio
    async def test_create_authorization_code_invalid_redirect(
        self, oauth_service, pkce_pair
    ):
        """Test authorization code creation with invalid redirect URI."""
        params = OAuthClientCreate(
            client_name="Test Client",
            redirect_uris=["http://localhost:8080/callback"],
        )
        client, _ = await oauth_service.create_client(params)

        with pytest.raises(InvalidRequestError, match="Invalid redirect_uri"):
            await oauth_service.create_authorization_code(
                client_id=client.client_id,
                redirect_uri="http://evil.com/callback",
                code_challenge=pkce_pair["challenge"],
            )

    @pytest.mark.asyncio
    async def test_validate_authorization_code(self, oauth_service, pkce_pair):
        """Test authorization code validation."""
        params = OAuthClientCreate(
            client_name="Test Client",
            redirect_uris=["http://localhost:8080/callback"],
        )
        client, _ = await oauth_service.create_client(params)

        auth_code = await oauth_service.create_authorization_code(
            client_id=client.client_id,
            redirect_uri="http://localhost:8080/callback",
            code_challenge=pkce_pair["challenge"],
        )

        validated = await oauth_service.validate_authorization_code(
            code=auth_code.code,
            client_id=client.client_id,
            redirect_uri="http://localhost:8080/callback",
            code_verifier=pkce_pair["verifier"],
        )

        assert validated is not None
        assert validated.code == auth_code.code

    @pytest.mark.asyncio
    async def test_validate_authorization_code_already_used(
        self, oauth_service, pkce_pair
    ):
        """Test authorization code validation when already used."""
        params = OAuthClientCreate(
            client_name="Test Client",
            redirect_uris=["http://localhost:8080/callback"],
        )
        client, _ = await oauth_service.create_client(params)

        auth_code = await oauth_service.create_authorization_code(
            client_id=client.client_id,
            redirect_uri="http://localhost:8080/callback",
            code_challenge=pkce_pair["challenge"],
        )

        # First use - should succeed
        await oauth_service.validate_authorization_code(
            code=auth_code.code,
            client_id=client.client_id,
            redirect_uri="http://localhost:8080/callback",
            code_verifier=pkce_pair["verifier"],
        )

        # Second use - should fail
        with pytest.raises(InvalidGrantError, match="already used"):
            await oauth_service.validate_authorization_code(
                code=auth_code.code,
                client_id=client.client_id,
                redirect_uri="http://localhost:8080/callback",
                code_verifier=pkce_pair["verifier"],
            )

    @pytest.mark.asyncio
    async def test_validate_authorization_code_wrong_pkce(
        self, oauth_service, pkce_pair
    ):
        """Test authorization code validation with wrong PKCE verifier."""
        params = OAuthClientCreate(
            client_name="Test Client",
            redirect_uris=["http://localhost:8080/callback"],
        )
        client, _ = await oauth_service.create_client(params)

        auth_code = await oauth_service.create_authorization_code(
            client_id=client.client_id,
            redirect_uri="http://localhost:8080/callback",
            code_challenge=pkce_pair["challenge"],
        )

        with pytest.raises(InvalidGrantError, match="PKCE verification failed"):
            await oauth_service.validate_authorization_code(
                code=auth_code.code,
                client_id=client.client_id,
                redirect_uri="http://localhost:8080/callback",
                code_verifier="wrong_verifier",
            )

    @pytest.mark.asyncio
    async def test_issue_token(self, oauth_service):
        """Test token issuance."""
        params = OAuthClientCreate(client_name="Test Client")
        client, _ = await oauth_service.create_client(params)

        access_token, token_model = await oauth_service.issue_token(
            client, scopes=["read", "write"]
        )

        assert access_token is not None
        assert len(access_token) == 64
        assert token_model.refresh_token is not None
        assert token_model.client_id == client.client_id

    @pytest.mark.asyncio
    async def test_validate_access_token(self, oauth_service):
        """Test access token validation."""
        params = OAuthClientCreate(client_name="Test Client")
        client, _ = await oauth_service.create_client(params)

        access_token, _ = await oauth_service.issue_token(client, scopes=["read"])

        validated = await oauth_service.validate_access_token(access_token)
        assert validated is not None
        assert validated.client_id == client.client_id

    @pytest.mark.asyncio
    async def test_validate_access_token_invalid(self, oauth_service):
        """Test invalid access token validation."""
        validated = await oauth_service.validate_access_token("invalid_token")
        assert validated is None

    @pytest.mark.asyncio
    async def test_refresh_access_token(self, oauth_service):
        """Test token refresh."""
        params = OAuthClientCreate(client_name="Test Client")
        client, _ = await oauth_service.create_client(params)

        _, original_token = await oauth_service.issue_token(client, scopes=["read"])

        new_access_token, new_token = await oauth_service.refresh_access_token(
            original_token.refresh_token, client.client_id
        )

        assert new_access_token is not None
        assert new_token.refresh_token != original_token.refresh_token

    @pytest.mark.asyncio
    async def test_refresh_access_token_invalid(self, oauth_service):
        """Test token refresh with invalid refresh token."""
        with pytest.raises(InvalidGrantError, match="Invalid refresh token"):
            await oauth_service.refresh_access_token("invalid", "client_id")

    @pytest.mark.asyncio
    async def test_revoke_token(self, oauth_service):
        """Test token revocation."""
        params = OAuthClientCreate(client_name="Test Client")
        client, _ = await oauth_service.create_client(params)

        access_token, token = await oauth_service.issue_token(client, scopes=["read"])

        # Revoke access token
        result = await oauth_service.revoke_token(access_token, "access_token")
        assert result is True

        # Token should no longer be valid
        validated = await oauth_service.validate_access_token(access_token)
        assert validated is None

    @pytest.mark.asyncio
    async def test_revoke_all_client_tokens(self, oauth_service):
        """Test revoking all tokens for a client."""
        params = OAuthClientCreate(client_name="Test Client")
        client, _ = await oauth_service.create_client(params)

        # Issue multiple tokens
        access_token1, _ = await oauth_service.issue_token(client, scopes=["read"])
        access_token2, _ = await oauth_service.issue_token(client, scopes=["write"])

        # Revoke all
        count = await oauth_service.revoke_all_client_tokens(client.client_id)
        assert count >= 2

        # Both tokens should be invalid
        assert await oauth_service.validate_access_token(access_token1) is None
        assert await oauth_service.validate_access_token(access_token2) is None


# =============================================================================
# Full PKCE Flow Tests
# =============================================================================


class TestPKCEFlow:
    """Tests for complete PKCE authorization flow."""

    @pytest.mark.asyncio
    async def test_full_pkce_flow(self, oauth_service):
        """Test complete PKCE authorization code flow."""
        # Step 1: Create client
        params = OAuthClientCreate(
            client_name="PKCE Test Client",
            redirect_uris=["http://localhost:8080/callback"],
            scopes=["read", "write"],
        )
        client, client_secret = await oauth_service.create_client(params)

        # Step 2: Generate PKCE pair (client-side)
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier, "S256")

        # Step 3: Create authorization code (authorization endpoint)
        auth_code = await oauth_service.create_authorization_code(
            client_id=client.client_id,
            redirect_uri="http://localhost:8080/callback",
            code_challenge=code_challenge,
            code_challenge_method="S256",
            scopes=["read", "write"],
        )

        # Step 4: Exchange code for tokens (token endpoint)
        from app.core.auth.schemas import OAuthTokenRequest

        token_request = OAuthTokenRequest(
            grant_type="authorization_code",
            code=auth_code.code,
            redirect_uri="http://localhost:8080/callback",
            code_verifier=code_verifier,
            client_id=client.client_id,
        )

        token_response = await oauth_service.process_token_request(token_request)

        assert token_response.access_token is not None
        assert token_response.refresh_token is not None
        assert token_response.token_type == "Bearer"
        assert token_response.expires_in > 0

        # Step 5: Validate access token
        validated = await oauth_service.validate_access_token(
            token_response.access_token
        )
        assert validated is not None

        # Step 6: Refresh token
        refresh_request = OAuthTokenRequest(
            grant_type="refresh_token",
            refresh_token=token_response.refresh_token,
            client_id=client.client_id,
        )

        new_token_response = await oauth_service.process_token_request(refresh_request)
        assert new_token_response.access_token is not None
        assert new_token_response.access_token != token_response.access_token


# =============================================================================
# API Endpoint Tests (optional, requires running app)
# =============================================================================


class TestOAuthEndpoints:
    """Tests for OAuth HTTP endpoints."""

    @pytest.fixture
    def app_client(self, temp_db, monkeypatch):
        """Create test client with OAuth service initialized."""
        monkeypatch.setenv("MEM_MESH_DATABASE_PATH", temp_db)
        monkeypatch.setenv("MEM_MESH_AUTH_ENABLED", "false")  # Disable auth for testing

        from app.web.app import app

        with TestClient(app) as client:
            yield client

    def test_oauth_metadata_endpoint(self, app_client):
        """Test OAuth metadata discovery endpoint."""
        response = app_client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200

        data = response.json()
        assert "issuer" in data
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "registration_endpoint" in data
        assert "code_challenge_methods_supported" in data
        assert "S256" in data["code_challenge_methods_supported"]

    def test_oauth_register_client(self, app_client):
        """Test dynamic client registration endpoint."""
        response = app_client.post(
            "/oauth/register",
            json={
                "client_name": "Test Client",
                "redirect_uris": ["http://localhost:8080/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_method": "client_secret_post",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert "client_id" in data
        assert "client_secret" in data
        assert data["client_name"] == "Test Client"

    def test_oauth_authorize_missing_params(self, app_client):
        """Test authorization endpoint with missing parameters."""
        # Missing required params should redirect with error
        response = app_client.get(
            "/oauth/authorize?response_type=code&client_id=test",
            follow_redirects=False,
        )
        # FastAPI will return 422 for missing required query params
        assert response.status_code == 422

    def test_oauth_token_invalid_grant(self, app_client):
        """Test token endpoint with invalid grant type."""
        response = app_client.post(
            "/oauth/token",
            data={
                "grant_type": "invalid_grant",
                "code": "test",
                "client_id": "test",
            },
        )
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "invalid_request"

    def test_oauth_revoke_token(self, app_client):
        """Test token revocation endpoint."""
        response = app_client.post(
            "/oauth/revoke",
            data={"token": "some_token"},
        )
        # Revocation always returns 200 per RFC 7009
        assert response.status_code == 200

    def test_oauth_introspect_invalid_token(self, app_client):
        """Test token introspection with invalid token."""
        response = app_client.post(
            "/oauth/introspect",
            data={"token": "invalid_token"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["active"] is False


# =============================================================================
# Dashboard API Tests
# =============================================================================


class TestOAuthDashboardAPI:
    """Tests for OAuth client management dashboard API."""

    @pytest.fixture
    def app_client(self, temp_db, monkeypatch):
        """Create test client."""
        monkeypatch.setenv("MEM_MESH_DATABASE_PATH", temp_db)
        monkeypatch.setenv("MEM_MESH_AUTH_ENABLED", "false")

        from app.web.app import app

        with TestClient(app) as client:
            yield client

    def test_list_clients_empty(self, app_client):
        """Test listing clients when none exist."""
        response = app_client.get("/api/oauth/clients")
        assert response.status_code == 200
        data = response.json()
        assert "clients" in data
        assert isinstance(data["clients"], list)

    def test_create_and_list_client(self, app_client):
        """Test creating and listing OAuth clients."""
        # Create client
        create_response = app_client.post(
            "/api/oauth/clients",
            json={
                "client_name": "Dashboard Test Client",
                "redirect_uris": ["http://localhost/callback"],
                "scopes": ["read", "write"],
            },
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert "client_id" in created
        assert "client_secret" in created

        # List clients
        list_response = app_client.get("/api/oauth/clients")
        assert list_response.status_code == 200
        clients = list_response.json()["clients"]
        assert any(c["client_id"] == created["client_id"] for c in clients)

    def test_delete_client(self, app_client):
        """Test deleting an OAuth client."""
        # Create client
        create_response = app_client.post(
            "/api/oauth/clients",
            json={"client_name": "To Delete"},
        )
        client_id = create_response.json()["client_id"]

        # Delete client
        delete_response = app_client.delete(f"/api/oauth/clients/{client_id}")
        assert delete_response.status_code == 200

        # Verify deleted (should not appear in list)
        list_response = app_client.get("/api/oauth/clients")
        clients = list_response.json()["clients"]
        assert not any(c["client_id"] == client_id for c in clients)

    def test_regenerate_client_secret(self, app_client):
        """Test regenerating client secret."""
        # Create client
        create_response = app_client.post(
            "/api/oauth/clients",
            json={"client_name": "Secret Regen Test"},
        )
        client_id = create_response.json()["client_id"]
        original_secret = create_response.json()["client_secret"]

        # Regenerate secret
        regen_response = app_client.post(
            f"/api/oauth/clients/{client_id}/regenerate-secret"
        )
        assert regen_response.status_code == 200
        new_secret = regen_response.json()["client_secret"]
        assert new_secret != original_secret


# ============================================================================
# Middleware Tests
# ============================================================================


class TestBearerTokenMiddleware:
    """Test OAuth middleware authentication logic."""

    def test_requires_auth_disabled_globally(self):
        """When auth_enabled=False, no paths require auth."""
        from app.web.oauth.middleware import BearerTokenMiddleware
        from unittest.mock import MagicMock

        middleware = BearerTokenMiddleware(app=MagicMock())
        settings = MagicMock()
        settings.auth_enabled = False
        settings.mcp_auth_enabled = True
        settings.web_auth_enabled = True

        # Even with mcp/web auth enabled, global disable wins
        assert middleware._requires_auth("/mcp/sse", settings) is False
        assert middleware._requires_auth("/api/memories", settings) is False
        assert middleware._requires_auth("/work", settings) is False

    def test_requires_auth_public_paths_exempt(self):
        """Public paths are always exempt from auth."""
        from app.web.oauth.middleware import BearerTokenMiddleware
        from unittest.mock import MagicMock

        middleware = BearerTokenMiddleware(app=MagicMock())
        settings = MagicMock()
        settings.auth_enabled = True
        settings.mcp_auth_enabled = True
        settings.web_auth_enabled = True

        # Public paths should be exempt
        assert middleware._requires_auth("/health", settings) is False
        assert middleware._requires_auth("/docs", settings) is False
        assert middleware._requires_auth("/static/js/main.js", settings) is False
        assert middleware._requires_auth("/favicon.ico", settings) is False

    def test_requires_auth_oauth_paths_exempt(self):
        """OAuth paths are always exempt from auth."""
        from app.web.oauth.middleware import BearerTokenMiddleware
        from unittest.mock import MagicMock

        middleware = BearerTokenMiddleware(app=MagicMock())
        settings = MagicMock()
        settings.auth_enabled = True
        settings.mcp_auth_enabled = True
        settings.web_auth_enabled = True

        # OAuth paths should be exempt (needed for auth flow)
        assert middleware._requires_auth("/.well-known/oauth-authorization-server", settings) is False
        assert middleware._requires_auth("/oauth/authorize", settings) is False
        assert middleware._requires_auth("/oauth/token", settings) is False
        assert middleware._requires_auth("/oauth/register", settings) is False

    def test_requires_auth_mcp_paths(self):
        """MCP paths follow mcp_auth_enabled setting."""
        from app.web.oauth.middleware import BearerTokenMiddleware
        from unittest.mock import MagicMock

        middleware = BearerTokenMiddleware(app=MagicMock())
        settings = MagicMock()
        settings.auth_enabled = True

        # MCP auth enabled
        settings.mcp_auth_enabled = True
        settings.web_auth_enabled = False
        assert middleware._requires_auth("/mcp/sse", settings) is True
        assert middleware._requires_auth("/mcp/messages", settings) is True

        # MCP auth disabled
        settings.mcp_auth_enabled = False
        assert middleware._requires_auth("/mcp/sse", settings) is False

    def test_requires_auth_api_paths(self):
        """API paths follow web_auth_enabled setting."""
        from app.web.oauth.middleware import BearerTokenMiddleware
        from unittest.mock import MagicMock

        middleware = BearerTokenMiddleware(app=MagicMock())
        settings = MagicMock()
        settings.auth_enabled = True

        # Web auth enabled
        settings.mcp_auth_enabled = False
        settings.web_auth_enabled = True
        assert middleware._requires_auth("/api/memories", settings) is True
        assert middleware._requires_auth("/api/oauth/clients", settings) is True

        # Web auth disabled
        settings.web_auth_enabled = False
        assert middleware._requires_auth("/api/memories", settings) is False

    def test_requires_auth_dashboard_pages(self):
        """Dashboard pages follow web_auth_enabled setting."""
        from app.web.oauth.middleware import BearerTokenMiddleware
        from unittest.mock import MagicMock

        middleware = BearerTokenMiddleware(app=MagicMock())
        settings = MagicMock()
        settings.auth_enabled = True
        settings.mcp_auth_enabled = False

        # Web auth enabled - dashboard pages should require auth
        settings.web_auth_enabled = True
        assert middleware._requires_auth("/", settings) is True
        assert middleware._requires_auth("/work", settings) is True
        assert middleware._requires_auth("/search", settings) is True

        # Web auth disabled - dashboard pages should not require auth
        settings.web_auth_enabled = False
        assert middleware._requires_auth("/", settings) is False
        assert middleware._requires_auth("/work", settings) is False

    def test_requires_auth_combined_settings(self):
        """Test various combinations of auth settings."""
        from app.web.oauth.middleware import BearerTokenMiddleware
        from unittest.mock import MagicMock

        middleware = BearerTokenMiddleware(app=MagicMock())
        settings = MagicMock()

        # Scenario 1: Only MCP auth enabled
        settings.auth_enabled = True
        settings.mcp_auth_enabled = True
        settings.web_auth_enabled = False
        assert middleware._requires_auth("/mcp/sse", settings) is True
        assert middleware._requires_auth("/api/memories", settings) is False
        assert middleware._requires_auth("/work", settings) is False

        # Scenario 2: Only Web auth enabled
        settings.mcp_auth_enabled = False
        settings.web_auth_enabled = True
        assert middleware._requires_auth("/mcp/sse", settings) is False
        assert middleware._requires_auth("/api/memories", settings) is True
        assert middleware._requires_auth("/work", settings) is True

        # Scenario 3: Both enabled
        settings.mcp_auth_enabled = True
        settings.web_auth_enabled = True
        assert middleware._requires_auth("/mcp/sse", settings) is True
        assert middleware._requires_auth("/api/memories", settings) is True
        assert middleware._requires_auth("/work", settings) is True


# ============================================================================
# Basic Auth Tests
# ============================================================================


class TestBasicAuth:
    """Test Basic Auth for web dashboard."""

    def test_verify_credentials_valid(self):
        """Test valid credentials verification."""
        from app.web.oauth.basic_auth import verify_credentials
        from unittest.mock import patch, MagicMock

        mock_settings = MagicMock()
        mock_settings.admin_username = "admin"
        mock_settings.admin_password = "secret123"

        with patch("app.web.oauth.basic_auth.get_settings", return_value=mock_settings):
            assert verify_credentials("admin", "secret123") is True
            assert verify_credentials("admin", "wrong") is False
            assert verify_credentials("wrong", "secret123") is False

    def test_verify_credentials_no_password_set(self):
        """Test credentials verification when no password is set."""
        from app.web.oauth.basic_auth import verify_credentials
        from unittest.mock import patch, MagicMock

        mock_settings = MagicMock()
        mock_settings.admin_username = "admin"
        mock_settings.admin_password = ""  # Empty password

        with patch("app.web.oauth.basic_auth.get_settings", return_value=mock_settings):
            assert verify_credentials("admin", "") is False

    @pytest.mark.asyncio
    async def test_session_lifecycle(self):
        """Test session creation, validation, and deletion."""
        from app.web.oauth.basic_auth import (
            create_session,
            validate_session,
            delete_session,
        )

        # Create session
        session_id = await create_session("testuser")
        assert session_id is not None
        assert len(session_id) > 20

        # Validate session
        session = await validate_session(session_id)
        assert session is not None
        assert session["username"] == "testuser"

        # Delete session
        await delete_session(session_id)
        assert await validate_session(session_id) is None

    @pytest.mark.asyncio
    async def test_validate_invalid_session(self):
        """Test validation of invalid session."""
        from app.web.oauth.basic_auth import validate_session

        assert await validate_session(None) is None
        assert await validate_session("") is None
        assert await validate_session("invalid-session-id") is None

    def test_basic_auth_middleware_disabled(self):
        """Test middleware when basic auth is disabled."""
        from app.web.oauth.basic_auth import BasicAuthMiddleware
        from unittest.mock import MagicMock

        middleware = BasicAuthMiddleware(app=MagicMock())

        # Public paths should always be exempt
        assert middleware._is_public_path("/health") is True
        assert middleware._is_public_path("/static/js/main.js") is True
        assert middleware._is_public_path("/login") is True
        assert middleware._is_public_path("/logout") is True

        # OAuth/MCP paths should be exempt
        assert middleware._is_oauth_path("/mcp/sse") is True
        assert middleware._is_oauth_path("/oauth/token") is True
        assert middleware._is_oauth_path("/.well-known/oauth-authorization-server") is True

        # Dashboard paths should not be exempt
        assert middleware._is_public_path("/") is False
        assert middleware._is_public_path("/work") is False
        assert middleware._is_oauth_path("/api/memories") is False
