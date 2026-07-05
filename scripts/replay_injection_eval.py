"""Offline replay harness: compare OLD vs NEW memory-injection formats.

Answers the "session memory has no effect" critique with evidence. For a sample
of real user prompts (captured by hooks), it re-runs the same hybrid search and
renders the retrieved memories two ways — the legacy blunt-truncation bullet and
the current :func:`app.core.services.recall.render_memory_lines` path — then
scores both with deterministic metrics and an optional blind LLM judge.

The premise is honest: if the NEW format shows no advantage, shrinking injection
is a valid outcome. So the comparison must be fair — same search results feed
both formats, the judge sees the two blocks blind (random A/B), and the
deterministic metrics need no LLM at all.

Real measurement is meant to run only after 2+ weeks of hook data has
accumulated; this module's job is a correct, dry-runnable harness.

Usage (single, background, on a COPY of prod):

    sqlite3 ~/…/memories.db ".backup /tmp/replay_eval.db"
    nohup python -m scripts.replay_injection_eval \\
        --db /tmp/replay_eval.db --project-id mem-mesh --samples 30 \\
        --out /tmp/replay_out > /tmp/replay.log 2>&1 &

──────────────────────────────────────────────────────────────────────────────
L-RULE COMPLIANCE CHECKLIST (see CLAUDE.md "로컬 측정·벤치마크 주의")
──────────────────────────────────────────────────────────────────────────────
  [L1] No CPU cross-encoder / large-ML repeated inference. This harness loads
       NO reranker; reranking stays off. The only ML model is the ONE embedding
       service the hybrid search already needs.
  [L2] No concurrent embedding models. Exactly one EmbeddingService is created.
  [L3] Cache isolation is not a concern here (no off/on A/B over the same svc);
       each run is a single format-vs-format pass on identical results.
  [L4] prod-DB safety: refuses to open the live DB (``--db`` must differ from
       ``settings.database_path``); warns loudly if the filename lacks a copy
       marker. Read your prod copy via ``.backup``. The harness's search_metrics
       writes then land only in the copy.
  [L5] Heavy work runs BACKGROUND + SINGLE. Run one process, in the background,
       and let it finish before starting another (see Usage above).

  Judge is a REMOTE API (ChatService → configured provider), never a local LLM.
──────────────────────────────────────────────────────────────────────────────
"""

import argparse
import asyncio
import json
import logging
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from app.core.redaction import redact_secrets
from app.core.services.recall import render_memory_lines
from app.mcp_common.token_estimator import estimate_tokens

logger = logging.getLogger("replay_injection_eval")

# Search parameters fixed to the production injection path (hook default).
SEARCH_THRESHOLD = 0.75
SEARCH_LIMIT = 3
SEARCH_MODE = "hybrid"

DEFAULT_SAMPLES = 30
MAX_SAMPLES = 50

# Old injection line reproduced by hand (NOT a call into current code) — the
# legacy shell hook did: f"- [{cat}] ({created[:10]}) {content[:300]}".
_OLD_CONTENT_LIMIT = 300

# Path substrings that signal a deliberate copy (not the live DB).
_COPY_MARKERS = ("backup", "copy", "eval", "replay", "snapshot", "tmp", "/tmp/")

# Sentence-terminal signals for the deterministic "mid-sentence cut" metric.
# Korean note-style endings (다/요/음/함) + terminal punctuation + closers.
_KO_ENDINGS = "다요음함"
_CLEAN_TAIL = set(".!?…" + _KO_ENDINGS + "\"')]}»”’」』】")


# ───────────────────────────── db path safety ──────────────────────────────


def resolve_prod_db_path() -> Optional[Path]:
    """Best-effort resolve of the live DB path from settings (None on failure)."""
    try:
        from app.core.config import get_settings

        raw = getattr(get_settings(), "database_path", None)
        return Path(raw).expanduser().resolve() if raw else None
    except Exception as exc:  # noqa: BLE001 — safety check must not crash the run
        logger.debug("could not resolve prod db path: %s", exc)
        return None


