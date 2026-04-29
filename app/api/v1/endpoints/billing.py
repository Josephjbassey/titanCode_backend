from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from app.db.models import User
from app.api.v1.endpoints.auth import RoleChecker

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

@router.post("/generate-invoice", status_code=status.HTTP_200_OK)
async def generate_invoice(
    body: GenerateInvoiceRequest,
    current_user: User = Depends(allow_admin),
) -> Any:
    """
    Generate a PDF invoice and a secure payment link (Paystack/Flutterwave).
    Automatically emails the client.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Billing endpoint is temporarily disabled until real Paystack/Flutterwave "
            "payment initialization and signed callback flow are fully implemented."
        ),
    )
