"""``setup-token`` — wire MEM_MESH_HOOK_TOKEN into the user's shell environment.

HTTP-mode hooks (``"type": "http"``) and the MCP http transport read the bearer
token from the *shell* environment (``$MEM_MESH_HOOK_TOKEN``); unlike command
(``.sh``) hooks they have **no file fallback**. So a token sitting in
``~/.mem-mesh/hook_token`` authenticates command hooks but NOT HTTP hooks / MCP
until it is also exported in the shell. This command bridges that gap: it ensures
the token file exists, then writes an idempotent ``export`` block into the
detected shell rc that *sources the token from the file* (the secret stays in the
one 0600 file, never duplicated as plaintext in the rc) and runs an auth test.
"""

import os
from pathlib import Path
from typing import Optional, Tuple

from app.cli.hooks.colors import dim, err, header, ok, warn
from app.core.config import HOOK_TOKEN_FILE

_BLOCK_START = "# >>> mem-mesh hook token >>>"
_BLOCK_END = "# <<< mem-mesh hook token <<<"


def _detect_shell_rc() -> Tuple[str, Path]:
    """Return ``(shell_name, rc_path)`` inferred from ``$SHELL``.

    bash prefers ``.bashrc`` but falls back to ``.bash_profile`` (macOS login
    shells); fish uses ``~/.config/fish/config.fish``; anything unknown lands on
    ``~/.profile``; the default is zsh / ``.zshrc`` (macOS default).
    """
    name = Path(os.environ.get("SHELL", "")).name
    home = Path.home()
    if name == "bash":
        rc = home / ".bashrc"
        if not rc.exists() and (home / ".bash_profile").exists():
            return "bash", home / ".bash_profile"
        return "bash", rc
    if name == "fish":
        return "fish", home / ".config" / "fish" / "config.fish"
    if name and name != "zsh":
        return name, home / ".profile"
    return "zsh", home / ".zshrc"


def _token_file_ref() -> str:
    """The token file path with ``$HOME`` collapsed, for embedding in the rc."""
    p = str(HOOK_TOKEN_FILE)
    home = str(Path.home())
    return p.replace(home, "$HOME", 1) if p.startswith(home) else p


def _export_block(shell: str) -> str:
    """An idempotent, file-sourced export block for ``shell`` (token only).

    Only the token is exported, and it is *sourced from the file* so the secret
    lives in the one 0600 file. The API URL is deliberately NOT exported here:
    it is resolved from the ``~/.mem-mesh/api_url`` SSOT (which install /
    ``--api-url`` writes), so pinning it as a literal env would shadow that file.
    """
    ref = _token_file_ref()
    out = [_BLOCK_START]
    if shell == "fish":
        out.append(f"test -r {ref}; and set -gx MEM_MESH_HOOK_TOKEN (cat {ref})")
    else:
        out.append(f'export MEM_MESH_HOOK_TOKEN="$(cat {ref} 2>/dev/null)"')
    out.append(_BLOCK_END)
    return "\n".join(out)


def _inject(rc_path: Path, block: str) -> str:
    """Idempotently place ``block`` in ``rc_path``.

    Returns ``'created'`` | ``'updated'`` | ``'unchanged'``. A pre-existing
    managed block (delimited by the markers) is replaced in place; otherwise the
    block is appended. The prior file is backed up to ``<name>.bak`` on any write.
    """
    existing = rc_path.read_text(encoding="utf-8") if rc_path.exists() else ""
    has_block = _BLOCK_START in existing and _BLOCK_END in existing
    if has_block:
        head = existing.split(_BLOCK_START, 1)[0].rstrip("\n")
        tail = existing.split(_BLOCK_END, 1)[1].lstrip("\n")
        new = f"{head}\n\n{block}\n{tail}" if head else f"{block}\n{tail}"
    else:
        base = existing if not existing or existing.endswith("\n") else existing + "\n"
        new = f"{base}\n{block}\n" if base else f"{block}\n"
    if new == existing:
        return "unchanged"
    if rc_path.exists():
        rc_path.with_name(rc_path.name + ".bak").write_text(existing, encoding="utf-8")
    else:
        rc_path.parent.mkdir(parents=True, exist_ok=True)
    rc_path.write_text(new, encoding="utf-8")
    return "updated" if has_block else "created"


def _resolve_or_create_token() -> Optional[str]:
    """Resolve the existing token, generating one (``~/.mem-mesh/hook_token``)
    if none is configured. Lazy import of the installer avoids a circular dep."""
    from app.core.config import resolve_hook_token

    token = resolve_hook_token()
    if token:
        return token
    try:
        from app.cli.install_hooks import _ensure_hook_token

        return _ensure_hook_token()
    except Exception as e:  # pragma: no cover - defensive
        print(f"  {err(f'token generation failed: {e}')}")
        return None


def cmd_setup_token(
    print_only: bool = False,
    api_url: Optional[str] = None,
    no_test: bool = False,
    rc_path: Optional[str] = None,
) -> None:
    """Ensure the token file, inject the shell export, and verify auth."""
    print(header("=== mem-mesh setup-token ==="))

    token = _resolve_or_create_token()
    if not token:
        return
    from app.cli.hooks.doctor import _mask_token

    in_shell = bool(os.environ.get("MEM_MESH_HOOK_TOKEN"))
    print(
        f"  token file:  {ok('ready')} {dim(_mask_token(token))} {dim(str(HOOK_TOKEN_FILE))}"
    )
    print(
        "  shell env:   "
        + (ok("already exported") if in_shell else warn("not set in this shell yet"))
    )

    # --api-url writes the URL SSOT (~/.mem-mesh/api_url), not a shell export:
    # hooks read that file directly, so an env pin would only shadow it.
    if api_url:
        from app.cli.install_hooks import API_URL_FILE, _ensure_api_url

        _ensure_api_url(api_url)
        print(f"  api_url:     {ok('written')} {dim(str(API_URL_FILE))}")

    shell, detected_rc = _detect_shell_rc()
    target_rc = Path(rc_path).expanduser() if rc_path else detected_rc
    block = _export_block(shell)

    if print_only:
        print(dim(f"\n  Add to {target_rc}  ({shell}):\n"))
        print(block)
        print(dim(f"\n  Then reload:  source {target_rc}"))
        return

    action = _inject(target_rc, block)
    tone = ok if action != "unchanged" else dim
    print(f"  {target_rc}: {tone(action)} {dim(f'({shell})')}")
    if action == "updated":
        print(dim(f"  backup:      {target_rc.name}.bak"))
    print(dim(f"  reload:      source {target_rc}   (or open a new terminal)"))

    if not no_test:
        from app.cli.hooks.doctor import _test_hook_auth
        from app.cli.hooks.status import resolve_api_url

        url, src = resolve_api_url()
        print()
        print(dim(f"  auth test against {url}  {dim(f'(from {src})')}"))
        _test_hook_auth(url)
