"""Tests for the CLI diagnostics surfaces: probe_api 3-state, shared collectors,
masking, the uvx-overwrite guard, mcp verify, and the top-level doctor.
"""

import http.server
import json
import threading
from pathlib import Path

import pytest

from app.cli.hooks import diagnostics, render
from app.cli.hooks.status import ApiProbe, check_connectivity, probe_api
from app.core.redaction import mask_secret


@pytest.fixture(autouse=True)
def _isolate_materialized_mem_mesh_files(monkeypatch, tmp_path):
    """Keep CLI materialization tests away from the real ~/.mem-mesh files."""
    from app.cli import install_hooks
    from app.core import config as core_config

    mem_dir = tmp_path / ".mem-mesh"
    monkeypatch.setattr(install_hooks, "API_URL_FILE", mem_dir / "api_url")
    monkeypatch.setattr(install_hooks, "HOOK_TOKEN_FILE", mem_dir / "hook_token")
    monkeypatch.setattr(core_config, "HOOK_TOKEN_FILE", mem_dir / "hook_token")


# ── local HTTP server fixture (returns a fixed status on /health) ──


def _serve_status(code: int):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(code)
            self.end_headers()
            self.wfile.write(b"ok" if code < 400 else b"nope")

        def log_message(self, *a):  # silence
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


# ── mask_secret (single masker) ──


def test_mask_secret_tail_only_no_leading_leak():
    tok = "5-jWabcdefghTESTq7JY"
    masked = mask_secret(tok)
    assert masked == "••••••••q7JY"
    assert not masked.startswith("5-jW")  # leading secret never shown
    assert tok[:4] not in masked


def test_mask_secret_edge_cases():
    assert mask_secret("") == ""
    assert mask_secret(None) == ""
    assert mask_secret("ab") == "••"  # shorter than reveal window


def test_mask_secret_unified_across_surfaces():
    from app.cli.hooks.doctor import _mask_token
    from app.web.dashboard.route_modules.security import _mask

    tok = "abcdEFGH1234wxyz"
    assert (
        mask_secret(tok)
        == _mask_token(tok)
        == _mask(tok)
        == diagnostics.mask_secret(tok)
    )


# ── probe_api 3-state + check_connectivity backward-compat ──


def test_probe_api_ok():
    srv, url = _serve_status(200)
    try:
        p = probe_api(url, timeout=3)
        assert p.state == "ok" and p.ok and p.alive and not p.auth_required
        assert p.status == 200
    finally:
        srv.shutdown()


@pytest.mark.parametrize("code", [401, 403, 407])
def test_probe_api_auth_required(code):
    srv, url = _serve_status(code)
    try:
        p = probe_api(url, timeout=3)
        assert p.state == "auth_required"
        assert p.alive and p.auth_required and not p.ok
        assert p.status == code
    finally:
        srv.shutdown()


def test_probe_api_unreachable():
    p = probe_api("http://127.0.0.1:59997", timeout=2)
    assert p.state == "unreachable"
    assert not p.alive and not p.ok and not p.auth_required


def test_check_connectivity_backward_compat():
    srv, url = _serve_status(200)
    try:
        ok, msg = check_connectivity(url, timeout=3)
        assert ok is True and "reachable" in msg
    finally:
        srv.shutdown()
    # 401 stays (False, "HTTP 401") for legacy callers
    srv, url = _serve_status(401)
    try:
        ok, msg = check_connectivity(url, timeout=3)
        assert ok is False and msg == "HTTP 401"
    finally:
        srv.shutdown()
    ok, msg = check_connectivity("http://127.0.0.1:59997", timeout=2)
    assert ok is False and msg.startswith("unreachable")


# ── _classify_mode ──


def test_classify_mode():
    cm = diagnostics._classify_mode
    assert cm({"url": "https://x/mcp/sse", "type": "http"}) == "http"
    assert cm({"command": "uvx", "args": ["--from", "mem-mesh[server]"]}) == "uvx"
    assert (
        cm({"command": "/usr/bin/python", "args": ["-m", "app.mcp_stdio"]}) == "stdio"
    )
    assert cm(None) is None
    assert cm({}) is None