def validate_db_path(target: Path, prod: Optional[Path]) -> List[str]:
    """Guard against measuring the live DB. Returns warnings; raises if it IS prod.

    Hard-fails when ``target`` resolves to the configured production DB (L4).
    Otherwise returns a (possibly empty) list of soft warnings — e.g. the file
    name carries no copy marker, so the operator should confirm it is a
    ``.backup`` copy and not a symlink/hardlink to prod.
    """
    warnings: List[str] = []
    if prod is not None and target == prod:
        raise SystemExit(
            f"REFUSING: --db points at the live production DB ({target}).\n"
            'Run against a copy: sqlite3 prod.db ".backup /tmp/replay_eval.db"'
        )
    name = target.name.lower()
    if not any(marker in str(target).lower() for marker in _COPY_MARKERS):
        warnings.append(
            f"'{name}' has no copy marker (backup/copy/eval/tmp). "
            "Confirm this is a .backup copy, NOT the live DB."
        )
    return warnings


# ─────────────────────────── prompt collection ─────────────────────────────


async def _table_exists(db: Any, name: str) -> bool:
    try:
        row = await db.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return row is not None
    except Exception as exc:  # noqa: BLE001
        logger.debug("table check failed for %s: %s", name, exc)
        return False


async def collect_prompts(db: Any, project_id: str, limit: int) -> List[str]:
    """Gather up to ``limit`` distinct, redacted user prompts for ``project_id``.

    Sources (t4): ``hook_events_archive`` (long-term) + ``hook_events`` live
    ``UserPromptSubmit`` rows. Archive rows were redacted at archive time; we
    re-run :func:`redact_secrets` here (idempotent) so a direct ``hook_events``
    read is scrubbed too before any prompt text reaches the judge API. Most
    recent first, de-duplicated on the redacted text.
    """
    seen: set = set()
    out: List[str] = []
    for table in ("hook_events_archive", "hook_events"):
        if len(out) >= limit:
            break
        if not await _table_exists(db, table):
            continue
        try:
            rows = await db.fetchall(
                f"SELECT prompt FROM {table} "
                "WHERE project_id = ? AND prompt IS NOT NULL AND TRIM(prompt) <> '' "
                "ORDER BY created_at DESC",
                (project_id,),
            )
        except Exception as exc:  # noqa: BLE001 — a bad table never breaks the run
            logger.debug("prompt query failed on %s: %s", table, exc)
            continue
        for row in rows:
            if len(out) >= limit:
                break
            prompt = redact_secrets((row["prompt"] or "").strip())
            if not prompt or prompt in seen:
                continue
            seen.add(prompt)
            out.append(prompt)
    return out


# ──────────────────────────── format rendering ─────────────────────────────


def old_format_line(category: Any, created_at: Any, content: Any) -> str:
    """Reproduce the legacy bullet: ``- [cat] (YYYY-MM-DD) content[:300]``.

    Hardcoded on purpose (the original lived in a shell hook, since replaced) so
    the harness pins the OLD behavior even after the app code moves on.
    """
    cat = category or "unknown"
    created = str(created_at or "")[:10]
    body = (content or "")[:_OLD_CONTENT_LIMIT]
    return f"- [{cat}] ({created}) {body}"


async def build_pair(
    db: Any,
    search_service: Any,
    prompt: str,
    *,
    project_id: Optional[str] = None,
    threshold: float = SEARCH_THRESHOLD,
    limit: int = SEARCH_LIMIT,
) -> Optional[dict]:
    """Run one search and render the SAME results in both formats.

    ``project_id`` MUST match the scope the production hook searches with —
    a None scope would evaluate global results the hook never injects (and
    leak other projects' memories into judge prompts), skewing the A/B.

    Returns ``None`` when the prompt retrieves nothing above ``threshold`` (that
    prompt simply contributes no injection under either format). Otherwise a
    dict of the prompt, the retrieved items, and both rendered line lists.
    """
    result = await search_service.search(
        query=prompt[:300],
        project_id=project_id,
        limit=max(limit * 3, 8),
        search_mode=SEARCH_MODE,
        sort_by="relevance",
        sort_direction="desc",
        record_access=False,
    )
    items = list(getattr(result, "results", None) or [])
    relevant = [
        it
        for it in items
        if float(getattr(it, "similarity_score", 0.0) or 0.0) > threshold
    ][:limit]
    if not relevant:
        return None

    old_lines = [
        old_format_line(
            getattr(it, "category", None),
            getattr(it, "created_at", None),
            getattr(it, "content", None),
        )
        for it in relevant
    ]
    new_lines = await render_memory_lines(db, relevant)
    return {
        "prompt": prompt,
        "items": relevant,
        "old_lines": old_lines,
        "new_lines": new_lines,
    }


# ─────────────────────────── deterministic metrics ─────────────────────────


