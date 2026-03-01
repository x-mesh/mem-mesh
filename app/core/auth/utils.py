"""
OAuth utility functions.

PKCE, 시크릿 생성, 해싱 등 유틸리티 함수.
"""

import base64
import hashlib
import secrets
from typing import Optional


def generate_client_id(prefix: str = "mem_") -> str:
    """Generate a unique client ID.

    Args:
        prefix: Prefix for the client ID

    Returns:
        Unique client ID (e.g., "mem_abc123def456")
    """
    return f"{prefix}{secrets.token_hex(16)}"


def generate_client_secret() -> str:
    """Generate a secure client secret.

    Returns:
        Secure random string (64 characters)
    """
    return secrets.token_urlsafe(48)


def generate_token() -> str:
    """Generate a secure access/refresh token.

    Returns:
        Secure random token (64 characters)
    """
    return secrets.token_urlsafe(48)


def generate_authorization_code() -> str:
    """Generate a secure authorization code.

    Returns:
        Secure random authorization code (32 characters)
    """
    return secrets.token_urlsafe(24)


def hash_secret(secret: str) -> str:
    """Hash a client secret using SHA-256.

    Args:
        secret: Plain text secret

    Returns:
        Hashed secret (hex string)
    """
    return hashlib.sha256(secret.encode()).hexdigest()


def verify_secret(plain_secret: str, hashed_secret: str) -> bool:
    """Verify a plain secret against its hash.

    Args:
        plain_secret: Plain text secret to verify
        hashed_secret: Stored hash to compare against

    Returns:
        True if secrets match
    """
    return secrets.compare_digest(hash_secret(plain_secret), hashed_secret)


def generate_code_verifier() -> str:
    """Generate a PKCE code verifier.

    Returns:
        Random string between 43-128 characters (URL-safe)
    """
    return secrets.token_urlsafe(64)


def generate_code_challenge(code_verifier: str, method: str = "S256") -> str:
    """Generate a PKCE code challenge from verifier.

    Args:
        code_verifier: The code verifier string
        method: Challenge method ("S256" or "plain")

    Returns:
        Code challenge string

    Raises:
        ValueError: If method is not supported
    """
    if method == "plain":
        return code_verifier
    elif method == "S256":
        digest = hashlib.sha256(code_verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    else:
        raise ValueError(f"Unsupported code challenge method: {method}")


def verify_pkce(
    code_verifier: str, code_challenge: str, code_challenge_method: str = "S256"
) -> bool:
    """Verify PKCE code verifier against challenge.

    Args:
        code_verifier: The code verifier from token request
        code_challenge: The stored code challenge
        code_challenge_method: The challenge method used

    Returns:
        True if verification succeeds
    """
    try:
        expected_challenge = generate_code_challenge(
            code_verifier, code_challenge_method
        )
        return secrets.compare_digest(expected_challenge, code_challenge)
    except Exception:
        return False


def parse_bearer_token(authorization_header: Optional[str]) -> Optional[str]:
    """Parse Bearer token from Authorization header.

    Args:
        authorization_header: The Authorization header value

    Returns:
        The token string if valid Bearer token, None otherwise
    """
    if not authorization_header:
        return None

    parts = authorization_header.split()
    if len(parts) != 2:
        return None

    scheme, token = parts
    if scheme.lower() != "bearer":
        return None

    return token


def generate_state() -> str:
    """Generate a secure state parameter for OAuth flow.

    Returns:
        Secure random state string
    """
    return secrets.token_urlsafe(32)
