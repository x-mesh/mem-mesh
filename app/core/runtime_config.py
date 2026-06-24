"""Runtime configuration overrides (DB-backed) for a subset of settings.

Precedence per key: **environment variable (``MEM_MESH_<KEY>``) > DB override >
code default**. Env always wins ("env-pinned"): when the env var is set the
value is read-only from the dashboard. Only when the env var is absent may a DB
override (set via the dashboard, like onboarding does for the embedding model)
take effect.

Overrides are cached in-process and read synchronously by the auth middleware on
every request (no DB hit per request), so a dashboard change applies without a
restart. The cache is loaded once at startup (:func:`load_overrides`) and kept
in sync by :func:`set_override` / :func:`clear_override`.

Security: ``admin_password`` is stored as a salted PBKDF2 hash in the DB (never
plaintext); env-provided passwords stay plaintext (legacy compat). Verify via
:func:`check_admin_password`, never by comparing the value from :func:`effective`.

Single-worker only: ``_overrides`` is a per-process cache, updated by whichever
worker handles a PUT. With ``MEM_MESH_SERVER_WORKERS > 1`` other workers keep
stale values until restart, so dashboard auth changes would be incoherent — the
deployment pins ``workers=1`` (docker-compose) and the write API warns otherwise.
"""

import base64
import hashlib
import os
import secrets
from typing import Tuple

from app.core.auth.utils import verify_secret
from app.core.config import get_settings

_PBKDF2_ITER = 100_000


