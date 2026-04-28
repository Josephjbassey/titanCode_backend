"""
TitanCode Technologies — Real-Time Notification Manager
=========================================================
This module provides the central WebSocket connection manager that enables
real-time push notifications to connected users.

Architecture:
    ┌──────────────┐      ┌──────────────────────┐
    │  API Endpoint │────▶│   ConnectionManager   │
    │ (approve app) │     │  ┌──────────────────┐ │
    └──────────────┘      │  │ active_connections│ │
                          │  │ {user_id: [ws1]}  │ │
                          │  └──────────────────┘ │
                          │        │               │
                          │        ▼               │
                          │  Push JSON message to  │
                          │  the target user's     │
                          │  WebSocket connections │
                          └──────────────────────┘

Key Design Decisions:
    - A user can have MULTIPLE connections (e.g. browser + mobile).
    - All connections for a user receive the same notification.
    - Disconnections are handled gracefully — no crashes.
    - Messages are JSON-structured with `type`, `title`, and `message` fields.

Usage (from any endpoint):
    from app.core.notifications import manager

    await manager.send_personal_message(
        user_id=42,
        message={
            "type": "approval",
            "title": "Application Approved",
            "message": "Welcome to TitanCode!",
        }
    )
"""

import asyncio
import json
import logging
from typing import Dict, List, Any

from fastapi import WebSocket
from redis.asyncio import Redis

from app.core.config import settings
# Logger for tracking connection events
logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages active WebSocket connections and message delivery.

    Attributes:
        active_connections: A dictionary mapping user IDs to their list
                           of active WebSocket connections.
                           Example: {1: [ws1, ws2], 5: [ws3]}

    Methods:
        connect()               — Register a new WebSocket connection.
        disconnect()            — Remove a connection when the client leaves.
        send_personal_message() — Send a message to a specific user.
        broadcast()             — Send a message to ALL connected users.
    """

    def __init__(self):
        """Initialize with an empty connections dictionary."""
        # Dict[int, List[WebSocket]] — one user can have multiple connections
        self.active_connections: Dict[int, List[WebSocket]] = {}
        self.redis: Redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        self._listener_task: asyncio.Task | None = None
        self._listener_lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        """
        Accept a new WebSocket connection and register it.

        If the user already has existing connections (e.g. from another
        browser tab), the new connection is added to the list.

        Args:
            websocket: The WebSocket connection object from FastAPI.
            user_id:   The authenticated user's database ID.
        """
        # Accept the WebSocket handshake
        await websocket.accept()

        # Add the connection to the user's list
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        await self._ensure_listener_running()

        logger.info(f"User {user_id} connected. Total connections: {len(self.active_connections[user_id])}")

    def disconnect(self, websocket: WebSocket, user_id: int) -> None:
        """
        Remove a WebSocket connection when the client disconnects.

        If this was the user's last connection, remove them from the
        dictionary entirely to keep memory clean.

        Args:
            websocket: The WebSocket connection to remove.
            user_id:   The user's database ID.
        """
        if user_id in self.active_connections:
            # Remove this specific WebSocket from the user's list
            self.active_connections[user_id] = [
                ws for ws in self.active_connections[user_id] if ws != websocket
            ]
            # Clean up the key if no connections remain
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

        logger.info(f"User {user_id} disconnected.")

    async def send_personal_message(self, user_id: int, message: Dict[str, Any]) -> None:
        """
        Send a JSON message to all of a specific user's connections.

        If the user is not currently connected, the message is silently
        dropped (no error). In a production system, you would queue these
        for later delivery or store them as unread notifications.

        Args:
            user_id: The target user's database ID.
            message: A dictionary to send as JSON. Expected structure:
                     {
                         "type": "approval" | "wallet" | "task" | "system",
                         "title": "Short title",
                         "message": "Detailed description",
                     }
        """
        await self._publish_personal_message(user_id, message)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """
        Send a JSON message to ALL connected users.

        Useful for system-wide announcements like maintenance windows
        or company-wide updates.

        Args:
            message: A dictionary to send as JSON to everyone.
        """
        for user_id in list(self.active_connections.keys()):
            await self.send_personal_message(user_id, message)

    async def _ensure_listener_running(self) -> None:
        """Start a single Redis Pub/Sub listener per process."""
        if self._listener_task and not self._listener_task.done():
            return
        async with self._listener_lock:
            if self._listener_task and not self._listener_task.done():
                return
            self._listener_task = asyncio.create_task(self._listen_for_messages())

    async def _publish_personal_message(self, user_id: int, message: Dict[str, Any]) -> None:
        payload = json.dumps({"user_id": user_id, "message": message})
        await self.redis.publish("notifications:personal", payload)

    async def _deliver_local_message(self, user_id: int, message: Dict[str, Any]) -> None:
        if user_id not in self.active_connections:
            return
        dead_connections = []
        for connection in self.active_connections[user_id]:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)
        for dead in dead_connections:
            self.active_connections[user_id].remove(dead)
        if user_id in self.active_connections and not self.active_connections[user_id]:
            del self.active_connections[user_id]

    async def _listen_for_messages(self) -> None:
        """Listen for cross-worker notification events from Redis."""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe("notifications:personal")
        try:
            async for item in pubsub.listen():
                if item.get("type") != "message":
                    continue
                data = item.get("data")
                if not data:
                    continue
                try:
                    payload = json.loads(data)
                    user_id = int(payload["user_id"])
                    message = payload["message"]
                except Exception:
                    logger.warning("Invalid notification payload on Redis pubsub channel")
                    continue
                await self._deliver_local_message(user_id, message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Notification listener crashed: %s", exc)
        finally:
            await pubsub.unsubscribe("notifications:personal")
            await pubsub.close()


# ── Singleton Instance ─────────────────────────────────────────────────
# Import this from anywhere in the app:
#   from app.core.notifications import manager
manager = ConnectionManager()
