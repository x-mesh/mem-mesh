"""Dry-run tests for the OLD-vs-NEW injection replay harness (t10 / R12).

The harness is exercised end-to-end on a temporary fixture DB with a FAKE search
service (no embedding model is loaded) and a MOCK LLM judge. Both the judge-on
and judge-off (LLM not configured) paths are covered, plus report-schema and
prod-DB safety checks.
"""

import json
from types import SimpleNamespace
from typing import List

import pytest

from app.core.schemas.responses import SearchResult
from scripts import replay_injection_eval as rh

# pytest-asyncio runs in ``asyncio_mode = "auto"`` (pyproject.toml), so async
# tests need no explicit marker.


# ─────────────────────────────── fixtures ──────────────────────────────────


def _memory(
    mid: str, content: str, score: float, created_at: str = "2026-07-05T09:00:00Z"
):
    return SearchResult(
        id=mid,
        content=content,
        similarity_score=score,
        created_at=created_at,
        project_id="replay-test",
        category="decision",
        source="extracted",
    )


# A long free-text note: the OLD format cuts it at 300 chars mid-sentence, while
# the NEW render clips on a sentence boundary.
_LONG = (
    "We decided to migrate the injection formatter to a shared recall path so "
    "both hooks emit identical bullets. The formatter derives a title and a "
    "sentence-bounded summary instead of a blunt character cut, and it annotates "
    "each line with a relative age and a source tag so the assistant can weigh "
    "how trustworthy the memory is before acting on it in a later coding turn "
    "that continues the migration work across several files and modules."
)


class FakeSearchService:
    """Returns a fixed result set for any query (no embeddings, no DB search)."""

    def __init__(self, results: List[SearchResult]):
        self._results = results
        self.db = None

    async def search(self, query, **kwargs):  # noqa: ANN001 — harness passes kwargs
        self.last_kwargs = dict(kwargs)
        return SimpleNamespace(results=list(self._results))


class FakeChatService:
    """Mock ChatService: content-aware blind judge that always prefers NEW."""

    def __init__(self, *, configured: bool):
        self._configured = configured
        self.calls = 0

    async def is_configured(self, settings):
        return self._configured

    async def get_effective_config(self, settings):
        return {
            "values": {"llm_provider": "anthropic", "llm_model": "claude-test"},
            "sources": {},
        }

    async def complete(self, messages, settings, **kwargs):
        self.calls += 1
        user = messages[-1]["content"]
        block_a = user.split("BLOCK A:", 1)[1].split("BLOCK B:", 1)[0]

        def _is_new(block: str) -> bool:
            return (" · " in block) or (" — " in block)

        hi = {"relevance": 5, "completeness": 5, "misleading_risk": 5}
        lo = {"relevance": 3, "completeness": 2, "misleading_risk": 2}
        a_new = _is_new(block_a)
        payload = {
            "A": hi if a_new else lo,
            "B": lo if a_new else hi,
            "winner": "A" if a_new else "B",
        }
        return SimpleNamespace(text=json.dumps(payload))


async def _seed_prompts(
    db, project_id: str, prompts: List[str], table: str = "hook_events"
):
    for i, prompt in enumerate(prompts):
        await db.execute(
            f"INSERT INTO {table} "
            "(id, project_id, ide_session_id, client_type, event_name, turn_index, "
            "prompt, assistant_message, saved_memory, created_at) "
            "VALUES (?, ?, ?, ?, 'UserPromptSubmit', ?, ?, NULL, 0, ?)",
            (
                f"{table}-{i}",
                project_id,
                "sess-1",
                "claude_code",
                i,
                prompt,
                f"2026-07-0{(i % 9) + 1}T10:00:00Z",
            ),
        )


# ─────────────────────────────── unit tests ────────────────────────────────


def test_old_format_line_reproduces_legacy_bullet():
    line = rh.old_format_line("decision", "2026-07-05T09:00:00Z", "x" * 500)
    assert line.startswith("- [decision] (2026-07-05) ")
    body = rh._line_body(line)
    assert len(body) == 300  # blunt [:300] cut


def test_is_mid_sentence_cut_detects_hard_cut():
    # Blunt cut ending mid-word, source longer than body → hard cut.
    old = rh.old_format_line("decision", "2026-07-05", _LONG)
    assert rh._is_mid_sentence_cut(_LONG, old) is True
    # A clean, un-truncated line is not a cut.
    clean = "- [decision] (오늘 · extracted) Short whole thought."
    assert rh._is_mid_sentence_cut("Short whole thought.", clean) is False


def test_validate_db_path_refuses_prod(tmp_path):
    prod = tmp_path / "memories.db"
    prod.write_text("x")
    with pytest.raises(SystemExit):
        rh.validate_db_path(prod.resolve(), prod.resolve())


def test_validate_db_path_warns_without_copy_marker(tmp_path):
    other = (tmp_path / "memories.db").resolve()
    warnings = rh.validate_db_path(other, (tmp_path / "elsewhere.db").resolve())
    assert warnings and "copy" in warnings[0].lower()
    backup = (tmp_path / "replay_eval.db").resolve()
    assert rh.validate_db_path(backup, None) == []


def test_extract_json_pulls_object_from_noise():
    assert rh._extract_json('noise {"a": 1} tail') == {"a": 1}
    assert rh._extract_json("no json here") is None


# ─────────────────────────── integration (dry-run) ─────────────────────────


async def test_collect_prompts_redacts_secrets(temp_db):
    await _seed_prompts(
        temp_db,
        "replay-test",
        ["how do I use sk-ant-abcdef1234567890 safely?", "reach me at me@example.com"],
    )
    prompts = await rh.collect_prompts(temp_db, "replay-test", 10)
    joined = "\n".join(prompts)
    assert "sk-ant-abcdef1234567890" not in joined
    assert "me@example.com" not in joined
    assert "<REDACTED>" in joined


