"""MCP configuration manager for dev tools.

Detects installed dev tools and configures mem-mesh MCP server entries
in their respective config files without touching other entries.
"""

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.cli.hooks.colors import bold, dim, err, info, ok, warn

# ── Tool Registry ──

MCP_TOOLS: list[dict] = [
    {
        "name": "Cursor",
        "key": "cursor",
        "config_path": Path.home() / ".cursor" / "mcp.json",
        "detect": lambda: (Path.home() / ".cursor").exists(),
    },
    {
        "name": "Kiro",
        "key": "kiro",
        "config_path": Path.home() / ".kiro" / "settings" / "mcp.json",
        "detect": lambda: (Path.home() / ".kiro").exists(),
    },
    {
        "name": "Claude Desktop",
        "key": "claude-desktop",
        "config_path": Path.home()
        / "Library"
        / "Application Support"
        / "Claude"
        / "claude_desktop_config.json",
        "detect": lambda: (
            Path.home() / "Library" / "Application Support" / "Claude"
        ).exists(),
    },
    {
        "name": "VS Code",
        "key": "vscode",
        "config_path": Path.home() / ".vscode" / "mcp.json",
        "detect": lambda: (Path.home() / ".vscode").exists(),
    },
    {
        "name": "Windsurf",
        "key": "windsurf",
        "config_path": Path.home() / ".windsurf" / "mcp.json",
        "detect": lambda: (Path.home() / ".windsurf").exists(),
    },
    {
        "name": "LM Studio",
        "key": "lmstudio",
        "config_path": Path.home() / ".lmstudio" / "mcp.json",
        "detect": lambda: (Path.home() / ".lmstudio").exists(),
    },
]

# MCP entry key name in all config files
MCP_SERVER_KEY = "mem-mesh"


def detect_tools() -> list[dict]:
    """Detect installed dev tools that support MCP configuration."""
    detected = []
    for tool in MCP_TOOLS:
        installed = tool["detect"]()
        has_config = tool["config_path"].exists()
        detected.append({
            **tool,
            "installed": installed,
            "has_config": has_config,
        })
    return detected


def backup_config(config_path: Path) -> Optional[Path]:
    """Create a timestamped backup of a config file before modification.

    Returns the backup path, or None if the file doesn't exist.
    """
    if not config_path.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = config_path.with_suffix(f".{timestamp}.bak")

    shutil.copy2(config_path, backup_path)
    return backup_path


def generate_mcp_entry(
    mode: str,
    url: str = "http://localhost:8000",
    auto_approve: bool = True,
) -> dict:
    """Generate a mem-mesh MCP server entry.

    Args:
        mode: 'sse' or 'stdio'
        url: API server URL (used for SSE mode)
        auto_approve: Whether to add autoApprove list for common tools
    """
    approve_list = [
        "add", "search", "context", "update", "delete", "stats",
        "pin_add", "pin_complete", "pin_promote",
        "session_resume", "session_end",
        "link", "unlink", "get_links",
        "batch_operations", "weekly_review",
    ]

    if mode == "sse":
        entry: dict = {
            "url": f"{url.rstrip('/')}/mcp/sse",
            "transport": "sse",
        }
    else:
        # stdio mode — use the current Python interpreter
        python_path = sys.executable
        entry = {
            "command": python_path,
            "args": ["-m", "app.mcp_stdio"],
        }

    if auto_approve:
        entry["autoApprove"] = approve_list

    return entry


def read_config(config_path: Path) -> dict:
    """Read and parse a JSON config file. Returns empty dict structure if missing."""
    if not config_path.exists():
        return {"mcpServers": {}}

    try:
        text = config_path.read_text(encoding="utf-8")
        data = json.loads(text)
        if "mcpServers" not in data:
            data["mcpServers"] = {}
        return data
    except (json.JSONDecodeError, OSError):
        return {"mcpServers": {}}


