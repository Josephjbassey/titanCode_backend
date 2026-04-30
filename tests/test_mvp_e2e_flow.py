import hashlib
import hmac
import json
import time

import pytest

from app.core.config import settings


@pytest.mark.asyncio
async def test_mvp_lead_to_paid_invoice_updates_dashboard_revenue(client, admin_token_headers, monkeypatch):
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "test_paystack_secret")

    async def _fake_init_paystack_payment(*, amount, email, metadata):
        return f"https://pay.test/{metadata['invoice_id']}"

    monkeypatch.setattr("app.api.v1.endpoints.billing._initialize_paystack_payment", _fake_init_paystack_payment)
    monkeypatch.setattr("app.api.v1.endpoints.billing.enqueue_email_task", lambda *args, **kwargs: None)

    monkeypatch.setattr("app.tasks.financials.process_payout_calculation.delay", lambda *args, **kwargs: None)

    lead_payload = {
        "name": "E2E Client",
        "email": "e2e.client@example.com",
        "phone": "+15550001111",
        "company": "E2E Co",
        "project_type": "Web App",
        "budget_range": "5000-10000",
        "timeline": "30 days",
        "description": "Need MVP delivery",
        "source": "direct",
    }
    lead_resp = await client.post("/api/v1/leads", json=lead_payload)
    assert lead_resp.status_code == 201
    lead_id = lead_resp.json()["id"]

    for status in ["contacted", "qualified", "proposal_sent", "won"]:
        up = await client.patch(f"/api/v1/leads/{lead_id}", json={"status": status}, headers=admin_token_headers)
        assert up.status_code == 200

    convert = await client.post(f"/api/v1/leads/{lead_id}/convert-to-project", headers=admin_token_headers)
    assert convert.status_code == 201
    project_id = convert.json()["id"]

    invoice_req = {
        "project_id": project_id,
        "email": "billing@example.com",
        "client_name": "E2E Client",
        "company_name": "E2E Co",
        "items": [{"description": "MVP milestone", "amount": 1200.00}],
        "payment_method": "paystack",
    }
    invoice_create = await client.post("/api/v1/billing/generate-invoice", json=invoice_req, headers=admin_token_headers)
    assert invoice_create.status_code == 200
    invoice_id = invoice_create.json()["invoice_id"]

    webhook_payload = {
        "event": "charge.success",
        "data": {
            "amount": 120000,
            "metadata": {"project_id": str(project_id), "invoice_id": invoice_id},
        },
    }
    raw = json.dumps(webhook_payload).encode("utf-8")
    signature = hmac.new(settings.PAYSTACK_SECRET_KEY.encode("utf-8"), raw, hashlib.sha512).hexdigest()

    webhook_resp = await client.post(
        "/api/v1/webhooks/paystack",
        content=raw,
        headers={
            "x-paystack-signature": signature,
            "x-paystack-event-id": "evt_mvp_e2e_1",
            "x-paystack-timestamp": str(int(time.time())),
        },
    )
    assert webhook_resp.status_code == 200

    invoice_get = await client.get(f"/api/v1/billing/invoices/{invoice_id}", headers=admin_token_headers)
    assert invoice_get.status_code == 200
    assert invoice_get.json()["status"] == "paid"

    revenue = await client.get("/api/v1/dashboard/revenue", headers=admin_token_headers)
    assert revenue.status_code == 200
    assert float(revenue.json()["paid_revenue"]) >= 1200.0
