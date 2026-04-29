from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.v1.endpoints.auth import RoleChecker
from app.db.database import get_db
from app.db.models import ClientInquiry, Project, Transaction, Withdrawal

router = APIRouter()
allow_admin = RoleChecker(["CEO", "Admin"])


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), _=Depends(allow_admin)) -> Any:
    total_leads = (await db.execute(select(func.count(ClientInquiry.id)))).scalar_one()
    active_projects = (await db.execute(select(func.count(Project.id)).where(Project.status.in_(["active", "in_progress"])))).scalar_one()
    completed_projects = (await db.execute(select(func.count(Project.id)).where(Project.status == "completed"))).scalar_one()
    pending_withdrawals = (await db.execute(select(func.count(Withdrawal.id)).where(Withdrawal.status == "pending"))).scalar_one()
    total_revenue = (await db.execute(select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.transaction_type == "credit"))).scalar_one()
    return {
        "total_leads": total_leads,
        "active_projects": active_projects,
        "completed_projects": completed_projects,
        "pending_withdrawals": pending_withdrawals,
        "total_revenue": str(total_revenue),
    }


@router.get("/leads")
async def leads(db: AsyncSession = Depends(get_db), _=Depends(allow_admin)) -> Any:
    rows = await db.execute(select(ClientInquiry.status, func.count(ClientInquiry.id)).group_by(ClientInquiry.status))
    return {"pipeline": {status: count for status, count in rows.all()}}


@router.get("/projects")
async def projects(db: AsyncSession = Depends(get_db), _=Depends(allow_admin)) -> Any:
    rows = await db.execute(select(Project.status, func.count(Project.id)).group_by(Project.status))
    return {"projects": {status: count for status, count in rows.all()}}


@router.get("/revenue")
async def revenue(db: AsyncSession = Depends(get_db), _=Depends(allow_admin)) -> Any:
    total_credits = (await db.execute(select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.transaction_type == "credit"))).scalar_one()
    total_debits = (await db.execute(select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.transaction_type == "debit"))).scalar_one()
    return {"total_credits": str(total_credits), "total_debits": str(total_debits)}


@router.get("/payouts")
async def payouts(db: AsyncSession = Depends(get_db), _=Depends(allow_admin)) -> Any:
    rows = await db.execute(select(Withdrawal.status, func.count(Withdrawal.id)).group_by(Withdrawal.status))
    return {"withdrawals": {status: count for status, count in rows.all()}}
