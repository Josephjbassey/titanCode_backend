import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.future import select
from app.db.models import Project, Wallet, User
from app.core.config import settings

@pytest.fixture
def mock_stripe_event():
    """
    Beginner Note: A 'Fixture' is a reusable piece of test data.
    This simulates a real message Stripe would send us.
    """
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
    Integration Test: What happens when Stripe sends a 'Payment Success' message?
    
    Goal:
    1. The project in our database should become 'completed'.
    2. A background task should be triggered to calculate payouts.
    """
    # 1. SETUP: Create an admin and a project in the test database.
    admin = User(full_name="Admin", email="admin_success@test.com", password_hash="hash", role="CEO", status="approved")
    db_session.add(admin)
    await db_session.flush()

    project = Project(name="Webhook Test Project", status="active", budget=1000.00, client_id=admin.id)
    db_session.add(project)
    await db_session.commit()
    
    # Update our mock message to point to the real project ID we just created.
    project_id = project.id
    mock_stripe_event["data"]["object"]["metadata"]["project_id"] = str(project_id)

    # 2. MOCKING: 
    # We 'patch' (replace) the real Stripe signature checker and Celery task 
    # so we don't actually need a real Stripe account or a running Celery worker for this test.
    with patch("stripe.Webhook.construct_event", return_value=mock_stripe_event), \
         patch("app.tasks.financials.process_payout_calculation.delay") as mock_celery:
        
        # 3. EXECUTION: Send the mock webhook to our API.
        headers = {"Stripe-Signature": "t=123,v1=abc"}
        response = await client.post("/api/v1/webhooks/stripe", content=json.dumps(mock_stripe_event), headers=headers)
        
        assert response.status_code == 200
        assert response.json() == {"status": "success"}
        
        # 4. VERIFICATION: Did the database change correctly?
        await db_session.refresh(project)
        assert project.status == "completed"
        
        # 5. VERIFICATION: Was the background payout task called?
        mock_celery.assert_called_once_with(project_id)

@pytest.mark.asyncio
async def test_stripe_webhook_idempotency(client, db_session, mock_stripe_event):
    """
    Idempotency Test: If Stripe sends the same message twice, do we pay twice?
    
    Goal: The second request should be ignored peacefully.
    """
    # 1. Create a project that is ALREADY completed.
    admin = User(full_name="Admin", email="admin_idemp_final@test.com", password_hash="hash", role="CEO", status="approved")
    db_session.add(admin)
    await db_session.flush()

    project = Project(name="Idempotency Test", status="completed", budget=1000.00, client_id=admin.id)
    db_session.add(project)
    await db_session.commit()
    mock_stripe_event["data"]["object"]["metadata"]["project_id"] = str(project.id)

    with patch("stripe.Webhook.construct_event", return_value=mock_stripe_event), \
         patch("app.tasks.financials.process_payout_calculation.delay") as mock_celery:
        
        # 2. Send the webhook.
        headers = {"Stripe-Signature": "t=123,v1=abc"}
        response = await client.post("/api/v1/webhooks/stripe", content=json.dumps(mock_stripe_event), headers=headers)
        
        # 3. Check that it succeeded but didn't run the payout engine again.
        assert response.status_code == 200
        assert response.json()["info"] == "already_processed"
        mock_celery.assert_not_called()

@pytest.mark.asyncio
async def test_stripe_webhook_invalid_signature(client):
    """
    Security Test: Can someone fake a Stripe message?
    
    Goal: Requests with bad signatures should be rejected with an error.
    """
    import stripe
    # We force the signature checker to raise an Error.
    with patch("stripe.Webhook.construct_event", side_effect=stripe.error.SignatureVerificationError("Invalid", "sig", "payload")):
        headers = {"Stripe-Signature": "invalid"}
        response = await client.post("/api/v1/webhooks/stripe", content="{}", headers=headers)
        
        # Verify rejection.
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid signature"
