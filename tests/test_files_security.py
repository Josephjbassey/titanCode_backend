import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import User


def unique_email(prefix: str = "file_test") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@test.com"


async def create_approved_user_token(client: AsyncClient, db_session: AsyncSession, prefix: str) -> str:
    email = unique_email(prefix)
    password = "SecurePass123!"

    await client.post(
        "/api/v1/auth/register",
        json={"full_name": f"{prefix} User", "email": email, "password": password},
    )

    result = await db_session.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    user.status = "approved"
    await db_session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )
    return login.json()["access_token"]


@pytest.mark.asyncio
async def test_private_file_download_and_delete_unauthorized(client: AsyncClient, db_session: AsyncSession):
    owner_token = await create_approved_user_token(client, db_session, "owner")
    attacker_token = await create_approved_user_token(client, db_session, "attacker")

    upload_response = await client.post(
        "/api/v1/files/upload",
        headers={"Authorization": f"Bearer {owner_token}"},
        data={"folder": "general", "visibility": "private"},
        files={"file": ("secret.txt", b"super secret", "text/plain")},
    )
    assert upload_response.status_code == 200
    payload = upload_response.json()

    forbidden_download = await client.get(
        f"/api/v1/files/{payload['folder']}/{payload['filename']}",
        headers={"Authorization": f"Bearer {attacker_token}"},
    )
    assert forbidden_download.status_code == 403

    forbidden_delete = await client.delete(
        f"/api/v1/files/{payload['folder']}/{payload['filename']}",
        headers={"Authorization": f"Bearer {attacker_token}"},
    )
    assert forbidden_delete.status_code == 403


@pytest.mark.asyncio
async def test_large_file_limit_behavior(client: AsyncClient, db_session: AsyncSession):
    user_token = await create_approved_user_token(client, db_session, "largefile")

    near_limit = b"a" * (10 * 1024 * 1024)
    near_limit_response = await client.post(
        "/api/v1/files/upload",
        headers={"Authorization": f"Bearer {user_token}"},
        data={"folder": "general", "visibility": "private"},
        files={"file": ("near_limit.txt", near_limit, "text/plain")},
    )
    assert near_limit_response.status_code == 200

    oversized = b"a" * (10 * 1024 * 1024 + 1)
    oversized_response = await client.post(
        "/api/v1/files/upload",
        headers={"Authorization": f"Bearer {user_token}"},
        data={"folder": "general", "visibility": "private"},
        files={"file": ("too_big.txt", oversized, "text/plain")},
    )
    assert oversized_response.status_code == 413
