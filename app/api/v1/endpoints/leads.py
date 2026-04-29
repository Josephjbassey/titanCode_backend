from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.v1.endpoints.auth import RoleChecker, get_current_user
from app.core.config import settings
from app.core.tasks import enqueue_email_task
from app.db.database import get_db
from app.db.models import ClientInquiry, Project, User

router = APIRouter()
allow_admin = RoleChecker(["CEO", "Admin"])


class LeadCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str | None = None
    company: str | None = None
    project_type: str | None = None
    budget_range: str | None = None
    timeline: str | None = None
    description: str | None = None
    source: str | None = "direct"


class LeadUpdate(BaseModel):
    status: str | None = None
    follow_up_at: datetime | None = None
    lost_reason: str | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_lead(payload: LeadCreate, db: AsyncSession = Depends(get_db)) -> Any:
    inquiry = ClientInquiry(
        full_name=payload.name,
        email=payload.email,
        phone=payload.phone,
        company=payload.company,
        service_interest=payload.project_type,
        message=payload.description,
        status="new",
    )
    db.add(inquiry)
    await db.commit()
    await db.refresh(inquiry)

    hr_email = settings.EMAILS_FROM_EMAIL or "info@titancode.com"
    enqueue_email_task(
        recipient_email=hr_email,
        subject=f"New Lead: {payload.name}",
        body=f"Lead {payload.name} ({payload.email}) submitted.",
        html_content=f"<p>Lead <strong>{payload.name}</strong> ({payload.email}) submitted.</p>",
    )
    return inquiry


@router.get("")
async def list_leads(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> Any:
    filters = []
    if status_filter:
        filters.append(ClientInquiry.status == status_filter)
    total = (await db.execute(select(func.count(ClientInquiry.id)).where(*filters))).scalar_one()
    result = await db.execute(
        select(ClientInquiry).where(*filters).order_by(ClientInquiry.created_at.desc()).offset(offset).limit(limit)
    )
    items = result.scalars().all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{lead_id}")
async def get_lead(lead_id: int, db: AsyncSession = Depends(get_db), _current_user: User = Depends(allow_admin)) -> Any:
    result = await db.execute(select(ClientInquiry).where(ClientInquiry.id == lead_id))
    lead = result.scalars().first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.patch("/{lead_id}")
async def update_lead(lead_id: int, body: LeadUpdate, db: AsyncSession = Depends(get_db), _current_user: User = Depends(allow_admin)) -> Any:
    result = await db.execute(select(ClientInquiry).where(ClientInquiry.id == lead_id))
    lead = result.scalars().first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if body.status is not None:
        lead.status = body.status
    if body.lost_reason:
        lead.message = (lead.message or "") + f"\nLost reason: {body.lost_reason}"
    await db.commit()
    await db.refresh(lead)
    return lead


@router.post("/{lead_id}/convert-to-project", status_code=status.HTTP_201_CREATED)
async def convert_lead_to_project(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role not in ["CEO", "Admin", "Manager"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    res = await db.execute(select(ClientInquiry).where(ClientInquiry.id == lead_id))
    lead = res.scalars().first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.status in {"won", "converted"}:
        existing_client = (await db.execute(select(User).where(User.email == lead.email))).scalars().first()
        if existing_client:
            existing_project = (
                await db.execute(
                    select(Project)
                    .where(Project.client_id == existing_client.id)
                    .order_by(Project.created_at.desc())
                )
            ).scalars().first()
            if existing_project:
                raise HTTPException(
                    status_code=409,
                    detail=f"Lead already converted to project #{existing_project.id}",
                )

    user_res = await db.execute(select(User).where(User.email == lead.email))
    client = user_res.scalars().first()
    if not client:
        client = User(
            email=lead.email,
            full_name=lead.full_name,
            password_hash="!",
            role="Client",
            status="pending",
            phone_number=lead.phone,
        )
        db.add(client)
        await db.flush()

    project = Project(
        name=lead.company or f"Project for {lead.full_name}",
        description=lead.message,
        budget=0,
        client_id=client.id,
        status="pending",
    )
    db.add(project)
    lead.status = "converted"
    await db.commit()
    await db.refresh(project)
    return project