def _ends_cleanly(body: str) -> bool:
    """True if ``body`` ends at a natural sentence/label boundary (or ``…``)."""
    t = body.rstrip()
    if not t:
        return True
    return t[-1] in _CLEAN_TAIL


def _line_body(line: str) -> str:
    """Strip the ``- [cat] (meta) `` prefix, leaving the rendered body text."""
    m = re.match(r"^- \[[^\]]*\]\s*\([^)]*\)\s*(.*)$", line, re.S)
    return m.group(1) if m else line


def _is_mid_sentence_cut(source: str, line: str) -> bool:
    """True if the line dropped content AND ended mid-sentence (a hard cut).

    Truncation is judged against the whitespace-collapsed source; a body that
    ends on a clean boundary or an explicit ``…`` marker is never a hard cut,
    so short title-only lines and boundary-clipped summaries do not count.
    """
    body = _line_body(line)
    norm_source = re.sub(r"\s+", " ", source or "").strip()
    truncated = len(norm_source) > len(body.strip())
    return truncated and not _ends_cleanly(body)


def _tokens(text: str) -> int:
    """Token estimate with a char-based fallback when tiktoken is unavailable."""
    est = estimate_tokens(text)
    if est is not None:
        return est
    return max(1, round(len(text) / 4)) if text else 0


def deterministic_metrics(pairs: Sequence[dict]) -> dict:
    """Aggregate no-LLM metrics for both formats over all built pairs.

    Per format: average injected-block tokens per sample, average characters
    per line, and the share of lines that were cut mid-sentence.
    """

    def _side(key: str) -> dict:
        block_tokens: List[int] = []
        line_chars: List[int] = []
        cut_flags: List[bool] = []
        for pair in pairs:
            lines = pair[key]
            block_tokens.append(_tokens("\n".join(lines)))
            for it, line in zip(pair["items"], lines):
                line_chars.append(len(line))
                cut_flags.append(
                    _is_mid_sentence_cut(getattr(it, "content", "") or "", line)
                )
        n_lines = len(cut_flags)
        return {
            "lines": n_lines,
            "avg_block_tokens": round(_mean(block_tokens), 2),
            "avg_chars_per_line": round(_mean(line_chars), 2),
            "mid_sentence_cut_rate": round(
                _mean([1.0 if c else 0.0 for c in cut_flags]), 4
            ),
        }

    old = _side("old_lines")
    new = _side("new_lines")
    return {
        "old": old,
        "new": new,
        "delta_new_minus_old": {
            "avg_block_tokens": round(
                new["avg_block_tokens"] - old["avg_block_tokens"], 2
            ),
            "avg_chars_per_line": round(
                new["avg_chars_per_line"] - old["avg_chars_per_line"], 2
            ),
            "mid_sentence_cut_rate": round(
                new["mid_sentence_cut_rate"] - old["mid_sentence_cut_rate"], 4
            ),
        },
    }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ─────────────────────────────── LLM judge ─────────────────────────────────

_JUDGE_SYSTEM = (
    "You are a strict evaluator of memory snippets injected into an AI coding "
    "assistant at session start. Given a user prompt and two candidate injection "
    "blocks, score each block. All scores are 1-5 where 5 is BEST. Criteria: "
    "relevance (how well the block matches the prompt), completeness (lines are "
    "whole thoughts, not cut mid-sentence), misleading_risk (5 = little risk; 1 = "
    "high risk because age/source/context is missing). Respond with ONLY a JSON "
    'object: {"A": {"relevance": n, "completeness": n, "misleading_risk": n}, '
    '"B": {...}, "winner": "A" | "B" | "tie"}.'
)

_JUDGE_CRITERIA = ("relevance", "completeness", "misleading_risk")


