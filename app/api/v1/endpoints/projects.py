"""
TitanCode Technologies — Projects Endpoints
=============================================
This module handles CRUD operations for client projects.
Projects represent paid work for external clients.
"""

import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing import Any, List
from sqlalchemy import func

from app.core.config import settings
from app.db.database import get_db
from app.db.models import AuditLog, Project, User, project_members, utcnow
from app.schemas.project import (
    Project as ProjectSchema,
    ProjectCreate,
    ProjectListResponse,
    ProjectUpdate,
)
from app.api.v1.endpoints.auth import get_current_user, RoleChecker
from app.services.project_service import ProjectService
from app.services.integration_service import IntegrationService
from app.core.notifications import manager as notification_manager
from app.core.email import send_email
from app.tasks.financials import process_payout_calculation

logger = logging.getLogger(__name__)

# Create a new router instance
router = APIRouter()

# ── RBAC Dependencies ──────────────────────────────────────────────────
allow_managers = RoleChecker(["CEO", "Admin", "Manager"])
allow_admin = RoleChecker(["CEO", "Admin"])


class ProjectCommentCreate(BaseModel):
    content: str


class ProjectCommentItem(BaseModel):
    id: int
    project_id: int
    content: str
    author_id: int | None = None
    author_name: str
    author_role: str
    author_avatar: str | None = None
    created_at: datetime



@router.post("/create", response_model=ProjectSchema, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_managers),
) -> Any:
    project = await ProjectService.create_project(db, project_in)
    project.member_ids = [m.id for m in project.members]
    return project


