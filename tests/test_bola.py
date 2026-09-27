import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import User


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@test.com"


async def _register_approve_login(client: AsyncClient, db_session: AsyncSession, prefix: str, full_name: str) -> tuple[int, str]:
    email = unique_email(prefix)
    password = "Password123!"
    await client.post("/api/v1/auth/register", json={
        "full_name": full_name,
        "email": email,
        "password": password,
    })

    result = await db_session.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    assert user is not None
    user.status = "approved"
    await db_session.commit()

    resp = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return user.id, token


@pytest.mark.asyncio
async def test_bola_project_access(client: AsyncClient, db_session: AsyncSession):
    """Verify that a user cannot access another user's project."""
    
    # 1. Create User A (The Owner)
    user_a_id, token_a = await _register_approve_login(client, db_session, "user_a", "User A")

    # 2. Create User B (The Attacker)
    user_b_id, token_b = await _register_approve_login(client, db_session, "user_b", "User B")

    # 3. Admin creates a project for User A
    resp = await client.post("/api/v1/auth/login", data={
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    })
    admin_token = resp.json()["access_token"]

    project_resp = await client.post(
        "/api/v1/projects/create",
        json={
            "name": "Private Project A",
            "description": "Sensitive content",
            "client_id": user_a_id,
            "budget": "1000.00",
            "deadline": "2026-12-31T00:00:00"
        },
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert project_resp.status_code == 201
    project_id = project_resp.json()["id"]

    # 4. User B attempts to access Project A -> Should be 403
    forbidden_resp = await client.get(
        f"/api/v1/projects/{project_id}",
        headers={"Authorization": f"Bearer {token_b}"}
    )
    assert forbidden_resp.status_code == 403

    # 5. User A attempts to access Project A -> Should be 200
    allowed_resp = await client.get(
        f"/api/v1/projects/{project_id}",
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert allowed_resp.status_code == 200


@pytest.mark.asyncio
async def test_bola_task_access(client: AsyncClient, db_session: AsyncSession):
    """Verify that a user cannot access another user's task."""
    
    # Login as admin
    resp = await client.post("/api/v1/auth/login", data={
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    })
    admin_token = resp.json()["access_token"]

    # Create User C
    user_c_id, token_c = await _register_approve_login(client, db_session, "user_c", "User C")

    # Create User D
    user_d_id, token_d = await _register_approve_login(client, db_session, "user_d", "User D")

    # Create a project first (required for task)
    proj_resp = await client.post(
        "/api/v1/projects/create",
        json={
            "name": "Project for Task",
            "client_id": user_c_id,
            "budget": "500.00",
        },
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert proj_resp.status_code == 201
    project_id = proj_resp.json()["id"]

    # Admin creates a task assigned to User C
    task_resp = await client.post(
        "/api/v1/tasks/create",
        json={
            "project_id": project_id,
            "assigned_user": user_c_id,
            "task_title": "Task for C",
            "description": "Secret Task"
        },
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert task_resp.status_code == 201
    task_id = task_resp.json()["id"]

    # User D attempts to access Task C -> Should be 403
    forbidden_resp = await client.get(
        f"/api/v1/tasks/{task_id}",
        headers={"Authorization": f"Bearer {token_d}"}
    )
    assert forbidden_resp.status_code == 403

    # User C attempts to access Task C -> Should be 200
    allowed_resp = await client.get(
        f"/api/v1/tasks/{task_id}",
        headers={"Authorization": f"Bearer {token_c}"}
    )
    assert allowed_resp.status_code == 200


@pytest.mark.asyncio
async def test_sensitive_data_leakage(client: AsyncClient):
    """Verify that sensitive bank info is not leaked in the public user list."""
    
    # Login as admin
    resp = await client.post("/api/v1/auth/login", data={
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    })
    admin_token = resp.json()["access_token"]

    # Get user list
    users_resp = await client.get(
        "/api/v1/users/",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert users_resp.status_code == 200
    users = users_resp.json()["items"]
    
    for user in users:
        assert "bank_name" not in user
        assert "bank_account_number" not in user
