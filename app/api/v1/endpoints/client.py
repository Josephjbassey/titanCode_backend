"""
TitanCode Technologies — Client Onboarding Endpoints
=====================================================
This module handles the full client intake and onboarding flow, implementing
the PM's decision to use a manual-first approach:

  1. Prospect fills the "Hire Us" form (no account needed).
  2. HR receives an email and contacts them manually.
  3. After a consultation, admin sends a magic link to the client.
  4. Client clicks the link → account instantly activated, no re-filling forms.

Endpoints:
    POST /client/hire-us             — Public form submission (no auth)
    POST /client/send-magic-link     — Admin sends magic link to a client email
    GET  /client/onboard             — Magic link activation (no auth, token in query)

RBAC:
    • hire-us       → anyone (public, no auth)
    • send-magic-link → CEO, Admin only
    • onboard       → anyone with a valid token (public)
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Any

from app.core import security
from app.core.config import settings
from app.core.email import send_email
from app.db.database import get_db
from app.db.models import ClientInquiry as ClientInquiryModel, User
from app.schemas.client import (
    ClientInquiry,
    ClientInquiryCreate,
    SendMagicLinkRequest,
    MagicLinkOnboardResponse,
)
from app.api.v1.endpoints.auth import RoleChecker

router = APIRouter()

# Only CEO and Admin can dispatch magic links
allow_admin = RoleChecker(["CEO", "Admin"])


# ═══════════════════════════════════════════════════════════════════════
# POST /client/hire-us — Public Hire Us form
# ═══════════════════════════════════════════════════════════════════════
@router.post("/hire-us", response_model=ClientInquiry, status_code=status.HTTP_201_CREATED)
async def hire_us(
    inquiry_in: ClientInquiryCreate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Accept a public Hire Us form submission.

    This is the ONLY action required from the prospect at this stage.
    No account creation, no password, no dashboard.

    What happens:
        1. Saves the inquiry to the database.
        2. Sends an email notification to TitanCode HR.
        3. Returns the created inquiry record.

    The HR team then contacts the prospect manually (email, WhatsApp, etc.)
    and schedules a consultation. After the meeting, an admin can send
    a magic link via POST /client/send-magic-link.
    """
    # Save the inquiry record
    inquiry = ClientInquiryModel(**inquiry_in.model_dump())
    db.add(inquiry)
    await db.commit()
    await db.refresh(inquiry)

    # Send notification email to HR team
    hr_email = settings.EMAILS_FROM_EMAIL or "info@titancode.com"
    await send_email(
        recipient_email=hr_email,
        subject=f"🔔 New Hire Inquiry: {inquiry_in.full_name} — {inquiry_in.company or 'No Company'}",
        body=(
            f"You have a new inquiry from the Hire Us form.\n\n"
            f"Name:             {inquiry_in.full_name}\n"
            f"Email:            {inquiry_in.email}\n"
            f"Company:          {inquiry_in.company or 'N/A'}\n"
            f"Phone:            {inquiry_in.phone or 'N/A'}\n"
            f"Service Interest: {inquiry_in.service_interest or 'N/A'}\n\n"
            f"Message:\n{inquiry_in.message or '(no message provided)'}\n\n"
            f"— TitanCode Platform"
        ),
        html_content=(
            f"<h2>New Hire Inquiry</h2>"
            f"<table style='border-collapse:collapse;font-family:sans-serif;'>"
            f"<tr><td style='padding:8px;font-weight:bold;'>Name</td><td style='padding:8px;'>{inquiry_in.full_name}</td></tr>"
            f"<tr><td style='padding:8px;font-weight:bold;'>Email</td><td style='padding:8px;'><a href='mailto:{inquiry_in.email}'>{inquiry_in.email}</a></td></tr>"
            f"<tr><td style='padding:8px;font-weight:bold;'>Company</td><td style='padding:8px;'>{inquiry_in.company or 'N/A'}</td></tr>"
            f"<tr><td style='padding:8px;font-weight:bold;'>Phone</td><td style='padding:8px;'>{inquiry_in.phone or 'N/A'}</td></tr>"
            f"<tr><td style='padding:8px;font-weight:bold;'>Service</td><td style='padding:8px;'>{inquiry_in.service_interest or 'N/A'}</td></tr>"
            f"</table>"
            f"<h3>Message</h3><p>{inquiry_in.message or '(no message provided)'}</p>"
        ),
    )

    # Auto-reply to the prospect acknowledging receipt
    await send_email(
        recipient_email=inquiry_in.email,
        subject="We received your inquiry — TitanCode Technologies",
        body=(
            f"Hi {inquiry_in.full_name},\n\n"
            f"Thank you for reaching out to TitanCode Technologies! We've received your inquiry "
            f"and our team will be in touch with you shortly to discuss your project.\n\n"
            f"In the meantime, feel free to reply to this email if you have any questions.\n\n"
            f"— The TitanCode Team"
        ),
        html_content=(
            f"<p>Hi <strong>{inquiry_in.full_name}</strong>,</p>"
            f"<p>Thank you for reaching out to <strong>TitanCode Technologies</strong>!</p>"
            f"<p>We've received your inquiry and our team will be in touch with you shortly "
            f"to discuss your project.</p>"
            f"<p>In the meantime, feel free to reply to this email with any questions.</p>"
            f"<br><p>— The TitanCode Team</p>"
        ),
    )

    return inquiry


