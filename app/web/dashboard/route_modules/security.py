"""Dashboard Security / Token Management API.

Surfaces the three independent auth mechanisms in one place:

* **Hook token** — shared secret for ``POST /api/hooks/claude/*``. Auto-generated
  at startup (see :func:`app.core.config.bootstrap_hook_token`); this module
  exposes its masked value, can reveal/rotate it, and reports whether an
  env-pinned ``MEM_MESH_HOOK_TOKEN`` overrides rotation.
* **Web dashboard auth** — Basic Auth (admin user/pass) and/or OAuth web auth;
  read-only status here (toggling lives in env/.env, not runtime).
* **MCP OAuth** — clients are managed by the existing ``/api/oauth/clients`` API;
  the dashboard page reuses that, this module only reports whether MCP auth is on.

Secret-exposure policy (``_can_reveal``): the plaintext hook token is returned
only when an authenticated surface is enforced (Basic Auth on, or OAuth web auth
on — the middleware guarantees the caller is authenticated by the time the
handler runs) OR the request originates from loopback (local dev / SSH tunnel).
Otherwise only a masked value is returned, so a 0.0.0.0-exposed, unauthenticated
server never leaks the token over the network. Admin passwords are never
returned — only whether one is set.
"""

import logging

from fastapi import APIRouter, Body, HTTPException, Request, Response

from app.core import runtime_config as rc
from app.core.config import (
    get_effective_bind_host,
    get_settings,
    hook_token_source,
    resolve_hook_token,
    rotate_hook_token,
)
from app.web.oauth.middleware import is_loopback_host

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/security", tags=["Security"])

# Hook endpoint events that accept native HTTP hooks (mirrors
# app.cli.install_hooks._HTTP_HOOK_ENDPOINTS); used to render install snippets.
_HOOK_ENDPOINT = "/api/hooks/claude/{event}"


def _mask(token: str) -> str:
    """Mask a secret for display. Delegates to the single core masker (tail-only)."""
    from app.core.redaction import mask_secret

    return mask_secret(token)


def _web_auth_enforced() -> bool:
    """True only when OAuth web auth actually gated this API request.

    Basic Auth is intentionally NOT counted: it protects dashboard *pages* only
    and EXEMPTS /api/* (so API/MCP/hook clients with no session aren't locked
    out). A Basic-Auth session is therefore not proof that an /api caller
    authenticated — counting it would let a remote, sessionless caller reveal
    the token / change auth whenever Basic Auth is on. Only a validated OAuth
    bearer (BearerTokenMiddleware) counts; otherwise _can_reveal falls back to
    loopback.
    """
    if rc.effective_bool("auth_enabled"):
        return rc.effective_tribool("web_auth_enabled")
    return False


def _can_reveal(request: Request) -> bool:
    """Whether the plaintext token / auth change is allowed for this request.

    Allowed for: a validated OAuth web-auth bearer; a logged-in dashboard
    session (Basic Auth — the operator authenticated and reaches /api via
    dual-auth, so revealing to them is safe and expected, e.g. recovering the
    token); or a loopback request. Otherwise masked only.
    """
    if _web_auth_enforced():
        return True
    if getattr(request.state, "dashboard_session", None):
        return True
    client = request.client.host if request.client else None
    return is_loopback_host(client)


def _hook_status(request: Request) -> dict:
    token = resolve_hook_token()
    source = hook_token_source()
    reveal = _can_reveal(request)
    return {
        "configured": token is not None,
        "source": source,
        "env_pinned": source == "env",
        "masked": _mask(token) if token else "",
        "can_reveal": reveal,
        "endpoint": _HOOK_ENDPOINT,
    }


