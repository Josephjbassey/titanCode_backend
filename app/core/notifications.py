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

import logging
from typing import Dict, List, Any

from fastapi import WebSocket

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
        if user_id in self.active_connections:
            # Send to ALL of the user's active connections
            dead_connections = []
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    # Connection died unexpectedly — mark for cleanup
                    dead_connections.append(connection)

            # Remove any dead connections
            for dead in dead_connections:
                self.active_connections[user_id].remove(dead)
            if user_id in self.active_connections and not self.active_connections[user_id]:
                del self.active_connections[user_id]

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


# ── Singleton Instance ─────────────────────────────────────────────────
# Import this from anywhere in the app:
#   from app.core.notifications import manager
manager = ConnectionManager()
