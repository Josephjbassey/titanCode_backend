"""
TitanCode Technologies — Projects Endpoints
=============================================
This module handles CRUD operations for client projects.
Projects represent paid work for external clients.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing import Any, List
from sqlalchemy import func

from app.db.database import get_db
from app.db.models import Project, User, project_members
from app.schemas.project import (
    Project as ProjectSchema,
    ProjectCreate,
    ProjectListResponse,
    ProjectUpdate,
)
from app.api.v1.endpoints.auth import get_current_user, RoleChecker
from app.services.project_service import ProjectService

# Create a new router instance
router = APIRouter()

# ── RBAC Dependencies ──────────────────────────────────────────────────
allow_managers = RoleChecker(["CEO", "Admin", "Manager"])
allow_admin = RoleChecker(["CEO", "Admin"])


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
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    updated_project = await ProjectService.update_project(db, project, project_in)
    updated_project.member_ids = [m.id for m in updated_project.members]
    return updated_project


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
