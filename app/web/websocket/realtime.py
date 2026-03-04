"""
WebSocket 기반 실시간 업데이트 시스템.

메모리 생성/수정/삭제 시 연결된 클라이언트들에게 실시간으로 알림을 전송합니다.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.routing import APIRouter

logger = logging.getLogger(__name__)

# WebSocket Router
router = APIRouter(prefix="/ws", tags=["WebSocket"])


class EventType(str, Enum):
    """실시간 이벤트 타입"""

    MEMORY_CREATED = "memory_created"
    MEMORY_UPDATED = "memory_updated"
    MEMORY_DELETED = "memory_deleted"
    STATS_UPDATED = "stats_updated"
    CONNECTION_ESTABLISHED = "connection_established"
    HEARTBEAT = "heartbeat"


class ConnectionManager:
    """WebSocket 연결 관리자"""

    def __init__(self):
        # 활성 연결들
        self.active_connections: Dict[str, WebSocket] = {}
        # 프로젝트별 구독자들
        self.project_subscribers: Dict[str, Set[str]] = {}
        # 전체 구독자들
        self.global_subscribers: Set[str] = set()
        # 하트비트 태스크들
        self.heartbeat_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        """클라이언트 연결"""
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.global_subscribers.add(client_id)

        # 하트비트 시작
        self.heartbeat_tasks[client_id] = asyncio.create_task(
            self._heartbeat_loop(client_id)
        )

        logger.info(f"WebSocket client connected: {client_id}")

        # 연결 확인 메시지 전송
        await self.send_to_client(
            client_id,
            {
                "type": EventType.CONNECTION_ESTABLISHED,
                "data": {
                    "client_id": client_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": "WebSocket connection established",
                },
            },
        )

    def disconnect(self, client_id: str) -> None:
        """클라이언트 연결 해제"""
        if client_id in self.active_connections:
            del self.active_connections[client_id]

        if client_id in self.global_subscribers:
            self.global_subscribers.remove(client_id)

        # 프로젝트 구독에서 제거
        for project_id, subscribers in self.project_subscribers.items():
            subscribers.discard(client_id)

        # 하트비트 태스크 취소
        if client_id in self.heartbeat_tasks:
            self.heartbeat_tasks[client_id].cancel()
            del self.heartbeat_tasks[client_id]

        logger.info(f"WebSocket client disconnected: {client_id}")

    def subscribe_to_project(self, client_id: str, project_id: str) -> None:
        """특정 프로젝트 구독"""
        if project_id not in self.project_subscribers:
            self.project_subscribers[project_id] = set()

        self.project_subscribers[project_id].add(client_id)
        logger.debug(f"Client {client_id} subscribed to project {project_id}")

    def unsubscribe_from_project(self, client_id: str, project_id: str) -> None:
        """특정 프로젝트 구독 해제"""
        if project_id in self.project_subscribers:
            self.project_subscribers[project_id].discard(client_id)

            # 구독자가 없으면 프로젝트 제거
            if not self.project_subscribers[project_id]:
                del self.project_subscribers[project_id]

        logger.debug(f"Client {client_id} unsubscribed from project {project_id}")

    async def send_to_client(self, client_id: str, message: Dict[str, Any]) -> bool:
        """특정 클라이언트에게 메시지 전송"""
        if client_id not in self.active_connections:
            return False

        try:
            websocket = self.active_connections[client_id]
            await websocket.send_text(json.dumps(message))
            return True
        except Exception as e:
            logger.debug(f"Failed to send message to client {client_id}, disconnecting: {e}")
            self.disconnect(client_id)
            return False

    async def broadcast_to_all(self, message: Dict[str, Any]) -> int:
        """모든 클라이언트에게 브로드캐스트"""
        sent_count = 0
        disconnected_clients = []

        for client_id in list(self.active_connections.keys()):
            if await self.send_to_client(client_id, message):
                sent_count += 1
            else:
                disconnected_clients.append(client_id)

        # 연결 해제된 클라이언트 정리
        for client_id in disconnected_clients:
            self.disconnect(client_id)

        return sent_count

    async def broadcast_to_project(
        self, project_id: str, message: Dict[str, Any]
    ) -> int:
        """특정 프로젝트 구독자들에게 브로드캐스트"""
        if project_id not in self.project_subscribers:
            return 0

        sent_count = 0
        disconnected_clients = []

        for client_id in list(self.project_subscribers[project_id]):
            if await self.send_to_client(client_id, message):
                sent_count += 1
            else:
                disconnected_clients.append(client_id)

        # 연결 해제된 클라이언트 정리
        for client_id in disconnected_clients:
            self.disconnect(client_id)

        return sent_count

    async def _heartbeat_loop(self, client_id: str) -> None:
        """하트비트 루프"""
        try:
            while client_id in self.active_connections:
                await asyncio.sleep(30)  # 30초마다 하트비트

                if client_id in self.active_connections:
                    success = await self.send_to_client(
                        client_id,
                        {
                            "type": EventType.HEARTBEAT,
                            "data": {
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            },
                        },
                    )

                    if not success:
                        break
        except asyncio.CancelledError:
            # Task cancelled - heartbeat loop terminated gracefully
            pass
        except Exception as e:
            logger.error(f"Heartbeat error for client {client_id}: {e}")
            self.disconnect(client_id)

    async def disconnect_all(self) -> None:
        """모든 클라이언트 연결 해제 (서버 종료 시 사용)"""
        logger.info(
            f"Disconnecting all WebSocket clients ({len(self.active_connections)} connections)"
        )

        # 모든 하트비트 태스크 취소 (빠른 정리)
        for task in list(self.heartbeat_tasks.values()):
            if not task.done():
                task.cancel()

        # 모든 WebSocket 연결 닫기 (타임아웃 설정)
        close_tasks = []
        for client_id, websocket in list(self.active_connections.items()):
            try:
                # 비동기로 연결 닫기
                close_tasks.append(websocket.close(code=1001, reason="Server shutdown"))
            except Exception as e:
                logger.warning(
                    f"Error preparing to close WebSocket for client {client_id}: {e}"
                )

        # 모든 연결 닫기를 병렬로 실행 (최대 2초 대기)
        if close_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*close_tasks, return_exceptions=True), timeout=2.0
                )
            except asyncio.TimeoutError:
                logger.warning("WebSocket close operations timed out")

        # 모든 데이터 정리
        self.active_connections.clear()
        self.global_subscribers.clear()
        self.project_subscribers.clear()
        self.heartbeat_tasks.clear()

        logger.info("All WebSocket connections disconnected")

    def get_stats(self) -> Dict[str, Any]:
        """연결 통계 반환"""
        return {
            "total_connections": len(self.active_connections),
            "global_subscribers": len(self.global_subscribers),
            "project_subscriptions": {
                project_id: len(subscribers)
                for project_id, subscribers in self.project_subscribers.items()
            },
        }


# 전역 연결 관리자
connection_manager = ConnectionManager()


class RealtimeNotifier:
    """실시간 알림 발송자"""

    @staticmethod
    async def notify_memory_created(memory_data: Dict[str, Any]) -> None:
        """메모리 생성 알림"""
        message = {
            "type": EventType.MEMORY_CREATED,
            "data": {
                "memory": memory_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

        # 디버깅: 전송되는 메모리 데이터 로깅
        logger.info(f"WebSocket notify_memory_created - Memory data: {memory_data}")

        # 전체 브로드캐스트
        total_sent = await connection_manager.broadcast_to_all(message)

        # 프로젝트별 브로드캐스트 (있는 경우)
        project_id = memory_data.get("project_id")
        if project_id:
            project_sent = await connection_manager.broadcast_to_project(
                project_id, message
            )
            logger.debug(
                f"Memory created notification sent to {total_sent} clients ({project_sent} project subscribers)"
            )
        else:
            logger.debug(f"Memory created notification sent to {total_sent} clients")

    @staticmethod
    async def notify_memory_updated(
        memory_id: str, memory_data: Dict[str, Any]
    ) -> None:
        """메모리 수정 알림"""
        message = {
            "type": EventType.MEMORY_UPDATED,
            "data": {
                "memory_id": memory_id,
                "memory": memory_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

        total_sent = await connection_manager.broadcast_to_all(message)

        project_id = memory_data.get("project_id")
        if project_id:
            project_sent = await connection_manager.broadcast_to_project(
                project_id, message
            )
            logger.debug(
                f"Memory updated notification sent to {total_sent} clients ({project_sent} project subscribers)"
            )
        else:
            logger.debug(f"Memory updated notification sent to {total_sent} clients")

    @staticmethod
    async def notify_memory_deleted(
        memory_id: str, project_id: Optional[str] = None
    ) -> None:
        """메모리 삭제 알림"""
        message = {
            "type": EventType.MEMORY_DELETED,
            "data": {
                "memory_id": memory_id,
                "project_id": project_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

        total_sent = await connection_manager.broadcast_to_all(message)

        if project_id:
            project_sent = await connection_manager.broadcast_to_project(
                project_id, message
            )
            logger.debug(
                f"Memory deleted notification sent to {total_sent} clients ({project_sent} project subscribers)"
            )
        else:
            logger.debug(f"Memory deleted notification sent to {total_sent} clients")

    @staticmethod
    async def broadcast(event_type: str, data: Dict[str, Any]) -> int:
        """범용 이벤트 브로드캐스트 (model_download 등)"""
        message = {
            "type": event_type,
            "data": {
                **data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        total_sent = await connection_manager.broadcast_to_all(message)
        logger.debug(f"Broadcast '{event_type}' sent to {total_sent} clients")
        return total_sent

    @staticmethod
    async def notify_stats_updated(stats_data: Dict[str, Any]) -> None:
        """통계 업데이트 알림"""
        message = {
            "type": EventType.STATS_UPDATED,
            "data": {
                "stats": stats_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

        total_sent = await connection_manager.broadcast_to_all(message)
        logger.debug(f"Stats updated notification sent to {total_sent} clients")


# WebSocket 엔드포인트
@router.websocket("/realtime")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """실시간 업데이트 WebSocket 엔드포인트"""
    await connection_manager.connect(websocket, client_id)

    try:
        while True:
            # 클라이언트로부터 메시지 수신
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                await handle_client_message(client_id, message)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from client {client_id}: {data}")
            except Exception as e:
                logger.error(f"Error handling message from client {client_id}: {e}")

    except WebSocketDisconnect:
        connection_manager.disconnect(client_id)
    except Exception as e:
        logger.debug(f"WebSocket error for client {client_id}: {e}")
        connection_manager.disconnect(client_id)


async def handle_client_message(client_id: str, message: Dict[str, Any]) -> None:
    """클라이언트 메시지 처리"""
    msg_type = message.get("type")
    data = message.get("data", {})

    if msg_type == "subscribe_project":
        project_id = data.get("project_id")
        if project_id:
            connection_manager.subscribe_to_project(client_id, project_id)
            await connection_manager.send_to_client(
                client_id,
                {
                    "type": "subscription_confirmed",
                    "data": {
                        "project_id": project_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                },
            )

    elif msg_type == "unsubscribe_project":
        project_id = data.get("project_id")
        if project_id:
            connection_manager.unsubscribe_from_project(client_id, project_id)
            await connection_manager.send_to_client(
                client_id,
                {
                    "type": "unsubscription_confirmed",
                    "data": {
                        "project_id": project_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                },
            )

    elif msg_type == "ping":
        await connection_manager.send_to_client(
            client_id,
            {
                "type": "pong",
                "data": {"timestamp": datetime.now(timezone.utc).isoformat()},
            },
        )

    else:
        logger.warning(f"Unknown message type from client {client_id}: {msg_type}")


@router.get("/stats")
async def websocket_stats():
    """WebSocket 연결 통계"""
    return connection_manager.get_stats()


# 전역 notifier 인스턴스
notifier = RealtimeNotifier()
