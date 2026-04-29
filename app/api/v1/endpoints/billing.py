from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from app.db.models import User
from app.api.v1.endpoints.auth import RoleChecker
from app.core.config import settings
from app.core.pdf_generator import generate_invoice_pdf
from app.core.tasks import enqueue_email_task
from fastapi.concurrency import run_in_threadpool

from app.core.rate_limiter import limiter
router = APIRouter()

allow_admin = RoleChecker(["CEO", "Admin"])

class InvoiceItem(BaseModel):
    description: str
    amount: float

class GenerateInvoiceRequest(BaseModel):
    email: EmailStr
    client_name: str
    company_name: str = "N/A"
    items: list[InvoiceItem]
    payment_method: str = "paystack" # "paystack" or "flutterwave"


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
    body: GenerateInvoiceRequest,
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
        "client_name": body.client_name,
        "company_name": body.company_name,
    }

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

    return {
        "message": f"Invoice generated and sent to {body.email}",
        "total_amount": f"{total_amount:.2f}",
        "payment_method": body.payment_method,
        "payment_url": payment_url,
        "invoice_id": invoice_id,
    }
