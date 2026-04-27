import hashlib
import hmac
import json
import time

import pytest

from app.db.models import Product, User


def _signed_headers(api_key: str, body: bytes, timestamp: int, nonce: str) -> dict[str, str]:
    signature = hmac.new(
        key=api_key.encode("utf-8"),
        msg=body + str(timestamp).encode("utf-8") + nonce.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return {
        "X-API-Key": api_key,
        "X-Signature": signature,
        "X-Timestamp": str(timestamp),
        "X-Nonce": nonce,
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
async def test_revenue_report_accepts_valid_signature(client, db_session):
    admin = User(
        full_name="Revenue Admin",
        email="revenue_admin_valid@test.com",
        password_hash="hash",
        role="CEO",
        status="approved",
    )
    db_session.add(admin)
    await db_session.flush()

    api_key = "revenue-secret-key-valid"
    product = Product(name="Revenue Tool", api_key=api_key, created_by=admin.id)
    db_session.add(product)
    await db_session.commit()

    body = json.dumps({"amount": "15.75", "source": "Signed Test"}, separators=(",", ":")).encode("utf-8")
    headers = _signed_headers(api_key=api_key, body=body, timestamp=int(time.time()), nonce="nonce-valid-1")

    response = await client.post("/api/v1/revenue/report", content=body, headers=headers)
    assert response.status_code == 201
    payload = response.json()
    assert payload["product_id"] == product.id
    assert payload["amount"] == "15.75"


@pytest.mark.asyncio
async def test_revenue_report_rejects_invalid_signature(client, db_session):
    admin = User(
        full_name="Revenue Admin",
        email="revenue_admin_invalid@test.com",
        password_hash="hash",
        role="CEO",
        status="approved",
    )
    db_session.add(admin)
    await db_session.flush()

    api_key = "revenue-secret-key-invalid"
    product = Product(name="Revenue Tool", api_key=api_key, created_by=admin.id)
    db_session.add(product)
    await db_session.commit()

    body = json.dumps({"amount": "10.00", "source": "Tampered"}, separators=(",", ":")).encode("utf-8")
    headers = _signed_headers(api_key=api_key, body=body, timestamp=int(time.time()), nonce="nonce-invalid-1")
    headers["X-Signature"] = "not-a-valid-signature"

    response = await client.post("/api/v1/revenue/report", content=body, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid signature"


@pytest.mark.asyncio
async def test_revenue_report_rejects_replayed_nonce(client, db_session):
    admin = User(
        full_name="Revenue Admin",
        email="revenue_admin_replay@test.com",
        password_hash="hash",
        role="CEO",
        status="approved",
    )
    db_session.add(admin)
    await db_session.flush()

    api_key = "revenue-secret-key-replay"
    product = Product(name="Revenue Tool", api_key=api_key, created_by=admin.id)
    db_session.add(product)
    await db_session.commit()

    body = json.dumps({"amount": "22.00", "source": "Replay"}, separators=(",", ":")).encode("utf-8")
    timestamp = int(time.time())
    nonce = "nonce-replay-1"
    headers = _signed_headers(api_key=api_key, body=body, timestamp=timestamp, nonce=nonce)

    first = await client.post("/api/v1/revenue/report", content=body, headers=headers)
    assert first.status_code == 201

    second = await client.post("/api/v1/revenue/report", content=body, headers=headers)
    assert second.status_code == 401
    assert second.json()["detail"] == "Nonce already used"
