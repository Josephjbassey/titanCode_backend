import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings


@pytest.mark.asyncio
async def test_paystack_webhook_rejects_invalid_signature(client):
    payload = {"event": "charge.success", "data": {"metadata": {"project_id": "1"}}}
    response = await client.post(
        "/api/v1/webhooks/paystack",
        content=json.dumps(payload),
        headers={"x-paystack-signature": "invalid"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid signature"


@pytest.mark.asyncio
async def test_paystack_webhook_processes_success_event(client):
    payload = {"event": "charge.success", "data": {"metadata": {"project_id": "42"}}}
    raw = json.dumps(payload).encode("utf-8")
    expected_signature = hmac.new(
        (settings.PAYSTACK_SECRET_KEY or "").encode("utf-8"),
        raw,
        hashlib.sha512,
    ).hexdigest()

    with patch("app.api.v1.endpoints.webhooks.PaymentService.process_successful_payment", new_callable=AsyncMock) as mock_process:
        response = await client.post(
            "/api/v1/webhooks/paystack",
            content=raw,
            headers={"x-paystack-signature": expected_signature},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_process.assert_awaited_once()


@pytest.mark.asyncio
async def test_flutterwave_webhook_rejects_invalid_hash(client):
    payload = {"event": "charge.completed", "data": {"status": "successful", "meta": {"project_id": "7"}}}
    response = await client.post(
        "/api/v1/webhooks/flutterwave",
        json=payload,
        headers={"verif-hash": "wrong"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid signature"