@router.get("/overview")
async def security_overview(request: Request, response: Response):
    """Combined status of hook token, web dashboard auth, and MCP auth."""
    response.headers["Cache-Control"] = "no-store"
    effective_host = get_effective_bind_host()
    return {
        "hook": _hook_status(request),
        "web_dashboard_auth": {
            "basic_auth_enabled": rc.effective_bool("web_basic_auth_enabled"),
            "admin_username": rc.effective("admin_username")[0],
            "admin_password_set": rc.admin_password_set(),
            "oauth_web_auth_enabled": _web_auth_enforced()
            and not rc.effective_bool("web_basic_auth_enabled"),
        },
        "mcp_auth": {
            "oauth_auth_enabled": rc.effective_bool("auth_enabled"),
            "mcp_auth_enabled": rc.effective_tribool("mcp_auth_enabled"),
        },
        "bind": {
            "effective_host": effective_host,
            "is_loopback": is_loopback_host(effective_host),
        },
    }


@router.get("/hook/reveal")
async def reveal_hook_token(request: Request, response: Response):
    """Return the plaintext hook token, subject to the reveal policy."""
    if not _can_reveal(request):
        raise HTTPException(
            status_code=403,
            detail=(
                "Revealing the hook token requires an authenticated dashboard "
                "(enable Basic Auth or OAuth web auth) or a local request. "
                "Under Docker the published port is NAT'd so requests appear "
                "non-local; use the server's MEM_MESH_HOOK_TOKEN value when set, "
                "or read the server-generated fallback from the data volume "
                "(`cat ./data/hook_token` or `docker compose exec mem-mesh "
                "cat /app/data/hook_token`), or enable Basic Auth."
            ),
        )
    token = resolve_hook_token()
    if not token:
        raise HTTPException(status_code=404, detail="No hook token configured")
    response.headers["Cache-Control"] = "no-store"
    return {"token": token, "source": hook_token_source()}


@router.post("/hook/regenerate")
async def regenerate_hook_token(request: Request, response: Response):
    """Rotate the hook token (writes a new value to ``<data dir>/hook_token``).

    No-op-warning when an env-pinned ``MEM_MESH_HOOK_TOKEN`` is set, because
    :func:`resolve_hook_token` would keep returning the env value. All existing
    hook clients must be reinstalled with the new token afterwards.
    """
    if hook_token_source() == "env":
        raise HTTPException(
            status_code=409,
            detail=(
                "MEM_MESH_HOOK_TOKEN is pinned via the environment/.env; "
                "rotation here has no effect. Remove it from .env (or change it "
                "there) and restart to rotate."
            ),
        )
    new_token = rotate_hook_token()
    logger.info("Hook token rotated via dashboard")
    response.headers["Cache-Control"] = "no-store"
    reveal = _can_reveal(request)
    return {
        "rotated": True,
        "source": "data_file",
        "token": new_token if reveal else None,
        "masked": _mask(new_token),
        "can_reveal": reveal,
        "warning": "All existing hook clients must be reinstalled with the new token.",
        # Concrete per-surface steps so the operator isn't left guessing which
        # clients broke. The token file is already updated on this host; remote
        # client hosts must pull the new value.
        "remediation": [
            "Re-stamp the new token into every tool config: `mem-mesh mcp config --auth` on each client host (and `mem-mesh hooks install` to refresh HTTP-hook headers).",
            "Verify everything reconnects with `mem-mesh doctor`.",
        ],
    }


# ───────────────────────── runtime config ──────────────────────────


@router.get("/config")
async def security_config(request: Request, response: Response):
    """Effective runtime config for managed auth settings.

    Each entry reports the active ``value``, its ``source`` (``env`` / ``db`` /
    ``default``), and whether it is ``env_pinned`` (read-only). Secrets are
    never returned — only whether a password is set.
    """
    response.headers["Cache-Control"] = "no-store"
    items = {}
    for key, kind in rc.MANAGED_AUTH_KEYS.items():
        if kind == "secret":
            value = rc.admin_password_set()
        elif kind == "tribool":
            value = rc.effective_tribool(key)
        elif kind == "bool":
            value = rc.effective_bool(key)
        else:
            value, _ = rc.effective(key)
        items[key] = {
            "value": value,
            "kind": kind,
            "source": rc.source_of(key),
            "env_pinned": rc.is_env_pinned(key),
            "env_var": rc.env_var_name(key),
        }
    return {"auth": items}