def write_config(config_path: Path, data: dict) -> None:
    """Write config data to JSON file, creating parent directories if needed."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def configure_tool(
    tool: dict,
    mcp_entry: dict,
    do_backup: bool = True,
) -> tuple[bool, str]:
    """Configure mem-mesh MCP entry for a single tool.

    Returns (success, message).
    """
    config_path: Path = tool["config_path"]

    # Backup existing config
    backup_path = None
    if do_backup and config_path.exists():
        backup_path = backup_config(config_path)

    # Read existing config
    data = read_config(config_path)

    # Check if already configured with same settings
    existing = data["mcpServers"].get(MCP_SERVER_KEY)
    if existing == mcp_entry:
        return True, "already up to date"

    # Update only the mem-mesh entry
    action = "updated" if existing else "added"
    data["mcpServers"][MCP_SERVER_KEY] = mcp_entry

    # Write back
    try:
        write_config(config_path, data)
    except OSError as e:
        return False, f"write failed: {e}"

    msg = f"{action}"
    if backup_path:
        msg += f" (backup: {backup_path.name})"
    return True, msg


def remove_tool_config(tool: dict) -> tuple[bool, str]:
    """Remove mem-mesh MCP entry from a tool's config.

    Returns (success, message).
    """
    config_path: Path = tool["config_path"]

    if not config_path.exists():
        return True, "no config file"

    data = read_config(config_path)
    if MCP_SERVER_KEY not in data.get("mcpServers", {}):
        return True, "not configured"

    # Backup before removal
    backup_config(config_path)

    del data["mcpServers"][MCP_SERVER_KEY]
    try:
        write_config(config_path, data)
    except OSError as e:
        return False, f"write failed: {e}"

    return True, "removed"


# ── Interactive Flow ──


def _prompt_choice(prompt: str, options: list[str], default: str = "") -> str:
    """Simple numbered choice prompt."""
    for i, opt in enumerate(options, 1):
        print(f"    {bold(str(i))}. {opt}")
    while True:
        raw = input(f"  {prompt} ").strip()
        if not raw and default:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print(f"    Enter 1-{len(options)}")


def run_mcp_setup(
    url: str = "http://localhost:8000",
    yes: bool = False,
) -> None:
    """Interactive MCP configuration step for onboarding."""
    print(bold("[3/3] MCP Configuration"))
    print()

    # Show API URL
    env_url = os.getenv("MEM_MESH_API_URL", "")
    if env_url:
        print(f"  API URL: {info(env_url)} {dim('(from MEM_MESH_API_URL)')}")
        url = env_url
    else:
        print(f"  API URL: {info(url)}")
    print()

    # Detect tools
    tools = detect_tools()
    installed_tools = [t for t in tools if t["installed"]]

    if not installed_tools:
        print(f"  {warn('No supported dev tools detected.')}")
        print(dim("  Supported: Cursor, Kiro, Claude Desktop, VS Code, Windsurf, LM Studio"))
        print()
        return

    # Show detected tools
    print(f"  {bold('Detected tools:')}")
    for t in tools:
        if t["installed"]:
            config_status = ok("config exists") if t["has_config"] else dim("no config yet")
            # Check if mem-mesh already configured
            if t["has_config"]:
                data = read_config(t["config_path"])
                if MCP_SERVER_KEY in data.get("mcpServers", {}):
                    config_status = ok("mem-mesh configured")
            print(f"    {ok('✓')} {t['name']:<16} {dim(str(t['config_path']))}  [{config_status}]")
        else:
            print(f"    {dim('✗')} {t['name']:<16} {dim('not installed')}")
    print()

    if yes:
        # Non-interactive: configure all detected tools with SSE mode
        mode = "sse"
        targets = installed_tools
    else:
        # Choose connection mode
        print(f"  {bold('Connection mode:')}")
        mode_options = [
            f"SSE {dim('(recommended — uses running API server)')}",
            f"Stdio {dim('(standalone — runs MCP process per tool, no server needed)')}",
            f"Skip {dim('(configure later)')}",
        ]
        chosen_mode = _prompt_choice("Choose [1]: ", mode_options, default=mode_options[0])
        mode_idx = mode_options.index(chosen_mode)
        if mode_idx == 2:
            print(f"  {dim('Skipping MCP configuration.')}")
            print()
            return
        mode = "sse" if mode_idx == 0 else "stdio"
        print()

        # Choose which tools to configure
        if len(installed_tools) == 1:
            targets = installed_tools
            print(f"  Configuring: {info(installed_tools[0]['name'])}")
        else:
            tool_names = [t["name"] for t in installed_tools]
            print(f"  {bold('Configure mem-mesh MCP for:')}")
            target_options = [
                f"All detected ({', '.join(tool_names)})",
                "Select individually",
                "Skip",
            ]
            chosen_target = _prompt_choice(
                "Choose [1]: ", target_options, default=target_options[0]
            )
            target_idx = target_options.index(chosen_target)

            if target_idx == 2:
                print(f"  {dim('Skipping MCP configuration.')}")
                print()
                return
            elif target_idx == 0:
                targets = installed_tools
            else:
                # Individual selection
                targets = []
                for t in installed_tools:
                    answer = input(
                        f"    Configure {bold(t['name'])}? [Y/n] "
                    ).strip().lower()
                    if answer not in ("n", "no"):
                        targets.append(t)
        print()

    if not targets:
        print(f"  {dim('No tools selected.')}")
        print()
        return

    # Generate MCP entry
    mcp_entry = generate_mcp_entry(mode=mode, url=url)

    # Show what will be written
    print(f"  {bold('MCP entry')} ({mode} mode):")
    entry_json = json.dumps({"mem-mesh": mcp_entry}, indent=2)
    for line in entry_json.splitlines():
        print(f"    {dim(line)}")
    print()

    # Configure each tool
    for t in targets:
        success, msg = configure_tool(t, mcp_entry, do_backup=True)
        if success:
            print(f"  {ok('✓')} {t['name']}: {msg}")
        else:
            print(f"  {err('✗')} {t['name']}: {msg}")
    print()
