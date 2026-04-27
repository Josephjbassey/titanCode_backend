import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, User


def unique_email(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


@pytest.mark.asyncio
async def test_update_project_status_uses_project_name_field_safely(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token_headers,
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: status update notifications/email should use Project.name and not crash."""
    client_user = User(
        email=unique_email("client"),
        password_hash="pw",
        full_name="Client User",
        role="Member",
    )
    member_user = User(
        email=unique_email("member"),
        password_hash="pw",
        full_name="Member User",
        role="Member",
    )
    db_session.add_all([client_user, member_user])
    await db_session.commit()

    project = Project(
        name=f"Regression Project {uuid.uuid4().hex[:6]}",
        client_id=client_user.id,
        status="pending",
        budget="1000.00",
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    sent_notifications = []
    sent_emails = []
    payout_triggers = []

    async def fake_send_personal_message(user_id: int, message: dict):
        sent_notifications.append({"user_id": user_id, "message": message})

    async def fake_send_email(recipient_email: str, subject: str, body: str, html_content: str | None = None):
        sent_emails.append(
            {
                "recipient_email": recipient_email,
                "subject": subject,
                "body": body,
                "html_content": html_content,
            }
        )
        return True

    def fake_delay(project_id: int):
        payout_triggers.append(project_id)

    monkeypatch.setattr(
        "app.api.v1.endpoints.projects.notification_manager.send_personal_message",
        fake_send_personal_message,
    )
    monkeypatch.setattr("app.api.v1.endpoints.projects.send_email", fake_send_email)
    monkeypatch.setattr("app.api.v1.endpoints.projects.process_payout_calculation.delay", fake_delay)

    response = await client.put(
        f"/api/v1/projects/update?project_id={project.id}",
        json={"status": "completed", "member_ids": [member_user.id]},
        headers=admin_token_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["id"] == project.id
    assert payload["status"] == "completed"
    assert payload["name"] == project.name
    assert member_user.id in payload["member_ids"]

    # side-effects: payout triggered on transition to completed
    assert payout_triggers == [project.id]

    # side-effects: client update notification + assigned-member notification
    assert len(sent_notifications) == 2
    update_notification = next(n for n in sent_notifications if n["message"]["type"] == "project_update")
    assignment_notification = next(n for n in sent_notifications if n["message"]["type"] == "project_assigned")

    assert update_notification["user_id"] == client_user.id
    assert update_notification["message"]["title"] == f"Project Update: {project.name}"
    assert assignment_notification["user_id"] == member_user.id
    assert project.name in assignment_notification["message"]["message"]

    # side-effects: email subject/body uses project.name
    assert len(sent_emails) == 1
    email = sent_emails[0]
    assert email["recipient_email"] == client_user.email
    assert f"Project Update: {project.name}" in email["subject"]
    assert f"Project: {project.name}" in email["body"]
    assert project.name in (email["html_content"] or "")