# ── collect_token_status ──


def test_collect_token_status_env_first(monkeypatch, tmp_path):
    """CLI diagnostics report the client-effective token: env first, file fallback."""
    from app.core import config as core_config

    token_file = tmp_path / "hook_token"
    token_file.write_text("filetoken", encoding="utf-8")
    monkeypatch.setattr(core_config, "HOOK_TOKEN_FILE", token_file)
    monkeypatch.setenv("MEM_MESH_HOOK_TOKEN", "supersecrettoken")
    t = diagnostics.collect_token_status()
    assert t.source == "env" and t.present
    assert t.in_shell_env
    assert t.masked.endswith("oken") and "super" not in t.masked


def test_collect_token_status_file_fallback(monkeypatch, tmp_path):
    from app.core import config as core_config

    token_file = tmp_path / "hook_token"
    token_file.write_text("materializedtoken", encoding="utf-8")
    monkeypatch.setattr(core_config, "HOOK_TOKEN_FILE", token_file)
    monkeypatch.delenv("MEM_MESH_HOOK_TOKEN", raising=False)
    t = diagnostics.collect_token_status()
    assert t.source == "materialized_file" and t.present
    assert not t.in_shell_env
    assert t.masked.endswith("oken") and "mater" not in t.masked


def test_collect_token_status_none(monkeypatch, tmp_path):
    from app.core import config as core_config

    monkeypatch.setattr(core_config, "HOOK_TOKEN_FILE", tmp_path / "absent")
    monkeypatch.delenv("MEM_MESH_HOOK_TOKEN", raising=False)
    t = diagnostics.collect_token_status()
    assert t.source == "none" and not t.present and t.masked == ""


def test_hooks_doctor_client_hook_token_prefers_env(monkeypatch, tmp_path):
    from app.cli.hooks import doctor
    from app.core import config as core_config

    token_file = tmp_path / "hook_token"
    token_file.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setattr(core_config, "HOOK_TOKEN_FILE", token_file)
    monkeypatch.setenv("MEM_MESH_HOOK_TOKEN", "env-token")

    assert doctor._client_hook_token() == "env-token"


def test_hooks_doctor_client_hook_token_uses_file(monkeypatch, tmp_path):
    from app.cli.hooks import doctor
    from app.core import config as core_config

    token_file = tmp_path / "hook_token"
    token_file.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setattr(core_config, "HOOK_TOKEN_FILE", token_file)
    monkeypatch.delenv("MEM_MESH_HOOK_TOKEN", raising=False)

    assert doctor._client_hook_token() == "file-token"


def test_hooks_doctor_client_hook_token_none(monkeypatch, tmp_path):
    from app.cli.hooks import doctor
    from app.core import config as core_config

    monkeypatch.setattr(core_config, "HOOK_TOKEN_FILE", tmp_path / "missing")
    monkeypatch.delenv("MEM_MESH_HOOK_TOKEN", raising=False)

    assert doctor._client_hook_token() == ""


# ── uvx-overwrite guard (the #4 footgun) ──


def _fake_tool(config_path: Path, key="cursor", name="FakeTool"):
    return {
        "name": name,
        "key": key,
        "config_path": config_path,
        "detect": lambda: True,
        "installed": True,
        "has_config": config_path.exists(),
    }


def test_yes_unreachable_does_not_flip_existing_http_to_uvx(
    monkeypatch, tmp_path, capsys
):
    # The footgun: server unreachable so the global auto-pick is uvx, but an
    # existing http entry must NOT be flipped to a local uvx backend.
    import app.cli.mcp_config as m

    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mem-mesh": {"url": "https://remote/mcp/sse", "type": "http"}
                }
            }
        )
    )
    monkeypatch.setattr(m, "detect_tools", lambda: [_fake_tool(cfg)])
    monkeypatch.setattr(m, "has_uvx", lambda: True)
    monkeypatch.setattr(m, "verify_tool_config", lambda t, url="": (True, "ok"))

    m.run_mcp_setup(
        url="http://localhost:8000",
        yes=True,
        preferred_mode=None,
        server_reachable=False,
    )
    capsys.readouterr()
    after = json.loads(cfg.read_text())["mcpServers"]["mem-mesh"]
    assert "command" not in after  # never flipped to a uvx command entry
    assert "url" in after  # stays on the http backend


