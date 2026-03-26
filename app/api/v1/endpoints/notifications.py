"""
TitanCode Technologies — WebSocket Notification Endpoints
==========================================================
This module provides the WebSocket endpoint for real-time notifications.

How it works:
    1. The client connects to `ws://host/api/v1/notifications/ws?token=<JWT>`
    2. The server validates the JWT to identify the user.
    3. The connection is registered in the ConnectionManager.
    4. While connected, the user receives JSON messages pushed by the server
       whenever relevant events occur (approvals, wallet transactions, etc).
    5. The client can also send messages (e.g. "ping") to keep the connection alive.

Connection Flow:
    ┌────────┐  ws://host/ws?token=xxx    ┌──────────┐
    │ Client │ ──────────────────────────▶│  Server  │
    │        │                            │          │
    │        │  {"type":"approval",...}   │          │
    │        │ ◀──────────────────────────│          │
    │        │                            │          │
    │        │  "ping"                    │          │
    │        │ ──────────────────────────▶│ (ignored)│
    └────────┘                            └──────────┘

Security:
    - JWT is passed as a query parameter (WebSockets don't support headers
      during the handshake in browsers).
    - Invalid or expired tokens result in immediate connection closure.
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

import jwt
from jwt.exceptions import InvalidTokenError

from app.core.config import settings
from app.core.notifications import manager
from app.db.database import AsyncSessionLocal
from app.db.models import User

# Logger for WebSocket events
logger = logging.getLogger(__name__)

# Create the router — all routes here will be prefixed with /api/v1/notifications
router = APIRouter()


async def authenticate_websocket(token: str) -> int | None:
    """
    Validate a JWT token and return the user ID.

    This is a standalone function (not a FastAPI dependency) because
    WebSocket endpoints don't support the standard Depends() chain
    for the initial connection handshake.

    Args:
        token: The JWT access token string from the query parameter.

    Returns:
        The user's ID (int) if the token is valid, or None if invalid.
    """
    try:
        # Decode the JWT using the same secret and algorithm as the rest of the app
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        # Extract the user ID from the "sub" (subject) claim
        user_id: str = payload.get("sub")
        if user_id is None:
            return None

        # Verify the user actually exists in the database
        async with AsyncSessionLocal() as db:
            stmt = select(User).where(User.id == int(user_id))
            result = await db.execute(stmt)
            user = result.scalars().first()
            if user is None:
                return None

        return int(user_id)

    except (InvalidTokenError, ValueError):
        # Token is expired, malformed, or user_id isn't a valid int
        return None


# ═══════════════════════════════════════════════════════════════════════
# WEBSOCKET ENDPOINT: Real-time notification stream
# ═══════════════════════════════════════════════════════════════════════
@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token for authentication"),
):
    """
    WebSocket endpoint for receiving real-time notifications.

    Connection:
        ws://localhost:8000/api/v1/notifications/ws?token=<your_jwt_here>

    Messages Received (JSON):
        {
            "type": "approval" | "wallet" | "task" | "system",
            "title": "Short title of the event",
            "message": "Detailed description of what happened"
        }

    Authentication:
        The JWT token must be passed as the `token` query parameter.
        If the token is invalid or expired, the connection is closed
        immediately with code 4001 (Unauthorized).

    Keepalive:
        Clients can send any text message (e.g. "ping") to keep the
        connection alive. The server echoes it back as a JSON pong.
    """
    # ── Step 1: Authenticate the user ──────────────────────────────────
    user_id = await authenticate_websocket(token)
    if user_id is None:
        # Reject the connection with a custom close code
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    # ── Step 2: Register the connection ────────────────────────────────
    await manager.connect(websocket, user_id)
    logger.info(f"WebSocket connected for user {user_id}")

    try:
        # ── Step 3: Listen for client messages ─────────────────────────
        # The main loop keeps the connection open. Incoming messages from
        # the client are mostly used for keepalive ("ping").
        while True:
            data = await websocket.receive_text()

            # Echo back as a pong to confirm the connection is alive
            if data.lower() == "ping":
                await websocket.send_json({
                    "type": "system",
                    "title": "Pong",
                    "message": "Connection is alive",
                })
            else:
                # For any other message, acknowledge receipt
                await websocket.send_json({
                    "type": "system",
                    "title": "Received",
                    "message": f"Server received: {data}",
                })

    except WebSocketDisconnect:
        # ── Step 4: Clean up on disconnect ─────────────────────────────
        manager.disconnect(websocket, user_id)
        logger.info(f"WebSocket disconnected for user {user_id}")
