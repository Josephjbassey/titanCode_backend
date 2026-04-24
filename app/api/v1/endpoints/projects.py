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
from app.tasks.financials import process_payout_calculation
from app.core.security import get_password_hash
import secrets
from app.core.email import send_email

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
) -> Any:
    """
    Unified "Hire Us" Form — Captures Project Request & Auto-Registers Client.

    This endpoint is PUBLIC to reduce conversion friction.
    1. It checks if a user with the provided email exists.
    2. If not, it creates a new "Client" account in the background.
    3. It creates a pending Project linked to that client.
    4. It notifies HR to initiate manual outreach.
    """
    # Step 1: Check-or-Create the Client Account
    stmt = select(User).where(User.email == project_in.client_email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user:
        # Auto-generate a secure random password for the background account
        temp_password = secrets.token_urlsafe(16)
        user = User(
            email=project_in.client_email,
            full_name=project_in.client_full_name,
            phone_number=project_in.client_phone,
            password_hash=get_password_hash(temp_password),
            role="Client",
            status="approved", # Activated for project tracking
        )
        db.add(user)
        await db.flush() # Get user.id

    # Step 2: Create the Project
    project_data = project_in.model_dump(exclude={"client_email", "client_full_name", "client_phone"})
    project = Project(
        **project_data,
        client_id=user.id,
        status="pending"
    )
    db.add(project)
    await db.commit()
    await db.refresh(project, attribute_names=["members"])

    # Step 3: Notify HR
    await send_email(
        recipient_email="hr@titancode.tech",
        subject=f"🔥 NEW LEAD: {project.name}",
        body=(
            f"Hello HR Team,\n\n"
            f"A new client has used the Unified Hire Us form!\n\n"
            f"CLIENT DETAILS:\n"
            f"- Name: {project_in.client_full_name}\n"
            f"- Email: {project_in.client_email}\n"
            f"- Phone: {project_in.client_phone or "Not provided"}\n\n"
            f"PROJECT DETAILS:\n"
            f"- Title: {project.name}\n"
            f"- Budget: ${project.budget}\n"
            f"- Description: {project.description}\n\n"
            "ACTION REQUIRED:\n"
            "Please contact the client via WhatsApp/Email to finalize the project scope."
        )
    )

    return project
