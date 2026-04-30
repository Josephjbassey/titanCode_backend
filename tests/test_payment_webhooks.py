import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings


def _paystack_sig(raw: bytes) -> str:
    return hmac.new((settings.PAYSTACK_SECRET_KEY or "").encode("utf-8"), raw, hashlib.sha512).hexdigest()


def _flutterwave_sig(raw: bytes) -> str:
    secret = getattr(settings, "FLUTTERWAVE_WEBHOOK_SECRET", None) or settings.FLUTTERWAVE_SECRET_KEY or ""
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_paystack_webhook_rejects_invalid_signature(client):
    payload = {"event": "charge.success", "data": {"metadata": {"project_id": "1"}, "amount": 1000}}
    response = await client.post(
        "/api/v1/webhooks/paystack",
        content=json.dumps(payload),
        headers={
            "x-paystack-signature": "invalid",
            "x-paystack-event-id": "evt_1",
            "x-paystack-timestamp": "1710000000",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_paystack_webhook_rejects_replayed_timestamp(client):
    payload = {"event": "charge.success", "data": {"metadata": {"project_id": "1"}, "amount": 1000}}
    raw = json.dumps(payload).encode("utf-8")
    response = await client.post(
        "/api/v1/webhooks/paystack",
        content=raw,
        headers={
            "x-paystack-signature": _paystack_sig(raw),
            "x-paystack-event-id": "evt_replay",
            "x-paystack-timestamp": "1",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_paystack_webhook_processes_success_event(client):
    payload = {"event": "charge.success", "data": {"metadata": {"project_id": "42", "invoice_id": "inv_1"}, "amount": 1000}}
    raw = json.dumps(payload).encode("utf-8")

    with patch("app.api.v1.endpoints.webhooks.WebhookService.process_project_payment_success", new_callable=AsyncMock) as mock_process:
        response = await client.post(
            "/api/v1/webhooks/paystack",
            content=raw,
            headers={
                "x-paystack-signature": _paystack_sig(raw),
                "x-paystack-event-id": "evt_ok",
                "x-paystack-timestamp": "4102444800",
            },
        )
        assert response.status_code == 200
        mock_process.assert_awaited_once()


@pytest.mark.asyncio
async def test_flutterwave_webhook_rejects_invalid_hash(client):
    payload = {"event": "charge.completed", "data": {"status": "successful", "meta": {"project_id": "7"}, "amount": 10}}
    response = await client.post(
        "/api/v1/webhooks/flutterwave",
        json=payload,
        headers={
            "verif-hash": "wrong",
            "x-flutterwave-event-id": "flw_1",
            "x-flutterwave-timestamp": "4102444800",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_flutterwave_webhook_valid_and_duplicate_event(client):
    payload = {"event": "charge.completed", "data": {"status": "successful", "meta": {"project_id": "7"}, "amount": 10}}
    raw = json.dumps(payload).encode("utf-8")

    with patch("app.api.v1.endpoints.webhooks.WebhookService.process_project_payment_success", new_callable=AsyncMock) as mock_process:
        response = await client.post(
            "/api/v1/webhooks/flutterwave",
            content=raw,
            headers={
                "x-flutterwave-signature": _flutterwave_sig(raw),
                "x-flutterwave-event-id": "flw_dup",
                "x-flutterwave-timestamp": "4102444800",
            },
        )
        assert response.status_code == 200
        assert mock_process.await_count == 1

