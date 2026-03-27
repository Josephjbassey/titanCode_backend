"""
TitanCode Technologies — Meetings Endpoints
==========================================
This module handles meeting management and scheduling. It provides endpoints
for creating, listing, updating, and cancelling meetings between team 
members and clients.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Any, List
from datetime import datetime

from app.core.notifications import manager as notification_manager
from app.core.email import send_email
from app.db.database import get_db
from app.db.models import Meeting, User
from app.schemas.meeting import Meeting as MeetingSchema, MeetingCreate, MeetingUpdate
from app.api.v1.endpoints.auth import get_current_user, RoleChecker

# Create the router instance
router = APIRouter()

# RBAC: Only CEO, Admin, and Managers can schedule or cancel meetings
allow_managers = RoleChecker(["CEO", "Admin", "Manager"])


# ═══════════════════════════════════════════════════════════════════════
# POST /meetings/create — Schedule a new meeting
# ═══════════════════════════════════════════════════════════════════════
@router.post("/create", response_model=MeetingSchema, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    meeting_in: MeetingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allow_managers),
) -> Any:
    """
    Schedule a new meeting and notify the involved client.

    Args:
        meeting_in: Meeting data (title, scheduled_at, etc.)
        db: Database session.
        current_user: The manager scheduling the meeting.

    Returns:
        The newly created meeting record.
    """
    # Create the meeting record
    meeting_data = meeting_in.model_dump()
    
    # Auto-generate a meeting link if not provided
    if not meeting_data.get("meeting_link"):
        # Automated Meeting Link generation (simulating a provider like Agora/WebRTC or Google Meet)
        meeting_data["meeting_link"] = f"https://meet.titancode.tech/{meeting_data['title'].lower().replace(' ', '-')}-{meeting_in.scheduled_at.strftime('%m%d')}"

    meeting = Meeting(**meeting_data, created_by=current_user.id)
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)

    # 1. Send WebSocket notification to the client if assigned
    if meeting.client_id:
        await notification_manager.send_personal_message(
            user_id=meeting.client_id,
            message={
                "type": "meeting",
                "title": f"New Meeting: {meeting.title} 📅",
                "message": (
                    f"A new meeting has been scheduled for "
                    f"{meeting.scheduled_at.strftime('%Y-%m-%d %H:%M')}. "
                    "Please check your dashboard for details."
                ),
                "meeting_id": meeting.id,
            },
        )
        
        # 2. Send EMAIL notification to the client
        result = await db.execute(select(User).where(User.id == meeting.client_id))
        client = result.scalars().first()
        if client and client.email:
            await send_email(
                recipient_email=client.email,
                subject=f"New Meeting Scheduled: {meeting.title}",
                body=(
                    f"Hello {client.full_name},\n\n"
                    f"A new meeting has been scheduled for you: {meeting.title}.\n"
                    f"Scheduled at: {meeting.scheduled_at.strftime('%Y-%m-%d %H:%M')}\n"
                    f"Meeting Link: {meeting.meeting_link}\n\n"
                    "We look forward to seeing you there!\n"
                    "— TitanCode Technologies Team"
                )
            )

    return meeting


# ═══════════════════════════════════════════════════════════════════════
# GET /meetings — List all meetings
# ═══════════════════════════════════════════════════════════════════════
@router.get("/", response_model=List[MeetingSchema])
async def list_meetings(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Any:
    """
    List all meetings in the system.
    
    In a real-world scenario, we would filter this by department or 
    user involvement, but for the MVP we show all.
    """
    result = await db.execute(select(Meeting).order_by(Meeting.scheduled_at.asc()))
    return result.scalars().all()


# ═══════════════════════════════════════════════════════════════════════
# GET /meetings/{meeting_id} — Get meeting details
# ═══════════════════════════════════════════════════════════════════════
@router.get("/{meeting_id}", response_model=MeetingSchema)
async def get_meeting(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Any:
    """Retrieve details for a specific meeting."""
    result = await db.execute(select(Meeting).where(Meeting.id == meeting_id))
    meeting = result.scalars().first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


# ═══════════════════════════════════════════════════════════════════════
# PUT /meetings/update — Update a meeting
# ═══════════════════════════════════════════════════════════════════════
@router.put("/update", response_model=MeetingSchema)
async def update_meeting(
    meeting_id: int,
    meeting_in: MeetingUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_managers),
) -> Any:
    """Update scheduling, links, or status for a meeting."""
    result = await db.execute(select(Meeting).where(Meeting.id == meeting_id))
    meeting = result.scalars().first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    update_data = meeting_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(meeting, field, value)

    await db.commit()
    await db.refresh(meeting)
    return meeting


# ═══════════════════════════════════════════════════════════════════════
# DELETE /meetings/{meeting_id} — Cancel a meeting
# ═══════════════════════════════════════════════════════════════════════
@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_meeting(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_managers),
) -> None:
    """
    Mark a meeting as cancelled. 
    We use soft-deletion (status update) to preserve audit history.
    """
    result = await db.execute(select(Meeting).where(Meeting.id == meeting_id))
    meeting = result.scalars().first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    meeting.status = "cancelled"
    await db.commit()

    # Notify the client about the cancellation
    if meeting.client_id:
        await notification_manager.send_personal_message(
            user_id=meeting.client_id,
            message={
                "type": "meeting",
                "title": "Meeting Cancelled ❌",
                "message": f"The scheduled meeting '{meeting.title}' has been cancelled.",
                "meeting_id": meeting.id,
            },
        )


# ═══════════════════════════════════════════════════════════════════════
# GET /meetings/{meeting_id}/join — Join a meeting
# ═══════════════════════════════════════════════════════════════════════
@router.get("/{meeting_id}/join")
async def join_meeting(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get the join link for a meeting and mark it as 'completed' or 'active'.
    
    This simulates the hand-off to a WebRTC/Agora session.
    """
    result = await db.execute(select(Meeting).where(Meeting.id == meeting_id))
    meeting = result.scalars().first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if meeting.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot join a cancelled meeting")

    # In a real system, we might mark it as 'in_progress' here
    # meeting.status = "in_progress"
    # await db.commit()

    return {
        "meeting_id": meeting.id,
        "title": meeting.title,
        "meeting_link": meeting.meeting_link,
        "message": "Redirecting to your video session..."
    }
