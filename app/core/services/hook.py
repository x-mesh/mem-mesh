"""Hook event stream service.

Claude Code HTTP hooks POST every lifecycle event to mem-mesh. This service
persists those events keyed by the IDE session id and reconstructs the
per-session state the legacy shell hooks used to derive by parsing the
client-side transcript file:

* **continuation detection** — has this session been seen before? (post-compaction)
* **Q&A pairing** — the prompt that preceded a given Stop event
* **turn counting** — assistant turns since the last memory save

Reconstructing from the event stream is both transcript-file-free (works for
remote / Docker deployments) and more reliable than re-parsing JSONL.
"""

import logging
import re
import weakref
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from app.core.database.base import Database
from app.core.redaction import redact_secrets

logger = logging.getLogger(__name__)

# Substrings that mark a turn as having saved something to mem-mesh.
_SAVE_MARKERS = ("mcp__mem-mesh__add", "mcp__mem-mesh__pin_add")

# Canonical counter unit: one user submission = one turn. The save-reminder
# counts UserPromptSubmit events only, matching the command-hook's per-turn
# semantics. Stop is part of the response lifecycle and must not inflate N.
_COUNT_EVENT = "UserPromptSubmit"

# Tools whose completion counts as a "write" — the objective signal that real
# work happened. The reminder gate uses this so pin/save nags fire only after
# an actual file edit, never on a read-only (question/analysis) turn.
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

# Event name recorded for a write-tool PostToolUse. Distinct from the lifecycle
# events so it never inflates the UserPromptSubmit turn counter.
_WRITE_EVENT = "PostToolUse"


# ── Injection-utilization judge (t9) ──────────────────────────────────────────
# Deterministic Stop-time heuristic deciding whether an injected memory was
# actually used by the assistant, so an injection hit rate exists even with no
# LLM judge configured. A conservative proxy beats "unjudged".

# A memory id counts as referenced when its leading hex prefix (this many chars)
# appears verbatim in the assistant message. 8 hex chars is short enough that an
# agent quoting ``mem a1b2c3d4…`` matches, long enough to make an accidental
# collision unlikely.
_ID_PREFIX_LEN = 8

# Keyword utilization: at least this many of a memory's top content keywords must
# appear in the message. Requiring two independent hits keeps a single shared
# common word from scoring a false "utilized".
_KEYWORD_MATCH_MIN = 2

# How many top-frequency content keywords to extract per memory for matching.
_KEYWORD_TOP_N = 8

# Tokens too generic to be evidence of reuse. English already needs >= 3 chars;
# a small Korean function-word set is pruned explicitly (those survive the
# >= 2-hangul tokenizer). Kept deliberately small — over-pruning would starve
# short memories of any keyword to match on.
_EN_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "all",
        "can",
        "was",
        "has",
        "have",
        "this",
        "that",
        "with",
        "from",
        "its",
        "use",
        "used",
        "using",
        "via",
        "per",
        "new",
        "any",
        "out",
        "get",
        "got",
        "set",
        "one",
        "two",
        "now",
        "how",
        "who",
        "why",
        "into",
        "onto",
        "than",
        "then",
        "them",
        "they",
        "their",
        "there",
        "here",
        "been",
        "will",
        "would",
        "should",
        "could",
        "also",
        "only",
        "just",
        "non",
        "yes",
        "true",
        "false",
        "null",
        "none",
    }
)
_KO_STOPWORDS = frozenset(
    {
        "그리고",
        "그러나",
        "하지만",
        "그래서",
        "그런데",
        "때문",
        "위해",
        "통해",
        "대해",
        "경우",
        "정도",
        "이제",
        "다시",
        "현재",
        "이번",
        "해당",
        "관련",
        "여기",
        "저기",
        "거기",
        "이것",
        "그것",
        "저것",
        "무엇",
        "어떤",
        "모든",
        "각각",
        "다음",
        "이후",
        "이전",
        "그냥",
        "바로",
        "또한",
        "전체",
        "일부",
    }
)

_EN_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]{2,}")
_KO_TOKEN_RE = re.compile(r"[가-힣]{2,}")


