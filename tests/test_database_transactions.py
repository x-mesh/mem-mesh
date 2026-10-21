"""Runtime config writes must respect the owning Database transaction."""

import pytest


@pytest.mark.asyncio
async def test_app_config_commit_does_not_escape_managed_transaction(temp_db):
    await temp_db.set_app_config("transaction-test", "before")
    with pytest.raises(RuntimeError, match="rollback"):
        async with temp_db.transaction():
            await temp_db.set_app_config("transaction-test", "after")
            await temp_db.execute(
                "INSERT INTO reconciler_state(state_key, state_value, updated_at) VALUES ('transaction-test', 'after', datetime('now'))"
            )
            raise RuntimeError("rollback")
    assert await temp_db.get_app_config("transaction-test") == "before"
    assert (
        await temp_db.fetchone(
            "SELECT state_key FROM reconciler_state WHERE state_key = 'transaction-test'"
        )
        is None
    )


@pytest.mark.asyncio
async def test_app_config_and_nested_policy_write_commit_together(temp_db):
    from app.core.services.memory_reconciler import MemoryReconcilerService

    service = MemoryReconcilerService(temp_db)
    async with temp_db.transaction():
        await service.set_policy(
            "transaction-project", {"retain_evidence_content": False}
        )
    assert (await service.get_policy("transaction-project"))[
        "retain_evidence_content"
    ] is False
    with pytest.raises(RuntimeError, match="rollback"):
        async with temp_db.transaction():
            await service.set_policy(
                "transaction-project",
                {"retain_evidence_content": True, "auto_noise_suppression": True},
            )
            raise RuntimeError("rollback")
    policy = await service.get_policy("transaction-project")
    assert policy["retain_evidence_content"] is False
    assert policy["auto_noise_suppression"] is False