def _truthy(v) -> bool:
    return v in (True, "true", "True", "1", 1, "on", "yes")


# Keys the dashboard may write == keys honored from the DB (single source of
# truth in runtime_config). OAuth toggles are now included, but the PUT handler
# below guards the self-lockout case (enabling OAuth with Basic Auth off would
# cut the browser dashboard off from /api).
WRITABLE_KEYS = rc.DB_OVERRIDABLE_KEYS


@router.put("/auth")
async def update_auth_config(
    request: Request, response: Response, payload: dict = Body(...)
):
    """Set/clear dashboard auth overrides (DB). Pass ``null`` (or ``""``) to
    clear a key back to env/default. Env-pinned keys are skipped; secrets are
    hashed before storage.

    Gated by the same policy as token reveal (authenticated surface or local
    request) so a 0.0.0.0-exposed, unauthenticated server cannot be reconfigured
    — including having its auth disabled — remotely.
    """
    if not _can_reveal(request):
        raise HTTPException(
            status_code=403,
            detail=(
                "Changing auth settings requires an authenticated dashboard "
                "(Basic Auth / OAuth web auth) or a local request."
            ),
        )
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(status_code=400, detail="Expected a non-empty object")

    # Lockout guard against the RESULTING state (after this payload applies), not
    # the pre-mutation state. Covers: enabling Basic Auth, clearing the password
    # while it stays enabled, and the env-pinned-enabled + clear-password case.
    if "web_basic_auth_enabled" in payload and not rc.is_env_pinned(
        "web_basic_auth_enabled"
    ):
        resulting_basic = _truthy(payload.get("web_basic_auth_enabled"))
    else:
        resulting_basic = rc.effective_bool("web_basic_auth_enabled")
    if "admin_password" in payload and not rc.is_env_pinned("admin_password"):
        # "" / null clears the password; any non-empty string sets it.
        resulting_pw_set = bool(payload.get("admin_password"))
    else:
        resulting_pw_set = rc.admin_password_set()
    if resulting_basic and not resulting_pw_set:
        raise HTTPException(
            status_code=400,
            detail=(
                "This change would leave Basic Auth enabled with no admin "
                "password and lock you out. Set a password in the same request."
            ),
        )

    # OAuth lockout guard: enabling OAuth (auth_enabled — which inherits web auth
    # — or web_auth_enabled directly) puts /api behind a bearer token. The
    # browser dashboard reaches /api only through its Basic Auth session
    # (dual-auth), so OAuth without Basic Auth would lock the dashboard out of
    # its own API. Refuse unless Basic Auth ends up enabled (with a password,
    # already required above).
    def _resulting_on(key: str) -> bool:
        if key in payload and not rc.is_env_pinned(key):
            return _truthy(payload.get(key))
        return (
            rc.effective_bool(key)
            if key == "auth_enabled"
            else rc.effective_tribool(key)
        )

    if (_resulting_on("auth_enabled") or _resulting_on("web_auth_enabled")) and not (
        resulting_basic and resulting_pw_set
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Enable Basic Auth (web_basic_auth_enabled + an admin password) "
                "before turning on OAuth, or the browser dashboard loses access "
                "to /api. Set them in the same request."
            ),
        )

    response.headers["Cache-Control"] = "no-store"
    warnings = []
    if get_settings().server_workers > 1:
        warnings.append(
            "Multiple workers are configured; this change applies to one worker "
            "until all are restarted. Run a single worker for runtime auth changes."
        )
    applied, skipped = {}, {}
    for key, value in payload.items():
        if key not in rc.MANAGED_KEYS:
            skipped[key] = "unknown key"
            continue
        if key not in WRITABLE_KEYS:
            skipped[key] = f"env-only (set via {rc.env_var_name(key)})"
            continue
        if rc.is_env_pinned(key):
            skipped[key] = f"env-pinned ({rc.env_var_name(key)})"
            continue
        if key == "admin_username" and value:
            v = str(value)
            if len(v) > 64 or any(ord(c) < 32 for c in v):
                skipped[key] = "invalid username (too long or control chars)"
                continue
        try:
            if value is None or value == "":
                await rc.clear_override(db, key)
                applied[key] = "cleared"
            else:
                await rc.set_override(db, key, value)
                applied[key] = "set"
        except PermissionError:
            skipped[key] = "env-pinned"
        except Exception as e:  # pragma: no cover - defensive
            logger.error("Failed to set auth override %s: %s", key, e)
            skipped[key] = "error"
    logger.info("Auth config updated via dashboard: applied=%s", list(applied))

    # Turning OAuth/MCP auth ON means every MCP/API client must now present the
    # bearer token — but their config files were written without it (or with an
    # unexported ${MEM_MESH_HOOK_TOKEN}). Surface the exact remediation so the
    # operator isn't left chasing 401s (the gap doctor otherwise catches later).
    notices = []
    mcp_auth_keys = ("auth_enabled", "mcp_auth_enabled", "web_auth_enabled")
    if any(k in applied and _truthy(payload.get(k)) for k in mcp_auth_keys):
        notices.append(
            "MCP/API clients now require the bearer token. On each client host run "
            "`mem-mesh mcp config --auth` to stamp the literal token into each tool "
            "config (or `mem-mesh doctor` to verify)."
        )
    return {
        "applied": applied,
        "skipped": skipped,
        "warnings": warnings,
        "notices": notices,
    }


