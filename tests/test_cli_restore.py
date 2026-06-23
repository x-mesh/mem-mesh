"""Tests for `mem-mesh restore` — backup discovery, target derivation, and the
reversible restore (current file is backed up before being overwritten).
"""

import glob
import json

from app.cli import restore


def test_target_for_strips_timestamp_and_plain_bak(tmp_path):
    ts = tmp_path / "mcp.json.20260101_120000.bak"
    assert restore._target_for(ts) == tmp_path / "mcp.json"
    plain = tmp_path / "settings.json.bak"
    assert restore._target_for(plain) == tmp_path / "settings.json"
    assert restore._target_for(tmp_path / "not-a-backup.txt") is None


def test_backups_for_newest_first_includes_malformed(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text("{}")
    (tmp_path / "mcp.json.20260101_120000.bak").write_text("a")
    (tmp_path / "mcp.json.20260301_090000.bak").write_text("b")
    (tmp_path / "mcp.json.bak").write_text("malformed")  # untimestamped
    backups = restore._backups_for(cfg)
    names = [b.name for b in backups]
    # newest timestamp first, untimestamped malformed last
    assert names[0] == "mcp.json.20260301_090000.bak"
    assert names[1] == "mcp.json.20260101_120000.bak"
    assert names[-1] == "mcp.json.bak"


def test_restore_from_backup_is_reversible(tmp_path, capsys):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"v": "current"}))
    bak = tmp_path / "mcp.json.20260101_120000.bak"
    bak.write_text(json.dumps({"v": "old-good"}))

    rc = restore.cmd_restore(from_backup=str(bak), yes=True)
    capsys.readouterr()

    assert rc == 0
    assert json.loads(cfg.read_text()) == {"v": "old-good"}  # restored
    # the previous "current" content was snapshotted before overwrite
    safety = [
        p
        for p in glob.glob(str(tmp_path / "mcp.json.*.bak"))
        if "20260101_120000" not in p
    ]
    assert len(safety) == 1
    assert json.loads(open(safety[0]).read()) == {"v": "current"}


def test_restore_from_missing_backup_errors(tmp_path, capsys):
    rc = restore.cmd_restore(from_backup=str(tmp_path / "nope.json.bak"), yes=True)
    capsys.readouterr()
    assert rc == 1


def test_restore_list(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "mcp.json"
    cfg.write_text("{}")
    (tmp_path / "mcp.json.20260101_120000.bak").write_text("a")
    monkeypatch.setattr(restore, "_candidate_files", lambda: [("Cursor (MCP)", cfg)])

    rc = restore.cmd_restore(list_only=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Cursor (MCP)" in out
    assert "2026-01-01 12:00:00" in out  # human-formatted timestamp


def test_restore_no_backups(monkeypatch, tmp_path, capsys):
    empty = tmp_path / "mcp.json"
    empty.write_text("{}")
    monkeypatch.setattr(restore, "_candidate_files", lambda: [("X", empty)])
    rc = restore.cmd_restore()
    out = capsys.readouterr().out
    assert rc == 0 and "No backups found" in out


def test_main_routes_restore(monkeypatch):
    import app.cli.main as main_mod

    seen = {}

    def _fake(list_only=False, from_backup=None, yes=False):
        seen.update(list_only=list_only, from_backup=from_backup, yes=yes)
        return 0

    monkeypatch.setattr(restore, "cmd_restore", _fake)
    import pytest

    with pytest.raises(SystemExit) as exc:
        main_mod.main(["restore", "--from", "/x.json.bak", "-y"])
    assert exc.value.code == 0
    assert seen["from_backup"] == "/x.json.bak" and seen["yes"] is True
