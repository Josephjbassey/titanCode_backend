from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.database import get_db
from app.db.models import User, ClientInvoice, Project
from app.api.v1.endpoints.auth import RoleChecker
from app.core.config import settings
from app.core.pdf_generator import generate_invoice_pdf
from app.core.tasks import enqueue_email_task
from fastapi.concurrency import run_in_threadpool

from app.core.rate_limiter import limiter
from app.services.billing_service import BillingService
router = APIRouter()

allow_admin = RoleChecker(["CEO", "Admin"])

class InvoiceItem(BaseModel):
    description: str
    amount: float

class GenerateInvoiceRequest(BaseModel):
    project_id: int
    email: EmailStr
    client_name: str
    company_name: str = "N/A"
    items: list[InvoiceItem]
    payment_method: str = "paystack" # "paystack" or "flutterwave"


class InvoiceStatusUpdateRequest(BaseModel):
    status: str


def _to_cents(amount: Decimal) -> int:
    return int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def _initialize_paystack_payment(*, amount: Decimal, email: str, metadata: dict[str, Any]) -> str:
    if not settings.PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Paystack secret key is not configured")

    payload = {
        "email": email,
        "amount": _to_cents(amount),
        "metadata": metadata,
    }
    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post("https://api.paystack.co/transaction/initialize", json=payload, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Paystack payment initialization failed")
    data = response.json().get("data", {})
    auth_url = data.get("authorization_url")
    if not auth_url:
        raise HTTPException(status_code=502, detail="Paystack did not return an authorization URL")
    return auth_url


async def _initialize_flutterwave_payment(*, amount: Decimal, email: str, metadata: dict[str, Any]) -> str:
    if not settings.FLUTTERWAVE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Flutterwave secret key is not configured")

    payload = {
        "tx_ref": f"tc_{metadata['invoice_id']}",
        "amount": f"{amount:.2f}",
        "currency": "USD",
        "redirect_url": "https://titancode.com/payments/complete",
        "customer": {"email": email},
        "customizations": {"title": "TitanCode Invoice Payment"},
        "meta": metadata,
    }
    headers = {
        "Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post("https://api.flutterwave.com/v3/payments", json=payload, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Flutterwave payment initialization failed")
    data = response.json().get("data", {})
    link = data.get("link")
    if not link:
        raise HTTPException(status_code=502, detail="Flutterwave did not return a payment link")
    return link


@router.post("/generate-invoice", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def generate_invoice(
    request: Request,
    body: GenerateInvoiceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allow_admin),
) -> Any:
    """
    Generate a PDF invoice and a secure payment link (Paystack/Flutterwave).
    Automatically emails the client.
    """
    if not body.items:
        raise HTTPException(status_code=400, detail="At least one invoice item is required")

    normalized_items = [{"description": item.description, "amount": Decimal(str(item.amount))} for item in body.items]
    total_amount = sum((item["amount"] for item in normalized_items), Decimal("0.00"))
    total_amount = total_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    invoice_id = f"inv_{uuid4().hex}"

    metadata = {
        "invoice_id": invoice_id,
        "project_id": str(body.project_id),
        "client_name": body.client_name,
        "company_name": body.company_name,
    }
    project = (await db.execute(select(Project).where(Project.id == body.project_id))).scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if body.payment_method == "paystack":
        payment_url = await _initialize_paystack_payment(
            amount=total_amount,
            email=body.email,
            metadata=metadata,
        )
    elif body.payment_method == "flutterwave":
        payment_url = await _initialize_flutterwave_payment(
            amount=total_amount,
            email=body.email,
            metadata=metadata,
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid payment method")

    await run_in_threadpool(
        generate_invoice_pdf,
        client_name=body.client_name,
        company=body.company_name,
        items=[{"description": x["description"], "amount": f"{x['amount']:.2f}"} for x in normalized_items],
        total_amount=float(total_amount),
    )

    enqueue_email_task(
        recipient_email=body.email,
        subject="Your TitanCode Invoice & Secure Payment Link",
        body=(
            f"Hi {body.client_name},\n\n"
            f"Your invoice is ready.\n"
            f"Total Due: ${total_amount:.2f}\n\n"
            f"Please complete payment securely via {body.payment_method.capitalize()}:\n"
            f"{payment_url}\n\n"
            f"Invoice ID: {invoice_id}\n\n"
            "— TitanCode Finance Team"
        ),
        html_content=(
            f"<p>Hi <strong>{body.client_name}</strong>,</p>"
            f"<p>Your invoice is ready.</p>"
            f"<p><strong>Total Due: ${total_amount:.2f}</strong></p>"
            f"<p><a href='{payment_url}'>Pay securely via {body.payment_method.capitalize()}</a></p>"
            f"<p><strong>Invoice ID:</strong> {invoice_id}</p>"
            f"<br><p>— TitanCode Finance Team</p>"
        ),
    )
    invoice = ClientInvoice(
        invoice_id=invoice_id,
        project_id=body.project_id,
        client_email=body.email,
        total_amount=total_amount,
        provider=body.payment_method,
        payment_url=payment_url,
        status="payment_pending",
        created_by=current_user.id,
    )
    db.add(invoice)
    await db.commit()

    return {
        "message": f"Invoice generated and sent to {body.email}",
        "total_amount": f"{total_amount:.2f}",
        "payment_method": body.payment_method,
        "payment_url": payment_url,
        "invoice_id": invoice_id,
    }


@router.get("/invoices")
async def list_invoices(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> Any:
    return await BillingService.list_invoices(db, status_filter=status_filter, limit=limit, offset=offset)


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: str, db: AsyncSession = Depends(get_db), _current_user: User = Depends(allow_admin)) -> Any:
    return await BillingService.get_invoice_or_404(db, invoice_id)


@router.post("/invoices/{invoice_id}/initialize-payment")
async def initialize_payment(invoice_id: str, db: AsyncSession = Depends(get_db), _current_user: User = Depends(allow_admin)) -> Any:
    invoice = await BillingService.get_invoice_or_404(db, invoice_id)
    if invoice.status in {"paid", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Cannot initialize payment for {invoice.status} invoice")
    metadata = {"invoice_id": invoice.invoice_id, "project_id": str(invoice.project_id)}
    if invoice.provider == "flutterwave":
        payment_url = await _initialize_flutterwave_payment(amount=invoice.total_amount, email=invoice.client_email, metadata=metadata)
    else:
        payment_url = await _initialize_paystack_payment(amount=invoice.total_amount, email=invoice.client_email, metadata=metadata)
    invoice.payment_url = payment_url
    invoice.status = "payment_pending"
    await db.commit()
    return {"invoice_id": invoice.invoice_id, "payment_url": payment_url, "status": invoice.status}


@router.patch("/invoices/{invoice_id}/status")
async def mark_invoice_status(invoice_id: str, body: InvoiceStatusUpdateRequest, db: AsyncSession = Depends(get_db), _current_user: User = Depends(allow_admin)) -> Any:
    allowed = {"paid", "cancelled", "failed", "sent", "draft", "payment_pending"}
    if body.status not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported status {body.status}")
    invoice = await BillingService.get_invoice_or_404(db, invoice_id)
    invoice.status = body.status
    await db.commit()
    await db.refresh(invoice)
    return invoice
