"""Coverage / accumulation stats tests (t2).

Verifies StatsService.get_coverage_stats — enrichment title coverage over the
memories table and hook_events accumulation — plus the CoverageStatsResponse
schema. Guards the lazy ``memory_enrichment`` table (may be absent) and empty
DBs so the endpoint never 500s on a bare install.
"""

import pytest

from app.core.schemas.responses import CoverageStatsResponse
from app.core.services.enrich_store import EnrichmentStore
from app.core.services.hook import HookService


async def _add_memory(
    db,
    memory_id: str,
    *,
    project_id: str = "proj-a",
    content: str = "content long enough here",
    content_hash: str | None = None,
    category: str = "decision",
) -> None:
    await db.execute(
        """
        INSERT INTO memories (
            id, content, content_hash, project_id, category, source,
            embedding, tags, created_at, updated_at, content_bytes
        )
        VALUES (?, ?, ?, ?, ?, 'test', ?, '[]', ?, ?, ?)
        """,
        (
            memory_id,
            content,
            content_hash or f"h-{memory_id}",
            project_id,
            category,
            b"123",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            len(content),
        ),
    )


@pytest.mark.asyncio
async def test_enrichment_coverage_counts_and_ratio(temp_db, stats_service):
    # 3 memories in proj-a (2 enriched), 1 in proj-b (0 enriched).
    for i in range(3):
        await _add_memory(temp_db, f"a{i}", project_id="proj-a")
    await _add_memory(temp_db, "b0", project_id="proj-b")

    store = EnrichmentStore(temp_db)
    await store.upsert(memory_id="a0", title="Titled one")
    await store.upsert(memory_id="a1", title="Titled two")
    # a2 gets an enrichment row but a BLANK title → still counts as not enriched.
    await store.upsert(memory_id="a2", title="   ")

    data = await stats_service.get_coverage_stats()
    enr = data["enrichment"]

    assert enr["total_memories"] == 4
    assert enr["enriched_count"] == 2
    assert enr["coverage_ratio"] == 0.5

    by_project = {p["project_id"]: p for p in enr["by_project"]}
    assert by_project["proj-a"]["total"] == 3
    assert by_project["proj-a"]["enriched"] == 2
    assert by_project["proj-a"]["coverage_ratio"] == round(2 / 3, 4)
    assert by_project["proj-b"]["total"] == 1
    assert by_project["proj-b"]["enriched"] == 0
    assert by_project["proj-b"]["coverage_ratio"] == 0.0


@pytest.mark.asyncio
async def test_enrichment_coverage_project_filter(temp_db, stats_service):
    await _add_memory(temp_db, "a0", project_id="proj-a")
    await _add_memory(temp_db, "b0", project_id="proj-b")
    await EnrichmentStore(temp_db).upsert(memory_id="a0", title="T")

    data = await stats_service.get_coverage_stats(project_id="proj-a")
    enr = data["enrichment"]

    assert enr["total_memories"] == 1
    assert enr["enriched_count"] == 1
    assert enr["coverage_ratio"] == 1.0
    assert [p["project_id"] for p in enr["by_project"]] == ["proj-a"]


@pytest.mark.asyncio
async def test_coverage_missing_enrichment_table(temp_db, stats_service):
    # memory_enrichment is lazy — never created here. Coverage must still count
    # memories and report zero enriched instead of raising 'no such table'.
    await _add_memory(temp_db, "a0", project_id="proj-a")
    await _add_memory(temp_db, "a1", project_id="proj-a")

    exists = await temp_db.fetchone(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_enrichment'"
    )
    assert exists is None

    data = await stats_service.get_coverage_stats()
    enr = data["enrichment"]
    assert enr["total_memories"] == 2
    assert enr["enriched_count"] == 0
    assert enr["coverage_ratio"] == 0.0