def test_yes_unreachable_does_not_flip_existing_codex_http_to_uvx(
    monkeypatch, tmp_path, capsys
):
    import app.cli.mcp_config as m

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "\n".join(
            [
                "[mcp_servers.mem-mesh]",
                'url = "https://remote/mcp/sse"',
                'default_tools_approval_mode = "prompt"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(m, "detect_tools", lambda: [_fake_tool(cfg, "codex", "Codex")])
    monkeypatch.setattr(m, "has_uvx", lambda: True)
    monkeypatch.setattr(m, "verify_tool_config", lambda t, url="": (True, "ok"))

    m.run_mcp_setup(
        url="https://remote",
        yes=True,
        preferred_mode=None,
        server_reachable=False,
    )
    capsys.readouterr()
    text = cfg.read_text(encoding="utf-8")
    assert 'url = "https://remote/mcp/sse"' in text
    assert 'command = "uvx"' not in text
    assert "[mcp_servers.mem-mesh.tools.add]" in text
    assert 'approval_mode = "approve"' in text


def test_yes_repairs_same_transport_misconfig(monkeypatch, tmp_path, capsys):
    # A legacy http entry (transport:sse) MUST be repaired non-interactively —
    # the guard only blocks backend flips, not same-transport fixes.
    import app.cli.mcp_config as m

    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mem-mesh": {"url": "https://remote/mcp/sse", "transport": "sse"}
                }
            }
        )
    )
    monkeypatch.setattr(m, "detect_tools", lambda: [_fake_tool(cfg)])
    monkeypatch.setattr(m, "has_uvx", lambda: True)
    monkeypatch.setattr(m, "verify_tool_config", lambda t, url="": (True, "ok"))

    m.run_mcp_setup(
        url="https://remote", yes=True, preferred_mode=None, server_reachable=True
    )
    capsys.readouterr()
    after = json.loads(cfg.read_text())["mcpServers"]["mem-mesh"]
    assert "transport" not in after  # legacy key removed
    assert after.get("type") == "http"  # corrected to type
    assert "command" not in after  # still http, not flipped


def test_yes_uvx_fallback_for_new_tool_when_unreachable(monkeypatch, tmp_path, capsys):
    import app.cli.mcp_config as m

    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {}}))
    monkeypatch.setattr(m, "detect_tools", lambda: [_fake_tool(cfg)])
    monkeypatch.setattr(m, "has_uvx", lambda: True)
    monkeypatch.setattr(m, "verify_tool_config", lambda t, url="": (True, "ok"))

    summary = m.run_mcp_setup(
        url="http://localhost:8000",
        yes=True,
        preferred_mode=None,
        server_reachable=False,
    )
    capsys.readouterr()
    entry = json.loads(cfg.read_text())["mcpServers"]["mem-mesh"]
    assert summary["mode"] == "uvx"
    assert entry["command"] == "uvx"


# ── mcp verify exit code ──


def test_cmd_mcp_verify_exit_codes(monkeypatch, capsys):
    from app.cli import mcp_verify
    from app.cli.hooks.diagnostics import McpToolStatus

    def _ok_tools(url):
        return [
            McpToolStatus(
                "Cursor",
                "cursor",
                "/p",
                True,
                True,
                True,
                "http",
                {"url": "x"},
                True,
                "ok",
            ),
        ]

    monkeypatch.setattr(mcp_verify, "collect_mcp_status", _ok_tools)
    assert mcp_verify.cmd_mcp_verify(url="http://x") == 0
    capsys.readouterr()

    def _bad_tools(url):
        return [
            McpToolStatus(
                "Kiro",
                "kiro",
                "/p",
                True,
                True,
                True,
                "http",
                {"url": "x"},
                False,
                "broken",
            ),
        ]

    monkeypatch.setattr(mcp_verify, "collect_mcp_status", _bad_tools)
    assert mcp_verify.cmd_mcp_verify(url="http://x") == 1
    capsys.readouterr()


# ── doctor: 401 vs network distinction ──


