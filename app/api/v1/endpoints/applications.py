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
import secrets
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Any
from sqlalchemy import func

from app.core import security
from app.db.database import get_db
from app.db.models import Application, User, Department
from app.schemas.application import (
    Application as AppSchema,
    ApplicationCreate,
    ApplicationListResponse,
)
from app.api.v1.endpoints.auth import get_current_user, RoleChecker
from app.core.tasks import enqueue_email_task, enqueue_websocket_task

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
        app_in: The application data (department_id, github_url, portfolio).
        db: The database session.
        current_user: The authenticated user submitting the application.

    Returns:
        AppSchema: The newly created application with status "pending".

    Raises:
        HTTPException 404: If the department does not exist.
        HTTPException 400: If the user already has a pending application
                           for the same department.
    """
    # Step 1: Validate the department exists
    # If the user provides an invalid ID (like 0), we should return a clear 404
    stmt = select(Department).where(Department.id == app_in.department_id)
    dept_result = await db.execute(stmt)
    if not dept_result.scalars().first():
        raise HTTPException(
            status_code=404,
            detail=f"Department with ID {app_in.department_id} not found",
        )

    # Step 2: Check for duplicate pending applications
    # We use current_user.id to ensure security (users apply as themselves)
    result = await db.execute(
        select(Application).where(
            Application.user_id == current_user.id,
            Application.department_id == app_in.department_id,
            Application.status == "pending",
        )
    )
    if result.scalars().first():
        raise HTTPException(
            status_code=400,
            detail="You already have a pending application for this department",
        )

    # Step 3: Create the application record
    # We manually set user_id from current_user to prevent IDOR attacks
    application = Application(
        **app_in.model_dump(),
        user_id=current_user.id,
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)
    return application


# ═══════════════════════════════════════════════════════════════════════
# GET /applications — List all applications
# ═══════════════════════════════════════════════════════════════════════
@router.get("/", response_model=ApplicationListResponse)
async def list_applications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    department_id: int | None = Query(None),
    user_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    List all membership applications.

    Managers use this to see who has applied and their current status
    (pending, approved, rejected).

    Returns:
        List[AppSchema]: All application records in the database.
    """
    # SELECT * FROM applications
    filters = []
    if status_filter:
        filters.append(Application.status == status_filter)
    if department_id is not None:
        filters.append(Application.department_id == department_id)
    if user_id is not None:
        filters.append(Application.user_id == user_id)
    if current_user.role not in ["CEO", "Admin", "Manager"]:
        filters.append(Application.user_id == current_user.id)

    total = (await db.execute(select(func.count(Application.id)).where(*filters))).scalar_one()
    result = await db.execute(
        select(Application)
        .where(*filters)
        .order_by(Application.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = result.scalars().all()
    next_offset = offset + limit if offset + limit < total else None
    return {"items": items, "total": total, "limit": limit, "offset": offset, "next_offset": next_offset}


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

    # Step 6: Send a real-time WebSocket notification to the applicant
    enqueue_websocket_task(
        user_id=application.user_id,
        message={
            "type": "approval",
            "title": "Application Approved ✅",
            "message": "Congratulations! Your application has been approved. Welcome to the team!",
        },
    )

    # Step 7: Send email notification to the applicant
    if applicant and applicant.email:
        enqueue_email_task(
            recipient_email=applicant.email,
            subject="🎉 Your TitanCode Application Has Been Approved!",
            body=(
                f"Hi {applicant.full_name},\n\n"
                f"Congratulations! Your application to join TitanCode Technologies has been approved.\n\n"
                f"You are now an active member. Welcome to the team!\n\n"
                f"— The TitanCode Team"
            ),
            html_content=(
                f"<h2>Application Approved ✅</h2>"
                f"<p>Hi <strong>{applicant.full_name}</strong>,</p>"
                f"<p>Congratulations! Your application to join <strong>TitanCode Technologies</strong> "
                f"has been <strong>approved</strong>.</p>"
                f"<p>You are now an active member. Welcome to the team!</p>"
                f"<br><p>— The TitanCode Team</p>"
            ),
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

    # Step 5: Send a real-time WebSocket notification to the applicant
    enqueue_websocket_task(
        user_id=application.user_id,
        message={
            "type": "approval",
            "title": "Application Rejected ❌",
            "message": "Your application has been reviewed and was not approved at this time. You may reapply.",
        },
    )

    # Step 6: Send email notification to the applicant
    # Look up the applicant to get their name and email
    applicant_res = await db.execute(select(User).where(User.id == application.user_id))
    rejected_applicant = applicant_res.scalars().first()
    if rejected_applicant and rejected_applicant.email:
        enqueue_email_task(
            recipient_email=rejected_applicant.email,
            subject="Update on Your TitanCode Application",
            body=(
                f"Hi {rejected_applicant.full_name},\n\n"
                f"Thank you for applying to TitanCode Technologies. After careful review, "
                f"we are unable to approve your application at this time.\n\n"
                f"You are welcome to reapply in the future. We appreciate your interest!\n\n"
                f"— The TitanCode Team"
            ),
            html_content=(
                f"<p>Hi <strong>{rejected_applicant.full_name}</strong>,</p>"
                f"<p>Thank you for applying to <strong>TitanCode Technologies</strong>.</p>"
                f"<p>After careful review, we are unable to approve your application at this time. "
                f"You are welcome to reapply in the future.</p>"
                f"<br><p>— The TitanCode Team</p>"
            ),
        )

    return application


# ═══════════════════════════════════════════════════════════════════════
# POST /applications/public-apply — Public candidate intake flow
# ═══════════════════════════════════════════════════════════════════════
class PublicApplicationCreate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    name: str | None = None
    email: EmailStr
    phone_number: str | None = None
    phone: str | None = None
    country: str | None = "Nigeria"
    department_name: str | None = None
    department_id: int | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    portfolio: str | None = None
    about: str | None = None


@router.post("/public-apply", status_code=status.HTTP_201_CREATED)
async def public_application(
    payload: PublicApplicationCreate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Public zero-friction application intake for prospective engineering members.
    Creates an applicant account if none exists and records the application for HR/Manager review.
    """
    # 0. Resolve applicant naming & contact info
    f_name = payload.first_name
    l_name = payload.last_name
    if not f_name:
        raw_name = payload.full_name or payload.name or "Candidate"
        parts = raw_name.strip().split(" ", 1)
        f_name = parts[0]
        l_name = parts[1] if len(parts) > 1 else ""
    elif not l_name:
        l_name = ""

    full_name = f"{f_name} {l_name}".strip()
    phone_number = payload.phone_number or payload.phone
    portfolio_link = payload.portfolio_url or payload.portfolio or payload.linkedin_url

    # 1. Resolve target department
    dept = None
    if payload.department_id:
        dept = (await db.execute(select(Department).where(Department.id == payload.department_id))).scalars().first()
    elif payload.department_name:
        dept = (await db.execute(
            select(Department).where(Department.name.ilike(f"%{payload.department_name.strip()}%"))
        )).scalars().first()

    if not dept:
        # Fallback to the first existing department in database
        dept = (await db.execute(select(Department))).scalars().first()
        if not dept:
            # Bootstrap a default Engineering department if DB has no departments
            dept = Department(name="Engineering", description="Core Platform Engineering Division")
            db.add(dept)
            await db.flush()

    # 2. Check user record
    stmt = select(User).where(User.email == payload.email)
    user = (await db.execute(stmt)).scalars().first()

    if user:
        if user.role in ["CEO", "Admin", "Manager", "Member"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An active account with this email already exists. Please sign in to your dashboard.",
            )
        # Check if already has a pending application
        existing_app = (await db.execute(
            select(Application).where(
                Application.user_id == user.id,
                Application.status == "pending",
            )
        )).scalars().first()
        if existing_app:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You already have a pending application. Our team is currently reviewing your profile.",
            )
    else:
        # Create shadow/pending applicant user
        temp_password = secrets.token_urlsafe(16)
        user = User(
            full_name=full_name,
            email=payload.email,
            password_hash=security.get_password_hash(temp_password),
            role="Applicant",
            status="pending",
            country=payload.country or "Nigeria",
            phone_number=phone_number,
            github_url=payload.github_url,
            portfolio_url=portfolio_link,
            department_id=dept.id,
        )
        db.add(user)
        await db.flush()

    # 3. Create the Application record
    application = Application(
        user_id=user.id,
        department_id=dept.id,
        github_url=payload.github_url,
        portfolio=portfolio_link,
        status="pending",
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)

    # 4. Notify applicant via email
    enqueue_email_task(
        recipient_email=payload.email,
        subject="Your Application to TitanCode Technologies Has Been Received",
        body=(
            f"Hi {f_name},\n\n"
            f"Thank you for applying to join the {dept.name} department at TitanCode Technologies!\n\n"
            f"Our technical leads and HR team are reviewing your qualifications and portfolio. "
            f"We will be in touch with next steps regarding technical evaluation.\n\n"
            f"— The TitanCode Talent Team"
        ),
        html_content=(
            f"<p>Hi <strong>{f_name}</strong>,</p>"
            f"<p>Thank you for applying to join the <strong>{dept.name}</strong> department at TitanCode Technologies!</p>"
            f"<p>Our technical leads and HR team are reviewing your qualifications and portfolio. "
            f"We will be in touch shortly regarding next steps.</p>"
            f"<br><p>— The TitanCode Talent Team</p>"
        ),
    )

    # 5. Notify HR/Managers via WebSocket & internal email
    enqueue_websocket_task(
        user_id=1,  # Broadcast to admin/HR
        message={
            "type": "new_application",
            "title": f"New Candidate: {user.full_name} 💼",
            "message": f"Applied for {dept.name}. Portfolio and GitHub ready for review.",
            "application_id": application.id,
        },
    )

    return {
        "success": True,
        "message": "Application submitted successfully! Our team will review your portfolio.",
        "application_id": application.id,
    }

