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
from app.core.tasks import enqueue_email_task, enqueue_websocket_task
from app.tasks.financials import process_payout_calculation

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
    # Step 1: Unpack initial project data (exclude M2M fields)
    project_data = project_in.model_dump(exclude={"member_ids"})
    project = Project(**project_data)
    
    # Step 2: Handle M2M Member Assignment
    if project_in.member_ids:
        res = await db.execute(select(User).where(User.id.in_(project_in.member_ids)))
        project.members = res.scalars().all()

    db.add(project)
    await db.commit()
    await db.refresh(project, attribute_names=["members"])
    
    # Step 3: Populate member_ids for the response schema
    project.member_ids = [m.id for m in project.members]
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

    # BOLA CHECK: Only owner/admin or the assigned client can view
    if _current_user.role not in ["CEO", "Admin"] and project.client_id != _current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: You do not have permission to access this project",
        )

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
    
    # Step 5: Trigger Background Payout Task (Constraint #2 compliance)
    if trigger_payout:
        process_payout_calculation.delay(project.id)

    # Step 6: Notify client on status change
    if project_in.status and project.client_id:
        # Fetch client info for the email
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
        enqueue_websocket_task(
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
            enqueue_email_task(
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
            enqueue_websocket_task(
                user_id=member_id,
                message={
                    "type": "project_assigned",
                    "title": "Added to Project 🚀",
                    "message": f"You've been added to the project: {project.name}",
                    "project_id": project.id,
                },
            )

    # Populate member_ids for the response
    project.member_ids = [m.id for m in project.members]
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
    await db.refresh(project, attribute_names=["members"])
    return project
