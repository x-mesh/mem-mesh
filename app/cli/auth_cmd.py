"""Dashboard auth management from the CLI.

Server-side recovery path for a lost admin password: the dashboard normally
changes it via ``PUT /security/auth``, but that needs you to already be logged
in. When the password is lost, run ``mem-mesh auth set-password`` on the host
(or inside the container) to write a fresh PBKDF2 hash straight to the DB.

The write goes through :mod:`app.core.runtime_config`, so it shares the exact
hashing, env-pinning and key-allowlist rules as the dashboard route. Because the
running server caches overrides in-process (single-worker), a restart is needed
for the new password to take effect — the command says so.
"""

import asyncio
import getpass
import json
import sys
from typing import Optional

from app.cli.hooks.colors import dim, err, ok, warn
from app.core import runtime_config as rc
from app.core.config import Settings
from app.core.database.base import Database

# Mirror the setup form's floor (app.web.oauth.setup_routes.MIN_PASSWORD_LEN).
# Kept as a local constant so the CLI does not import the FastAPI web stack.
MIN_PASSWORD_LEN = 8


def cmd_set_password(
    *,
    username: Optional[str] = None,
    password: Optional[str] = None,
    enable_basic_auth: bool = False,
    json_mode: bool = False,
) -> int:
    """Set (reset) the dashboard admin password from the CLI.

    Returns a process exit code: 0 ok, 1 validation/runtime failure, 2 the key
    is env-pinned or no password could be read.
    """
    # Which managed keys this invocation will write. Check env-pinning up front
    # so we fail with a clear message instead of a late PermissionError.
    keys = ["admin_password"]
    if username is not None:
        keys.append("admin_username")
    if enable_basic_auth:
        keys.append("web_basic_auth_enabled")
    pinned = [rc.env_var_name(k) for k in keys if rc.is_env_pinned(k)]
    if pinned:
        return _fail(
            json_mode,
            "auth is pinned by environment variable(s): "
            + ", ".join(pinned)
            + ". Edit the .env / environment value instead of the DB override.",
            code=2,
        )

    # Read the password: explicit --password for automation, otherwise prompt
    # twice without echo. A non-TTY with no --password cannot prompt safely.
    if password is None:
        if not sys.stdin.isatty():
            return _fail(
                json_mode,
                "no TTY for an interactive prompt; pass --password "
                "(or pipe it via --password-stdin).",
                code=2,
            )
        try:
            password = getpass.getpass("New admin password: ")
            confirm = getpass.getpass("Confirm new password: ")
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return 130
        if password != confirm:
            return _fail(json_mode, "passwords do not match", code=1)

    if len(password) < MIN_PASSWORD_LEN:
        return _fail(
            json_mode,
            f"password must be at least {MIN_PASSWORD_LEN} characters",
            code=1,
        )

    try:
        result = asyncio.run(
            _apply(
                username=username,
                password=password,
                enable_basic_auth=enable_basic_auth,
            )
        )
    except Exception as exc:  # pragma: no cover - defensive
        return _fail(json_mode, f"failed to set password: {exc}", code=1)

    if json_mode:
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0

    print()
    print(ok(f"✓ Admin password updated (user: {result['username']})"))
    print(dim(f"  Database: {result['database_path']}"))
    print()
    print(
        warn(
            "⚠ Restart the server for the change to take effect "
            "(overrides are cached in-process)."
        )
    )
    if not result["basic_auth_enabled"]:
        print()
        print(
            warn(
                "⚠ Basic Auth is OFF — the dashboard login won't be enforced. "
                "Re-run with --enable-basic-auth to turn it on."
            )
        )
    print()
    return 0


async def _apply(
    *,
    username: Optional[str],
    password: str,
    enable_basic_auth: bool,
) -> dict:
    """Persist the new credentials to the DB and report the effective state."""
    settings = Settings()
    db = Database(settings.database_path, embedding_dim=settings.embedding_dim)
    await db.connect()
    try:
        # Load existing overrides so the effective-state read below reflects the
        # current DB (e.g. whether Basic Auth was already on).
        await rc.load_overrides(db)
        if username is not None:
            await rc.set_override(db, "admin_username", username)
        await rc.set_override(db, "admin_password", password)
        if enable_basic_auth:
            await rc.set_override(db, "web_basic_auth_enabled", True)
        return {
            "username": rc.effective_str("admin_username"),
            "basic_auth_enabled": rc.effective_bool("web_basic_auth_enabled"),
            "database_path": settings.database_path,
        }
    finally:
        await db.close()


def _fail(json_mode: bool, message: str, *, code: int) -> int:
    if json_mode:
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    else:
        print(err(f"✗ {message}"), file=sys.stderr)
    return code
