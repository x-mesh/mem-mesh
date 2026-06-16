"""Contracts for the Connect page one-line installer."""

from types import SimpleNamespace

from starlette.requests import Request

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
