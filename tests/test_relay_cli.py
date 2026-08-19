"""Relay CLI dispatch tests."""

import asyncio
from types import SimpleNamespace

import pytest

from app.cli.main import main
from app.core.database.base import Database
from app.core.database.connection import sqlite3 as connection_sqlite3
from app.core.services.relay import RelayService


def test_main_dispatches_relay_worker_once_json(monkeypatch):
    calls = {}

    def fake_cmd(**kwargs):
        calls.update(kwargs)
        return 0

    import app.cli.relay as relay_cli

    monkeypatch.setattr(relay_cli, "cmd_relay_worker", fake_cmd)

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "relay",
                "worker",
                "--once",
                "--json",
                "-v",
                "--tasks",
                "outbox,item",
                "--max-attempts",
                "9",
                "--backoff-max",
                "120",
                "--lease-seconds",
                "45",
                "--concurrency",
                "3",
            ]
        )

    assert exc.value.code == 0
    assert calls["once"] is True
    assert calls["json_mode"] is True
    assert calls["tasks"] == "outbox,item"
    assert calls["max_attempts"] == 9
    assert calls["backoff_max"] == 120
    assert calls["lease_seconds"] == 45
    assert calls["concurrency"] == 3
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
async def test_db_busy_backoff_is_async_and_bounded(monkeypatch):
    import app.cli.relay as relay_cli

    delays = []

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(relay_cli.random, "uniform", lambda _low, _high: 1.0)

    await relay_cli._backoff_after_db_busy(
        exc=connection_sqlite3.OperationalError("database is locked"),
        consecutive_failures=20,
        interval=1.0,
    )

    assert delays == [relay_cli._DB_BUSY_BACKOFF_MAX_SECONDS]


@pytest.mark.asyncio
async def test_daemon_connect_retries_db_busy(monkeypatch):
    import app.cli.relay as relay_cli

    class FlakyDatabase:
        def __init__(self):
            self.calls = 0

        async def connect(self):
            self.calls += 1
            if self.calls < 3:
                raise connection_sqlite3.OperationalError("database is locked")

    backoffs = []

    async def fake_backoff(**kwargs):
        backoffs.append(kwargs["consecutive_failures"])

    monkeypatch.setattr(relay_cli, "_backoff_after_db_busy", fake_backoff)
    db = FlakyDatabase()

    await relay_cli._connect_worker_database(db, once=False, interval=1.0)

    assert db.calls == 3
    assert backoffs == [1, 2]


@pytest.mark.asyncio
async def test_startup_retries_db_busy_during_ensure_schema(monkeypatch):
    """Schema prep needs the write lock too, so contention there must not kill
    the daemon — connect() surviving is not enough."""
    import app.cli.relay as relay_cli

    calls = {"schema": 0}

    async def flaky_ensure_schema():
        calls["schema"] += 1
        if calls["schema"] < 3:
            raise connection_sqlite3.OperationalError("database is locked")

    backoffs = []

    async def fake_backoff(**kwargs):
        backoffs.append(kwargs["consecutive_failures"])

    monkeypatch.setattr(relay_cli, "_backoff_after_db_busy", fake_backoff)

    await relay_cli._retry_startup_step_while_db_busy(
        flaky_ensure_schema, once=False, interval=1.0
    )

    assert calls["schema"] == 3
    assert backoffs == [1, 2]


@pytest.mark.asyncio
async def test_startup_once_does_not_retry_db_busy(monkeypatch):
    """--once is a one-shot run: it must surface contention instead of
    hanging on an unbounded retry loop."""
    import app.cli.relay as relay_cli

    calls = {"schema": 0}

    async def always_locked():
        calls["schema"] += 1
        raise connection_sqlite3.OperationalError("database is locked")

    with pytest.raises(connection_sqlite3.OperationalError):
        await relay_cli._retry_startup_step_while_db_busy(
            always_locked, once=True, interval=1.0
        )

    assert calls["schema"] == 1


@pytest.mark.asyncio
async def test_startup_step_reraises_non_busy_error(monkeypatch):
    """A real error must not be mistaken for contention and retried forever."""
    import app.cli.relay as relay_cli

    async def broken():
        raise ValueError("schema is malformed")

    with pytest.raises(ValueError):
        await relay_cli._retry_startup_step_while_db_busy(
            broken, once=False, interval=1.0
        )


