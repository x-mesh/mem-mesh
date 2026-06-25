"""Relay CLI dispatch tests."""

from types import SimpleNamespace

import pytest

from app.cli.main import main
from app.core.database.base import Database
from app.core.services.relay import RelayService


def test_main_dispatches_relay_worker_once_json(monkeypatch):
    calls = {}

    def fake_cmd(**kwargs):
        calls.update(kwargs)
        return 0

    import app.cli.relay as relay_cli

    monkeypatch.setattr(relay_cli, "cmd_relay_worker", fake_cmd)

    with pytest.raises(SystemExit) as exc:
        main(["relay", "worker", "--once", "--json", "-v", "--tasks", "outbox,item"])

    assert exc.value.code == 0
    assert calls["once"] is True
    assert calls["json_mode"] is True
    assert calls["tasks"] == "outbox,item"
    assert calls["verbose"] is True


def test_main_dispatches_relay_materialize_json(monkeypatch):
    calls = {}

    def fake_cmd(**kwargs):
        calls.update(kwargs)
        return 0

    import app.cli.relay as relay_cli

    monkeypatch.setattr(relay_cli, "cmd_relay_materialize", fake_cmd)

    with pytest.raises(SystemExit) as exc:
        main(["relay", "materialize", "--json", "--limit", "50"])

    assert exc.value.code == 0
    assert calls["json_mode"] is True
    assert calls["limit"] == 50


@pytest.mark.asyncio
async def test_relay_worker_verbose_reports_empty_outbox_queue(tmp_path, monkeypatch):
    import app.cli.relay as relay_cli

    db_path = tmp_path / "relay.db"
    settings = SimpleNamespace(
        database_path=str(db_path),
        embedding_dim=3,
        relay_hub_token="",
        relay_http_timeout=1.0,
        relay_prompt_version="relay-v1",
        relay_hub_url="",
        relay_source_node_id="",
        relay_sonnet_api_key="",
        relay_sonnet_model="claude-sonnet-4-6",
        relay_sonnet_base_url="https://api.anthropic.com/v1/messages",
    )
    monkeypatch.setattr(relay_cli, "Settings", lambda: settings)

    db = Database(str(db_path), embedding_dim=3)
    await db.connect()
    try:
        service = RelayService(db)
        await service.ensure_schema()
        await db.set_app_config("relay.hub_token", "relay-token")
        await db.set_app_config("relay.hub_url", "http://hub.local")
        await db.set_app_config("relay.source_node_id", "node-db")
    finally:
        await db.close()

    result = await relay_cli._run_relay_worker(
        once=True,
        tasks="outbox",
        interval=1.0,
        worker_id="test-worker",
        verbose=True,
    )

    assert result["outbox_processed"] == 0
    assert result["debug"]["before"]["settings"]["hub_token_configured"] is True
    assert result["debug"]["before"]["settings"]["hub_url"] == "http://hub.local"
    assert result["debug"]["before"]["settings"]["source_node_id"] == "node-db"
    assert result["debug"]["before"]["settings"]["sources"]["hub_token"] == "db"
    outbox = result["debug"]["before"]["queues"]["outbox"]
    assert outbox["total"] == 0
    assert "relay_outbox has no rows" in outbox["no_work_reason"]
