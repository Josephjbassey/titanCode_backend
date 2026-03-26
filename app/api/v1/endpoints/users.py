"""
TitanCode Technologies — Users Endpoints
==========================================
This module handles all CRUD (Create, Read, Update, Delete) operations
for managing users in the TitanCode platform.

Who can do what (RBAC):
    • CEO + Admin  → Can list, view, and update any user.
    • CEO only     → Can delete users (destructive action).
    • Members      → Cannot access these endpoints (use /auth/profile instead).

API Routes (all prefixed with /api/v1/users):
    GET    /            — List all users
    GET    /{user_id}   — Get one user by ID
    PUT    /update      — Update a user's information
    DELETE /{user_id}   — Delete a user permanently
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Any, List

from app.db.database import get_db
from app.db.models import User
from app.schemas.user import User as UserSchema, UserUpdate
from app.api.v1.endpoints.auth import get_current_user, RoleChecker

# Create a new router instance — this is registered in main.py
router = APIRouter()

# ── RBAC Dependencies ──────────────────────────────────────────────────
# These are reusable FastAPI "dependencies" that check the current user's
# role BEFORE the endpoint function runs. If the user's role isn't in the
# allowed list, a 403 Forbidden error is returned automatically.
allow_admin = RoleChecker(["CEO", "Admin"])       # CEO or Admin can access
allow_ceo = RoleChecker(["CEO"])                  # Only CEO can access


# ═══════════════════════════════════════════════════════════════════════
# GET /users — List all users
# ═══════════════════════════════════════════════════════════════════════
@router.get("/", response_model=List[UserSchema])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> Any:
    """
    Retrieve all users in the system.

    How it works:
        1. The `allow_admin` dependency checks that the caller is CEO or Admin.
        2. We query the database for ALL User rows.
        3. SQLAlchemy returns them, and Pydantic serializes them to JSON.

    Returns:
        List[UserSchema]: A list of all user records in the database.
    """
    # SELECT * FROM users
    result = await db.execute(select(User))
    return result.scalars().all()


# ═══════════════════════════════════════════════════════════════════════
# GET /users/{user_id} — Get a single user
# ═══════════════════════════════════════════════════════════════════════
@router.get("/{user_id}", response_model=UserSchema)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> Any:
    """
    Retrieve a single user by their database ID.

    Args:
        user_id: The integer primary key of the user to fetch.

    Returns:
        UserSchema: The user record if found.

    Raises:
        HTTPException 404: If no user exists with the given ID.
    """
    # SELECT * FROM users WHERE id = :user_id
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ═══════════════════════════════════════════════════════════════════════
# PUT /users/update — Update a user
# ═══════════════════════════════════════════════════════════════════════
@router.put("/update", response_model=UserSchema)
async def update_user(
    user_id: int,
    user_in: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> Any:
    """
    Update any user's information (partial update).

    Only the fields included in the request body will be changed.
    For example, sending `{"role": "Manager"}` will ONLY change the role
    and leave all other fields untouched.

    Args:
        user_id: The ID of the user to update (passed as a query parameter).
        user_in: The fields to update (from the request body).

    Returns:
        UserSchema: The updated user record.

    Raises:
        HTTPException 404: If no user exists with the given ID.
    """
    # Step 1: Find the user in the database
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Step 2: Extract only the fields that were actually sent
    # `exclude_unset=True` ensures we don't overwrite fields with None
    update_data = user_in.model_dump(exclude_unset=True)

    # Step 3: Apply each changed field to the SQLAlchemy model
    for field, value in update_data.items():
        setattr(user, field, value)

    # Step 4: Save changes to the database
    await db.commit()
    await db.refresh(user)   # Reload the user to get any DB-generated values
    return user


# ═══════════════════════════════════════════════════════════════════════
# DELETE /users/{user_id} — Delete a user
# ═══════════════════════════════════════════════════════════════════════
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_ceo),
) -> None:
    """
    Permanently delete a user from the system.

    ⚠️  This is a destructive action — only the CEO can perform it.
    The user record will be removed from the database entirely.
    Consider implementing soft-delete (setting status="inactive") instead
    for production use.

    Args:
        user_id: The ID of the user to delete.

    Raises:
        HTTPException 404: If no user exists with the given ID.
    """
    # Step 1: Find the user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Step 2: Delete and commit
    await db.delete(user)
    await db.commit()
    # No return body — 204 No Content response
