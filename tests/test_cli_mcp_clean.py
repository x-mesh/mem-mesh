"""Tests for project-scoped MCP override detection + `mem-mesh mcp clean`."""

import glob
import json

import pytest


def _write_claude(tmp_path, *, global_url, projects):
    claude = tmp_path / ".claude.json"
    data = {
        "mcpServers": {"mem-mesh": {"url": global_url, "type": "http"}},
        "projects": projects,
    }
    claude.write_text(json.dumps(data))
    return claude


def test_collect_claude_overrides_flags_diff(monkeypatch, tmp_path):
    import app.cli.hooks.diagnostics as d

    monkeypatch.setenv("HOME", str(tmp_path))
    _write_claude(
        tmp_path,
        global_url="http://localhost:8000/mcp/sse",
        projects={
            str(tmp_path / "a"): {
                "mcpServers": {
                    "mem-mesh": {"url": "https://remote/mcp/sse", "type": "http"}
                }
            },
            str(tmp_path / "b"): {
                "mcpServers": {
                    "mem-mesh": {"url": "http://localhost:8000/mcp/sse", "type": "http"}
                }
            },
            str(tmp_path / "c"): {"mcpServers": {"other": {}}},  # no mem-mesh
        },
    )
    ovs = {o.project_path: o for o in d.collect_claude_overrides()}
    assert len(ovs) == 2  # a, b only
    assert ovs[str(tmp_path / "a")].differs is True
    assert ovs[str(tmp_path / "b")].differs is False
    assert "https://remote" in ovs[str(tmp_path / "a")].summary


def test_collect_claude_overrides_missing_file(monkeypatch, tmp_path):
    import app.cli.hooks.diagnostics as d

    monkeypatch.setenv("HOME", str(tmp_path))  # no ~/.claude.json
    assert d.collect_claude_overrides() == []


def test_cmd_mcp_clean_removes_shadows_keeps_global(monkeypatch, tmp_path, capsys):
    import app.cli.mcp_clean as mc

    monkeypatch.setenv("HOME", str(tmp_path))
    claude = _write_claude(
        tmp_path,
        global_url="http://localhost:8000/mcp/sse",
        projects={
            str(tmp_path / "a"): {
                "mcpServers": {
                    "mem-mesh": {"url": "https://remote/mcp/sse"},
                    "keep": {},
                },
                "history": [1, 2],
            },
            str(tmp_path / "b"): {"otherKey": True},
        },
    )
    monkeypatch.setattr(mc, "CLAUDE_JSON", claude)

    rc = mc.cmd_mcp_clean(yes=True)
    capsys.readouterr()

    assert rc == 0
    after = json.loads(claude.read_text())
    a = after["projects"][str(tmp_path / "a")]
    assert "mem-mesh" not in a["mcpServers"]  # shadow removed
    assert "keep" in a["mcpServers"]  # sibling server preserved
    assert a["history"] == [1, 2]  # unrelated project state preserved
    assert "mem-mesh" in after["mcpServers"]  # global intact
    assert glob.glob(str(tmp_path / ".claude.json.*.bak"))  # backed up first


def test_cmd_mcp_clean_list_only_changes_nothing(monkeypatch, tmp_path, capsys):
    import app.cli.mcp_clean as mc

    monkeypatch.setenv("HOME", str(tmp_path))
    claude = _write_claude(
        tmp_path,
        global_url="http://localhost:8000/mcp/sse",
        projects={
            str(tmp_path / "a"): {
                "mcpServers": {"mem-mesh": {"url": "https://remote/mcp/sse"}}
            }
        },
    )
    monkeypatch.setattr(mc, "CLAUDE_JSON", claude)
    before = claude.read_text()

    rc = mc.cmd_mcp_clean(list_only=True)
    capsys.readouterr()
    assert rc == 0
    assert claude.read_text() == before  # untouched
    assert not glob.glob(str(tmp_path / ".claude.json.*.bak"))  # no backup on list


def test_cmd_mcp_clean_no_overrides(monkeypatch, tmp_path, capsys):
    import app.cli.mcp_clean as mc

    monkeypatch.setenv("HOME", str(tmp_path))
    claude = _write_claude(
        tmp_path, global_url="http://localhost:8000/mcp/sse", projects={}
    )
    monkeypatch.setattr(mc, "CLAUDE_JSON", claude)
    assert mc.cmd_mcp_clean(yes=True) == 0
    assert "No project-scoped overrides" in capsys.readouterr().out


def test_main_routes_mcp_clean(monkeypatch):
    import app.cli.main as main_mod
    import app.cli.mcp_clean as mc

    seen = {}
    monkeypatch.setattr(
        mc,
        "cmd_mcp_clean",
        lambda list_only=False, yes=False, dry_run=False: seen.update(
            list_only=list_only, yes=yes, dry_run=dry_run
        )
        or 0,
    )
    with pytest.raises(SystemExit) as exc:
        main_mod.main(["mcp", "clean", "--dry-run"])
    assert exc.value.code == 0 and seen["dry_run"] is True