def test_doctor_api_section_distinguishes_auth_from_network(monkeypatch, capsys):
    from app.cli import system_doctor

    issues = []
    monkeypatch.setattr(
        system_doctor,
        "probe_api",
        lambda url, timeout=5: ApiProbe("auth_required", 401, "alive but auth (401)"),
    )
    system_doctor._render_api("http://x", "test", issues)
    out = capsys.readouterr().out
    assert "auth gate, not a network error" in out
    assert any("requires authentication" in i for i in issues)

    issues2 = []
    monkeypatch.setattr(
        system_doctor,
        "probe_api",
        lambda url, timeout=5: ApiProbe("unreachable", None, "unreachable: refused"),
    )
    system_doctor._render_api("http://x", "test", issues2)
    out2 = capsys.readouterr().out
    assert "start the server" in out2
    assert any("unreachable" in i for i in issues2)


def test_doctor_conflicts_flags_tool_literal_drift(monkeypatch, capsys):
    """A stale generated literal is drift when it differs from the env SSOT."""
    from app.cli import system_doctor
    from app.cli.hooks.diagnostics import McpToolStatus

    monkeypatch.setenv("MEM_MESH_API_URL", "http://localhost:8000")
    monkeypatch.setenv("MEM_MESH_HOOK_TOKEN", "tok-NEW")
    monkeypatch.delenv("API_URL", raising=False)
    monkeypatch.setattr(
        system_doctor, "_read_config_file_url", lambda: "http://localhost:8000"
    )
    monkeypatch.setattr(system_doctor, "_materialized_hook_token", lambda: "tok-NEW")
    monkeypatch.setattr(system_doctor, "_server_private_hook_token", lambda: "tok-OLD")

    stale = McpToolStatus(
        "Cursor",
        "cursor",
        "/p",
        True,
        True,
        True,
        "http",
        {
            "url": "http://localhost:8000/mcp/sse",
            "type": "http",
            "headers": {"Authorization": "Bearer tok-OLD"},
        },
        True,
        "ok",
        (1, 2),
    )
    monkeypatch.setattr(system_doctor, "collect_mcp_status", lambda url: [stale])

    issues = []
    system_doctor._render_conflicts("http://localhost:8000", issues)
    out = capsys.readouterr().out
    assert "drift:" in out
    assert "stale" in out and "Cursor" in out
    assert "MEM_MESH_HOOK_TOKEN env" in out
    assert "/tmp/data/hook_token" not in out
    assert any("config drift" in i for i in issues)


def test_doctor_conflicts_clean_when_tools_match_effective_env(monkeypatch, capsys):
    """Clean state: generated literals match the env-first effective config."""
    from app.cli import system_doctor
    from app.cli.hooks.diagnostics import McpToolStatus

    monkeypatch.setenv("MEM_MESH_API_URL", "http://localhost:8000")
    monkeypatch.setenv("MEM_MESH_HOOK_TOKEN", "tok-MATCH")
    monkeypatch.delenv("API_URL", raising=False)
    monkeypatch.setattr(
        system_doctor, "_read_config_file_url", lambda: "http://localhost:8000"
    )
    monkeypatch.setattr(system_doctor, "_materialized_hook_token", lambda: "tok-MATCH")
    monkeypatch.setattr(system_doctor, "_server_private_hook_token", lambda: "old-data")

    aligned = McpToolStatus(
        "Cursor",
        "cursor",
        "/p",
        True,
        True,
        True,
        "http",
        {
            "url": "http://localhost:8000/mcp/sse",
            "type": "http",
            "headers": {"Authorization": "Bearer tok-MATCH"},
        },
        True,
        "ok",
        (1, 2),
    )
    monkeypatch.setattr(system_doctor, "collect_mcp_status", lambda url: [aligned])

    issues = []
    system_doctor._render_conflicts("http://localhost:8000", issues)
    out = capsys.readouterr().out
    assert "generated configs match the env-first effective config" in out
    assert "drift:" not in out
    assert issues == []


