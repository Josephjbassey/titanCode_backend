import pytest
from httpx import AsyncClient
from app.core.config import settings

@pytest.mark.asyncio
async def test_bola_project_access(client: AsyncClient):
    """Verify that a user cannot access another user's project."""
    
    # 1. Create User A (The Owner)
    user_a_email = "user_a@test.com"
    await client.post("/api/v1/auth/register", json={
        "full_name": "User A",
        "email": user_a_email,
        "password": "Password123!",
    })
    resp = await client.post("/api/v1/auth/login", data={"username": user_a_email, "password": "Password123!"})
    token_a = resp.json()["access_token"]

    # 2. Create User B (The Attacker)
    user_b_email = "user_b@test.com"
    await client.post("/api/v1/auth/register", json={
        "full_name": "User B",
        "email": user_b_email,
        "password": "Password123!",
    })
    resp = await client.post("/api/v1/auth/login", data={"username": user_b_email, "password": "Password123!"})
    token_b = resp.json()["access_token"]

    # 3. Admin creates a project for User A
    resp = await client.post("/api/v1/auth/login", data={
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    })
    admin_token = resp.json()["access_token"]
    
    user_a_id = (await client.get("/api/v1/auth/profile", headers={"Authorization": f"Bearer {token_a}"})).json()["id"]

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
async def test_bola_task_access(client: AsyncClient):
    """Verify that a user cannot access another user's task."""
    
    # Login as admin
    resp = await client.post("/api/v1/auth/login", data={
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    })
    admin_token = resp.json()["access_token"]

    # Create User C
    email_c = "user_c@test.com"
    await client.post("/api/v1/auth/register", json={
        "full_name": "User C",
        "email": email_c,
        "password": "Password123!",
    })
    token_c = (await client.post("/api/v1/auth/login", data={"username": email_c, "password": "Password123!"})).json()["access_token"]
    user_c_id = (await client.get("/api/v1/auth/profile", headers={"Authorization": f"Bearer {token_c}"})).json()["id"]

    # Create User D
    email_d = "user_d@test.com"
    await client.post("/api/v1/auth/register", json={
        "full_name": "User D",
        "email": email_d,
        "password": "Password123!",
    })
    token_d = (await client.post("/api/v1/auth/login", data={"username": email_d, "password": "Password123!"})).json()["access_token"]

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
    users = users_resp.json()
    
    for user in users:
        assert "bank_name" not in user
        assert "bank_account_number" not in user
