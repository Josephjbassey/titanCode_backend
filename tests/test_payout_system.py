import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from decimal import Decimal
import json
import uuid

def get_unique_email(base: str):
    return f"{uuid.uuid4().hex[:8]}_{base}"

from app.db.models import Project, User, Wallet, PayoutInvoice, Transaction, utcnow
from app.tasks.financials import process_payout_calculation, _process_payout_calculation_async

@pytest.mark.asyncio
async def test_payout_task_idempotency_and_logic(db_session: AsyncSession):
    """
    Test the process_payout_calculation task directly.
    Ensures:
    - 70/30 split logic
    - Wallet updates (atomic)
    - Transaction logging
    - Idempotency
    """
    # 1. Setup Mock Admin/Company User
    admin = User(email=get_unique_email("admin@titan.com"), password_hash="pw", full_name="Admin", role="Admin")
    db_session.add(admin)
    await db_session.commit()
    
    # 2. Setup Mock Members
    m1 = User(email=get_unique_email("m1@titan.com"), password_hash="pw", full_name="Member 1", role="Member")
    m2 = User(email=get_unique_email("m2@titan.com"), password_hash="pw", full_name="Member 2", role="Member")
    db_session.add_all([m1, m2])
    await db_session.commit()
    
    # 3. Setup Project
    project = Project(
        name="Final Payout Project",
        description="Payout test",
        client_id=admin.id,
        budget=Decimal("1000.00"),
        status="completed"
    )
    project.members = [m1, m2]
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project, attribute_names=["members"])

    # 4. Setup Wallets (Check if exists first to avoid IntegrityError)
    for u in [m1, m2, admin]:
        res = await db_session.execute(select(Wallet).where(Wallet.user_id == u.id))
        if not res.scalars().first():
            db_session.add(Wallet(user_id=u.id, balance=Decimal("0.00")))
    await db_session.commit()

    # 5. Run Task (First Pass) - Call async version directly to avoid loop conflict
    await _process_payout_calculation_async(project_id=project.id)

    # 6. Verify Results
    total_budget = Decimal("1000.00")
    team_share = total_budget * Decimal("0.70") # 700
    company_share = total_budget * Decimal("0.30") # 300
    per_member = team_share / 2 # 350

    # Check Wallets
    res1 = await db_session.execute(select(Wallet).where(Wallet.user_id == m1.id))
    wallet_m1 = res1.scalars().first()
    assert wallet_m1.balance == per_member
    
    res_admin = await db_session.execute(select(Wallet).where(Wallet.user_id == admin.id))
    wallet_admin = res_admin.scalars().first()
    assert wallet_admin.balance == company_share

    # Check Invoice
    inv_res = await db_session.execute(select(PayoutInvoice).where(PayoutInvoice.project_id == project.id))
    invoice = inv_res.scalars().first()
    assert invoice.total_payout_amount == total_budget
    assert invoice.team_payout_amount == team_share
    assert invoice.company_payout_amount == company_share

    # 7. Run Task (Second Pass - Idempotency Check)
    # This should not raise an error and should not double count.
    await _process_payout_calculation_async(project_id=project.id)
    
    # Verify no double counting
    await db_session.refresh(wallet_m1)
    assert wallet_m1.balance == per_member

@pytest.mark.asyncio
async def test_api_payout_trigger(client: AsyncClient, db_session: AsyncSession, admin_token_headers):
    """
    Test triggering the payout via API status update.
    """
    # 1. Create a project
    payload = {
        "name": "API Payout Project Final",
        "client_id": 1,
        "budget": "2000.00",
        "status": "active",
        "member_ids": []
    }
    response = await client.post("/api/v1/projects/create", json=payload, headers=admin_token_headers)
    assert response.status_code == 201
    project_id = response.json()["id"]

    # 2. Update status to completed
    update_payload = {"status": "completed"}
    response = await client.put(f"/api/v1/projects/update?project_id={project_id}", json=update_payload, headers=admin_token_headers)
    assert response.status_code == 200

    # Verify status changed
    assert response.json()["status"] == "completed"

@pytest.mark.asyncio
async def test_api_payout_approval_rbac(client: AsyncClient, db_session: AsyncSession, admin_token_headers, user_token_headers):
    """
    Test RBAC on Payout Approval endpoint.
    """
    # 1. Setup a user for client_id
    test_user = User(email=get_unique_email("client@titan.com"), password_hash="pw", full_name="Client", role="Member")
    db_session.add(test_user)
    await db_session.commit()

    # 2. Setup a real project first
    project = Project(
        name="RBAC Final Project",
        description="RBAC test",
        client_id=test_user.id,
        budget=Decimal("500.00"),
        status="completed"
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    # 3. Setup a mock invoice linked to the project
    invoice = PayoutInvoice(
        project_id=project.id,
        total_payout_amount=Decimal("500.00"),
        team_payout_amount=Decimal("350.00"),
        company_payout_amount=Decimal("150.00"),
        is_approved=False
    )
    db_session.add(invoice)
    await db_session.commit()
    await db_session.refresh(invoice)
    
    # 4. Try to approve with regular user (Should fail)
    response = await client.post(f"/api/v1/financials/payouts/{invoice.id}/approve", headers=user_token_headers)
    assert response.status_code == 403
    
    # 5. Approve with admin (Should succeed)
    response = await client.post(f"/api/v1/financials/payouts/{invoice.id}/approve", headers=admin_token_headers)
    assert response.status_code == 200
    assert response.json()["is_approved"] is True