@router.get("/", response_model=ProjectListResponse)
async def list_projects(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    client_id: int | None = Query(None),
    member_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    filters = []
    if status_filter:
        filters.append(Project.status == status_filter)
    if client_id is not None:
        filters.append(Project.client_id == client_id)

    count_stmt = select(func.count(func.distinct(Project.id)))
    list_stmt = select(Project).options(selectinload(Project.members))
    if member_id is not None:
        count_stmt = count_stmt.select_from(Project).join(project_members, project_members.c.project_id == Project.id)
        list_stmt = list_stmt.join(project_members, project_members.c.project_id == Project.id)
        filters.append(project_members.c.user_id == member_id)
    else:
        count_stmt = count_stmt.select_from(Project)

    if current_user.role not in ["CEO", "Admin"]:
        list_stmt = list_stmt.outerjoin(project_members, project_members.c.project_id == Project.id)
        count_stmt = count_stmt.outerjoin(project_members, project_members.c.project_id == Project.id)
        filters.append((Project.client_id == current_user.id) | (project_members.c.user_id == current_user.id))

    count_stmt = count_stmt.where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = list_stmt.where(*filters).order_by(Project.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    items = result.scalars().unique().all()
    for project in items:
        project.member_ids = [member.id for member in project.members]
    next_offset = offset + limit if offset + limit < total else None
    return {"items": items, "total": total, "limit": limit, "offset": offset, "next_offset": next_offset}


@router.get("/{project_id}", response_model=ProjectSchema)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Any:
    result = await db.execute(select(Project).options(selectinload(Project.members)).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if _current_user.role not in ["CEO", "Admin"] and project.client_id != _current_user.id:
        # Check if they are a member
        if _current_user.id not in [m.id for m in project.members]:
            raise HTTPException(status_code=403, detail="Forbidden")

    project.member_ids = [m.id for m in project.members]
    return project


@router.put("/update", response_model=ProjectSchema)
async def update_project(
    project_id: int,
    project_in: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_managers),
) -> Any:
    result = await db.execute(
        select(Project).options(selectinload(Project.members)).where(Project.id == project_id)
    )
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Step 2: Apply only the fields that were sent (partial update)
    update_data = project_in.model_dump(exclude_unset=True, exclude={"member_ids"})
    
    # Financial Logic: Check if status is transitioning to COMPLETED
    trigger_payout = False
    if project_in.status == "completed" and project.status != "completed":
        trigger_payout = True

    for field, value in update_data.items():
        setattr(project, field, value)
        
    # Step 3: Update Members (M2M) if provided
    if project_in.member_ids is not None:
        res = await db.execute(select(User).where(User.id.in_(project_in.member_ids)))
        project.members = res.scalars().all()

    # Step 4: Save changes
    await db.commit()
    await db.refresh(project, attribute_names=["members"])
    
    # Step 5: Trigger Background Payout Task (Constraint #2 compliance) & Slack Notification
    if trigger_payout:
        process_payout_calculation.delay(project.id)
        slack_message = (
            f"🚀 *Project Completed:* {project.name}\n"
            f"*Budget:* ${float(project.budget):,.2f} USD\n"
            f"Automated squad payouts initiated via Paystack multi-currency settlement."
        )
        await IntegrationService.dispatch_slack_notification(db, slack_message)

    # Step 6: Notify client on status change
    if project_in.status and project.client_id:
        client_result = await db.execute(select(User).where(User.id == project.client_id))
        client = client_result.scalars().first()

        status_display = project.status.upper()
        status_messages = {
            "active": "Great news! Work on your project has officially started.",
            "completed": "Your project has been completed. Our team will follow up shortly.",
            "cancelled": "Your project has been cancelled. Please contact us for details.",
            "pending": "Your project is now under review.",
        }
        status_note = status_messages.get(project.status, f"Status changed to: {project.status}")

        # WebSocket real-time push
        await notification_manager.send_personal_message(
            user_id=project.client_id,
            message={
                "type": "project_update",
                "title": f"Project Update: {project.name}",
                "message": status_note,
                "project_id": project.id,
                "status": project.status,
            },
        )

        # Email notification to client
        if client and client.email:
            await send_email(
                recipient_email=client.email,
                subject=f"Project Update: {project.name} — {status_display}",
                body=(
                    f"Hi {client.full_name},\n\n"
                    f"{status_note}\n\n"
                    f"Project: {project.name}\n"
                    f"Status:  {status_display}\n\n"
                    f"If you have any questions, just reply to this email.\n\n"
                    f"— The TitanCode Team"
                ),
                html_content=(
                    f"<p>Hi <strong>{client.full_name}</strong>,</p>"
                    f"<p>{status_note}</p>"
                    f"<table style='border-collapse:collapse;font-family:sans-serif;'>"
                    f"<tr><td style='padding:6px;font-weight:bold;'>Project</td><td style='padding:6px;'>{project.name}</td></tr>"
                    f"<tr><td style='padding:6px;font-weight:bold;'>Status</td><td style='padding:6px;'>{status_display}</td></tr>"
                    f"</table>"
                    f"<p>If you have any questions, just reply to this email.</p>"
                    f"<br><p>— The TitanCode Team</p>"
                ),
            )

    # Step 7: Notify newly assigned team members
    if project_in.member_ids is not None:
        for member_id in project_in.member_ids:
            await notification_manager.send_personal_message(
                user_id=member_id,
                message={
                    "type": "project_assigned",
                    "title": "Added to Project 🚀",
                    "message": f"You've been added to the project: {project.name}",
                    "project_id": project.id,
                },
            )

    project.member_ids = [m.id for m in project.members]
    return project


@router.get("/{project_id}/comments", response_model=List[ProjectCommentItem])
async def get_project_comments(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Retrieve chronological discussion updates and team comments for a project.
    """
    result = await db.execute(
        select(Project).options(selectinload(Project.members)).where(Project.id == project_id)
    )
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.role not in ["CEO", "Admin"] and project.client_id != current_user.id:
        if current_user.id not in [m.id for m in project.members]:
            raise HTTPException(status_code=403, detail="Forbidden")

    stmt = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "project",
            AuditLog.target_id == project_id,
            AuditLog.action == "project_comment",
        )
        .order_by(AuditLog.created_at.asc())
    )
    comments_result = await db.execute(stmt)
    records = comments_result.scalars().all()

    items = []
    for r in records:
        details = r.details or {}
        items.append(
            ProjectCommentItem(
                id=r.id,
                project_id=project_id,
                content=details.get("message", ""),
                author_id=r.actor_id,
                author_name=details.get("author_name", "Team Member"),
                author_role=details.get("author_role", "Member"),
                author_avatar=details.get("author_avatar"),
                created_at=r.created_at,
            )
        )
    return items


@router.post("/{project_id}/comments", response_model=ProjectCommentItem, status_code=status.HTTP_201_CREATED)
async def add_project_comment(
    project_id: int,
    body: ProjectCommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Post a project discussion comment or milestone update.
    Dispatches to Slack workspace and triggers real-time WebSocket alerts to participants.
    """
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Comment content cannot be empty")

    result = await db.execute(
        select(Project).options(selectinload(Project.members)).where(Project.id == project_id)
    )
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.role not in ["CEO", "Admin"] and project.client_id != current_user.id:
        if current_user.id not in [m.id for m in project.members]:
            raise HTTPException(status_code=403, detail="Forbidden")

    author_name = current_user.full_name or current_user.email
    author_avatar = getattr(current_user, "avatar_url", None) or getattr(current_user, "avatar", None)
    comment_audit = AuditLog(
        actor_type="user",
        actor_id=current_user.id,
        action="project_comment",
        target_type="project",
        target_id=project.id,
        details={
            "message": content,
            "author_name": author_name,
            "author_role": current_user.role,
            "author_avatar": author_avatar,
        },
        created_at=utcnow(),
    )
    db.add(comment_audit)
    await db.commit()
    await db.refresh(comment_audit)

    # 1. Post to Slack via Integration Registry
    slack_message = (
        f"💬 *Project Update on {project.name}*\n"
        f"*From:* {author_name} ({current_user.role})\n"
        f">{content}"
    )
    await IntegrationService.dispatch_slack_notification(db, slack_message)

    # 2. Push WebSocket notification to project participants
    recipients = {m.id for m in project.members}
    if project.client_id:
        recipients.add(project.client_id)
    recipients.discard(current_user.id)
    for uid in recipients:
        await notification_manager.send_personal_message(
            user_id=uid,
            message={
                "type": "project_comment",
                "title": f"New update on {project.name}",
                "message": f"{author_name}: {content[:100]}",
                "project_id": project.id,
            },
        )

    return ProjectCommentItem(
        id=comment_audit.id,
        project_id=project.id,
        content=content,
        author_id=current_user.id,
        author_name=author_name,
        author_role=current_user.role,
        author_avatar=author_avatar,
        created_at=comment_audit.created_at,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await db.delete(project)
    await db.commit()


@router.post("/client/request-project", response_model=ProjectSchema, status_code=status.HTTP_201_CREATED)
async def request_project(
) -> Any:
    raise HTTPException(
        status_code=410,
        detail=(
            "Deprecated endpoint. Use POST /api/v1/leads as the canonical lead intake flow."
        ),
    )

