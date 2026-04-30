from typing import Sequence

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models import ClientInvoice


class BillingService:
    @staticmethod
    async def list_invoices(
        db: AsyncSession,
        *,
        status_filter: str | None,
        limit: int,
        offset: int,
    ) -> Sequence[ClientInvoice]:
        query = select(ClientInvoice).order_by(ClientInvoice.created_at.desc()).offset(offset).limit(limit)
        if status_filter:
            query = query.where(ClientInvoice.status == status_filter)
        return (await db.execute(query)).scalars().all()

    @staticmethod
    async def get_invoice_or_404(db: AsyncSession, invoice_id: str) -> ClientInvoice:
        invoice = (await db.execute(select(ClientInvoice).where(ClientInvoice.invoice_id == invoice_id))).scalars().first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        return invoice

    @staticmethod
    async def update_invoice_status(
        db: AsyncSession,
        *,
        invoice: ClientInvoice,
        status: str,
    ) -> ClientInvoice:
        invoice.status = status
        await db.commit()
        await db.refresh(invoice)
        return invoice
