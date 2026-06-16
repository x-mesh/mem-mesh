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
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from app.core.database.base import Database

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


class HookService:
    """Records Claude Code hook events and derives per-session state."""

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

    async def prune_old_events(self, retention_days: int = 14) -> int:
        """Delete events older than ``retention_days``. Returns rows removed."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        cursor = await self.db.execute(
            "DELETE FROM hook_events WHERE created_at < ?", (cutoff,)
        )
        self.db.connection.commit()
        return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