# ═══════════════════════════════════════════════════════════════════════
# POST /client/send-magic-link — Admin dispatches onboarding link
# ═══════════════════════════════════════════════════════════════════════
@router.post("/send-magic-link", status_code=status.HTTP_200_OK)
async def send_magic_link(
    body: SendMagicLinkRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allow_admin),
) -> Any:
    """
    Generate and send a one-time magic link to a prospective client.

    This is called AFTER the initial consultation meeting, when the team
    has decided to proceed with the client. The link expires in 24 hours.

    Flow:
        1. Look up the client inquiry by email.
        2. Create (or update) a Client user record using inquiry data.
        3. Generate a signed magic link JWT (24hr expiry).
        4. Store the token on the user record.
        5. Mark the inquiry as "contacted".
        6. Send an invitation email with the magic link.

    Args:
        body: { email } — the prospect's email from the Hire Us form.
    """
    email = body.email

    # Step 1: Look up inquiry (optional — can send link to any email)
    inquiry_result = await db.execute(
        select(ClientInquiryModel)
        .where(ClientInquiryModel.email == email)
        .order_by(ClientInquiryModel.created_at.desc())
    )
    inquiry = inquiry_result.scalars().first()

    # Step 2: Check if a Client user already exists for this email
    user_result = await db.execute(select(User).where(User.email == email))
    client_user = user_result.scalars().first()

    if not client_user:
        # Pre-create the Client user from inquiry data (no password needed — magic link is auth)
        client_user = User(
            email=email,
            full_name=inquiry.full_name if inquiry else email.split("@")[0].title(),
            password_hash=security.get_password_hash(security.create_magic_link_token(email)),  # Placeholder hash
            role="Client",
            status="pending",
            phone_number=inquiry.phone if inquiry else None,
            onboarded=False,
        )
        db.add(client_user)
        await db.flush()  # Get the ID without committing

    # Step 3: Generate the magic link token
    token = security.create_magic_link_token(email)

    # Step 4: Store token on the user record
    from datetime import datetime, timezone
    client_user.magic_link_token = token
    client_user.magic_link_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    client_user.onboarded = False

    # Step 5: Update inquiry status to "contacted"
    if inquiry:
        inquiry.status = "contacted"

    await db.commit()

    # Step 6: Construct the magic link URL
    # In production, FRONTEND_URL should be in settings (e.g. https://app.titancode.com)
    frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
    magic_link = f"{frontend_url}/onboard?token={token}"

    # Step 7: Send invitation email
    await send_email(
        recipient_email=email,
        subject="You're invited to TitanCode — Activate Your Client Account",
        body=(
            f"Hi {client_user.full_name},\n\n"
            f"Great news! Following your consultation with the TitanCode team, "
            f"we're ready to get started on your project.\n\n"
            f"Click the link below to activate your client account — no registration required:\n\n"
            f"{magic_link}\n\n"
            f"This link is valid for 24 hours and can only be used once.\n\n"
            f"Once activated, you'll be able to track your project progress "
            f"and communicate with our team.\n\n"
            f"— The TitanCode Team"
        ),
        html_content=(
            f"<p>Hi <strong>{client_user.full_name}</strong>,</p>"
            f"<p>Great news! Following your consultation with the TitanCode team, "
            f"we're ready to get started on your project.</p>"
            f"<p>Click the button below to activate your client account — "
            f"<strong>no registration or password required</strong>:</p>"
            f"<p style='text-align:center;margin:32px 0;'>"
            f"<a href='{magic_link}' style='background:#4F46E5;color:white;padding:14px 28px;"
            f"border-radius:8px;text-decoration:none;font-weight:bold;font-size:16px;'>"
            f"Activate My Account →</a></p>"
            f"<p style='color:#666;font-size:12px;'>This link expires in 24 hours and can only be used once.</p>"
            f"<br><p>— The TitanCode Team</p>"
        ),
    )

    return {
        "message": f"Magic link sent to {email}. Link expires in 24 hours.",
        "email": email,
    }


