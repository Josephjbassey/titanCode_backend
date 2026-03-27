"""
TitanCode Technologies — Projects Endpoints
=============================================
This module handles CRUD operations for client projects.
Projects represent paid work for external clients.

Status lifecycle:
    pending → active → completed
                     → cancelled

Who can do what (RBAC):
    • Any authenticated user → Can view projects.
    • CEO, Admin, Manager    → Can create and update projects.
    • CEO, Admin             → Can delete projects.

API Routes (all prefixed with /api/v1/projects):
    POST   /create        — Create a new project
    GET    /              — List all projects
    GET    /{project_id}  — Get a single project by ID
    PUT    /update        — Update a project
    DELETE /{project_id}  — Delete a project
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Any, List

from app.db.database import get_db
from app.db.models import Project, User
from app.schemas.project import (
    Project as ProjectSchema,
    ProjectCreate,
    ProjectUpdate,
    ProjectRequest,
)
from app.api.v1.endpoints.auth import get_current_user, RoleChecker

# Create a new router instance — this is registered in main.py
router = APIRouter()

# ── RBAC Dependencies ──────────────────────────────────────────────────
allow_managers = RoleChecker(["CEO", "Admin", "Manager"])
allow_admin = RoleChecker(["CEO", "Admin"])


# ═══════════════════════════════════════════════════════════════════════
# POST /projects/create — Create a new project
# ═══════════════════════════════════════════════════════════════════════
@router.post("/create", response_model=ProjectSchema, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_managers),
) -> Any:
    """
    Create a new client project.

    A project starts with status "pending" by default (set in the
    database model). It should be moved to "active" once work begins.

    Args:
        project_in: Project data from the request body (name, description,
                    client_id, budget, deadline).

    Returns:
        ProjectSchema: The newly created project record.
    """
    # Unpack the Pydantic schema into an SQLAlchemy model and save
    project = Project(**project_in.model_dump())
    db.add(project)
    await db.commit()
    await db.refresh(project)  # Reload to get auto-generated fields (id, created_at)
    return project


# ═══════════════════════════════════════════════════════════════════════
# GET /projects — List all projects
# ═══════════════════════════════════════════════════════════════════════
@router.get("/", response_model=List[ProjectSchema])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Any:
    """
    List all projects in the system.

    Any authenticated user can view projects — this allows team members
    to see what work is available or in progress.

    Returns:
        List[ProjectSchema]: All project records in the database.
    """
    # SELECT * FROM projects
    result = await db.execute(select(Project))
    return result.scalars().all()


# ═══════════════════════════════════════════════════════════════════════
# GET /projects/{project_id} — Get a single project
# ═══════════════════════════════════════════════════════════════════════
@router.get("/{project_id}", response_model=ProjectSchema)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Any:
    """
    Retrieve a single project by its database ID.

    Args:
        project_id: The integer primary key of the project.

    Returns:
        ProjectSchema: The project record if found.

    Raises:
        HTTPException 404: If no project exists with the given ID.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# ═══════════════════════════════════════════════════════════════════════
# PUT /projects/update — Update a project
# ═══════════════════════════════════════════════════════════════════════
@router.put("/update", response_model=ProjectSchema)
async def update_project(
    project_id: int,
    project_in: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_managers),
) -> Any:
    """
    Update an existing project (partial update).

    Common use cases:
        • Change status from "pending" to "active" when work starts.
        • Extend the deadline or adjust the budget.
        • Mark as "completed" or "cancelled".

    Args:
        project_id: The ID of the project to update (query parameter).
        project_in: The fields to update (request body).

    Returns:
        ProjectSchema: The updated project record.

    Raises:
        HTTPException 404: If no project exists with the given ID.
    """
    # Step 1: Find the project
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Step 2: Apply only the fields that were sent (partial update)
    update_data = project_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)

    # Step 3: Save changes
    await db.commit()
    await db.refresh(project)
    return project


# ═══════════════════════════════════════════════════════════════════════
# DELETE /projects/{project_id} — Delete a project
# ═══════════════════════════════════════════════════════════════════════
@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> None:
    """
    Delete a project permanently.

    ⚠️  CEO and Admin only — this is a destructive action.
    All tasks associated with this project should be reassigned or
    deleted first to avoid orphaned records.

    Args:
        project_id: The ID of the project to delete.

    Raises:
        HTTPException 404: If no project exists with the given ID.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await db.delete(project)
    await db.commit()


# ═══════════════════════════════════════════════════════════════════════
# POST /projects/client/request-project — Request a new project (External)
# ═══════════════════════════════════════════════════════════════════════
@router.post("/client/request-project", response_model=ProjectSchema, status_code=status.HTTP_201_CREATED)
async def request_project(
    project_in: ProjectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Endpoint for external clients to request a new project.

    This differs from /create because it automatically assigns the
    client_id to the authenticated user submitting the request.

    Args:
        project_in: Project details (name, description, budget, deadline).

    Returns:
        ProjectSchema: The newly created "pending" project record.
    """
    project = Project(
        **project_in.model_dump(),
        client_id=current_user.id,
        status="pending"
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project