async def test_run_replay_search_is_project_scoped(temp_db):
    """cross-vendor review F1: the harness must search with the SAME project
    scope the production hook uses — a None scope evaluates global results the
    hook never injects and leaks other projects' memories into judge prompts."""
    await _seed_prompts(temp_db, "replay-test", ["scope check prompt"])
    search = FakeSearchService([_memory("m1", _LONG, 0.92)])

    await rh.run_replay(
        temp_db,
        search,
        FakeChatService(configured=False),
        SimpleNamespace(),
        project_id="replay-test",
        samples=5,
        seed=1,
        db_path="/tmp/replay_eval.db",
    )

    assert search.last_kwargs["project_id"] == "replay-test"


async def test_run_replay_deterministic_only(temp_db):
    """LLM not configured → judge skipped, deterministic metrics still produced."""
    await _seed_prompts(temp_db, "replay-test", ["migrate the injection formatter"])
    search = FakeSearchService([_memory("m1", _LONG, 0.92), _memory("m2", _LONG, 0.5)])
    chat = FakeChatService(configured=False)

    report = await rh.run_replay(
        temp_db,
        search,
        chat,
        SimpleNamespace(),
        project_id="replay-test",
        samples=5,
        seed=1,
        db_path="/tmp/replay_eval.db",
    )

    # Only the 0.92 memory clears threshold 0.75.
    assert report["samples_used"] == 1
    assert report["deterministic"]["old"]["lines"] == 1
    assert report["deterministic"]["new"]["lines"] == 1
    # OLD blunt-cuts the long note; NEW clips cleanly.
    assert report["deterministic"]["old"]["mid_sentence_cut_rate"] == 1.0
    assert report["deterministic"]["new"]["mid_sentence_cut_rate"] == 0.0
    # Judge disabled.
    assert report["judge"]["enabled"] is False
    assert report["llm"] is None
    assert report["judge"]["skipped_reason"] == "chat LLM not configured"


async def test_run_replay_with_mock_judge(temp_db):
    """LLM configured → blind A/B judge runs; NEW-preferring mock wins every pair."""
    await _seed_prompts(
        temp_db,
        "replay-test",
        ["migrate formatter", "share recall path", "add age tag"],
    )
    search = FakeSearchService([_memory("m1", _LONG, 0.9), _memory("m2", _LONG, 0.85)])
    chat = FakeChatService(configured=True)

    report = await rh.run_replay(
        temp_db,
        search,
        chat,
        SimpleNamespace(),
        project_id="replay-test",
        samples=5,
        seed=7,
        db_path="/tmp/replay_eval.db",
    )

    assert report["samples_used"] == 3
    assert report["judge"]["enabled"] is True
    assert report["judge"]["provider"] == "anthropic"
    assert report["judge"]["scored"] == 3
    llm = report["llm"]
    assert llm is not None
    assert llm["n"] == 3
    # Blind mapping correctly credits NEW regardless of A/B randomization.
    assert llm["win_rate_new"] == 1.0
    assert llm["ties"] == 0
    for crit in ("relevance", "completeness", "misleading_risk"):
        assert llm["new"][crit] >= llm["old"][crit]


async def test_run_replay_no_results_is_graceful(temp_db):
    """No prompt clears threshold → empty but valid report, judge skipped."""
    await _seed_prompts(temp_db, "replay-test", ["nothing relevant"])
    search = FakeSearchService([_memory("m1", _LONG, 0.4)])  # all below 0.75
    chat = FakeChatService(configured=True)

    report = await rh.run_replay(
        temp_db,
        search,
        chat,
        SimpleNamespace(),
        project_id="replay-test",
        samples=5,
        seed=1,
        db_path="/tmp/replay_eval.db",
    )
    assert report["samples_used"] == 0
    assert report["llm"] is None
    assert (
        report["judge"]["skipped_reason"] == "no prompts cleared the search threshold"
    )
    assert report["recommendation"]["recalibrate_threshold"] is True


# ─────────────────────────── report-schema tests ───────────────────────────

_REQUIRED_TOP = {
    "generated_at",
    "db_path",
    "project_id",
    "samples_requested",
    "prompts_collected",
    "samples_used",
    "search",
    "judge",
    "deterministic",
    "llm",
    "recommendation",
}


async def test_report_schema_and_write(temp_db, tmp_path):
    await _seed_prompts(temp_db, "replay-test", ["migrate formatter"])
    search = FakeSearchService([_memory("m1", _LONG, 0.9)])
    chat = FakeChatService(configured=True)

    report = await rh.run_replay(
        temp_db,
        search,
        chat,
        SimpleNamespace(),
        project_id="replay-test",
        samples=3,
        seed=1,
        db_path="/tmp/replay_eval.db",
    )

    assert _REQUIRED_TOP <= set(report.keys())
    assert set(report["search"]) == {"threshold", "limit", "mode"}
    assert set(report["judge"]) == {
        "enabled",
        "provider",
        "model",
        "scored",
        "skipped_reason",
    }
    for side in ("old", "new"):
        assert set(report["deterministic"][side]) == {
            "lines",
            "avg_block_tokens",
            "avg_chars_per_line",
            "mid_sentence_cut_rate",
        }
    assert set(report["recommendation"]) == {
        "recalibrate_threshold",
        "recalibrate_recency",
        "notes",
    }

    json_path, md_path = rh.write_report(report, tmp_path / "out")
    assert json_path.exists() and md_path.exists()
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert _REQUIRED_TOP <= set(loaded.keys())
    md = md_path.read_text(encoding="utf-8")
    assert "Injection Format Replay" in md
    assert "Recommendation" in md
