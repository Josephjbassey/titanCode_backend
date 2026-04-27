"""
TitanCode Technologies — Tasks Endpoints
==========================================
This module handles CRUD operations for task assignment and tracking
within projects. Tasks are the smallest unit of work — each task
belongs to a project and is assigned to a team member.

Status lifecycle:
    open → in_progress → completed

Who can do what (RBAC):
    • Any authenticated user → Can view tasks (see what's assigned to them).
    • CEO, Admin, Manager    → Can create and update tasks.
    • CEO, Admin             → Can delete tasks.

API Routes (all prefixed with /api/v1/tasks):
    POST   /create      — Create a new task
    GET    /            — List all tasks
    GET    /{task_id}   — Get a single task by ID
    PUT    /update      — Update a task
    DELETE /{task_id}   — Delete a task
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing import Any, List

from app.db.database import get_db
from app.db.models import Task, User
from app.schemas.task import Task as TaskSchema, TaskCreate, TaskListResponse, TaskUpdate
from app.api.v1.endpoints.auth import get_current_user, RoleChecker
from app.core.notifications import manager as notification_manager
from app.core.email import send_email
from sqlalchemy import select as sa_select
from sqlalchemy import func
from app.db.models import Project

# Create a new router instance — this is registered in main.py
router = APIRouter()

# ── RBAC Dependencies ──────────────────────────────────────────────────
allow_managers = RoleChecker(["CEO", "Admin", "Manager"])
allow_admin = RoleChecker(["CEO", "Admin"])


# ═══════════════════════════════════════════════════════════════════════
# POST /tasks/create — Create and assign a new task
# ═══════════════════════════════════════════════════════════════════════
@router.post("/create", response_model=TaskSchema, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_managers),
) -> Any:
    """
    Create a new task and assign it to a team member.

    A task starts with status "open" by default (set in the database model).
    The manager should move it to "in_progress" once the assignee starts
    working, and "completed" when done.

    Args:
        task_in: Task data from the request body (project_id, assigned_user,
                 task_title, description, deadline).

    Returns:
        TaskSchema: The newly created task record.
    """
    # Unpack the Pydantic schema into an SQLAlchemy model and save
    task = Task(**task_in.model_dump())
    db.add(task)
    await db.commit()
    await db.refresh(task)  # Reload to get auto-generated fields (id, created_at)

    # Notify the assigned team member via WebSocket + email
    if task.assigned_user:
        # Look up their email for the email notification
        assignee_result = await db.execute(sa_select(User).where(User.id == task.assigned_user))
        assignee = assignee_result.scalars().first()

        # Real-time WebSocket push
        await notification_manager.send_personal_message(
            user_id=task.assigned_user,
            message={
                "type": "task_assigned",
                "title": "New Task Assigned 📋",
                "message": f"You have been assigned a new task: {task.task_title}",
                "task_id": task.id,
            },
        )

        # Email notification
        if assignee and assignee.email:
            await send_email(
                recipient_email=assignee.email,
                subject=f"New Task Assigned: {task.task_title}",
                body=(
                    f"Hi {assignee.full_name},\n\n"
                    f"You have been assigned a new task:\n\n"
                    f"Task:     {task.task_title}\n"
                    f"Deadline: {task.deadline or 'Not set'}\n\n"
                    f"{task.description or ''}\n\n"
                    f"— The TitanCode Team"
                ),
                html_content=(
                    f"<p>Hi <strong>{assignee.full_name}</strong>,</p>"
                    f"<p>You have been assigned a new task:</p>"
                    f"<table style='border-collapse:collapse;font-family:sans-serif;'>"
                    f"<tr><td style='padding:6px;font-weight:bold;'>Task</td><td style='padding:6px;'>{task.task_title}</td></tr>"
                    f"<tr><td style='padding:6px;font-weight:bold;'>Deadline</td><td style='padding:6px;'>{task.deadline or 'Not set'}</td></tr>"
                    f"</table>"
                    f"<p>{task.description or ''}</p>"
                    f"<br><p>— The TitanCode Team</p>"
                ),
            )

    return task


# ═══════════════════════════════════════════════════════════════════════
# GET /tasks — List all tasks
# ═══════════════════════════════════════════════════════════════════════
@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    project_id: int | None = Query(None),
    assigned_user: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    List all tasks in the system.

    Any authenticated user can view tasks. In a future iteration,
    you might want to filter tasks by `assigned_user` so team members
    only see their own tasks.

    Returns:
        List[TaskSchema]: All task records in the database.
    """
    # SELECT * FROM tasks
    filters = []
    if status_filter:
        filters.append(Task.status == status_filter)
    if project_id is not None:
        filters.append(Task.project_id == project_id)
    if assigned_user is not None:
        filters.append(Task.assigned_user == assigned_user)

    count_stmt = select(func.count(Task.id)).select_from(Task)
    stmt = select(Task)
    if current_user.role not in ["CEO", "Admin"]:
        stmt = stmt.join(Project, Project.id == Task.project_id)
        count_stmt = count_stmt.join(Project, Project.id == Task.project_id)
        filters.append((Task.assigned_user == current_user.id) | (Project.client_id == current_user.id))

    total = (await db.execute(count_stmt.where(*filters))).scalar_one()
    result = await db.execute(
        stmt.where(*filters).order_by(Task.created_at.desc()).offset(offset).limit(limit)
    )
    items = result.scalars().all()
    next_offset = offset + limit if offset + limit < total else None
    return {"items": items, "total": total, "limit": limit, "offset": offset, "next_offset": next_offset}


