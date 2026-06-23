"""Deterministic secret/PII redaction for automatically captured content.

Hook auto-saves persist whole assistant turns, which can inadvertently contain
credentials or personal data. Every pattern below is masked to ``<REDACTED>``
before the text reaches long-term memory.

The function is **deterministic** (no randomness, no time) so the same input
always yields the same output — safe for dedup hashing and snapshot tests, and
idempotent: ``redact_secrets(redact_secrets(x)) == redact_secrets(x)``.

This lives in ``app.core`` (not in a single route module) so both the HTTP hook
path (``route_modules/hooks.py:_save_memory``) and any other server-side save
path can share one implementation.
"""

import re
from typing import Optional

REDACTED = "<REDACTED>"

# PEM private-key blocks (RSA/EC/OPENSSH/…). DOTALL so the body is consumed.
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

# Standalone high-signal token shapes. Order is specific → general.
_TOKEN_PATTERNS = (
    # JWT: header.payload.signature
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    # Anthropic / OpenAI style secret keys (sk-..., sk-ant-...)
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{10,}"),
    # GitHub PAT / OAuth / refresh / server / user-to-server tokens
    re.compile(r"\bgh[posru]_[A-Za-z0-9]{20,}"),
    # Slack tokens
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    # AWS access key id
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # Google API key
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
)

# Authorization headers / Bearer tokens.
#
# _AUTH_HEADER masks the WHOLE header value (scheme + credential), not just the
# first token. The old ``\S+`` consumed only the scheme word, so
# ``Authorization: Basic dXNlcjpwYXNz`` left the base64 credential exposed
# (same for ApiKey/Digest). Anchored to line start (``^`` + MULTILINE, leading
# whitespace allowed) so it consumes the rest of the header LINE — covering
# multi-token Digest — while NOT swallowing trailing prose when "Authorization:"
# merely appears mid-sentence (which would over-redact and could even drop a
# memory under the length gate). A mid-prose ``Bearer`` is still caught by
# _BEARER; group(1) preserves the indentation/key for readable header blocks.
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_AUTH_HEADER = re.compile(
    r"(?im)^([ \t]*Authorization\s*:\s*)" r"(?:[A-Za-z][A-Za-z0-9+.-]*\s+)?[^\r\n]+"
)

# .env / inline KEY=value where the key name is *exactly* a secret key.
#
# The key is matched against an allowlist anchored on both sides: ``\b`` on the
# left and the ``[:=]`` separator on the right, so the allowlist entry must be
# the WHOLE key — not a substring of a larger compound. This keeps non-secret
# config keys that merely *contain* a secret word intact:
#   max_tokens=4096, token_count=5, REFRESH_TOKEN_TTL=3600, retry_token_count=5
# while still masking the real ones regardless of value shape:
#   api_key=…, password=1234, auth_token=abc, client_secret=xyz, PASSWORD=p@ss
# (A previous version used ``[A-Z0-9_]*…[A-Z0-9_]*`` substring matching, which
# false-positived the config keys above and — because redaction runs before the
# dedup hash — collapsed max_tokens=4096 and max_tokens=8192 to one hash.)
_KV_SECRET = re.compile(
    r"(?i)\b("
    r"api[_-]?key|api[_-]?token|"
    r"access[_-]?key|access[_-]?token|"
    r"secret[_-]?key|client[_-]?secret|private[_-]?key|"
    r"refresh[_-]?token|auth[_-]?token|bearer[_-]?token|session[_-]?token|"
    r"secret|password|passwd|pwd"
    r")(\s*[:=]\s*)\S+"
)

# Email addresses (PII).
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def redact_secrets(text: str) -> str:
    """Mask credentials and PII in ``text``. Returns ``text`` unchanged if falsy.

    Covered: PEM private-key blocks, JWTs, ``sk-``/``sk-ant-`` keys, GitHub /
    Slack tokens, AWS / Google keys, ``Bearer`` + ``Authorization:`` header
    values, ``KEY=value`` secrets, and email addresses.
    """
    if not text:
        return text

    out = _PRIVATE_KEY_BLOCK.sub(REDACTED, text)
    for pattern in _TOKEN_PATTERNS:
        out = pattern.sub(REDACTED, out)
    # Mask the whole Authorization header value first (keep the indentation +
    # "Authorization:" prefix via group 1); then any standalone Bearer token
    # outside a header. A line-start ``Authorization: Bearer …`` is fully
    # consumed here, so _BEARER no longer double-masks it.
    out = _AUTH_HEADER.sub(lambda m: f"{m.group(1)}{REDACTED}", out)
    out = _BEARER.sub(f"Bearer {REDACTED}", out)
    # Keep the key name + original separator, mask only the value, so the
    # redaction stays readable (``KEY=…`` / ``KEY: …`` are both preserved).
    out = _KV_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
    out = _EMAIL.sub(REDACTED, out)
    return out


# Fixed-width mask body so the real secret length is never implied.
_MASK_BODY = "•" * 8  # ••••••••


def mask_secret(value: Optional[str], show: int = 4) -> str:
    """Mask a secret for *display*, revealing only the last ``show`` chars.

    Unlike :func:`redact_secrets` (which scrubs content before storage), this is
    a one-line preview so an operator can *identify* which token is configured
    without leaking it. mem-mesh hook tokens are random with no ``gho_``/
    ``sk_live_`` style key-type prefix, so the leading characters are raw secret
    and are never shown — only a short tail plus a fixed-width body. Returns
    ``""`` for an empty value. Single source of truth for every CLI/web surface
    that prints a masked token.
    """
    if not value:
        return ""
    if len(value) <= show:
        return "•" * len(value)
    return f"{_MASK_BODY}{value[-show:]}"
