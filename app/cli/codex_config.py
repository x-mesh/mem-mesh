"""Codex-specific config helpers.

Codex uses ``config.toml`` for MCP servers, unlike Claude/Cursor/Kiro JSON
``mcpServers`` files. Keep the text merge here narrow and marker-based so we
do not need an extra TOML writer dependency on Python 3.9.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# NOTE: ``_atomic_write_text`` is imported lazily inside the two writer functions
# below, NOT at module top level. Importing ``app.cli.hooks.json_ops`` here would
# trigger ``app.cli.hooks/__init__`` which eagerly imports ``status``, and
# ``status`` imports this module back -> circular import. Keeping it function-local
# makes ``codex_config`` a leaf module that is safe to import in any order.

CODEX_DIR = Path.home() / ".codex"
CODEX_HOOKS_DIR = CODEX_DIR / "hooks"
CODEX_HOOKS_FILE = CODEX_DIR / "hooks.json"
CODEX_CONFIG = CODEX_DIR / "config.toml"

_BEGIN = "# >>> mem-mesh managed MCP"
_END = "# <<< mem-mesh managed MCP"
_MEM_MESH_TABLE = re.compile(r"^\s*\[mcp_servers\.mem-mesh(?:\.|\])", re.MULTILINE)
_ANY_TABLE = re.compile(r"^\s*\[")
_HOOK_STATE_TABLE = re.compile(r'^\s*\[hooks\.state\.(?P<key>"(?:\\.|[^"\\])*")\]\s*$')
_TRUSTED_HOOK_HASH = re.compile(r'^\s*trusted_hash\s*=\s*"sha256:[0-9a-fA-F]{64}"\s*$')


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: List[str]) -> str:
    return "[" + ", ".join(_toml_string(v) for v in values) + "]"


def _toml_table_segment(value: str) -> str:
    if re.match(r"^[A-Za-z0-9_-]+$", value):
        return value
    return _toml_string(value)


def _approval_tool_names() -> List[str]:
    # Lazy import keeps this module free of CLI import cycles.
    from app.mcp_common.schemas import get_all_tool_schemas

    return [str(schema["name"]) for schema in get_all_tool_schemas()]


def build_codex_mcp_block(
    *,
    mode: str,
    url: str = "http://localhost:8000",
    path: str = "",
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    token: Optional[str] = None,
    approval_tools: Optional[List[str]] = None,
) -> str:
    """Return a managed ``[mcp_servers.mem-mesh]`` TOML block for Codex.

    For http mode with a ``token``, the literal bearer token is baked into a
    ``[mcp_servers.mem-mesh.http_headers]`` table — Codex has no inline
    ``bearer_token`` field, but ``http_headers`` carries literal static headers,
    so the generated config does not rely on runtime env inheritance.
    """
    env = {"MEM_MESH_CLIENT": "codex", **(env or {})}
    lines = [_BEGIN, "[mcp_servers.mem-mesh]"]

    if mode in ("http", "api", "sse"):
        lines.append(f"url = {_toml_string(url.rstrip('/') + '/mcp/sse')}")
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
        ]
    )
    if approval_tools is None:
        approval_tools = _approval_tool_names()
    for tool_name in approval_tools:
        lines.extend(
            [
                "",
                f"[mcp_servers.mem-mesh.tools.{_toml_table_segment(str(tool_name))}]",
                'approval_mode = "approve"',
            ]
        )
    is_remote = mode in ("http", "api", "sse")
    # [mcp_servers.mem-mesh.env]는 stdio(local) 전송에서만 유효하다. Codex는
    # streamable_http(url) 전송에서 env 테이블을 거부한다
    # ("env is not supported for streamable_http"). remote 모드에선 server가
    # clientInfo/User-Agent로 client를 자동 감지하므로 env 블록을 생략한다.
    if not is_remote and env:
        lines.append("")
        lines.append("[mcp_servers.mem-mesh.env]")
        for key in sorted(env):
            lines.append(f"{key} = {_toml_string(env[key])}")
    # Literal bearer header: generated config bakes the token here rather than
    # referencing an env var.
    if is_remote and token:
        lines.extend(
            [
                "",
                "[mcp_servers.mem-mesh.http_headers]",
                f"Authorization = {_toml_string(f'Bearer {token}')}",
            ]
        )
    lines.append(_END)
    return "\n".join(lines) + "\n"


def build_codex_mcp_block_from_entry(entry: Dict[str, Any]) -> str:
    """Convert the generic MCP entry dict used by onboarding into Codex TOML."""
    env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
    approval_tools = entry.get("autoApprove") if "autoApprove" in entry else []
    if not isinstance(approval_tools, list):
        approval_tools = []
    if "url" in entry:
        url = str(entry["url"]).rsplit("/mcp/sse", 1)[0]
        # Carry the literal bearer token from the generic entry's header into the
        # Codex http_headers table.
        token = None
        auth = (entry.get("headers") or {}).get("Authorization", "")
        if isinstance(auth, str) and auth.startswith("Bearer "):
            token = auth[len("Bearer ") :].strip() or None
        return build_codex_mcp_block(
            mode="http",
            url=url,
            env=env,
            token=token,
            approval_tools=[str(name) for name in approval_tools],
        )
    return build_codex_mcp_block(
        mode="local",
        command=str(entry.get("command", sys.executable)),
        args=[str(arg) for arg in entry.get("args", ["-m", "app.mcp_stdio"])],
        path=str(entry.get("cwd", "")),
        env=env,
        approval_tools=[str(name) for name in approval_tools],
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
    from app.cli.hooks.json_ops import _atomic_write_text

    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    cleaned = _strip_mem_mesh_tables(_strip_managed_block(existing)).rstrip()
    new_text = (cleaned + "\n\n" if cleaned else "") + block
    _atomic_write_text(config_path, new_text)


def remove_codex_mcp_config(config_path: Path) -> None:
    from app.cli.hooks.json_ops import _atomic_write_text

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


def _event_state_name(event_name: str) -> str:
    """Convert Codex hook event names to their state-table key form."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", event_name).lower()


