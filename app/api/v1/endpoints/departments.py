"""
TitanCode Technologies — Departments Endpoints
================================================
This module handles CRUD operations for company departments
(e.g., Frontend, Backend, UI/UX, DevOps, etc.).

Who can do what (RBAC):
    • Any authenticated user → Can view the department list.
    • CEO + Admin            → Can create and update departments.
    • CEO only               → Can delete departments.

API Routes (all prefixed with /api/v1/departments):
    GET    /         — List all departments
    POST   /create   — Create a new department
    PUT    /update   — Update a department
    DELETE /delete   — Delete a department
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Any, List

from app.db.database import get_db
from app.db.models import Department, User
from app.schemas.department import (
    Department as DeptSchema,
    DepartmentCreate,
    DepartmentUpdate,
)
from app.api.v1.endpoints.auth import get_current_user, RoleChecker

# Create a new router instance — this is registered in main.py
router = APIRouter()

# ── RBAC Dependencies ──────────────────────────────────────────────────
allow_admin = RoleChecker(["CEO", "Admin"])
allow_ceo = RoleChecker(["CEO"])


# ═══════════════════════════════════════════════════════════════════════
# GET /departments — List all departments
# ═══════════════════════════════════════════════════════════════════════
@router.get("/", response_model=List[DeptSchema])
async def list_departments(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Any:
    """
    Retrieve all departments.

    Any authenticated user can view departments — this helps team members
    see which departments exist when submitting applications.

    Returns:
        List[DeptSchema]: A list of all department records.
    """
    # SELECT * FROM departments
    result = await db.execute(select(Department))
    return result.scalars().all()


# ═══════════════════════════════════════════════════════════════════════
# POST /departments/create — Create a new department
# ═══════════════════════════════════════════════════════════════════════
@router.post("/create", response_model=DeptSchema, status_code=status.HTTP_201_CREATED)
async def create_department(
    dept_in: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> Any:
    """
    Create a new department.

    Before creating, we check if a department with the same name already
    exists to prevent duplicates (e.g., two "Frontend" departments).

    Args:
        dept_in: The department data from the request body.

    Returns:
        DeptSchema: The newly created department record.

    Raises:
        HTTPException 400: If a department with the same name already exists.
    """
    # Step 1: Check for duplicate names
    result = await db.execute(select(Department).where(Department.name == dept_in.name))
    if result.scalars().first():
        raise HTTPException(
            status_code=400,
            detail="Department with this name already exists",
        )

    # Step 2: Create the department model and save to database
    department = Department(**dept_in.model_dump())  # Unpack Pydantic data → SQLAlchemy model
    db.add(department)                               # Stage the INSERT
    await db.commit()                                # Execute the INSERT
    await db.refresh(department)                     # Reload to get the auto-generated ID
    return department


# ═══════════════════════════════════════════════════════════════════════
# PUT /departments/update — Update a department
# ═══════════════════════════════════════════════════════════════════════
@router.put("/update", response_model=DeptSchema)
async def update_department(
    dept_id: int,
    dept_in: DepartmentUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> Any:
    """
    Update an existing department (partial update).

    Only the fields included in the request body will be changed.

    Args:
        dept_id:  The ID of the department to update (query parameter).
        dept_in:  The fields to update (request body).

    Returns:
        DeptSchema: The updated department record.

    Raises:
        HTTPException 404: If no department exists with the given ID.
    """
    # Step 1: Find the department
    result = await db.execute(select(Department).where(Department.id == dept_id))
    department = result.scalars().first()
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    # Step 2: Apply only the fields that were actually sent
    update_data = dept_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(department, field, value)

    # Step 3: Save changes
    await db.commit()
    await db.refresh(department)
    return department


# ═══════════════════════════════════════════════════════════════════════
# DELETE /departments/delete — Delete a department
# ═══════════════════════════════════════════════════════════════════════
@router.delete("/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(
    dept_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_ceo),
) -> None:
    """
    Delete a department permanently.

    ⚠️  CEO only — this is a destructive action.
    Any users currently assigned to this department will have a
    dangling `department_id` reference, so consider reassigning
    them before deleting.

    Args:
        dept_id: The ID of the department to delete (query parameter).

    Raises:
        HTTPException 404: If no department exists with the given ID.
    """
    # Step 1: Find the department
    result = await db.execute(select(Department).where(Department.id == dept_id))
    department = result.scalars().first()
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    # Step 2: Delete and commit
    await db.delete(department)
    await db.commit()
