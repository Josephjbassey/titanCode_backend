import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Application,
    Department,
    Meeting,
    Product,
    Project,
    Revenue,
    Task,
    User,
    Wallet,
    Withdrawal,
)


def _unique_email(prefix: str) -> str:
    return f"{prefix}_{os.urandom(4).hex()}@test.com"


async def _register_and_login(client: AsyncClient, db_session: AsyncSession, role: str = "Member"):
    email = _unique_email("list")
    password = "SecurePass123!"
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": email.split("@")[0], "email": email, "password": password, "role": role},
    )

    user = (await db_session.execute(select(User).where(User.email == email))).scalars().first()
    user.status = "approved"
    await db_session.commit()

    login = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    token = login.json()["access_token"]
    return user, {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_users_list_supports_pagination_filter_and_non_admin_scope(client: AsyncClient, db_session: AsyncSession):
    member, member_headers = await _register_and_login(client, db_session)

    response = await client.get("/api/v1/users/?limit=5&offset=0&role=Member", headers=member_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == member.id
    assert payload["next_offset"] is None


@pytest.mark.asyncio
async def test_projects_and_tasks_lists_enforce_scope_and_boundaries(client: AsyncClient, db_session: AsyncSession, admin_token_headers):
    client_a, headers_a = await _register_and_login(client, db_session, role="Client")
    client_b, headers_b = await _register_and_login(client, db_session, role="Client")
    worker, _ = await _register_and_login(client, db_session)

    for idx, owner in enumerate([client_a, client_a, client_b], start=1):
        project = Project(name=f"proj-{idx}", client_id=owner.id, budget=Decimal("100.00"), status="active")
        db_session.add(project)
    await db_session.commit()

    projects_for_a = await client.get("/api/v1/projects/?limit=1&offset=0&status=active", headers=headers_a)
    assert projects_for_a.status_code == 200
    project_payload = projects_for_a.json()
    assert project_payload["total"] == 2
    assert len(project_payload["items"]) == 1
    assert project_payload["next_offset"] == 1

    overflow = await client.get("/api/v1/projects/?limit=1&offset=10", headers=headers_a)
    assert overflow.status_code == 200
    assert overflow.json()["items"] == []
    assert overflow.json()["next_offset"] is None

    projects = (await db_session.execute(select(Project).order_by(Project.id.asc()))).scalars().all()
    task_visible = Task(project_id=projects[0].id, assigned_user=worker.id, task_title="visible", status="open")
    task_hidden = Task(project_id=projects[2].id, assigned_user=worker.id, task_title="hidden", status="open")
    db_session.add_all([task_visible, task_hidden])
    await db_session.commit()

    tasks_for_client_b = await client.get("/api/v1/tasks/?limit=10&offset=0", headers=headers_b)
    assert tasks_for_client_b.status_code == 200
    task_payload = tasks_for_client_b.json()
    assert task_payload["total"] == 1
    assert task_payload["items"][0]["project_id"] == projects[2].id


@pytest.mark.asyncio
async def test_meetings_and_applications_lists_support_filters_and_scope(client: AsyncClient, db_session: AsyncSession, admin_token_headers):
    manager, manager_headers = await _register_and_login(client, db_session, role="Manager")
    applicant, applicant_headers = await _register_and_login(client, db_session)

    department = Department(name=f"dep-{os.urandom(2).hex()}")
    db_session.add(department)
    await db_session.flush()

    own_app = Application(user_id=applicant.id, department_id=department.id, status="pending")
    other_user = User(full_name="other", email=_unique_email("other"), password_hash="x", status="approved")
    db_session.add(other_user)
    await db_session.flush()
    other_app = Application(user_id=other_user.id, department_id=department.id, status="approved")
    db_session.add_all([own_app, other_app])

    meeting1 = Meeting(
        title="client meeting",
        scheduled_at=datetime.now(timezone.utc),
        created_by=manager.id,
        client_id=applicant.id,
        status="scheduled",
    )
    meeting2 = Meeting(
        title="other meeting",
        scheduled_at=datetime.now(timezone.utc),
        created_by=manager.id,
        client_id=other_user.id,
        status="cancelled",
    )
    db_session.add_all([meeting1, meeting2])
    await db_session.commit()

    apps_member = await client.get("/api/v1/applications/?limit=10&offset=0", headers=applicant_headers)
    assert apps_member.status_code == 200
    assert apps_member.json()["total"] == 1

    apps_manager = await client.get("/api/v1/applications/?status=approved", headers=manager_headers)
    assert apps_manager.status_code == 200
    assert apps_manager.json()["total"] >= 1

    meetings_member = await client.get("/api/v1/meetings/?status=scheduled", headers=applicant_headers)
    assert meetings_member.status_code == 200
    assert meetings_member.json()["total"] == 1
    assert meetings_member.json()["items"][0]["client_id"] == applicant.id

    invalid_limit = await client.get("/api/v1/meetings/?limit=101", headers=applicant_headers)
    assert invalid_limit.status_code == 422


@pytest.mark.asyncio
async def test_revenue_and_withdrawals_lists_metadata_and_filters(client: AsyncClient, db_session: AsyncSession, admin_token_headers):
    user, user_headers = await _register_and_login(client, db_session)

    admin = (await db_session.execute(select(User).where(User.email == "admin@titancode.com"))).scalars().first()
    product = Product(name=f"prod-{os.urandom(2).hex()}", api_key="abc", created_by=admin.id)
    db_session.add(product)
    await db_session.flush()

    db_session.add_all(
        [
            Revenue(product_id=product.id, amount=Decimal("10.00"), source="Stripe"),
            Revenue(product_id=product.id, amount=Decimal("20.00"), source="PayPal"),
        ]
    )

    wallet = Wallet(user_id=user.id, balance=Decimal("200.00"))
    db_session.add(wallet)
    await db_session.flush()
    db_session.add_all(
        [
            Withdrawal(user_id=user.id, amount=Decimal("10.00"), status="pending"),
            Withdrawal(user_id=user.id, amount=Decimal("15.00"), status="approved"),
        ]
    )
    await db_session.commit()

    revenue_resp = await client.get(
        f"/api/v1/revenue/history?product_id={product.id}&limit=1&offset=0",
        headers=admin_token_headers,
    )
    assert revenue_resp.status_code == 200
    revenue_payload = revenue_resp.json()
    assert revenue_payload["total"] == 2
    assert len(revenue_payload["items"]) == 1
    assert revenue_payload["next_offset"] == 1

    my_withdrawals = await client.get("/api/v1/financials/withdrawals?status=approved", headers=user_headers)
    assert my_withdrawals.status_code == 200
    assert my_withdrawals.json()["total"] == 1

    withdrawals_overflow = await client.get(
        "/api/v1/financials/withdrawals?limit=1&offset=20",
        headers=admin_token_headers,
    )
    assert withdrawals_overflow.status_code == 200
    assert withdrawals_overflow.json()["items"] == []