def _mem_mesh_hook_state_keys(hooks_path: Path) -> Set[str]:
    """Return Codex trust-state keys for mem-mesh handlers in hooks.json."""
    try:
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return set()

    source = str(hooks_path.expanduser().resolve())
    keys: Set[str] = set()
    for event_name, entries in hooks.items():
        if not isinstance(event_name, str) or not isinstance(entries, list):
            continue
        state_event = _event_state_name(event_name)
        for entry_index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            handlers = entry.get("hooks", [])
            if not isinstance(handlers, list):
                continue
            for handler_index, handler in enumerate(handlers):
                if not isinstance(handler, dict):
                    continue
                command = str(handler.get("command", ""))
                if "mem-mesh-" not in command:
                    continue
                keys.add(f"{source}:{state_event}:{entry_index}:{handler_index}")
    return keys


def _recorded_hook_trust_keys(config_path: Path) -> Set[str]:
    """Read hook keys with a recorded Codex trusted_hash from config.toml.

    Codex owns hash calculation and validation. This parser intentionally only
    detects whether a trust record exists; `/hooks` remains the authority for
    deciding whether the recorded hash still matches the current definition.
    """
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()

    recorded: Set[str] = set()
    current_key: Optional[str] = None
    for line in lines:
        table_match = _HOOK_STATE_TABLE.match(line)
        if table_match:
            try:
                current_key = str(json.loads(table_match.group("key")))
            except (json.JSONDecodeError, TypeError):
                current_key = None
            continue
        if line.lstrip().startswith("["):
            current_key = None
            continue
        if current_key and _TRUSTED_HOOK_HASH.match(line):
            recorded.add(current_key)
    return recorded


def codex_hook_trust_record_counts(
    hooks_path: Path, config_path: Path
) -> Tuple[int, int]:
    """Return ``(mem-mesh handlers, handlers with a Codex trust record)``.

    A recorded entry is not proof that its hash is current. Callers must direct
    users to Codex `/hooks` for the authoritative review state after changes.
    """
    expected = _mem_mesh_hook_state_keys(hooks_path)
    recorded = _recorded_hook_trust_keys(config_path)
    return len(expected), len(expected & recorded)
