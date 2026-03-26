"""
TitanCode Technologies — Applications Endpoints
=================================================
This module handles the membership application workflow. Users apply to
join a department, and managers review (approve/reject) the applications.

Workflow:
    1. A user submits an application   → POST /applications/apply
    2. A manager views all pending     → GET  /applications
    3. A manager approves it           → PUT  /applications/approve
       (this also updates the user's status and assigns them to the department)
    4. Or a manager rejects it         → PUT  /applications/reject

Who can do what (RBAC):
    • Any authenticated user               → Can submit an application.
    • CEO, Admin, Manager                  → Can list and review applications.

API Routes (all prefixed with /api/v1/applications):
    POST /apply    — Submit a new membership application
    GET  /         — List all applications
    PUT  /approve  — Approve a pending application
    PUT  /reject   — Reject a pending application
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Any, List

from app.core.notifications import manager as notification_manager

from app.db.database import get_db
from app.db.models import Application, User
from app.schemas.application import (
    Application as AppSchema,
    ApplicationCreate,
)
from app.api.v1.endpoints.auth import get_current_user, RoleChecker

# Create a new router instance — this is registered in main.py
router = APIRouter()

# ── RBAC Dependencies ──────────────────────────────────────────────────
# Only CEO, Admin, and Manager can review applications
allow_managers = RoleChecker(["CEO", "Admin", "Manager"])


# ═══════════════════════════════════════════════════════════════════════
# POST /applications/apply — Submit a new application
# ═══════════════════════════════════════════════════════════════════════
@router.post("/apply", response_model=AppSchema, status_code=status.HTTP_201_CREATED)
async def apply_to_department(
    app_in: ApplicationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Submit a membership application to join a department.

    The system checks for duplicate pending applications — a user cannot
    apply to the same department twice while a previous application
    is still pending.

    Args:
        app_in: The application data including user_id, department_id,
                and optional github_url/portfolio links.

    Returns:
        AppSchema: The newly created application with status "pending".

    Raises:
        HTTPException 400: If the user already has a pending application
                           for the same department.
    """
    # Step 1: Check for duplicate pending applications
    # We don't want the same user to apply twice to the same department
    result = await db.execute(
        select(Application).where(
            Application.user_id == app_in.user_id,
            Application.department_id == app_in.department_id,
            Application.status == "pending",  # Only block if still pending
        )
    )
    if result.scalars().first():
        raise HTTPException(
            status_code=400,
            detail="You already have a pending application for this department",
        )

    # Step 2: Create the application record
    application = Application(**app_in.model_dump())
    db.add(application)
    await db.commit()
    await db.refresh(application)
    return application


# ═══════════════════════════════════════════════════════════════════════
# GET /applications — List all applications
# ═══════════════════════════════════════════════════════════════════════
@router.get("/", response_model=List[AppSchema])
async def list_applications(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_managers),
) -> Any:
    """
    List all membership applications.

    Managers use this to see who has applied and their current status
    (pending, approved, rejected).

    Returns:
        List[AppSchema]: All application records in the database.
    """
    # SELECT * FROM applications
    result = await db.execute(select(Application))
    return result.scalars().all()


# ═══════════════════════════════════════════════════════════════════════
# PUT /applications/approve — Approve an application
# ═══════════════════════════════════════════════════════════════════════
@router.put("/approve", response_model=AppSchema)
async def approve_application(
    application_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allow_managers),
) -> Any:
    """
    Approve a pending membership application.

    This does TWO things:
        1. Updates the application → status = "approved", records who
           approved it and when.
        2. Updates the applicant's USER record → status = "approved",
           assigns them to the requested department.

    Args:
        application_id: The ID of the application to approve (query param).

    Returns:
        AppSchema: The updated application record.

    Raises:
        HTTPException 404: If the application doesn't exist.
        HTTPException 400: If the application was already reviewed.
    """
    # Step 1: Find the application
    result = await db.execute(
        select(Application).where(Application.id == application_id)
    )
    application = result.scalars().first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    # Step 2: Ensure it hasn't already been reviewed
    if application.status != "pending":
        raise HTTPException(
            status_code=400,
            detail="Application has already been reviewed",
        )

    # Step 3: Update the application record
    application.status = "approved"
    application.reviewed_by = current_user.id          # Who approved it
    application.reviewed_at = datetime.now(timezone.utc)  # When it was approved

    # Step 4: Update the applicant's user record
    # This is the key business logic — when approved, the user becomes
    # an active member of the department they applied to.
    user_result = await db.execute(
        select(User).where(User.id == application.user_id)
    )
    applicant = user_result.scalars().first()
    if applicant:
        applicant.status = "approved"                  # Activate the user
        applicant.department_id = application.department_id  # Assign to dept

    # Step 5: Save all changes in one transaction
    await db.commit()
    await db.refresh(application)

    # Step 6: Send a real-time notification to the applicant
    await notification_manager.send_personal_message(
        user_id=application.user_id,
        message={
            "type": "approval",
            "title": "Application Approved ✅",
            "message": "Congratulations! Your application has been approved. Welcome to the team!",
        },
    )

    return application


# ═══════════════════════════════════════════════════════════════════════
# PUT /applications/reject — Reject an application
# ═══════════════════════════════════════════════════════════════════════
@router.put("/reject", response_model=AppSchema)
async def reject_application(
    application_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allow_managers),
) -> Any:
    """
    Reject a pending membership application.

    Unlike approval, rejection does NOT modify the applicant's user
    record — they remain in their current state and can reapply later.

    Args:
        application_id: The ID of the application to reject (query param).

    Returns:
        AppSchema: The updated application record with status "rejected".

    Raises:
        HTTPException 404: If the application doesn't exist.
        HTTPException 400: If the application was already reviewed.
    """
    # Step 1: Find the application
    result = await db.execute(
        select(Application).where(Application.id == application_id)
    )
    application = result.scalars().first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    # Step 2: Ensure it hasn't already been reviewed
    if application.status != "pending":
        raise HTTPException(
            status_code=400,
            detail="Application has already been reviewed",
        )

    # Step 3: Mark as rejected and record who/when
    application.status = "rejected"
    application.reviewed_by = current_user.id
    application.reviewed_at = datetime.now(timezone.utc)

    # Step 4: Save changes
    await db.commit()
    await db.refresh(application)

    # Step 5: Send a real-time notification to the applicant
    await notification_manager.send_personal_message(
        user_id=application.user_id,
        message={
            "type": "approval",
            "title": "Application Rejected ❌",
            "message": "Your application has been reviewed and was not approved at this time. You may reapply.",
        },
    )

    return application
