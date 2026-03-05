"""
HTTP-based cross-process notifier.

stdio MCP 서버에서 웹서버로 HTTP POST를 보내 WebSocket 브로드캐스트를 트리거합니다.
RealtimeNotifier와 동일한 인터페이스를 제공하며, 의존성 추가 없이 stdlib urllib 사용.
"""

import asyncio
import json
import logging
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class HttpNotifier:
    """HTTP 기반 알림 발송자 (cross-process bridge).

    웹서버의 /api/internal/notify 엔드포인트로 이벤트를 전송합니다.
    fire-and-forget 방식으로, 웹서버가 꺼져 있어도 에러 로그만 남기고 진행합니다.
    """

    def __init__(self, base_url: str) -> None:
        self._url = f"{base_url.rstrip('/')}/api/internal/notify"

    def _fire(self, event_type: str, data: Dict[str, Any]) -> None:
        """동기 HTTP POST (fire-and-forget)."""
        payload = json.dumps({"type": event_type, "data": data}).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=2) as resp:
                resp.read()
        except Exception as e:
            logger.debug("HttpNotifier: failed to send %s: %s", event_type, e)

    async def _send(self, event_type: str, data: Dict[str, Any]) -> None:
        """비동기 fire-and-forget 전송."""
        try:
            await asyncio.to_thread(self._fire, event_type, data)
        except Exception as e:
            logger.debug("HttpNotifier: async send error for %s: %s", event_type, e)

    async def notify_memory_created(self, memory_data: Dict[str, Any]) -> None:
        await self._send("memory_created", {"memory": memory_data})

    async def notify_memory_updated(
        self, memory_id: str, memory_data: Dict[str, Any]
    ) -> None:
        await self._send(
            "memory_updated", {"memory_id": memory_id, "memory": memory_data}
        )

    async def notify_memory_deleted(
        self, memory_id: str, project_id: Optional[str] = None
    ) -> None:
        await self._send(
            "memory_deleted", {"memory_id": memory_id, "project_id": project_id}
        )

    async def notify_pin_created(self, pin_data: Dict[str, Any]) -> None:
        await self._send("pin_created", {"pin": pin_data})

    async def notify_pin_completed(self, pin_data: Dict[str, Any]) -> None:
        await self._send("pin_completed", {"pin": pin_data})

    async def notify_pin_promoted(self, pin_id: str, memory_id: str) -> None:
        await self._send(
            "pin_promoted", {"pin_id": pin_id, "memory_id": memory_id}
        )