def _extract_keywords(content: str, top_n: int = _KEYWORD_TOP_N) -> list[str]:
    """Top-``top_n`` content keywords (English + Korean) for utilization matching.

    English tokens are lowercased words of >= 3 alnum chars; Korean tokens are
    runs of >= 2 hangul syllables. Stopwords drop out, then the most frequent
    tokens win — the memory's "topic words". Returns ``[]`` for empty content.
    """
    if not content:
        return []
    text = content.lower()
    tokens = _EN_TOKEN_RE.findall(text) + _KO_TOKEN_RE.findall(text)
    counts: dict[str, int] = {}
    for tok in tokens:
        if tok in _EN_STOPWORDS or tok in _KO_STOPWORDS:
            continue
        counts[tok] = counts.get(tok, 0) + 1
    # Frequency desc, with insertion order (dict preserves it) as a stable
    # tie-break so identical content always yields the same keyword set.
    ranked = sorted(counts, key=lambda t: -counts[t])
    return ranked[:top_n]


def _keyword_in_message(keyword: str, message_lower: str) -> bool:
    """Whether one keyword occurs in the (already-lowercased) assistant message.

    Korean keywords use substring matching so a bare stem still matches its
    josa-inflected form (``검색`` in ``검색을``); English keywords use a word
    boundary so a short token never matches inside a longer word (``api`` must
    not match inside ``rapidly``).
    """
    if _KO_TOKEN_RE.fullmatch(keyword):
        return keyword in message_lower
    return re.search(rf"\b{re.escape(keyword)}\b", message_lower) is not None


def _id_referenced(memory_id: str, message_lower: str) -> bool:
    """Whether the memory id's >= 8-hex prefix appears in the lowercased message."""
    if not memory_id:
        return False
    prefix = memory_id[:_ID_PREFIX_LEN].lower()
    if len(prefix) < _ID_PREFIX_LEN:
        return False
    return prefix in message_lower


