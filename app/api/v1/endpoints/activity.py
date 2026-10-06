"""
TitanCode Technologies — Activity Feed Endpoints
=================================================
Provides activity feed aggregation for dashboards and team workspace updates.
Aggregates recent events from Tasks, Projects, and AuditLogs.
"""

from typing import Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.db.models import AuditLog, Task, Project, User
from app.api.v1.endpoints.auth import get_current_user

router = APIRouter()


class ActivityItem(BaseModel):
    id: int
    text: str
    timestamp: str
    author: str
    avatar: Optional[str] = None


class ActivityFeedResponse(BaseModel):
    items: List[ActivityItem]


@router.get("/feed", response_model=ActivityFeedResponse)
async def get_activity_feed(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get recent workspace activities aggregated from tasks, projects, and audit logs.
    Available to all authenticated team members and clients.
    """
    items: List[dict] = []

    # 1. Fetch recent tasks with assigned user
    task_stmt = (
        select(Task)
        .options(selectinload(Task.assignee))
        .order_by(Task.created_at.desc())
        .limit(limit)
    )
    task_res = await db.execute(task_stmt)
    tasks = task_res.scalars().all()
    for t in tasks:
        author_name = t.assignee.full_name if t.assignee else "Team Member"
        author_avatar = t.assignee.avatar_url if t.assignee else None
        ts = t.created_at.isoformat() if t.created_at else datetime.utcnow().isoformat()
        status_label = t.status.replace("_", " ").title()
        items.append({
            "id": t.id * 1000 + 1,
            "text": f"Task '{t.task_title}' is {status_label}",
            "timestamp": ts,
            "author": author_name,
            "avatar": author_avatar,
            "_raw_time": t.created_at or datetime.min,
        })

    # 2. Fetch recent projects with client info
    proj_stmt = (
        select(Project, User)
        .outerjoin(User, Project.client_id == User.id)
        .order_by(Project.created_at.desc())
        .limit(limit)
    )
    proj_res = await db.execute(proj_stmt)
    for p, u in proj_res.all():
        author_name = u.full_name if u else "TitanCode Client"
        author_avatar = u.avatar_url if u else None
        ts = p.created_at.isoformat() if p.created_at else datetime.utcnow().isoformat()
        status_label = p.status.replace("_", " ").title()
        items.append({
            "id": p.id * 1000 + 2,
            "text": f"Project '{p.name}' status set to {status_label}",
            "timestamp": ts,
            "author": author_name,
            "avatar": author_avatar,
            "_raw_time": p.created_at or datetime.min,
        })

    # 3. Fetch recent audit logs
    audit_stmt = (
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    audit_res = await db.execute(audit_stmt)
    audit_logs = audit_res.scalars().all()
    for log in audit_logs:
        ts = log.created_at.isoformat() if log.created_at else datetime.utcnow().isoformat()
        action_clean = log.action.replace("_", " ").title()
        target = f"{log.target_type.capitalize()} #{log.target_id}"
        items.append({
            "id": log.id * 1000 + 3,
            "text": f"{action_clean} on {target}",
            "timestamp": ts,
            "author": f"{log.actor_type.capitalize()} Action",
            "avatar": None,
            "_raw_time": log.created_at or datetime.min,
        })

    # Sort all by datetime descending
    items.sort(key=lambda x: x["_raw_time"], reverse=True)

    # Slice to limit
    trimmed = items[:limit]

    return {
        "items": [
            ActivityItem(
                id=item["id"],
                text=item["text"],
                timestamp=item["timestamp"],
                author=item["author"],
                avatar=item["avatar"],
            )
            for item in trimmed
        ]
    }