def test_doctor_ssot_shows_values_and_source(monkeypatch, capsys):
    """[SSOT] prints env as canonical and ~/.mem-mesh as materialized state."""
    from app.cli import system_doctor

    monkeypatch.setenv("MEM_MESH_API_URL", "http://localhost:8000")
    monkeypatch.setenv("MEM_MESH_HOOK_TOKEN", "5-jWabcdefghTESTq7JY")
    monkeypatch.delenv("API_URL", raising=False)
    monkeypatch.setattr(
        system_doctor, "_read_config_file_url", lambda: "http://localhost:8000"
    )
    monkeypatch.setattr(
        system_doctor, "_materialized_hook_token", lambda: "5-jWabcdefghTESTq7JY"
    )
    monkeypatch.setattr(system_doctor, "_server_private_hook_token", lambda: "old-data")
    monkeypatch.setattr(
        system_doctor,
        "_server_private_hook_token_source",
        lambda: "/tmp/data/hook_token",
    )

    issues = []
    system_doctor._render_ssot(issues)
    out = capsys.readouterr().out
    assert "[SSOT]" in out
    assert "http://localhost:8000" in out
    assert "MEM_MESH_API_URL env SSOT" in out
    assert "MEM_MESH_HOOK_TOKEN env SSOT" in out
    assert "~/.mem-mesh/api_url in sync" in out
    assert "~/.mem-mesh/hook_token in sync" in out
    assert "/tmp/data/hook_token" in out
    assert "q7JY" in out and "TEST" not in out  # token masked, tail only


def test_doctor_ssot_file_fallback_does_not_claim_in_sync(monkeypatch, capsys):
    """Fallback-only ~/.mem-mesh files are usable, but not an env sync state."""
    from app.cli import system_doctor

    monkeypatch.delenv("MEM_MESH_API_URL", raising=False)
    monkeypatch.delenv("API_URL", raising=False)
    monkeypatch.delenv("MEM_MESH_HOOK_TOKEN", raising=False)
    monkeypatch.setattr(
        system_doctor, "_read_config_file_url", lambda: "http://localhost:8000"
    )
    monkeypatch.setattr(system_doctor, "_materialized_hook_token", lambda: "file-token")
    monkeypatch.setattr(system_doctor, "_server_private_hook_token", lambda: None)

    issues = []
    system_doctor._render_ssot(issues)
    out = capsys.readouterr().out

    assert "(~/.mem-mesh fallback)" in out
    assert "~/.mem-mesh/api_url in sync" not in out
    assert "~/.mem-mesh/hook_token in sync" not in out
    assert "~/.mem-mesh/api_url missing" not in out
    assert "~/.mem-mesh/hook_token missing" not in out


def test_doctor_ssot_unset_does_not_duplicate_missing(monkeypatch, capsys):
    from app.cli import system_doctor

    monkeypatch.delenv("MEM_MESH_API_URL", raising=False)
    monkeypatch.delenv("API_URL", raising=False)
    monkeypatch.delenv("MEM_MESH_HOOK_TOKEN", raising=False)
    monkeypatch.setattr(system_doctor, "_read_config_file_url", lambda: None)
    monkeypatch.setattr(system_doctor, "_materialized_hook_token", lambda: None)
    monkeypatch.setattr(system_doctor, "_server_private_hook_token", lambda: None)

    issues = []
    system_doctor._render_ssot(issues)
    out = capsys.readouterr().out

    assert "api_url      not set" in out
    assert "hook_token   not set" in out
    assert "~/.mem-mesh/api_url missing" not in out
    assert "~/.mem-mesh/hook_token missing" not in out


# ── render fallback when rich is unavailable ──


def test_render_json_block_plain_fallback(monkeypatch, capsys):
    # NO_COLOR forces the plain numbered-line path (no rich).
    monkeypatch.setenv("NO_COLOR", "1")
    render.render_json_block('{\n  "a": 1\n}')
    out = capsys.readouterr().out
    assert "1 | {" in out
    assert '2 |   "a": 1' in out


# ── real file:line location for verbose rendering ──


def test_locate_entry_json(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        '{\n  "mcpServers": {\n    "other": {},\n    "mem-mesh": {\n'
        '      "url": "x"\n    }\n  }\n}\n'
    )
    # "mem-mesh": { opens on line 4, closing } on line 6.
    assert diagnostics._locate_entry(cfg) == (4, 6)


