"""Shared CLI diagnostics — single source of truth for token + MCP status.

``config``, ``status``, ``doctor`` and ``mcp verify`` all render the same
underlying facts. To keep those surfaces consistent, they collect their data
here instead of each re-implementing detection. This module only *reads* state
(it never mutates config) and reuses the already-tested primitives in
``app.cli.mcp_config`` and ``app.core.config``.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.cli.hooks.constants import DEFAULT_URL
from app.core.redaction import mask_secret  # re-exported single masker

__all__ = [
    "mask_secret",
    "TokenStatus",
    "collect_token_status",
    "McpToolStatus",
    "collect_mcp_status",
    "entry_json",
    "ClaudeMcpOverride",
    "collect_claude_overrides",
]


# ── Hook token ──


@dataclass
class TokenStatus:
    """Where the active hook token resolves from, plus a masked preview."""

    source: str  # "env" | "data_file" | "legacy_file" | "none"
    present: bool
    masked: str  # masked preview, or "" when absent

    @property
    def in_shell_env(self) -> bool:
        """True when the token comes from the shell env (covers HTTP hooks/MCP)."""
        return self.source == "env"


def collect_token_status() -> TokenStatus:
    """Resolve the hook token the same way the server does, without leaking it.

    Reuses ``app.core.config.hook_token_source`` / ``resolve_hook_token`` so the
    answer matches ``hooks status`` and ``doctor``. Only a masked preview is
    ever exposed; the raw value never leaves this function.
    """
    try:
        from app.core.config import hook_token_source, resolve_hook_token

        source = hook_token_source()
        token = resolve_hook_token()
    except Exception:
        return TokenStatus(source="none", present=False, masked="")

    return TokenStatus(
        source=source,
        present=bool(token),
        masked=mask_secret(token) if token else "",
    )


# ── MCP config ──


@dataclass
class McpToolStatus:
    """Per dev-tool view of the mem-mesh MCP entry across all known clients."""

    name: str
    key: str
    config_path: str
    installed: bool
    has_config: bool
    configured: bool  # a mem-mesh MCP entry is present
    mode: Optional[str]  # "uvx" | "stdio" | "http" | "codex" | None
    entry: Optional[
        Dict[str, Any]
    ]  # raw entry (verbose rendering); None for codex/absent
    verified: Optional[bool]  # verify_tool_config result; None when not applicable
    verify_message: str
    # 1-indexed (start, end) line span of the entry inside its real config file,
    # so verbose mode can show the *actual* file:line for debugging. None if the
    # entry could not be located (e.g. unreadable file).
    entry_lines: Optional[Tuple[int, int]] = None


def _locate_entry(
    config_path: Path, is_codex: bool = False
) -> Optional[Tuple[int, int]]:
    """Find the 1-indexed line span of the mem-mesh entry in its actual config file.

    Returns ``(start, end)`` so verbose output can point at the real file:line
    instead of a re-serialized copy numbered from 1. Best-effort: returns None
    when the file can't be read or the entry can't be located.
    """
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    if is_codex:
        # TOML: the [mcp_servers.mem-mesh] table plus its sub-tables
        # ([mcp_servers.mem-mesh.tools.*] etc.), up to the next foreign table.
        # NB: a [projects."/path/.../mem-mesh"] header also contains "mem-mesh",
        # so match the mcp_servers.mem-mesh table specifically, not any line.
        mm_table = re.compile(r"^\s*\[mcp_servers\.mem-mesh(?:\.|\])")
        any_table = re.compile(r"^\s*\[")
        start = None
        for i, line in enumerate(lines):
            if mm_table.match(line):
                start = i
                break
        if start is None:
            return None
        end = start
        for j in range(start + 1, len(lines)):
            if any_table.match(lines[j]) and not mm_table.match(lines[j]):
                break  # a non-mem-mesh table ends the block
            end = j
        return (start + 1, end + 1)

    # JSON: the "mem-mesh": key line, then brace-match to its closing brace.
    key_re = re.compile(r'"mem-mesh"\s*:')
    for i, line in enumerate(lines):
        if not key_re.search(line):
            continue
        depth = 0
        started = False
        for j in range(i, len(lines)):
            for ch in lines[j]:
                if ch == "{":
                    depth += 1
                    started = True
                elif ch == "}":
                    depth -= 1
            if started and depth == 0:
                return (i + 1, j + 1)
        return (i + 1, i + 1)
    return None


def _classify_mode(entry: Optional[Dict[str, Any]]) -> Optional[str]:
    """Infer the connection mode from a generated MCP entry (inverse of generate_mcp_entry)."""
    if not entry:
        return None
    if "url" in entry:
        return "http"
    command = str(entry.get("command", ""))
    args = entry.get("args", []) or []
    if command == "uvx" or any("uvx" in str(a) for a in args):
        return "uvx"
    if any("app.mcp_stdio" in str(a) for a in args):
        return "stdio"
    if "command" in entry:
        return "stdio"
    return None


def collect_mcp_status(url: str = DEFAULT_URL) -> List[McpToolStatus]:
    """Collect the mem-mesh MCP entry state for every supported dev tool.

    Walks the full ``mcp_config.MCP_TOOLS`` registry (9 clients) — not just
    Claude — and runs the shared ``verify_tool_config`` so the reported mode,
    reachability and Claude-Code project-override warnings line up with what the
    onboarding/setup flow produced.
    """
    from app.cli.codex_config import codex_config_has_mem_mesh
    from app.cli.mcp_config import (
        MCP_SERVER_KEY,
        detect_tools,
        read_config,
        verify_tool_config,
    )

    results: List[McpToolStatus] = []
    for tool in detect_tools():
        config_path: Path = tool["config_path"]
        installed = bool(tool.get("installed"))
        has_config = bool(tool.get("has_config"))

        entry: Optional[Dict[str, Any]] = None
        configured = False
        mode: Optional[str] = None
        entry_lines: Optional[Tuple[int, int]] = None

        if tool["key"] == "codex":
            configured = has_config and codex_config_has_mem_mesh(config_path)
            mode = "codex" if configured else None
            if configured:
                entry_lines = _locate_entry(config_path, is_codex=True)
        elif has_config:
            data = read_config(config_path)
            entry = data.get("mcpServers", {}).get(MCP_SERVER_KEY)
            configured = entry is not None
            mode = _classify_mode(entry)
            if configured:
                entry_lines = _locate_entry(config_path)

        verified: Optional[bool] = None
        verify_message = ""
        if installed:
            verified, verify_message = verify_tool_config(tool, url=url)

        results.append(
            McpToolStatus(
                name=tool["name"],
                key=tool["key"],
                config_path=str(config_path),
                installed=installed,
                has_config=has_config,
                configured=configured,
                mode=mode,
                entry=entry,
                verified=verified,
                verify_message=verify_message,
                entry_lines=entry_lines,
            )
        )
    return results


def entry_json(entry: Optional[Dict[str, Any]]) -> str:
    """Pretty-print an MCP entry as JSON (used by verbose rendering)."""
    if entry is None:
        return ""
    return json.dumps({"mem-mesh": entry}, indent=2, ensure_ascii=False)


# ── Claude Code project-scoped overrides (shadow the global entry) ──


@dataclass
class ClaudeMcpOverride:
    """A per-project mem-mesh MCP entry in ~/.claude.json that shadows global."""

    project_path: str
    entry: Dict[str, Any]
    differs: bool  # True when it differs from the global mcpServers entry

    @property
    def summary(self) -> str:
        """One-line 'mode url' description of the override target."""
        mode = _classify_mode(self.entry) or "-"
        url = self.entry.get("url", "")
        return f"{mode} {url}".strip()


def collect_claude_overrides() -> List[ClaudeMcpOverride]:
    """Project-scoped mem-mesh MCP entries that shadow the global one.

    Claude Code stores per-project servers under ``projects.<path>.mcpServers``
    in ``~/.claude.json``; when present they OVERRIDE the global
    ``mcpServers.mem-mesh`` for that project. The global-only collectors
    (:func:`collect_mcp_status`) never see these, which is why a project can use
    a different/stale server than ``status`` reports. Returns them so every
    surface can list and reconcile them.
    """
    from app.cli.mcp_config import MCP_SERVER_KEY

    claude = Path.home() / ".claude.json"
    try:
        data = json.loads(claude.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    global_entry = data.get("mcpServers", {}).get(MCP_SERVER_KEY)
    out: List[ClaudeMcpOverride] = []
    for path, conf in (data.get("projects") or {}).items():
        entry = (conf or {}).get("mcpServers", {}).get(MCP_SERVER_KEY)
        if entry is not None:
            out.append(
                ClaudeMcpOverride(
                    project_path=path,
                    entry=entry,
                    differs=(entry != global_entry),
                )
            )
    return out