def _hash_password(plain: str) -> str:
    """Salted PBKDF2-SHA256 hash for human-chosen admin passwords."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, _PBKDF2_ITER)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITER,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def _verify_password(plain: str, stored: str) -> bool:
    """Verify against a PBKDF2 hash, falling back to legacy unsalted sha256."""
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iter_s, salt_b64, dk_b64 = stored.split("$")
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(dk_b64)
            dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, int(iter_s))
        except Exception:
            return False
        return secrets.compare_digest(dk, expected)
    # Legacy unsalted sha256 — verified for back-compat, never newly written.
    return verify_secret(plain, stored)


# Managed keys -> kind. 'tribool' allows None (inherit from auth_enabled);
# 'secret' is hashed when stored in the DB.
MANAGED_AUTH_KEYS = {
    "auth_enabled": "bool",
    "mcp_auth_enabled": "tribool",
    "web_auth_enabled": "tribool",
    "web_basic_auth_enabled": "bool",
    "admin_username": "str",
    "admin_password": "secret",
}

# Non-auth runtime settings (display/formatting, public URL), kept separate from
# the auth keys above so changes to one never touch the other. 'str' kind =
# stored and returned verbatim.
MANAGED_DISPLAY_KEYS = {
    "display_timezone": "str",
    "public_url": "str",
}

# Hook-tuning runtime settings. 'int' kind = parsed back to int by
# effective_int(); stored verbatim like 'str'. Kept separate so a hook-config
# change never touches auth or display keys.
MANAGED_HOOK_KEYS = {
    "hook_min_message_length": "int",
}

# All runtime-managed keys (auth + display + hook), public so callers can
# validate "is this a known managed key?" (e.g. the security route).
# effective()/_to_stored() resolve a key's kind from this merged view.
MANAGED_KEYS = {**MANAGED_AUTH_KEYS, **MANAGED_DISPLAY_KEYS, **MANAGED_HOOK_KEYS}

# Keys that may be set from the dashboard AND honored from the DB. Single source
# of truth shared with the security route's WRITABLE_KEYS, and the ONLY keys
# load_overrides() reads — a stray ``config.<other>`` row is therefore never
# honored. The OAuth toggles are included: enabling OAuth would otherwise lock
# the browser out of /api, but the security route guards that case (it refuses
# to enable OAuth unless Basic Auth is/stays on, so the dashboard keeps /api via
# its session — dual-auth). ``display_timezone`` cannot weaken security.
DB_OVERRIDABLE_KEYS = {
    "web_basic_auth_enabled",
    "admin_username",
    "admin_password",
    "display_timezone",
    "public_url",
    "auth_enabled",
    "mcp_auth_enabled",
    "web_auth_enabled",
    "hook_min_message_length",
}

_ENV_PREFIX = "MEM_MESH_"

# In-process cache of DB overrides: key -> stored string value.
_overrides: dict = {}


def env_var_name(key: str) -> str:
    return f"{_ENV_PREFIX}{key.upper()}"


def is_env_pinned(key: str) -> bool:
    """True when ``MEM_MESH_<KEY>`` is present in the environment.

    ``.env`` is loaded into ``os.environ`` at startup, so this covers both the
    real environment and the ``.env`` file. An env-pinned key is read-only from
    the dashboard.
    """
    return os.environ.get(env_var_name(key)) is not None


async def load_overrides(db) -> None:
    """Populate the in-process cache from the DB (called once at startup).

    Only ``DB_OVERRIDABLE_KEYS`` are read, so a stray ``config.auth_enabled`` row
    can never be honored — the read path shares the write allowlist.
    """
    _overrides.clear()
    for key in DB_OVERRIDABLE_KEYS:
        try:
            val = await db.get_app_config(key)
        except Exception:
            val = None
        if val is not None:
            _overrides[key] = val


async def set_override(db, key: str, value) -> None:
    """Persist a DB override and refresh the cache. Secrets are hashed.

    Raises ``PermissionError`` if the key is env-pinned (env wins; the override
    would be inert and misleading), ``ValueError`` for a key that is not
    runtime-overridable.
    """
    if key not in DB_OVERRIDABLE_KEYS:
        raise ValueError(f"key not overridable at runtime: {key}")
    if is_env_pinned(key):
        raise PermissionError(f"{env_var_name(key)} is set; this key is env-pinned")
    stored = _to_stored(key, value)
    await db.set_app_config(key, stored)
    _overrides[key] = stored


async def clear_override(db, key: str) -> None:
    """Remove a DB override (revert to env/default)."""
    if key not in DB_OVERRIDABLE_KEYS:
        raise ValueError(f"key not overridable at runtime: {key}")
    await db.delete_app_config(key)
    _overrides.pop(key, None)


def _to_stored(key: str, value) -> str:
    kind = MANAGED_KEYS[key]
    if kind == "secret":
        return _hash_password(str(value))
    if kind in ("bool", "tribool"):
        return "true" if _as_bool(value) else "false"
    return str(value)


def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _settings_value(key):
    return getattr(get_settings(), key, None)


def effective(key: str) -> Tuple[object, str]:
    """Return ``(value, source)`` for a managed key.

    ``source`` is ``"env"`` | ``"db"`` | ``"default"``. For ``secret`` keys the
    value is the raw stored form (plaintext from env, a hash from the DB) — use
    :func:`check_admin_password` for verification, never a direct compare.
    """
    if key not in MANAGED_KEYS:
        raise ValueError(f"unknown managed key: {key}")
    kind = MANAGED_KEYS[key]
    if is_env_pinned(key):
        return _settings_value(key), "env"
    if key in _overrides:
        raw = _overrides[key]
        if kind in ("bool", "tribool"):
            return _as_bool(raw), "db"
        return raw, "db"
    return _settings_value(key), "default"


def effective_bool(key: str) -> bool:
    """Effective value of a plain boolean key."""
    val, _ = effective(key)
    return bool(val)


def effective_str(key: str) -> str:
    """Effective value of a plain string key (e.g. ``display_timezone``)."""
    val, _ = effective(key)
    return "" if val is None else str(val)


def effective_int(key: str) -> int:
    """Effective value of an 'int' key (e.g. ``hook_min_message_length``).

    DB overrides are stored as strings; parse back to int, falling back to the
    code default if a stored value is somehow non-numeric.
    """
    val, _ = effective(key)
    try:
        return int(val)
    except (TypeError, ValueError):
        return int(_settings_value(key) or 0)


def effective_tribool(key: str) -> bool:
    """Effective value of a tri-state auth flag, inheriting ``auth_enabled`` when
    this key is not explicitly set.

    "Explicitly set" means an env var for *this* key, or a DB override for it.
    We must not read ``settings.<key>`` for the unset case: pydantic's
    ``apply_auth_inheritance`` already folds it to a concrete bool against the
    *env* auth_enabled, which would ignore a DB override of auth_enabled.
    """
    if is_env_pinned(key):
        v = _settings_value(key)
        return effective_bool("auth_enabled") if v is None else bool(v)
    if key in _overrides:
        return _as_bool(_overrides[key])
    return effective_bool("auth_enabled")


def source_of(key: str) -> str:
    """The active source for a key: ``"env"`` | ``"db"`` | ``"default"``."""
    return effective(key)[1]


def check_admin_password(plain: str) -> bool:
    """Verify a password against the active source (env plaintext or DB hash)."""
    val, source = effective("admin_password")
    if not val:
        return False
    if source == "db":
        return _verify_password(str(plain), str(val))
    return secrets.compare_digest(str(plain), str(val))


def admin_password_set() -> bool:
    """Whether any admin password is configured (env or DB), without exposing it."""
    val, _ = effective("admin_password")
    return bool(val)
