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
    # Total: 1000 | Squad (60%): 600 | Overhead (15%): 150 | Treasury (25%): 250
    # Per Member (600 / 2): 300
    total_budget = Decimal("1000.00")
    team_share = Decimal("600.00")
    per_member = Decimal("300.00")

    # Check Member 1's Wallet: Should have exactly 300.00
    res1 = await db_session.execute(select(Wallet).where(Wallet.user_id == m1.id))
    wallet_m1 = res1.scalars().first()
    assert wallet_m1.balance == per_member
    
    # Check Company Wallet: Should have treasury (250) + overhead (150) = 400.00
    res_admin = await db_session.execute(select(Wallet).where(Wallet.user_id == admin.id))
    wallet_admin = res_admin.scalars().first()
    assert wallet_admin.balance == Decimal("400.00")

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
    me_resp = await client.get("/api/v1/auth/profile", headers=admin_token_headers)
    assert me_resp.status_code == 200
    admin_id = me_resp.json()["id"]

    # 1. Create a new active project via the API.
    payload = {
        "name": "API Payout Project",
        "client_id": admin_id,
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


def test_currency_subunit_utilities():
    """
    Test conversion between major currency units and smallest integer subunits (zero decimals).
    """
    from app.core.currency import (
        to_subunits,
        from_subunits,
        distribute_subunits_equally,
        split_subunits_by_percentages,
    )

    # 1. USD: 1000.00 USD -> 100,000 cents
    assert to_subunits(Decimal("1000.00"), "USD") == 100000
    assert to_subunits(1000.00, "USD") == 100000
    assert to_subunits("1000.00", "USD") == 100000
    assert from_subunits(100000, "USD") == Decimal("1000.00")

    # 2. NGN (Nigerian Naira): 500.50 NGN -> 50,050 kobo
    assert to_subunits(Decimal("500.50"), "NGN") == 50050
    assert from_subunits(50050, "NGN") == Decimal("500.50")

    # 3. GHS (Ghanaian Cedi): 250.75 GHS -> 25,075 pesewas
    assert to_subunits(Decimal("250.75"), "GHS") == 25075
    assert from_subunits(25075, "GHS") == Decimal("250.75")

    # 4. Zero-decimal currency: JPY (Japanese Yen)
    assert to_subunits(5000, "JPY") == 5000
    assert from_subunits(5000, "JPY") == Decimal("5000")

    # 5. Equal distribution with odd remainder (e.g., 70,000 cents among 3 members)
    shares = distribute_subunits_equally(70000, 3)
    assert len(shares) == 3
    assert shares == [23334, 23333, 23333]
    assert sum(shares) == 70000

    # 6. Split by percentages preserves exact total
    splits = split_subunits_by_percentages(
        100000,
        {"squad": 60.0, "overhead": 15.0, "treasury": 25.0},
        remainder_key="treasury",
    )
    assert splits["squad"] == 60000
    assert splits["overhead"] == 15000
    assert splits["treasury"] == 25000
    assert sum(splits.values()) == 100000


@pytest.mark.asyncio
async def test_currency_subunits_zero_loss_odd_splits(db_session: AsyncSession):
    """
    Verify that project payouts split across an odd number of members
    lose zero subunits/cents (conservation of funds).
    """
    admin = User(email=get_unique_email("admin_subunits@titan.com"), password_hash="pw", full_name="Admin", role="Admin")
    m1 = User(email=get_unique_email("m1_odd@titan.com"), password_hash="pw", full_name="Member 1", role="Member")
    m2 = User(email=get_unique_email("m2_odd@titan.com"), password_hash="pw", full_name="Member 2", role="Member")
    m3 = User(email=get_unique_email("m3_odd@titan.com"), password_hash="pw", full_name="Member 3", role="Member")
    db_session.add_all([admin, m1, m2, m3])
    await db_session.commit()

    # Project with $1000.00 budget split across 3 members
    project = Project(
        name="Odd Split Subunits Project",
        client_id=admin.id,
        budget=Decimal("1000.00"),
        status="completed",
    )
    project.members = [m1, m2, m3]
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project, attribute_names=["members"])

    for u in [m1, m2, m3, admin]:
        db_session.add(Wallet(user_id=u.id, balance=Decimal("0.00"), currency="USD"))
    await db_session.commit()

    # Process payout
    await _process_payout_calculation_async(project_id=project.id)

    # Check member wallets
    w1 = (await db_session.execute(select(Wallet).where(Wallet.user_id == m1.id))).scalars().first()
    w2 = (await db_session.execute(select(Wallet).where(Wallet.user_id == m2.id))).scalars().first()
    w3 = (await db_session.execute(select(Wallet).where(Wallet.user_id == m3.id))).scalars().first()
    w_admin = (await db_session.execute(select(Wallet).where(Wallet.user_id == admin.id))).scalars().first()

    # In default 70/30 split:
    # Squad share: 70,000 cents ($700.00).
    # 70000 // 3 = 23333 cents, remainder 1 cent allocated to member 1.
    assert w1.balance == Decimal("233.34")
    assert w2.balance == Decimal("233.33")
    assert w3.balance == Decimal("233.33")
    assert (w1.balance + w2.balance + w3.balance) == Decimal("700.00")
    assert w_admin.balance == Decimal("300.00")

    # In total: 233.34 + 233.33 + 233.33 + 300.00 = 1000.00
    assert (w1.balance + w2.balance + w3.balance + w_admin.balance) == Decimal("1000.00")