class HookService:
    """Records Claude Code hook events and derives per-session state."""

    # Memoizes the lazy ``hook_events_archive`` schema per Database instance
    # (like EnrichmentStore / MaintenanceService) so no schema_migrator bump is
    # needed. See :meth:`ensure_archive_schema`.
    _archive_schema_ready: "weakref.WeakSet" = weakref.WeakSet()

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _detect_save(*texts: Optional[str]) -> bool:
        """True if any text references a mem-mesh save tool call."""
        for text in texts:
            if text and any(marker in text for marker in _SAVE_MARKERS):
                return True
        return False

    async def record_event(
        self,
        *,
        project_id: str,
        ide_session_id: str,
        event_name: str,
        client_type: Optional[str] = None,
        prompt: Optional[str] = None,
        assistant_message: Optional[str] = None,
        saved_memory: Optional[bool] = None,
    ) -> int:
        """Append an event to the session stream and return its turn index.

        ``saved_memory`` is auto-detected from the prompt/assistant text when
        not supplied explicitly.
        """
        now = datetime.now(timezone.utc).isoformat()

        row = await self.db.fetchone(
            "SELECT MAX(turn_index) AS m FROM hook_events WHERE ide_session_id = ?",
            (ide_session_id,),
        )
        next_turn = ((row["m"] if row and row["m"] is not None else -1)) + 1

        if saved_memory is None:
            saved_memory = self._detect_save(prompt, assistant_message)

        await self.db.execute(
            """
            INSERT INTO hook_events (
                id, project_id, ide_session_id, client_type, event_name,
                turn_index, prompt, assistant_message, saved_memory, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                project_id,
                ide_session_id,
                client_type,
                event_name,
                next_turn,
                prompt,
                assistant_message,
                1 if saved_memory else 0,
                now,
            ),
        )
        self.db.connection.commit()
        return next_turn

    async def is_continuation(self, ide_session_id: str) -> bool:
        """True if this session id already has recorded events.

        Claude Code preserves ``session_id`` across context compaction, so a
        SessionStart for a session we have already seen means the context was
        compacted and resumed rather than freshly started.
        """
        if not ide_session_id:
            return False
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS c FROM hook_events WHERE ide_session_id = ?",
            (ide_session_id,),
        )
        return bool(row and row["c"])

    async def get_last_prompt(self, ide_session_id: str) -> Optional[str]:
        """The most recent user prompt recorded for this session, if any."""
        if not ide_session_id:
            return None
        row = await self.db.fetchone(
            """
            SELECT prompt FROM hook_events
            WHERE ide_session_id = ? AND prompt IS NOT NULL AND prompt != ''
            ORDER BY turn_index DESC
            LIMIT 1
            """,
            (ide_session_id,),
        )
        return row["prompt"] if row else None

    async def turns_since_save(self, ide_session_id: str) -> int:
        """Count user-prompt turns since the last memory save in this session.

        Canonical meaning: the number of UserPromptSubmit events recorded after
        the most recent save. A save may be *detected* on any event (an explicit
        ``add`` usually lands on a Stop turn's assistant message), so the
        "last save" lookup is not restricted by event type — but only
        UserPromptSubmit events are *counted*, so Stop/SubagentStop events never
        inflate the reminder threshold. Returns the total user-prompt count when
        nothing has been saved yet.
        """
        if not ide_session_id:
            return 0

        last_save = await self.db.fetchone(
            """
            SELECT MAX(turn_index) AS m FROM hook_events
            WHERE ide_session_id = ? AND saved_memory = 1
            """,
            (ide_session_id,),
        )
        last_save_turn = (
            last_save["m"] if last_save and last_save["m"] is not None else -1
        )

        row = await self.db.fetchone(
            """
            SELECT COUNT(*) AS c FROM hook_events
            WHERE ide_session_id = ? AND turn_index > ? AND event_name = ?
            """,
            (ide_session_id, last_save_turn, _COUNT_EVENT),
        )
        return int(row["c"]) if row else 0

    async def record_write(
        self,
        *,
        project_id: str,
        ide_session_id: str,
        tool_name: str,
        client_type: Optional[str] = None,
    ) -> int:
        """Record a write-tool PostToolUse event into the session stream.

        Stored as a ``PostToolUse`` event with the tool name kept in
        ``assistant_message`` for debugging. ``saved_memory`` stays 0 so write
        events never reset the save reminder; they are the *evidence* the gate
        looks for, not a save.
        """
        return await self.record_event(
            project_id=project_id,
            ide_session_id=ide_session_id,
            event_name=_WRITE_EVENT,
            client_type=client_type,
            assistant_message=tool_name,
            saved_memory=False,
        )

    async def writes_since_save(self, ide_session_id: str) -> int:
        """Count write events recorded after the most recent memory save.

        Mirrors :meth:`turns_since_save` but counts ``PostToolUse`` write events
        instead of user prompts. A pin_add / add lands as ``saved_memory=1``, so
        a fresh pin or save resets this to 0 — the gate then stays quiet until
        the next real edit. Zero means "no uncaptured work", so a pin/save
        reminder would be noise and is suppressed.
        """
        if not ide_session_id:
            return 0

        last_save = await self.db.fetchone(
            """
            SELECT MAX(turn_index) AS m FROM hook_events
            WHERE ide_session_id = ? AND saved_memory = 1
            """,
            (ide_session_id,),
        )
        last_save_turn = (
            last_save["m"] if last_save and last_save["m"] is not None else -1
        )

        row = await self.db.fetchone(
            """
            SELECT COUNT(*) AS c FROM hook_events
            WHERE ide_session_id = ? AND turn_index > ? AND event_name = ?
            """,
            (ide_session_id, last_save_turn, _WRITE_EVENT),
        )
        return int(row["c"]) if row else 0

    async def record_injected(
        self,
        *,
        project_id: str,
        ide_session_id: str,
        memory_ids: list[str],
        turn_index: int,
        injected_via: str,
    ) -> int:
        """Record the memories actually injected into an IDE session's context.

        Writes one ``injected_memories`` row per id in ``memory_ids`` (list order
        = ``position``, 0-based) for the given ``turn_index`` and injection point
        ``injected_via`` (``"session_start"`` | ``"user_prompt_submit"``). This is
        the write side of the injection→utilization link: without it the injected
        ``memory_id`` list is discarded, and "is a memory helpful?" cannot be
        answered with data.

        "Injected" means *surfaced into additionalContext* — which is NOT the same
        as *utilized*. ``memories.access_count`` counts genuine recall (an agent's
        own ``search``); this table only records what was *offered*. The utilized
        verdict (injected ∧ later referenced) is a separate Stop-time step and is
        not derived here.

        Best-effort like the rest of the hook path: an empty ``ide_session_id``
        (no join key — the row would be an un-joinable orphan) or an empty id list
        is skipped, and any write failure is rolled back, logged, and swallowed so
        a hook response is never blocked. Returns rows written (0 when skipped or
        on failure).
        """
        if not ide_session_id:
            return 0
        ids = [str(m) for m in memory_ids if m]
        if not ids:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        try:
            async with self.db.transaction():
                for position, memory_id in enumerate(ids):
                    await self.db.execute(
                        """
                        INSERT INTO injected_memories (
                            id, project_id, ide_session_id, memory_id,
                            turn_index, position, injected_via, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            project_id,
                            ide_session_id,
                            memory_id,
                            turn_index,
                            position,
                            injected_via,
                            now,
                        ),
                    )
        except Exception as e:  # noqa: BLE001 — hooks must not break the session
            logger.warning(f"injected-memory record failed ({injected_via}): {e}")
            return 0
        return len(ids)

    @staticmethod
    def _judge_row(
        *,
        memory_id: str,
        injection_turn: int,
        message_lower: str,
        content: Optional[str],
        max_activity_turn: int,
    ) -> tuple[int, str]:
        """Return ``(utilized, judge_method)`` for one injected memory.

        Pure and deterministic (no I/O) so the verdict rules are unit-testable in
        isolation. First matching rule wins; see :meth:`judge_injected` for the
        rationale of each tier.
        """
        if _id_referenced(memory_id, message_lower):
            return 1, "id_ref"
        if content:
            keywords = _extract_keywords(content)
            hits = sum(1 for kw in keywords if _keyword_in_message(kw, message_lower))
            if hits >= _KEYWORD_MATCH_MIN:
                return 1, "keyword"
        if max_activity_turn > injection_turn:
            return 0, "activity_only"
        return 0, "none"

    async def _load_memory_contents(self, memory_ids: list[str]) -> dict[str, str]:
        """Map ``memory_id`` → ``content`` for the given ids (missing ids absent).

        Injected ids may point at memories deleted since (no FK); those simply
        don't come back and fall through to the id/activity checks with no
        keyword content to match on.
        """
        ids = [m for m in memory_ids if m]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = await self.db.fetchall(
            f"SELECT id, content FROM memories WHERE id IN ({placeholders})",
            tuple(ids),
        )
        return {row["id"]: row["content"] for row in rows}

    async def judge_injected(
        self, ide_session_id: str, assistant_message: Optional[str]
    ) -> dict:
        """Judge whether this session's still-unjudged injected memories were used.

        Deterministic Stop-time heuristic (no LLM): for every ``injected_memories``
        row in this session with ``utilized IS NULL``, derive a verdict from the
        latest assistant message and the session's event stream, then persist
        ``utilized`` / ``judge_method`` / ``judged_at``.

        Verdict per row (first match wins):

        * the memory id's >= 8-hex prefix appears in the message → ``(1, 'id_ref')``
        * >= :data:`_KEYWORD_MATCH_MIN` of the memory's top keywords appear →
          ``(1, 'keyword')``
        * a write/save event exists after the memory's injection turn →
          ``(0, 'activity_only')`` — real work happened but nothing ties it to
          *this* memory, so it is a weak signal: recorded, but not counted utilized
        * otherwise → ``(0, 'none')``

        Only NULL rows are touched, so verdicts accumulate across Stops and are
        never overwritten — each Stop judges the rows still open against that
        turn's latest message. Best-effort like the rest of the hook path: any
        failure is logged and swallowed so the Stop response is never blocked.
        Returns a ``{judged, utilized, by_method}`` summary (all zero when
        skipped / on failure).
        """
        empty: dict = {"judged": 0, "utilized": 0, "by_method": {}}
        if not ide_session_id:
            return empty
        try:
            rows = await self.db.fetchall(
                """
                SELECT id, memory_id, turn_index FROM injected_memories
                WHERE ide_session_id = ? AND utilized IS NULL
                """,
                (ide_session_id,),
            )
            if not rows:
                return empty

            message_lower = (assistant_message or "").lower()

            # Weak "activity" signal: the highest turn at which a write
            # (PostToolUse) or a save (saved_memory=1) happened this session. A
            # memory injected before that turn had *some* downstream work, even
            # if nothing attributes it to that specific memory.
            activity = await self.db.fetchone(
                """
                SELECT MAX(turn_index) AS m FROM hook_events
                WHERE ide_session_id = ? AND (event_name = ? OR saved_memory = 1)
                """,
                (ide_session_id, _WRITE_EVENT),
            )
            max_activity_turn = (
                activity["m"] if activity and activity["m"] is not None else -1
            )

            contents = await self._load_memory_contents([r["memory_id"] for r in rows])

            now = datetime.now(timezone.utc).isoformat()
            summary: dict = {"judged": 0, "utilized": 0, "by_method": {}}
            async with self.db.transaction():
                for r in rows:
                    utilized, method = self._judge_row(
                        memory_id=r["memory_id"],
                        injection_turn=r["turn_index"],
                        message_lower=message_lower,
                        content=contents.get(r["memory_id"]),
                        max_activity_turn=max_activity_turn,
                    )
                    await self.db.execute(
                        """
                        UPDATE injected_memories
                        SET utilized = ?, judge_method = ?, judged_at = ?
                        WHERE id = ?
                        """,
                        (utilized, method, now, r["id"]),
                    )
                    summary["judged"] += 1
                    summary["utilized"] += utilized
                    summary["by_method"][method] = (
                        summary["by_method"].get(method, 0) + 1
                    )
            return summary
        except Exception as e:  # noqa: BLE001 — hooks must not break the session
            logger.warning(f"injected-memory judge failed: {e}")
            return empty

    async def ensure_archive_schema(self) -> None:
        """Lazily create the long-term ``hook_events_archive`` table.

        Mirrors ``hook_events`` plus an ``archived_at`` timestamp. Memoized per
        Database instance (like EnrichmentStore / MaintenanceService), so the
        table is created on first prune with no schema_migrator registration.
        The archive keeps no retention of its own; an ``archived_at`` index is
        the only extra, so a future manual cleanup stays cheap.
        """
        if self.db in HookService._archive_schema_ready:
            return
        async with self.db.transaction():
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS hook_events_archive (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    ide_session_id TEXT NOT NULL,
                    client_type TEXT,
                    event_name TEXT NOT NULL,
                    turn_index INTEGER NOT NULL DEFAULT 0,
                    prompt TEXT,
                    assistant_message TEXT,
                    saved_memory INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    archived_at TEXT NOT NULL
                )
                """)
            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS idx_hook_events_archive_archived_at
                ON hook_events_archive(archived_at)
                """)
        HookService._archive_schema_ready.add(self.db)

    async def prune_old_events(self, retention_days: int = 14) -> int:
        """Archive then delete events older than ``retention_days``.

        Rows past retention are moved to ``hook_events_archive`` before being
        deleted, so the replay harness can still reach them after retention
        would otherwise drop them. The move + delete run in a single
        transaction: a failure rolls both back, leaving the source rows intact.
        ``prompt`` / ``assistant_message`` get a defensive :func:`redact_secrets`
        pass at archive time — rows written before redaction landed are not
        scrubbed retroactively, so this is the last gate before long-term
        storage. Returns rows removed from ``hook_events``.
        """
        await self.ensure_archive_schema()
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        archived_at = datetime.now(timezone.utc).isoformat()

        async with self.db.transaction():
            rows = await self.db.fetchall(
                "SELECT * FROM hook_events WHERE created_at < ?", (cutoff,)
            )
            for row in rows:
                await self.db.execute(
                    """
                    INSERT INTO hook_events_archive (
                        id, project_id, ide_session_id, client_type, event_name,
                        turn_index, prompt, assistant_message, saved_memory,
                        created_at, archived_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["project_id"],
                        row["ide_session_id"],
                        row["client_type"],
                        row["event_name"],
                        row["turn_index"],
                        redact_secrets(row["prompt"]),
                        redact_secrets(row["assistant_message"]),
                        row["saved_memory"],
                        row["created_at"],
                        archived_at,
                    ),
                )
            cursor = await self.db.execute(
                "DELETE FROM hook_events WHERE created_at < ?", (cutoff,)
            )
            removed = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        return removed
