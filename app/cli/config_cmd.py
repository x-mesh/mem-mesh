"""Configuration display for mem-mesh.

Shows all relevant environment variables and their current values.
"""

import os

from app.cli.hooks.colors import bold, dim, err, header, info, ok, warn
from app.cli.hooks.constants import DEFAULT_URL
from app.cli.hooks.status import (
    _extract_url_from_script,
    check_connectivity,
    resolve_api_url,
)
from app.cli.hooks.constants import CLAUDE_HOOKS_DIR
from app.core.version import __VERSION__


# All env vars that mem-mesh recognizes
ENV_VARS = [
    ("MEM_MESH_API_URL", "API server URL (runtime override for hooks)", DEFAULT_URL),
    ("API_URL", "API server URL (fallback)", None),
    ("DATABASE_PATH", "SQLite database path", "data/memories.db"),
    ("LOG_LEVEL", "Logging level", "INFO"),
    ("MEM_MESH_SERVER_HOST", "Server bind host", "0.0.0.0"),
    ("MEM_MESH_SERVER_PORT", "Server bind port", "8000"),
    ("MEM_MESH_SERVER_WORKERS", "Uvicorn worker count", "1"),
    ("ANTHROPIC_API_KEY", "Anthropic API key (for enhanced hook profile)", None),
    ("NO_COLOR", "Disable ANSI color output", None),
]


def cmd_config() -> None:
    """Display current configuration."""
    print()
    print(header("=== mem-mesh configuration ==="))
    print()

    # Version
    print(f"  Version: {bold(__VERSION__)}")
    print(f"  Default URL: {info(DEFAULT_URL)}")
    print()

    # Resolved API URL
    print(header("[API URL Resolution]"))
    baked_url = (
        _extract_url_from_script(CLAUDE_HOOKS_DIR / "mem-mesh-session-start.sh")
        or _extract_url_from_script(CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh")
    )
    url, source = resolve_api_url(baked_url)
    print(f"  Effective URL: {bold(url)} {dim(f'(from {source})')}")
    print(f"  Priority: MEM_MESH_API_URL > API_URL > installed hook URL > default")
    print()

    # Environment variables
    print(header("[Environment Variables]"))
    for var_name, description, default in ENV_VARS:
        value = os.environ.get(var_name)
        if value:
            # Mask sensitive values
            if "KEY" in var_name or "SECRET" in var_name or "TOKEN" in var_name:
                display = ok(value[:8] + "..." + value[-4:]) if len(value) > 12 else ok("***")
            else:
                display = ok(value)
        elif default:
            display = dim(f"not set (default: {default})")
        else:
            display = dim("not set")

        print(f"  {var_name:30s} {display}")
        print(f"  {' ' * 30} {dim(description)}")
    print()

    # Installed hook URL (baked)
    print(header("[Installed Hook URL]"))
    if baked_url:
        print(f"  Baked in scripts: {info(baked_url)}")
        print(dim("  This URL was set at hook install time."))
        print(dim("  Override at runtime with MEM_MESH_API_URL env var."))
    else:
        print(f"  {dim('No hooks installed or URL not found in scripts.')}")
    print()

    # Quick connectivity test
    print(header("[Quick Check]"))
    reachable, message = check_connectivity(url, timeout=3)
    if reachable:
        print(f"  API server: {ok(message)}")
    else:
        print(f"  API server: {err(message)}")
    print()

    # Docker status
    print(header("[Docker]"))
    import shutil

    if shutil.which("docker"):
        import subprocess

        result = subprocess.run(
            ["docker", "ps", "--filter", "name=mem-mesh", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t", 1)
                name = parts[0]
                status = parts[1] if len(parts) > 1 else "unknown"
                if "Up" in status:
                    print(f"  {name}: {ok(status)}")
                else:
                    print(f"  {name}: {warn(status)}")
        else:
            print(f"  {dim('No mem-mesh containers running')}")
    else:
        print(f"  {dim('Docker not installed')}")
    print()
