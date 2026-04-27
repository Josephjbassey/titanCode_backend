import asyncio
from decimal import Decimal
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, User, Wallet, Withdrawal, PayoutInvoice
from app.tasks.financials import _process_payout_calculation_async


async def _register_and_login_user(client: AsyncClient, db_session: AsyncSession, email: str) -> dict[str, str]:
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Finance User", "email": email, "password": "SecurePass123!"},
    )

    user = (await db_session.execute(select(User).where(User.email == email))).scalars().first()
    user.status = "approved"
    await db_session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "SecurePass123!"},
    )
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_duplicate_reject_action_is_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token_headers,
    monkeypatch,
):
    monkeypatch.setattr("app.api.v1.endpoints.financials.send_email", lambda *args, **kwargs: asyncio.sleep(0))
    monkeypatch.setattr(
        "app.api.v1.endpoints.financials.notification_manager.send_personal_message",
        lambda *args, **kwargs: asyncio.sleep(0),
    )

    user_headers = await _register_and_login_user(client, db_session, "dup_action_user@test.com")
    user = (await db_session.execute(select(User).where(User.email == "dup_action_user@test.com"))).scalars().first()
    wallet = Wallet(user_id=user.id, balance=Decimal("100.00"), currency="USD")
    db_session.add(wallet)
    await db_session.commit()

    req = await client.post(
        "/api/v1/financials/withdrawals/request",
        json={"amount": "40.00", "bank_info": "bank-123"},
        headers=user_headers,
    )
    assert req.status_code == 201
    withdrawal_id = req.json()["id"]

    first = await client.post(
        f"/api/v1/financials/withdrawals/{withdrawal_id}/action",
        json={"status": "rejected"},
        headers=admin_token_headers,
    )
    second = await client.post(
        f"/api/v1/financials/withdrawals/{withdrawal_id}/action",
        json={"status": "rejected"},
        headers=admin_token_headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200

    await db_session.refresh(wallet)
    assert wallet.balance == Decimal("100.00")


@pytest.mark.asyncio
async def test_concurrent_conflicting_actions_allow_only_one_transition(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token_headers,
    monkeypatch,
):
    monkeypatch.setattr("app.api.v1.endpoints.financials.send_email", lambda *args, **kwargs: asyncio.sleep(0))
    monkeypatch.setattr(
        "app.api.v1.endpoints.financials.notification_manager.send_personal_message",
        lambda *args, **kwargs: asyncio.sleep(0),
    )

    user_headers = await _register_and_login_user(client, db_session, "concurrent_action_user@test.com")
    user = (await db_session.execute(select(User).where(User.email == "concurrent_action_user@test.com"))).scalars().first()
    db_session.add(Wallet(user_id=user.id, balance=Decimal("100.00"), currency="USD"))
    await db_session.commit()

    req = await client.post(
        "/api/v1/financials/withdrawals/request",
        json={"amount": "50.00", "bank_info": "bank-xyz"},
        headers=user_headers,
    )
    assert req.status_code == 201
    withdrawal_id = req.json()["id"]

    approve_req = client.post(
        f"/api/v1/financials/withdrawals/{withdrawal_id}/action",
        json={"status": "approved"},
        headers=admin_token_headers,
    )
    reject_req = client.post(
        f"/api/v1/financials/withdrawals/{withdrawal_id}/action",
        json={"status": "rejected"},
        headers=admin_token_headers,
    )
    responses = await asyncio.gather(approve_req, reject_req)

    status_codes = sorted([r.status_code for r in responses])
    assert status_codes == [200, 409]


@pytest.mark.asyncio
async def test_payout_task_rolls_back_on_partial_failure(db_session: AsyncSession):
    admin = User(email="rollback_admin@test.com", password_hash="pw", full_name="Admin", role="Admin")
    member = User(email="rollback_member@test.com", password_hash="pw", full_name="Member", role="Member")
    db_session.add_all([admin, member])
    await db_session.commit()

    project = Project(name="Rollback Project", client_id=admin.id, budget=Decimal("1000.00"), status="completed")
    project.members = [member]
    db_session.add(project)
    await db_session.commit()

    with patch("app.tasks.financials.AsyncSession.flush", side_effect=RuntimeError("forced flush failure")):
        with pytest.raises(RuntimeError, match="forced flush failure"):
            await _process_payout_calculation_async(project.id)

    member_wallet = (await db_session.execute(select(Wallet).where(Wallet.user_id == member.id))).scalars().first()
    admin_wallet = (await db_session.execute(select(Wallet).where(Wallet.user_id == admin.id))).scalars().first()
    invoice = (await db_session.execute(select(PayoutInvoice).where(PayoutInvoice.project_id == project.id))).scalars().first()

    assert member_wallet is None
    assert admin_wallet is None
    assert invoice is None


@pytest.mark.asyncio
async def test_paid_transition_requires_idempotency_key(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token_headers,
    monkeypatch,
):
    monkeypatch.setattr("app.api.v1.endpoints.financials.send_email", lambda *args, **kwargs: asyncio.sleep(0))
    monkeypatch.setattr(
        "app.api.v1.endpoints.financials.notification_manager.send_personal_message",
        lambda *args, **kwargs: asyncio.sleep(0),
    )

    user_headers = await _register_and_login_user(client, db_session, "idempotency_user@test.com")
    user = (await db_session.execute(select(User).where(User.email == "idempotency_user@test.com"))).scalars().first()
    db_session.add(Wallet(user_id=user.id, balance=Decimal("80.00"), currency="USD"))
    await db_session.commit()

    req = await client.post(
        "/api/v1/financials/withdrawals/request",
        json={"amount": "20.00", "bank_info": "bank-idem"},
        headers=user_headers,
    )
    withdrawal_id = req.json()["id"]

    approved = await client.post(
        f"/api/v1/financials/withdrawals/{withdrawal_id}/action",
        json={"status": "approved"},
        headers=admin_token_headers,
    )
    assert approved.status_code == 200

    missing_key = await client.post(
        f"/api/v1/financials/withdrawals/{withdrawal_id}/action",
        json={"status": "paid"},
        headers=admin_token_headers,
    )
    assert missing_key.status_code == 400

    paid = await client.post(
        f"/api/v1/financials/withdrawals/{withdrawal_id}/action",
        json={"status": "paid", "idempotency_key": "pay_key_12345"},
        headers=admin_token_headers,
    )
    assert paid.status_code == 200

    replay = await client.post(
        f"/api/v1/financials/withdrawals/{withdrawal_id}/action",
        json={"status": "paid", "idempotency_key": "pay_key_12345"},
        headers=admin_token_headers,
    )
    assert replay.status_code == 200

    conflict = await client.post(
        f"/api/v1/financials/withdrawals/{withdrawal_id}/action",
        json={"status": "paid", "idempotency_key": "pay_key_other"},
        headers=admin_token_headers,
    )
    assert conflict.status_code == 409

    withdrawal = (
        await db_session.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id))
    ).scalars().first()
    assert withdrawal.external_payout_idempotency_key == "pay_key_12345"