@pytest.mark.asyncio
async def test_worker_startup_survives_schema_contention(tmp_path, monkeypatch):
    """Wiring guard: the retry must actually be applied at the call site.

    The helper-level tests above still pass if someone reverts the call site to
    a bare `await service.ensure_schema()`, so this drives the real startup
    path and fails on that revert.
    """
    import app.cli.relay as relay_cli

    monkeypatch.setenv("MEM_MESH_DATABASE_PATH", str(tmp_path / "relay.db"))

    calls = {"schema": 0}

    async def flaky_ensure_schema(self):
        calls["schema"] += 1
        if calls["schema"] < 3:
            raise connection_sqlite3.OperationalError("database is locked")

    class _StopAfterSchema(Exception):
        pass

    async def stop_after_schema(self, settings):
        raise _StopAfterSchema

    backoffs = []

    async def fake_backoff(**kwargs):
        backoffs.append(kwargs["consecutive_failures"])

    monkeypatch.setattr(RelayService, "ensure_schema", flaky_ensure_schema)
    monkeypatch.setattr(RelayService, "get_effective_config", stop_after_schema)
    monkeypatch.setattr(relay_cli, "_backoff_after_db_busy", fake_backoff)

    with pytest.raises(_StopAfterSchema):
        await relay_cli._run_relay_worker_instance(
            once=False,
            enabled_override=None,
            interval=0.01,
            worker_id="test-worker",
            max_attempts=3,
            backoff_max=1.0,
            lease_seconds=60,
            concurrency=1,
        )

    assert calls["schema"] == 3
    assert backoffs == [1, 2]


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
        relay_llm_api_key="",
        relay_llm_model="claude-sonnet-4-6",
        relay_llm_base_url="https://api.anthropic.com/v1/messages",
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
        max_attempts=5,
        backoff_max=30.0,
        lease_seconds=45,
        concurrency=1,
        verbose=True,
    )

    assert result["outbox_processed"] == 0
    assert result["debug"]["before"]["worker"]["max_attempts"] == 5
    assert result["debug"]["before"]["worker"]["backoff_max"] == 30.0
    assert result["debug"]["before"]["worker"]["lease_seconds"] == 45
    assert result["debug"]["before"]["worker"]["concurrency"] == 1
    assert result["debug"]["before"]["settings"]["hub_token_configured"] is True
    assert result["debug"]["before"]["settings"]["hub_url"] == "http://hub.local"
    assert result["debug"]["before"]["settings"]["source_node_id"] == "node-db"
    assert result["debug"]["before"]["settings"]["sources"]["hub_token"] == "db"
    outbox = result["debug"]["before"]["queues"]["outbox"]
    assert outbox["total"] == 0
    assert "relay_outbox has no rows" in outbox["no_work_reason"]


@pytest.mark.asyncio
async def test_refresh_worker_config_hot_reloads_without_rebuilding_heavy_resources(
    tmp_path,
):
    """A dashboard edit (LLM key, hub token, prompt version) must take effect
    on an already-running worker without a process restart, and without
    reloading the embedding model — only _refresh_worker_config's cheap
    fields should change."""
    import app.cli.relay as relay_cli

    settings = SimpleNamespace(
        embedding_model="dummy-model",
        relay_llm_timeout=5.0,
        relay_http_timeout=5.0,
    )

    db = Database(str(tmp_path / "relay.db"), embedding_dim=3)
    await db.connect()
    try:
        service = RelayService(db)
        await service.ensure_schema()
        await db.set_app_config("relay.hub_token", "old-token")
        await db.set_app_config("relay.llm_provider", "anthropic")
        await db.set_app_config("relay.llm_api_key", "old-key")
        await db.set_app_config("relay.llm_model", "old-model")
        await db.set_app_config("relay.prompt_version", "v1")

        eff = await service.get_effective_config(settings)
        active = {"item", "aggregate", "outbox"}
        worker = await relay_cli._build_relay_worker(
            db=db,
            settings=settings,
            service=service,
            relay_config=eff["values"],
            active=active,
            worker_id="w-1",
            max_attempts=3,
            backoff_max=30.0,
            lease_seconds=60,
        )
        embedding_service = worker.embedding_service
        assert worker.text_enricher.api_key == "old-key"
        assert worker.outbox_bearer_token == "old-token"
        assert worker.prompt_version == "v1"

        # Simulate a dashboard edit: rotate the LLM key and hub token, bump
        # prompt_version — no restart, no rebuild.
        await db.set_app_config("relay.llm_api_key", "new-key")
        await db.set_app_config("relay.hub_token", "new-token")
        await db.set_app_config("relay.prompt_version", "v2")

        await relay_cli._refresh_worker_config(
            db=db, settings=settings, service=service, worker=worker, active=active
        )

        assert worker.text_enricher.api_key == "new-key"
        assert worker.digest_generator is worker.text_enricher
        assert worker.outbox_bearer_token == "new-token"
        assert worker.prompt_version == "v2"
        # The heavy resource is untouched — same object, no reload.
        assert worker.embedding_service is embedding_service
    finally:
        await db.close()
