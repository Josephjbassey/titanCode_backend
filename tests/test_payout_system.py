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
    Unit Test: Verifying the Payout Calculation Logic.
    
    What we are testing:
    1. If a project has a budget of 1000, does the team get 700?
    2. Does it split equally among members?
    3. Can we run it twice without paying people twice? (Idempotency)
    """
    # STEP 1: Create a mock Admin (Company Owner)
    admin = User(email=get_unique_email("admin@titan.com"), password_hash="pw", full_name="Admin", role="Admin")
    db_session.add(admin)
    await db_session.commit()
    
    # STEP 2: Create mock Team Members
    m1 = User(email=get_unique_email("m1@titan.com"), password_hash="pw", full_name="Member 1", role="Member")
    m2 = User(email=get_unique_email("m2@titan.com"), password_hash="pw", full_name="Member 2", role="Member")
    db_session.add_all([m1, m2])
    await db_session.commit()
    
    # STEP 3: Create a Completed Project
    project = Project(
        name="Final Payout Project",
        client_id=admin.id,
        budget=Decimal("1000.00"),
        status="completed"
    )
    project.members = [m1, m2]
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project, attribute_names=["members"])

    # STEP 4: Ensure everyone has an empty wallet to start with.
    for u in [m1, m2, admin]:
        res = await db_session.execute(select(Wallet).where(Wallet.user_id == u.id))
        if not res.scalars().first():
            db_session.add(Wallet(user_id=u.id, balance=Decimal("0.00")))
    await db_session.commit()

    # STEP 5: RUN THE ENGINE
    # We call the async version of the task directly to see if the math is right.
    await _process_payout_calculation_async(project_id=project.id)

    # STEP 6: VERIFY THE MATH
    # Total: 1000 | Team (70%): 700 | Company (30%): 300
    # Per Member (700 / 2): 350
    total_budget = Decimal("1000.00")
    team_share = Decimal("700.00")
    per_member = Decimal("350.00")

    # Check Member 1's Wallet: Should have exactly 350.00
    res1 = await db_session.execute(select(Wallet).where(Wallet.user_id == m1.id))
    wallet_m1 = res1.scalars().first()
    assert wallet_m1.balance == per_member
    
    # Check Company Wallet: Should have exactly 300.00
    res_admin = await db_session.execute(select(Wallet).where(Wallet.user_id == admin.id))
    wallet_admin = res_admin.scalars().first()
    assert wallet_admin.balance == Decimal("300.00")

    # STEP 7: IDEMPOTENCY CHECK
    # We run the task again. It should see the PayoutInvoice exists and QUIT without adding more money.
    await _process_payout_calculation_async(project_id=project.id)
    
    # Verify Member 1 STILL has 350.00, not 700.00.
    await db_session.refresh(wallet_m1)
    assert wallet_m1.balance == per_member

@pytest.mark.asyncio
async def test_api_payout_trigger(client: AsyncClient, db_session: AsyncSession, admin_token_headers):
    """
    Integration Test: Does updating the project status via API trigger the flow?
    """
    # 1. Create a new active project via the API.
    payload = {
        "name": "API Payout Project",
        "client_id": 1,
        "budget": "2000.00",
        "status": "active",
        "member_ids": []
    }
    response = await client.post("/api/v1/projects/create", json=payload, headers=admin_token_headers)
    assert response.status_code == 201
    project_id = response.json()["id"]

    # 2. Update the status to 'completed'.
    # This change should automatically trigger the payout task in a real environment.
    update_payload = {"status": "completed"}
    response = await client.put(f"/api/v1/projects/update?project_id={project_id}", json=update_payload, headers=admin_token_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "completed"

@pytest.mark.asyncio
async def test_api_payout_approval_rbac(client: AsyncClient, db_session: AsyncSession, admin_token_headers, user_token_headers):
    """
    Security Test: Can a random user approve a payout? (Role Based Access Control)
    """
    # 1. Setup a project and an invoice that needs approval.
    test_user = User(email=get_unique_email("client@titan.com"), password_hash="pw", full_name="Client", role="Member")
    db_session.add(test_user)
    await db_session.commit()

    project = Project(name="RBAC Project", client_id=test_user.id, budget=Decimal("500.00"), status="completed")
    db_session.add(project)
    await db_session.commit()

    invoice = PayoutInvoice(project_id=project.id, total_payout_amount=Decimal("500.00"), team_payout_amount=Decimal("350.00"), company_payout_amount=Decimal("150.00"), is_approved=False)
    db_session.add(invoice)
    await db_session.commit()
    
    # 2. FAIL CASE: Try to approve with a regular 'Member' account.
    # We expect a 403 Forbidden error.
    response = await client.post(f"/api/v1/financials/payouts/{invoice.id}/approve", headers=user_token_headers)
    assert response.status_code == 403
    
    # 3. SUCCESS CASE: Try to approve with an 'Admin' account.
    # We expect a 200 OK success.
    response = await client.post(f"/api/v1/financials/payouts/{invoice.id}/approve", headers=admin_token_headers)
    assert response.status_code == 200
    assert response.json()["is_approved"] is True