def _judge_user_message(prompt: str, a_block: str, b_block: str) -> str:
    return (
        f"USER PROMPT:\n{prompt}\n\n"
        f"BLOCK A:\n{a_block or '(empty)'}\n\n"
        f"BLOCK B:\n{b_block or '(empty)'}\n\n"
        "Return the JSON now."
    )


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first balanced ``{...}`` JSON object out of an LLM reply."""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _valid_scores(side: Any) -> Optional[dict]:
    """Coerce one side of the judge JSON to {criterion: 1-5 int} or None."""
    if not isinstance(side, dict):
        return None
    out = {}
    for crit in _JUDGE_CRITERIA:
        val = side.get(crit)
        if not isinstance(val, (int, float)):
            return None
        out[crit] = max(1, min(5, int(round(val))))
    return out


@dataclass
class JudgeOutcome:
    old: dict
    new: dict
    winner: str  # "old" | "new" | "tie"


async def judge_pair(
    chat_service: Any,
    settings: Any,
    pair: dict,
    *,
    rng: random.Random,
) -> Optional[JudgeOutcome]:
    """Blind A/B LLM scoring of one pair. Returns None on any provider/parse error.

    Order is randomized per pair (old/new hidden behind A/B) so position bias
    cannot favor one format. The A/B result is mapped back to old/new here.
    """
    # Memory content can carry secrets predating write-time redaction — scrub
    # both rendered blocks (idempotent) before anything leaves for the judge API.
    old_block = redact_secrets("\n".join(pair["old_lines"]))
    new_block = redact_secrets("\n".join(pair["new_lines"]))
    a_is_old = rng.random() < 0.5
    a_block, b_block = (old_block, new_block) if a_is_old else (new_block, old_block)

    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {
            "role": "user",
            "content": _judge_user_message(pair["prompt"], a_block, b_block),
        },
    ]
    try:
        result = await chat_service.complete(messages, settings, max_tokens=400)
    except Exception as exc:  # noqa: BLE001 — one bad call skips this sample only
        logger.debug("judge call failed: %s", exc)
        return None

    parsed = _extract_json(getattr(result, "text", "") or "")
    if parsed is None:
        return None
    a_scores = _valid_scores(parsed.get("A"))
    b_scores = _valid_scores(parsed.get("B"))
    if a_scores is None or b_scores is None:
        return None

    old_scores, new_scores = (a_scores, b_scores) if a_is_old else (b_scores, a_scores)

    raw_winner = str(parsed.get("winner", "")).strip().upper()
    if raw_winner in ("A", "B"):
        winner_is_old = (raw_winner == "A") == a_is_old
        winner = "old" if winner_is_old else "new"
    else:
        old_sum = sum(old_scores.values())
        new_sum = sum(new_scores.values())
        winner = "old" if old_sum > new_sum else "new" if new_sum > old_sum else "tie"
    return JudgeOutcome(old=old_scores, new=new_scores, winner=winner)


def aggregate_judge(outcomes: Sequence[JudgeOutcome]) -> Optional[dict]:
    """Average per-criterion scores and win rates over judged pairs (None if 0)."""
    if not outcomes:
        return None
    n = len(outcomes)

    def _avg(fmt: str) -> dict:
        return {
            crit: round(_mean([getattr(o, fmt)[crit] for o in outcomes]), 3)
            for crit in _JUDGE_CRITERIA
        }

    new_wins = sum(1 for o in outcomes if o.winner == "new")
    old_wins = sum(1 for o in outcomes if o.winner == "old")
    ties = sum(1 for o in outcomes if o.winner == "tie")
    return {
        "n": n,
        "old": _avg("old"),
        "new": _avg("new"),
        "win_rate_new": round(new_wins / n, 3),
        "win_rate_old": round(old_wins / n, 3),
        "ties": ties,
    }


# ────────────────────────────── recommendation ─────────────────────────────


def build_recommendation(
    *,
    samples_used: int,
    samples_requested: int,
    deterministic: dict,
    llm: Optional[dict],
) -> dict:
    """Turn the metrics into an advisory (threshold / recency recalibration)."""
    notes: List[str] = []
    recalibrate_threshold = False
    recalibrate_recency = False

    coverage = samples_used / samples_requested if samples_requested else 0.0
    if coverage < 0.5:
        recalibrate_threshold = True
        notes.append(
            f"Only {samples_used}/{samples_requested} prompts cleared threshold "
            f"{SEARCH_THRESHOLD}; consider lowering it to raise injection coverage."
        )

    cut = deterministic["new"]["mid_sentence_cut_rate"]
    if cut > 0.1:
        notes.append(
            f"NEW format still cut {cut:.0%} of lines mid-sentence — inspect the "
            "summary clipper."
        )

    if llm is not None:
        if llm["new"]["misleading_risk"] < 3.5:
            recalibrate_recency = True
            notes.append(
                "Judge flags residual misleading risk in NEW format "
                f"(misleading_risk={llm['new']['misleading_risk']}); the age/source "
                "signal may need stronger recency weighting."
            )
        if llm["win_rate_new"] < 0.5:
            notes.append(
                f"NEW format wins only {llm['win_rate_new']:.0%} of blind matchups — "
                "the richer format is not clearly better; shrinking injection is on "
                "the table."
            )
        else:
            notes.append(
                f"NEW format wins {llm['win_rate_new']:.0%} of blind matchups."
            )

    if not notes:
        notes.append("No recalibration signal; current format/threshold look healthy.")
    return {
        "recalibrate_threshold": recalibrate_threshold,
        "recalibrate_recency": recalibrate_recency,
        "notes": notes,
    }


# ──────────────────────────────── orchestration ────────────────────────────


async def run_replay(
    db: Any,
    search_service: Any,
    chat_service: Any,
    settings: Any,
    *,
    project_id: str,
    samples: int = DEFAULT_SAMPLES,
    threshold: float = SEARCH_THRESHOLD,
    limit: int = SEARCH_LIMIT,
    db_path: str = "",
    seed: Optional[int] = None,
) -> dict:
    """Core harness: collect → search → render both → score → report dict.

    Services are injected so a real run wires the production stack while tests
    supply fakes (no embedding model, mocked judge). When the chat LLM is not
    configured the judge is skipped and only deterministic metrics are reported.
    """
    samples = max(1, min(samples, MAX_SAMPLES))
    prompts = await collect_prompts(db, project_id, samples)

    pairs: List[dict] = []
    for prompt in prompts:
        pair = await build_pair(
            db,
            search_service,
            prompt,
            project_id=project_id,
            threshold=threshold,
            limit=limit,
        )
        if pair is not None:
            pairs.append(pair)

    deterministic = deterministic_metrics(pairs)

    judge_enabled = False
    judge_provider: Optional[str] = None
    judge_model: Optional[str] = None
    skipped_reason: Optional[str] = None
    outcomes: List[JudgeOutcome] = []
    try:
        judge_enabled = bool(await chat_service.is_configured(settings))
    except Exception as exc:  # noqa: BLE001
        judge_enabled = False
        skipped_reason = f"config check failed: {exc}"

    if judge_enabled and pairs:
        try:
            cfg = await chat_service.get_effective_config(settings)
            judge_provider = cfg["values"].get("llm_provider") or None
            judge_model = cfg["values"].get("llm_model") or None
        except Exception:  # noqa: BLE001 — provider label is best-effort only
            pass
        rng = random.Random(seed)
        for pair in pairs:
            outcome = await judge_pair(chat_service, settings, pair, rng=rng)
            if outcome is not None:
                outcomes.append(outcome)
    elif not judge_enabled and skipped_reason is None:
        skipped_reason = "chat LLM not configured"
    elif not pairs and judge_enabled:
        skipped_reason = "no prompts cleared the search threshold"

    llm = aggregate_judge(outcomes)
    recommendation = build_recommendation(
        samples_used=len(pairs),
        samples_requested=samples,
        deterministic=deterministic,
        llm=llm,
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": db_path,
        "project_id": project_id,
        "samples_requested": samples,
        "prompts_collected": len(prompts),
        "samples_used": len(pairs),
        "search": {"threshold": threshold, "limit": limit, "mode": SEARCH_MODE},
        "judge": {
            "enabled": judge_enabled,
            "provider": judge_provider,
            "model": judge_model,
            "scored": len(outcomes),
            "skipped_reason": skipped_reason,
        },
        "deterministic": deterministic,
        "llm": llm,
        "recommendation": recommendation,
    }


# ──────────────────────────────── reporting ────────────────────────────────


def render_markdown(report: dict) -> str:
    """Human-readable markdown summary of a report dict."""
    d = report["deterministic"]
    lines = [
        "# Injection Format Replay — OLD vs NEW",
        "",
        f"- Generated: {report['generated_at']}",
        f"- DB: `{report['db_path']}`",
        f"- Project: `{report['project_id']}`",
        f"- Prompts collected: {report['prompts_collected']}",
        f"- Samples used (cleared threshold): {report['samples_used']} / "
        f"{report['samples_requested']}",
        f"- Search: mode={report['search']['mode']} threshold="
        f"{report['search']['threshold']} limit={report['search']['limit']}",
        "",
        "## Deterministic metrics",
        "",
        "| metric | OLD | NEW | Δ(new-old) |",
        "| --- | ---: | ---: | ---: |",
        f"| avg block tokens | {d['old']['avg_block_tokens']} | "
        f"{d['new']['avg_block_tokens']} | {d['delta_new_minus_old']['avg_block_tokens']} |",
        f"| avg chars/line | {d['old']['avg_chars_per_line']} | "
        f"{d['new']['avg_chars_per_line']} | {d['delta_new_minus_old']['avg_chars_per_line']} |",
        f"| mid-sentence cut rate | {d['old']['mid_sentence_cut_rate']} | "
        f"{d['new']['mid_sentence_cut_rate']} | "
        f"{d['delta_new_minus_old']['mid_sentence_cut_rate']} |",
        "",
    ]
    judge = report["judge"]
    lines.append("## LLM judge")
    lines.append("")
    if report["llm"] is None:
        lines.append(f"_Skipped: {judge.get('skipped_reason') or 'unavailable'}._")
    else:
        llm = report["llm"]
        lines.append(
            f"Provider `{judge.get('provider')}` / model `{judge.get('model')}` — "
            f"scored {judge['scored']} pairs (blind A/B)."
        )
        lines.append("")
        lines.append("| criterion (1-5, 5=best) | OLD | NEW |")
        lines.append("| --- | ---: | ---: |")
        for crit in _JUDGE_CRITERIA:
            lines.append(f"| {crit} | {llm['old'][crit]} | {llm['new'][crit]} |")
        lines.append("")
        lines.append(
            f"- Win rate NEW: {llm['win_rate_new']:.0%} · OLD: "
            f"{llm['win_rate_old']:.0%} · ties: {llm['ties']}"
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append("")
    rec = report["recommendation"]
    lines.append(f"- recalibrate_threshold: **{rec['recalibrate_threshold']}**")
    lines.append(f"- recalibrate_recency: **{rec['recalibrate_recency']}**")
    for note in rec["notes"]:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, out_dir: Path) -> Tuple[Path, Path]:
    """Write ``report.json`` + ``report.md`` into ``out_dir``. Returns both paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"replay_{stamp}.json"
    md_path = out_dir / f"replay_{stamp}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


