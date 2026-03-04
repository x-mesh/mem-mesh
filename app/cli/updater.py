"""Self-update command for mem-mesh.

Checks PyPI for the latest version and upgrades via pip.
Optionally re-installs hooks to pick up template changes.
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Optional, Tuple

from app.cli.hooks.colors import bold, dim, err, header, info, ok, warn
from app.core.version import __VERSION__


PYPI_URL = "https://pypi.org/pypi/mem-mesh/json"


def _parse_version(v: str) -> Tuple[int, ...]:
    """Parse version string to comparable tuple."""
    parts = []
    for part in v.split("."):
        # Strip pre-release suffixes for comparison
        num = ""
        for ch in part:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts)


def _fetch_latest_version(timeout: int = 10) -> Optional[str]:
    """Fetch latest version from PyPI."""
    try:
        req = urllib.request.Request(PYPI_URL, method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("info", {}).get("version")
    except (urllib.error.URLError, json.JSONDecodeError, OSError, KeyError):
        return None


def cmd_update(
    skip_hooks: bool = False,
    check_only: bool = False,
    pre: bool = False,
) -> None:
    """Check for updates and upgrade mem-mesh."""
    print()
    print(header("=== mem-mesh update ==="))
    print()

    # Step 1: Version check
    print(bold("[1/3] Version Check"))
    print(f"  Current: {info(__VERSION__)}")

    latest = _fetch_latest_version()
    if latest is None:
        print(f"  Latest:  {err('failed to fetch from PyPI')}")
        print(dim("  Check your network connection or try again later."))
        print()
        return

    print(f"  Latest:  {info(latest)}")

    current_tuple = _parse_version(__VERSION__)
    latest_tuple = _parse_version(latest)

    if current_tuple >= latest_tuple:
        print(f"  {ok('Already up to date.')}")
        print()
        return

    print(f"  {warn(f'Update available: {__VERSION__} -> {latest}')}")
    print()

    if check_only:
        print(dim(f"  Run 'mem-mesh update' to upgrade."))
        print()
        return

    # Step 2: Upgrade via pip
    print(bold("[2/3] Updating CLI"))

    pip_args = [sys.executable, "-m", "pip", "install", "--upgrade", "mem-mesh"]
    if pre:
        pip_args.append("--pre")

    print(f"  {dim(' '.join(pip_args))}")

    result = subprocess.run(
        pip_args,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"  {ok(f'Updated to {latest}')}")
    else:
        print(f"  {err('Update failed')}")
        stderr = result.stderr.strip()
        if stderr:
            # Show last 3 lines of error
            for line in stderr.splitlines()[-3:]:
                print(f"    {dim(line)}")
        print()
        return
    print()

    # Step 3: Re-install hooks
    print(bold("[3/3] Updating Hooks"))

    if skip_hooks:
        print(f"  {dim('Skipped (--skip-hooks)')}")
        print()
        _print_done(latest)
        return

    try:
        from app.cli.hooks.constants import DEFAULT_URL
        from app.cli.hooks.status import resolve_api_url, _extract_url_from_script
        from app.cli.hooks.constants import CLAUDE_HOOKS_DIR
        from app.cli.install_hooks import cmd_install

        baked_url = (
            _extract_url_from_script(CLAUDE_HOOKS_DIR / "mem-mesh-session-start.sh")
            or _extract_url_from_script(CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh")
        )
        url, _source = resolve_api_url(baked_url)

        cmd_install("all", url, "api", "", "standard")
        print(f"  {ok('Hooks updated.')}")
    except Exception as e:
        print(f"  {warn(f'Hook update failed: {e}')}")
        print(dim("  Run 'mem-mesh hooks install' manually to update hooks."))
    print()

    _print_done(latest)


def _print_done(version: str) -> None:
    """Print completion message."""
    print(ok(f"Update complete! Now running mem-mesh {version}"))
    print()
