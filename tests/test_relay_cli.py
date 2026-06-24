"""Relay CLI dispatch tests."""

import pytest

from app.cli.main import main


def test_main_dispatches_relay_worker_once_json(monkeypatch):
    calls = {}

    def fake_cmd(**kwargs):
        calls.update(kwargs)
        return 0

    import app.cli.relay as relay_cli

    monkeypatch.setattr(relay_cli, "cmd_relay_worker", fake_cmd)

    with pytest.raises(SystemExit) as exc:
        main(["relay", "worker", "--once", "--json", "--tasks", "outbox,item"])

    assert exc.value.code == 0
    assert calls["once"] is True
    assert calls["json_mode"] is True
    assert calls["tasks"] == "outbox,item"