# ═══════════════════════════════════════════════════════════════════════
# GET /client/onboard?token=xxx — Client activates their account
# ═══════════════════════════════════════════════════════════════════════
@router.get("/onboard", response_model=MagicLinkOnboardResponse)
async def onboard_client(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Validate a magic link token and activate the client's account.

    This endpoint is hit when the client clicks their onboarding email link.
    No login form, no password, no re-registration.

    Flow:
        1. Decode and validate the JWT token (built-in expiry check).
        2. Load the matching user record from DB.
        3. Verify the stored token matches (prevents token reuse).
        4. Check the user hasn't already onboarded.
        5. Activate the account: status=approved, onboarded=True, clear token.
        6. Mark inquiry as "converted".
        7. Return fresh JWT tokens — the client is immediately logged in.

    Returns:
        access_token + refresh_token for immediate use by the frontend.
    """
    # Step 1: Decode the magic link JWT
    try:
        email = security.decode_magic_link_token(token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    # Step 2: Find the user record
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No client account found for this invitation link.",
        )

    # Step 3: Verify stored token matches (single-use enforcement)
    if user.magic_link_token != token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This magic link has already been used or is invalid.",
        )

    # Step 4: Check not already onboarded
    if user.onboarded:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account has already been activated.",
        )

    # Step 5: Activate account and consume the token
    user.status = "approved"
    user.onboarded = True
    user.magic_link_token = None
    user.magic_link_expires_at = None

    # Step 6: Mark the inquiry as converted
    inquiry_result = await db.execute(
        select(ClientInquiryModel)
        .where(ClientInquiryModel.email == email)
        .order_by(ClientInquiryModel.created_at.desc())
    )
    inquiry = inquiry_result.scalars().first()
    if inquiry:
        inquiry.status = "converted"

    await db.commit()

    # Step 7: Issue JWT tokens — client is immediately logged in
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    # Send a welcome email
    await send_email(
        recipient_email=email,
        subject="Welcome to TitanCode Technologies! 🎉",
        body=(
            f"Hi {user.full_name},\n\n"
            f"Your TitanCode client account is now active!\n\n"
            f"You can now log in anytime at your client portal. "
            f"Our team is ready to begin working on your project.\n\n"
            f"If you have any questions, just reply to this email.\n\n"
            f"— The TitanCode Team"
        ),
        html_content=(
            f"<h2>Welcome to TitanCode! 🎉</h2>"
            f"<p>Hi <strong>{user.full_name}</strong>,</p>"
            f"<p>Your client account is now <strong>active</strong>.</p>"
            f"<p>Our team is ready to begin working on your project. "
            f"You can track your project progress through your client portal.</p>"
            f"<p>If you have any questions, just reply to this email.</p>"
            f"<br><p>— The TitanCode Team</p>"
        ),
    )

    return MagicLinkOnboardResponse(
        access_token=security.create_access_token(user.id, expires_delta=access_token_expires),
        refresh_token=security.create_refresh_token(user.id, expires_delta=refresh_token_expires),
        token_type="bearer",
        message=f"Welcome, {user.full_name}! Your account has been activated.",
    )


# ═══════════════════════════════════════════════════════════════════════
# GET /client/inquiries — List all Hire Us submissions (Admin only)
# ═══════════════════════════════════════════════════════════════════════
@router.get("/inquiries", response_model=list[ClientInquiry])
async def list_inquiries(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> Any:
    """
    List all Hire Us form submissions.
    Accessible only to CEO and Admin roles for CRM-style tracking.
    """
    result = await db.execute(
        select(ClientInquiryModel).order_by(ClientInquiryModel.created_at.desc())
    )
    return result.scalars().all()