def test_locate_entry_codex_skips_project_path_false_match(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[projects."/x/mem-mesh"]\n'  # line 1: contains "mem-mesh" but is NOT the MCP table
        "trust = 1\n"
        "\n"
        "[mcp_servers.mem-mesh]\n"  # line 4: the real entry
        'url = "x"\n'
        "\n"
        "[mcp_servers.mem-mesh.tools.add]\n"  # line 7: sub-table, still ours
        "approve = 1\n"
        "\n"
        "[other]\n"  # line 10: foreign table ends the span
        "z = 1\n"
    )
    span = diagnostics._locate_entry(cfg, is_codex=True)
    assert span is not None
    assert span[0] == 4  # starts at [mcp_servers.mem-mesh], not the projects line
    assert span[1] >= 7  # includes the .tools.add sub-table


def test_render_entry_source_uses_real_file_lines(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")  # plain numbered-line path
    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        '{\n  "mcpServers": {\n    "mem-mesh": {\n      "url": "x"\n    }\n  }\n}\n'
    )
    render.render_entry_source(str(cfg), (3, 5), '{"fallback": true}')
    out = capsys.readouterr().out
    assert f"{cfg}:3" in out  # clickable real path:line header
    assert "3 |" in out and '"mem-mesh"' in out  # real line number, not 1
    assert "fallback" not in out  # rendered the real file, not the fallback


def test_render_entry_source_falls_back_when_no_lines(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    render.render_entry_source("/nonexistent.json", None, '{"x": 1}')
    out = capsys.readouterr().out
    assert "1 |" in out and '"x": 1' in out  # fallback numbered-from-1 block


# ── config backups (fix 1 + 2) ──


def test_timestamped_backup_preserves_extension(tmp_path):
    from app.cli.hooks.json_ops import timestamped_backup

    f = tmp_path / ".claude.json"
    f.write_text("{}")
    b = timestamped_backup(f)
    assert b is not None
    assert b.name.startswith(".claude.json.") and b.name.endswith(".bak")
    assert timestamped_backup(tmp_path / "missing.json") is None


def test_merge_json_settings_backs_up_on_change_and_skips_noop(tmp_path):
    import glob

    from app.cli.hooks.json_ops import _merge_json_settings

    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"hooks": {"Stop": []}, "other": 1}, indent=2))
    patch = {
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mem-mesh-x"}]}]}
    }

    _merge_json_settings(s, patch)
    baks = glob.glob(str(tmp_path / "settings.json.*.bak"))
    assert len(baks) == 1  # backed up before the change

    _merge_json_settings(s, patch)  # identical merge → no write, no new backup
    assert len(glob.glob(str(tmp_path / "settings.json.*.bak"))) == 1


# ── MCP entry auth header + db-path propagation (fix 3 + 4) ──


def test_generate_mcp_entry_with_auth_header():
    from app.cli.mcp_config import generate_mcp_entry

    # Generated MCP config stamps the literal token; GUI clients do not need to
    # inherit MEM_MESH_HOOK_TOKEN at runtime.
    e = generate_mcp_entry(
        "http", url="https://x", tool_key="cursor", with_auth=True, token="real-tok-123"
    )
    assert e["headers"]["Authorization"] == "Bearer real-tok-123"
    assert "${" not in e["headers"]["Authorization"]
    # with_auth but no token → header omitted (caller warns)
    assert "headers" not in generate_mcp_entry("http", url="https://x", with_auth=True)
    # without auth → no header at all
    assert "headers" not in generate_mcp_entry("http", url="https://x", with_auth=False)


def test_generate_mcp_entry_propagates_explicit_db_path(monkeypatch):
    from app.cli.mcp_config import generate_mcp_entry

    monkeypatch.setenv("MEM_MESH_DATABASE_PATH", "/tmp/mydb.db")
    e = generate_mcp_entry("uvx", tool_key="cursor")
    assert e["env"]["MEM_MESH_DATABASE_PATH"] == "/tmp/mydb.db"
    # http is a remote backend — never gets the local DB path
    eh = generate_mcp_entry("http", url="https://x", tool_key="cursor")
    assert "MEM_MESH_DATABASE_PATH" not in (eh.get("env") or {})