@pytest.mark.asyncio
async def test_hook_events_accumulation(temp_db, stats_service):
    hooks = HookService(temp_db)
    await hooks.record_event(
        project_id="proj-a", ide_session_id="s1", event_name="SessionStart"
    )
    await hooks.record_event(
        project_id="proj-a",
        ide_session_id="s1",
        event_name="UserPromptSubmit",
        prompt="fix the parser",
    )
    # Empty-prompt UserPromptSubmit must NOT count toward prompt_events.
    await hooks.record_event(
        project_id="proj-a",
        ide_session_id="s1",
        event_name="UserPromptSubmit",
        prompt="   ",
    )
    await hooks.record_event(
        project_id="proj-b",
        ide_session_id="s2",
        event_name="UserPromptSubmit",
        prompt="add tests",
    )

    data = await stats_service.get_coverage_stats()
    he = data["hook_events"]

    assert he["total_events"] == 4
    assert he["prompt_events"] == 2  # only the two non-blank prompts
    assert he["by_event"]["UserPromptSubmit"] == 3
    assert he["by_event"]["SessionStart"] == 1
    assert he["by_project"] == {"proj-a": 3, "proj-b": 1}
    assert he["first_event_at"] is not None
    assert he["last_event_at"] is not None
    assert he["first_event_at"] <= he["last_event_at"]


@pytest.mark.asyncio
async def test_hook_events_project_filter(temp_db, stats_service):
    hooks = HookService(temp_db)
    await hooks.record_event(
        project_id="proj-a",
        ide_session_id="s1",
        event_name="UserPromptSubmit",
        prompt="a",
    )
    await hooks.record_event(
        project_id="proj-b",
        ide_session_id="s2",
        event_name="UserPromptSubmit",
        prompt="b",
    )

    data = await stats_service.get_coverage_stats(project_id="proj-b")
    he = data["hook_events"]
    assert he["total_events"] == 1
    assert he["prompt_events"] == 1
    assert he["by_project"] == {"proj-b": 1}


@pytest.mark.asyncio
async def test_hook_events_counts_archived_prompts(temp_db, stats_service):
    """cross-vendor review F3: pruned-then-archived prompts must still count —
    otherwise replay data is under-reported right after a prune and the M2b
    measurement gets wrongly deferred."""
    hooks = HookService(temp_db)
    await hooks.record_event(
        project_id="proj-a",
        ide_session_id="s1",
        event_name="UserPromptSubmit",
        prompt="old prompt headed for the archive",
    )
    await hooks.record_event(
        project_id="proj-a",
        ide_session_id="s1",
        event_name="UserPromptSubmit",
        prompt="fresh live prompt",
    )
    # Age the first row past retention, then prune → it moves to the archive.
    await temp_db.execute(
        "UPDATE hook_events SET created_at = '2020-01-01T00:00:00Z' "
        "WHERE prompt LIKE 'old prompt%'"
    )
    await hooks.prune_old_events(retention_days=14)

    data = await stats_service.get_coverage_stats(project_id="proj-a")
    he = data["hook_events"]
    assert he["prompt_events"] == 1  # live only
    assert he["archived_prompt_events"] == 1
    assert he["replay_prompts_total"] == 2


@pytest.mark.asyncio
async def test_coverage_response_schema_validates(temp_db, stats_service):
    await _add_memory(temp_db, "a0", project_id="proj-a")
    await EnrichmentStore(temp_db).upsert(memory_id="a0", title="T")
    await HookService(temp_db).record_event(
        project_id="proj-a",
        ide_session_id="s1",
        event_name="UserPromptSubmit",
        prompt="hello",
    )

    data = await stats_service.get_coverage_stats()
    resp = CoverageStatsResponse(**data)

    assert resp.enrichment.total_memories == 1
    assert resp.enrichment.enriched_count == 1
    assert resp.hook_events.total_events == 1
    assert resp.hook_events.prompt_events == 1
    assert resp.query_time_ms >= 0.0


@pytest.mark.asyncio
async def test_coverage_empty_db(temp_db, stats_service):
    data = await stats_service.get_coverage_stats()
    resp = CoverageStatsResponse(**data)

    assert resp.enrichment.total_memories == 0
    assert resp.enrichment.enriched_count == 0
    assert resp.enrichment.coverage_ratio == 0.0
    assert resp.enrichment.by_project == []
    assert resp.hook_events.total_events == 0
    assert resp.hook_events.prompt_events == 0
    assert resp.hook_events.by_event == {}
    assert resp.hook_events.by_project == {}
    assert resp.hook_events.first_event_at is None
    assert resp.hook_events.last_event_at is None