# ═══════════════════════════════════════════════════════════════════════
# GET /tasks/{task_id} — Get a single task
# ═══════════════════════════════════════════════════════════════════════
@router.get("/{task_id}", response_model=TaskSchema)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Any:
    """
    Retrieve a single task by its database ID.

    Args:
        task_id: The integer primary key of the task.

    Returns:
        TaskSchema: The task record if found.

    Raises:
        HTTPException 404: If no task exists with the given ID.
    """
    # Step 1: Find the task (eagerly load the project for the BOLA check below)
    stmt = (
        select(Task)
        .options(selectinload(Task.project))
        .where(Task.id == task_id)
    )
    result = await db.execute(stmt)
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # BOLA CHECK: Only Admin/CEO or the assigned user or the project's client can view
    if _current_user.role not in ["CEO", "Admin"] and \
       task.assigned_user != _current_user.id and \
       (task.project and task.project.client_id != _current_user.id):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: You do not have permission to access this task",
        )

    return task


# ═══════════════════════════════════════════════════════════════════════
# PUT /tasks/update — Update a task
# ═══════════════════════════════════════════════════════════════════════
@router.put("/update", response_model=TaskSchema)
async def update_task(
    task_id: int,
    task_in: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_managers),
) -> Any:
    """
    Update an existing task (partial update).

    Common use cases:
        • Change status: "open" → "in_progress" → "completed".
        • Reassign to a different team member.
        • Extend or shorten the deadline.

    Args:
        task_id: The ID of the task to update (query parameter).
        task_in: The fields to update (request body).

    Returns:
        TaskSchema: The updated task record.

    Raises:
        HTTPException 404: If no task exists with the given ID.
    """
    # Step 1: Find the task (eagerly load the project for the BOLA check below)
    stmt = (
        select(Task)
        .options(selectinload(Task.project))
        .where(Task.id == task_id)
    )
    result = await db.execute(stmt)
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Step 2: Apply only the fields that were sent (partial update)
    update_data = task_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)

    # Step 3: Save changes
    await db.commit()
    await db.refresh(task)
    return task


# ═══════════════════════════════════════════════════════════════════════
# DELETE /tasks/{task_id} — Delete a task
# ═══════════════════════════════════════════════════════════════════════
@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> None:
    """
    Delete a task permanently.

    ⚠️  CEO and Admin only — this is a destructive action.
    Consider moving tasks to "completed" or "cancelled" status
    instead of deleting, to preserve work history.

    Args:
        task_id: The ID of the task to delete.

    Raises:
        HTTPException 404: If no task exists with the given ID.
    """
    # Step 1: Find the task (eagerly load the project for the BOLA check below)
    stmt = (
        select(Task)
        .options(selectinload(Task.project))
        .where(Task.id == task_id)
    )
    result = await db.execute(stmt)
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    await db.delete(task)
    await db.commit()