# ──────────────────────────────── CLI wiring ───────────────────────────────


async def _amain(args: argparse.Namespace) -> int:
    target = Path(args.db).expanduser().resolve()
    if not target.exists():
        raise SystemExit(f"DB not found: {target}")
    warnings = validate_db_path(target, resolve_prod_db_path())
    for warn in warnings:
        logger.warning("DB-PATH WARNING: %s", warn)

    logger.info(
        "Replay harness starting (single-process, run me in the BACKGROUND). "
        "DB=%s project=%s samples=%s",
        target,
        args.project_id,
        args.samples,
    )

    # Lazy imports so --help and the safety checks run without heavy deps.
    from app.core.config import get_settings
    from app.core.database.base import Database
    from app.core.embeddings.service import EmbeddingService
    from app.core.services.chat import ChatService
    from app.core.services.unified_search import UnifiedSearchService

    settings = get_settings()
    db = Database(str(target), embedding_dim=1024)
    await db.connect()
    try:
        model = (
            await db.get_embedding_metadata("embedding_model") or "nlpai-lab/KURE-v1"
        )
        embedding_service = EmbeddingService(
            model_name=model, preload=True
        )  # the ONE model
        search_service = UnifiedSearchService(
            db=db,
            embedding_service=embedding_service,
            enable_quality_features=True,
            enable_korean_optimization=True,
            enable_noise_filter=True,
            enable_score_normalization=True,
            score_normalization_method="sigmoid",
        )
        chat_service = ChatService(db)
        report = await run_replay(
            db,
            search_service,
            chat_service,
            settings,
            project_id=args.project_id,
            samples=args.samples,
            db_path=str(target),
            seed=args.seed,
        )
    finally:
        await db.close()

    out_dir = Path(args.out).expanduser().resolve()
    json_path, md_path = write_report(report, out_dir)
    logger.info("Report written: %s", json_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nMarkdown: {md_path}\nJSON:     {json_path}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline OLD-vs-NEW memory injection replay harness.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db",
        required=True,
        help='Path to a COPY of the DB (sqlite3 prod.db ".backup /tmp/x.db"). '
        "Refuses the live DB.",
    )
    parser.add_argument("--project-id", required=True, help="project_id to sample.")
    parser.add_argument(
        "--samples",
        type=int,
        default=DEFAULT_SAMPLES,
        help=f"Prompt samples (default {DEFAULT_SAMPLES}, max {MAX_SAMPLES}).",
    )
    parser.add_argument(
        "--out",
        default="./replay_out",
        help="Output directory for report.json + report.md.",
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="Seed for blind A/B ordering."
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = build_arg_parser().parse_args(argv)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
