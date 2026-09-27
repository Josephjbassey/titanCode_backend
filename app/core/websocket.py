"""
WebSocket module compatibility shim.
Re-exports ConnectionManager and manager from app.core.notifications.
"""
from app.core.notifications import ConnectionManager, manager

__all__ = ["ConnectionManager", "manager"]
