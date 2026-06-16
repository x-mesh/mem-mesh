"""Codex-specific config helpers.

Codex uses ``config.toml`` for MCP servers, unlike Claude/Cursor/Kiro JSON
``mcpServers`` files. Keep the text merge here narrow and marker-based so we
do not need an extra TOML writer dependency on Python 3.9.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.cli.hooks.json_ops import _atomic_write_text

CODEX_DIR = Path.home() / ".codex"
CODEX_HOOKS_DIR = CODEX_DIR / "hooks"
CODEX_HOOKS_FILE = CODEX_DIR / "hooks.json"
CODEX_CONFIG = CODEX_DIR / "config.toml"

_BEGIN = "# >>> mem-mesh managed MCP"
_END = "# <<< mem-mesh managed MCP"
_MEM_MESH_TABLE = re.compile(r"^\s*\[mcp_servers\.mem-mesh(?:\.|\])", re.MULTILINE)
_ANY_TABLE = re.compile(r"^\s*\[")


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: List[str]) -> str:
    return "[" + ", ".join(_toml_string(v) for v in values) + "]"


def build_codex_mcp_block(
    *,
    mode: str,
    url: str = "http://localhost:8000",
    path: str = "",
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
) -> str:
    """Return a managed ``[mcp_servers.mem-mesh]`` TOML block for Codex."""
    env = {"MEM_MESH_CLIENT": "codex", **(env or {})}
    lines = [_BEGIN, "[mcp_servers.mem-mesh]"]

    if mode in ("http", "api", "sse"):
        lines.extend(
            [
                f"url = {_toml_string(url.rstrip('/') + '/mcp/sse')}",
                'bearer_token_env_var = "MEM_MESH_HOOK_TOKEN"',
            ]
        )
    else:
        server_command = command or sys.executable
        server_args = args or ["-m", "app.mcp_stdio"]
        lines.extend(
            [
                f"command = {_toml_string(server_command)}",
                f"args = {_toml_array(server_args)}",
            ]
        )
        if path:
            lines.append(f"cwd = {_toml_string(str(Path(path).expanduser()))}")

    lines.extend(
        [
            "enabled = true",
            'default_tools_approval_mode = "prompt"',
            "startup_timeout_sec = 20",
            "tool_timeout_sec = 60",
            "",
            "[mcp_servers.mem-mesh.env]",
        ]
    )
    for key in sorted(env):
        lines.append(f"{key} = {_toml_string(env[key])}")
    lines.append(_END)
    return "\n".join(lines) + "\n"


def build_codex_mcp_block_from_entry(entry: Dict[str, Any]) -> str:
    """Convert the generic MCP entry dict used by onboarding into Codex TOML."""
    env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
    if "url" in entry:
        url = str(entry["url"]).rsplit("/mcp/sse", 1)[0]
        return build_codex_mcp_block(mode="http", url=url, env=env)
    return build_codex_mcp_block(
        mode="local",
        command=str(entry.get("command", sys.executable)),
        args=[str(arg) for arg in entry.get("args", ["-m", "app.mcp_stdio"])],
        path=str(entry.get("cwd", "")),
        env=env,
    )


def _strip_managed_block(text: str) -> str:
    lines = text.splitlines(keepends=True)
    result: List[str] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == _BEGIN:
            i += 1
            while i < len(lines) and lines[i].strip() != _END:
                i += 1
            if i < len(lines):
                i += 1
            continue
        result.append(lines[i])
        i += 1
    return "".join(result)


def _strip_mem_mesh_tables(text: str) -> str:
    """Remove unmanaged mem-mesh MCP tables to avoid duplicate TOML tables."""
    lines = text.splitlines(keepends=True)
    result: List[str] = []
    skipping = False
    for line in lines:
        if _MEM_MESH_TABLE.match(line):
            skipping = True
            continue
        if skipping and _ANY_TABLE.match(line) and not _MEM_MESH_TABLE.match(line):
            skipping = False
        if not skipping:
            result.append(line)
    return "".join(result)


def merge_codex_mcp_config(config_path: Path, block: str) -> None:
    """Upsert the mem-mesh MCP block in a Codex ``config.toml`` file."""
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    cleaned = _strip_mem_mesh_tables(_strip_managed_block(existing)).rstrip()
    new_text = (cleaned + "\n\n" if cleaned else "") + block
    _atomic_write_text(config_path, new_text)


def remove_codex_mcp_config(config_path: Path) -> None:
    if not config_path.exists():
        return
    existing = config_path.read_text(encoding="utf-8")
    cleaned = _strip_mem_mesh_tables(_strip_managed_block(existing)).rstrip()
    _atomic_write_text(config_path, (cleaned + "\n") if cleaned else "")


def codex_config_has_mem_mesh(config_path: Path) -> bool:
    if not config_path.exists():
        return False
    text = config_path.read_text(encoding="utf-8")
    return _BEGIN in text or bool(_MEM_MESH_TABLE.search(text))
