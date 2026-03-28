import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.future import select
from app.db.models import Project, Wallet, User
from app.core.config import settings

@pytest.fixture
def mock_stripe_event():
    return {
        "id": "evt_test",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test",
                "metadata": {"project_id": "1"}
            }
        }
    }

@pytest.mark.asyncio
async def test_stripe_webhook_success(client, db_session, mock_stripe_event):
    """
    Test successful Stripe webhook processing:
    1. Project status is COMPLETED.
    2. Celery task is dispatched.
    """
    # 1. Setup Data: Project with ID 1
    # Create an admin/user if needed, but we just need a project.
    admin = User(full_name="Admin", email="admin_success@test.com", password_hash="hash", role="CEO", status="approved")
    db_session.add(admin)
    await db_session.flush()

    project = Project(
        name="Webhook Test Project",
        description="Test",
        status="active",
        budget=1000.00,
        client_id=admin.id
    )
    db_session.add(project)
    await db_session.commit()
    project_id = project.id # Should be 1 in a fresh test DB
    mock_stripe_event["data"]["object"]["metadata"]["project_id"] = str(project_id)

    # 2. Mock Stripe Verification and Celery
    with patch("stripe.Webhook.construct_event", return_value=mock_stripe_event), \
         patch("app.tasks.financials.process_payout_calculation.delay") as mock_celery:
        
        headers = {"Stripe-Signature": "t=123,v1=abc"}
        response = await client.post("/api/v1/webhooks/stripe", content=json.dumps(mock_stripe_event), headers=headers)
        
        assert response.status_code == 200
        assert response.json() == {"status": "success"}
        
        # 3. Verify DB State
        await db_session.refresh(project)
        assert project.status == "completed"
        
        # 4. Verify Celery Dispatch
        mock_celery.assert_called_once_with(project_id)

@pytest.mark.asyncio
async def test_stripe_webhook_idempotency(client, db_session, mock_stripe_event):
    """
    Test that duplicate webhooks do not trigger redundant Celery tasks.
    """
    admin = User(full_name="Admin", email="admin_idemp_final@test.com", password_hash="hash", role="CEO", status="approved")
    db_session.add(admin)
    await db_session.flush()

    # 1. Setup Data: Project already COMPLETED
    project = Project(
        name="Idempotency Test",
        description="Test",
        status="completed",
        budget=1000.00,
        client_id=admin.id
    )
    db_session.add(project)
    await db_session.commit()
    project_id = project.id
    mock_stripe_event["data"]["object"]["metadata"]["project_id"] = str(project_id)

    # 2. Mock Stripe Verification and Celery
    with patch("stripe.Webhook.construct_event", return_value=mock_stripe_event), \
         patch("app.tasks.financials.process_payout_calculation.delay") as mock_celery:
        
        headers = {"Stripe-Signature": "t=123,v1=abc"}
        response = await client.post("/api/v1/webhooks/stripe", content=json.dumps(mock_stripe_event), headers=headers)
        
        assert response.status_code == 200
        assert response.json()["info"] == "already_processed"
        
        # 3. Verify Celery was NOT called again
        mock_celery.assert_not_called()

@pytest.mark.asyncio
async def test_stripe_webhook_invalid_signature(client):
    """
    Test that invalid signatures are rejected with 400.
    """
    import stripe
    with patch("stripe.Webhook.construct_event", side_effect=stripe.error.SignatureVerificationError("Invalid", "sig", "payload")):
        headers = {"Stripe-Signature": "invalid"}
        response = await client.post("/api/v1/webhooks/stripe", content="{}", headers=headers)
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid signature"