def test_generate_mcp_entry_no_db_path_when_unset(monkeypatch):
    from app.cli.mcp_config import generate_mcp_entry

    monkeypatch.delenv("MEM_MESH_DATABASE_PATH", raising=False)
    e = generate_mcp_entry("stdio", tool_key="cursor")
    assert "MEM_MESH_DATABASE_PATH" not in (e.get("env") or {})  # never guessed


def test_ensure_hook_token_materializes_env_and_ignores_server_data_dir(
    monkeypatch, tmp_path
):
    # The .sh hooks read ~/.mem-mesh/hook_token directly. The CLI materializes the
    # operator env token there and must not copy server-private data-dir state.
    import app.cli.install_hooks as ih
    from app.core import config as cc

    materialized = tmp_path / "hook_token"
    monkeypatch.setattr(ih, "HOOK_TOKEN_FILE", materialized)
    monkeypatch.setattr(cc, "resolve_hook_token", lambda: "SERVER-DATADIR-TOKEN")
    monkeypatch.setattr(cc, "_read_token_file", lambda p: None)
    monkeypatch.setenv("MEM_MESH_HOOK_TOKEN", "ENV-TOKEN")

    tok = ih._ensure_hook_token()
    assert tok == "ENV-TOKEN"
    assert materialized.read_text().strip() == "ENV-TOKEN"


def test_doctor_flags_missing_mcp_auth_token(monkeypatch, capsys):
    from app.cli import system_doctor as sd
    from app.cli.hooks.diagnostics import McpToolStatus

    http_no_auth = McpToolStatus(
        "Cursor",
        "cursor",
        "/p",
        True,
        True,
        True,
        "http",
        {"url": "x", "type": "http"},
        True,
        "ok",
        (1, 2),
    )
    monkeypatch.setattr(sd, "collect_mcp_status", lambda url: [http_no_auth])
    issues = []
    sd._render_mcp("http://x", False, issues, mcp_auth_required=True)
    capsys.readouterr()
    assert any("no token" in i for i in issues)

    # With a literal token header present, no missing-token flag.
    monkeypatch.setattr(sd, "_effective_hook_token", lambda: None)
    monkeypatch.setattr(sd, "_effective_hook_token_source", lambda: None)
    http_auth = McpToolStatus(
        "Cursor",
        "cursor",
        "/p",
        True,
        True,
        True,
        "http",
        {"url": "x", "headers": {"Authorization": "Bearer real-tok-123"}},
        True,
        "ok",
        (1, 2),
    )
    monkeypatch.setattr(sd, "collect_mcp_status", lambda url: [http_auth])
    issues2 = []
    sd._render_mcp("http://x", False, issues2, mcp_auth_required=True)
    capsys.readouterr()
    assert not any("no token" in i for i in issues2)


# ── doctor helpers: env-first effective token + baked-literal extraction ──


def test_effective_hook_token_prefers_env(monkeypatch):
    from app.cli import system_doctor

    monkeypatch.setenv("MEM_MESH_HOOK_TOKEN", "ENV-CANONICAL")
    monkeypatch.setattr(system_doctor, "_materialized_hook_token", lambda: "FILE")
    assert system_doctor._effective_hook_token() == "ENV-CANONICAL"
    assert system_doctor._effective_hook_token_source() == "MEM_MESH_HOOK_TOKEN env"


def test_effective_hook_token_falls_back_to_materialized_file(monkeypatch):
    from app.cli import system_doctor

    monkeypatch.delenv("MEM_MESH_HOOK_TOKEN", raising=False)
    monkeypatch.setattr(system_doctor, "_materialized_hook_token", lambda: "FILE")
    assert system_doctor._effective_hook_token() == "FILE"
    assert system_doctor._effective_hook_token_source()


def test_server_private_hook_token_is_not_effective(monkeypatch):
    from app.cli import system_doctor

    monkeypatch.delenv("MEM_MESH_HOOK_TOKEN", raising=False)
    monkeypatch.setattr(system_doctor, "_materialized_hook_token", lambda: None)
    monkeypatch.setattr(system_doctor, "_server_private_hook_token", lambda: "DATA")
    assert system_doctor._effective_hook_token() is None


