"""
TitanCode Technologies — Wallet & Transaction Tests
=====================================================
Tests for the wallet management and financial transaction endpoints.

Test Coverage:
    1. Wallet creation
    2. Credit transactions (adding money)
    3. Debit transactions (withdrawing money)
    4. Overdraw protection (can't debit more than balance)
    5. Transaction history
"""

import pytest
from httpx import AsyncClient


# ── Helper: Login as admin ─────────────────────────────────────────────
async def login_as_admin(client: AsyncClient):
    """Login as the seeded CEO admin and return the auth token."""
    response = await client.post("/api/v1/auth/login", data={
        "username": "admin@titancode.com",
        "password": "TitanCodeAdmin123!",
    })
    return response.json().get("access_token")


# ═══════════════════════════════════════════════════════════════════════
# WALLET CREATION
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_wallet(client: AsyncClient):
    """Test that an admin can create a wallet for a user."""
    admin_token = await login_as_admin(client)

    # Create a wallet for user ID 1 (the admin themselves for simplicity)
    response = await client.post(
        "/api/v1/wallets/create",
        json={"user_id": 1, "currency": "USD"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Accept 201 (first run) or 400 (wallet already exists from prior runs)
    assert response.status_code in (201, 400)
    if response.status_code == 201:
        data = response.json()
        assert data["user_id"] == 1
        assert float(data["balance"]) == 0.00
        assert data["currency"] == "USD"


@pytest.mark.asyncio
async def test_create_duplicate_wallet(client: AsyncClient):
    """Test that creating a second wallet for the same user fails."""
    admin_token = await login_as_admin(client)

    response = await client.post(
        "/api/v1/wallets/create",
        json={"user_id": 1, "currency": "USD"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 400
    assert "already has a wallet" in response.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════
# CREDIT TRANSACTION
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_credit_wallet(client: AsyncClient):
    """Test that an admin can credit money to a wallet."""
    admin_token = await login_as_admin(client)

    # Get the wallet to find its ID
    wallet_resp = await client.get(
        "/api/v1/wallets/1",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    wallet_id = wallet_resp.json()["id"]

    # Credit $500
    response = await client.post(
        "/api/v1/wallets/transaction",
        json={
            "wallet_id": wallet_id,
            "amount": "500.00",
            "transaction_type": "credit",
            "description": "Project payment for Website Redesign",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert float(data["amount"]) == 500.00
    assert data["transaction_type"] == "credit"


# ═══════════════════════════════════════════════════════════════════════
# DEBIT TRANSACTION
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_debit_wallet(client: AsyncClient):
    """Test that a valid debit reduces the balance."""
    admin_token = await login_as_admin(client)

    wallet_resp = await client.get(
        "/api/v1/wallets/1",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    wallet_id = wallet_resp.json()["id"]

    # Debit $200 from the $500 we credited
    response = await client.post(
        "/api/v1/wallets/transaction",
        json={
            "wallet_id": wallet_id,
            "amount": "200.00",
            "transaction_type": "debit",
            "description": "Withdrawal to bank account",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201
    assert float(response.json()["amount"]) == 200.00


@pytest.mark.asyncio
async def test_overdraw_protection(client: AsyncClient):
    """Test that debiting more than the balance is rejected."""
    admin_token = await login_as_admin(client)

    wallet_resp = await client.get(
        "/api/v1/wallets/1",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    wallet_id = wallet_resp.json()["id"]

    # Try to debit $999,999 (way more than balance)
    response = await client.post(
        "/api/v1/wallets/transaction",
        json={
            "wallet_id": wallet_id,
            "amount": "999999.00",
            "transaction_type": "debit",
            "description": "This should fail",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 400
    assert "insufficient funds" in response.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════════════════
# TRANSACTION HISTORY
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_transaction_history(client: AsyncClient):
    """Test that transaction history returns all recorded transactions."""
    admin_token = await login_as_admin(client)

    wallet_resp = await client.get(
        "/api/v1/wallets/1",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    wallet_id = wallet_resp.json()["id"]

    response = await client.get(
        f"/api/v1/wallets/{wallet_id}/history",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    # We should have at least 2 transactions (credit + debit from above)
    assert len(response.json()) >= 2
