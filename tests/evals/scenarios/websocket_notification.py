"""Scenario 5: WebSocket real-time notification.

Tests that when a memory is created via MCP SSE, a WebSocket
`memory_created` event is emitted to connected dashboard clients.
"""

from __future__ import annotations

from tests.evals.models import (
    ConversationMessage,
    EvalScenario,
    EvalTier,
    ExpectedAction,
)

# ---------------------------------------------------------------------------
# Scenario 5-A: MCP add → WS memory_created event
# ---------------------------------------------------------------------------

WS_MEMORY_CREATED = EvalScenario(
    id="ws_notification_01",
    name="MCP add → WS memory_created 이벤트",
    description=(
        "MCP SSE를 통해 memory를 추가하면 WebSocket으로 "
        "memory_created 이벤트가 브로드캐스트되는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["websocket", "notification", "realtime"],
    conversation=[
        ConversationMessage(
            role="system",
            content="WebSocket integration test — not a conversation scenario",
        ),
    ],
    expected_action=ExpectedAction.SAVE,
    expected_content_patterns=[r"memory_created"],
)

# ---------------------------------------------------------------------------
# Scenario 5-B: Batch operations → multiple WS events
# ---------------------------------------------------------------------------

WS_BATCH_EVENTS = EvalScenario(
    id="ws_notification_02",
    name="Batch add → 다수 WS 이벤트",
    description=(
        "batch_operations로 여러 메모리를 추가하면 "
        "각각에 대해 WS 이벤트가 발생하는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["websocket", "notification", "batch"],
    conversation=[
        ConversationMessage(
            role="system",
            content="WebSocket batch integration test — not a conversation scenario",
        ),
    ],
    expected_action=ExpectedAction.SAVE,
    expected_content_patterns=[r"memory_created"],
)

ALL_SCENARIOS = [WS_MEMORY_CREATED, WS_BATCH_EVENTS]