def test_entry_literal_token_extracts_baked_literal():
    """Generated MCP config bakes a literal Bearer token; env refs are stale."""
    from app.cli.system_doctor import _entry_literal_token

    assert (
        _entry_literal_token({"headers": {"Authorization": "Bearer real-tok-123"}})
        == "real-tok-123"
    )
    # a ${ENV} reference is NOT a literal (env reliance was removed)
    assert (
        _entry_literal_token(
            {"headers": {"Authorization": "Bearer ${MEM_MESH_HOOK_TOKEN}"}}
        )
        is None
    )
    # absent / non-bearer / empty all yield None
    assert _entry_literal_token(None) is None
    assert _entry_literal_token({}) is None
    assert _entry_literal_token({"headers": {"Authorization": "Basic xyz"}}) is None
    assert _entry_literal_token({"headers": {"Authorization": "Bearer "}}) is None


# ── CLI routing: new subcommands are wired into main.py ──


def test_main_routes_doctor(monkeypatch):
    import app.cli.main as main_mod
    import app.cli.system_doctor as sd

    seen = {}

    def _fake_doctor(verbose=False):
        seen["v"] = verbose
        return 0

    monkeypatch.setattr(sd, "cmd_system_doctor", _fake_doctor)
    with pytest.raises(SystemExit) as exc:
        main_mod.main(["doctor", "-v"])
    assert exc.value.code == 0 and seen["v"] is True


def test_main_routes_mcp_verify(monkeypatch):
    import app.cli.main as main_mod
    import app.cli.mcp_verify as mv

    seen = {}
    monkeypatch.setattr(
        mv,
        "cmd_mcp_verify",
        lambda url, verbose=False: seen.update(url=url, verbose=verbose) or 1,
    )
    with pytest.raises(SystemExit) as exc:
        main_mod.main(["mcp", "verify", "--url", "http://x:8000"])
    assert exc.value.code == 1 and seen["url"] == "http://x:8000"


def test_hooks_setup_token_no_longer_routed():
    """The old file->shell-env bridge is gone, so argparse rejects the subcommand."""
    import app.cli.main as main_mod

    with pytest.raises(SystemExit) as exc:
        main_mod.main(["hooks", "setup-token", "--print", "--no-test"])
    assert exc.value.code != 0  # argparse: invalid choice 'setup-token'


def test_doctor_mcp_flags_url_split(monkeypatch, capsys):
    """[MCP] warns when an entry's host differs from the hook [API] host."""
    from types import SimpleNamespace

    from app.cli import system_doctor

    fake = SimpleNamespace(
        installed=True,
        configured=True,
        verified=True,
        mode="http",
        verify_message="configured (HTTP, server reachable)",
        name="Claude Code",
        config_path="/x",
        entry_lines=None,
        entry={"url": "https://meme.24x365.online/mcp/sse", "type": "http"},
    )
    monkeypatch.setattr(system_doctor, "collect_mcp_status", lambda url: [fake])

    issues = []
    system_doctor._render_mcp("http://localhost:8000", False, issues)
    out = capsys.readouterr().out
    assert "URL split" in out
    assert "meme.24x365.online" in out and "localhost" in out
    assert any("URL split" in i for i in issues)


def test_doctor_mcp_no_split_when_aligned(monkeypatch, capsys):
    """No split warning when the MCP entry host matches the hook host."""
    from types import SimpleNamespace

    from app.cli import system_doctor

    fake = SimpleNamespace(
        installed=True,
        configured=True,
        verified=True,
        mode="http",
        verify_message="ok",
        name="Claude Code",
        config_path="/x",
        entry_lines=None,
        entry={"url": "http://localhost:8000/mcp/sse", "type": "http"},
    )
    monkeypatch.setattr(system_doctor, "collect_mcp_status", lambda url: [fake])

    issues = []
    system_doctor._render_mcp("http://localhost:8000", False, issues)
    out = capsys.readouterr().out
    assert "URL split" not in out
    assert issues == []
