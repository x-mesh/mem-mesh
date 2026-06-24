"""Contracts for the Connect page one-line installer."""

from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.cli.mcp_config import MCP_SERVER_KEY
from app.web.dashboard.route_modules import connect


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/all",
            "root_path": "",
            "scheme": "http",
            "server": ("localhost", 8000),
            "client": ("198.51.100.10", 49152),
            "headers": [(b"host", b"localhost:8000")],
            "app": SimpleNamespace(state=SimpleNamespace()),
        }
    )


def test_all_installer_payload_includes_kiro_and_antigravity() -> None:
    payload = connect._bootstrap_payload(
        target="all",
        url="http://localhost:8000",
        profile="standard",
        mcp_auth_on=False,
        token=None,
    )

    assert {"codex", "claude", "kiro", "antigravity"} <= set(payload["clients"])
    assert payload["rules_installed"] is True

    kiro = payload["clients"]["kiro"]
    assert kiro["mcp_json_path"] == "~/.kiro/settings/mcp.json"
    assert kiro["kiro_hooks_json_path"] == "~/.kiro/settings/hooks.json"
    assert kiro["mcp_json"]["mcpServers"][MCP_SERVER_KEY]["env"] == {
        "MEM_MESH_CLIENT": "kiro"
    }
    assert "auto-create-pin-on-task.kiro.hook" in kiro["kiro_hook_files"]
    assert (
        "pin_add"
        in kiro["kiro_hook_files"]["auto-create-pin-on-task.kiro.hook"]["then"][
            "prompt"
        ]
    )
    assert (
        "session_resume"
        in kiro["kiro_hook_files"]["load-project-context.kiro.hook"]["then"]["prompt"]
    )

    antigravity = payload["clients"]["antigravity"]
    assert antigravity["mcp_json_path"] == "~/.antigravity/mcp.json"
    assert "hooks_dir" not in antigravity
    assert antigravity["mcp_json"]["mcpServers"][MCP_SERVER_KEY]["env"] == {
        "MEM_MESH_CLIENT": "antigravity"
    }


def test_connect_installer_accepts_kiro_and_antigravity_targets() -> None:
    kiro_script = connect.build_install_script(_request(), target="kiro")
    antigravity_script = connect.build_install_script(_request(), target="antigravity")

    assert "merge_kiro_hooks_json" in kiro_script
    assert "write_hook_files" in kiro_script
    assert "hook rules: session_resume" in kiro_script
    assert "mem-mesh client install complete" in antigravity_script
    assert "hook rules: not installed for this MCP-only target" in antigravity_script


@pytest.mark.asyncio
async def test_connect_hooks_http_bakes_revealed_token(monkeypatch) -> None:
    monkeypatch.setattr(connect, "resolve_hook_token", lambda: "route-http-token")
    monkeypatch.setattr(connect, "_can_reveal", lambda request: True)

    result = await connect.connect_hooks(
        _request(),
        Response(),
        client="claude",
        mode="http",
        server_url="http://localhost:8000",
    )

    hook = result["settings"]["hooks"]["SessionStart"][0]["hooks"][0]
    assert hook["type"] == "http"
    assert hook["headers"]["Authorization"] == "Bearer route-http-token"
    assert "literal Authorization header" in result["note"]


@pytest.mark.asyncio
async def test_connect_hooks_http_omits_unrevealed_token(monkeypatch) -> None:
    monkeypatch.setattr(connect, "resolve_hook_token", lambda: "hidden-token")
    monkeypatch.setattr(connect, "_can_reveal", lambda request: False)

    result = await connect.connect_hooks(
        _request(),
        Response(),
        client="claude",
        mode="http",
        server_url="http://localhost:8000",
    )

    hook = result["settings"]["hooks"]["SessionStart"][0]["hooks"][0]
    assert "headers" not in hook
    assert result["hook_token"] is None
    assert result["hook_token_masked"].endswith("oken")