# ───────────────────────── hook tuning config ──────────────────────────


@router.get("/hook-config")
async def hook_config(request: Request, response: Response):
    """Effective hook-tuning runtime config (e.g. the SubagentStop save
    threshold). Each entry reports the active ``value``, its ``source``
    (env/db/default) and whether it is ``env_pinned`` (read-only)."""
    response.headers["Cache-Control"] = "no-store"
    items = {}
    for key, kind in rc.MANAGED_HOOK_KEYS.items():
        items[key] = {
            "value": rc.effective_int(key),
            "kind": kind,
            "source": rc.source_of(key),
            "env_pinned": rc.is_env_pinned(key),
            "env_var": rc.env_var_name(key),
        }
    return {"hook": items}


@router.put("/hook-config")
async def update_hook_config(
    request: Request, response: Response, payload: dict = Body(...)
):
    """Set/clear hook-tuning overrides (DB). Pass ``null`` (or ``""``) to clear a
    key back to env/default. Gated by the same policy as the auth config — an
    authenticated dashboard or a local request — so an exposed, unauthenticated
    server cannot be retuned remotely."""
    if not _can_reveal(request):
        raise HTTPException(
            status_code=403,
            detail=(
                "Changing hook settings requires an authenticated dashboard "
                "(Basic Auth / OAuth web auth) or a local request."
            ),
        )
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(status_code=400, detail="Expected a non-empty object")

    response.headers["Cache-Control"] = "no-store"
    warnings = []
    if get_settings().server_workers > 1:
        warnings.append(
            "Multiple workers are configured; this change applies to one worker "
            "until all are restarted. Run a single worker for runtime changes."
        )
    applied, skipped = {}, {}
    for key, value in payload.items():
        if key not in rc.MANAGED_HOOK_KEYS:
            skipped[key] = "unknown or non-hook key"
            continue
        if rc.is_env_pinned(key):
            skipped[key] = f"env-pinned ({rc.env_var_name(key)})"
            continue
        try:
            if value is None or value == "":
                await rc.clear_override(db, key)
                applied[key] = "cleared"
            else:
                iv = int(value)
                if iv < 0:
                    skipped[key] = "must be >= 0"
                    continue
                await rc.set_override(db, key, iv)
                applied[key] = iv
        except (ValueError, TypeError):
            skipped[key] = "not an integer"
        except PermissionError:
            skipped[key] = "env-pinned"
        except Exception as e:  # pragma: no cover - defensive
            logger.error("Failed to set hook override %s: %s", key, e)
            skipped[key] = "error"
    logger.info("Hook config updated via dashboard: applied=%s", list(applied))
    return {"applied": applied, "skipped": skipped, "warnings": warnings}
