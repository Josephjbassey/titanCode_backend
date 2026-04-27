"""
TitanCode Technologies — Pydantic Schemas: Task
=================================================
Schemas for task assignment and tracking within projects.

Status lifecycle: open → in_progress → completed
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class TaskBase(BaseModel):
    """Fields required when creating a task."""
    project_id: int                          # FK → the parent project
    assigned_user: int                       # FK → the team member working on it
    task_title: str
    description: Optional[str] = None
    deadline: Optional[datetime] = None


class TaskCreate(TaskBase):
    """Schema for POST /tasks/create — inherits all base fields."""
    pass


class TaskUpdate(BaseModel):
    """Schema for PUT /tasks/update — all fields optional for partial updates."""
    assigned_user: Optional[int] = None
    task_title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None             # open | in_progress | completed
    deadline: Optional[datetime] = None


class TaskInDBBase(TaskBase):
    """Adds server-generated fields for database responses."""
    id: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class Task(TaskInDBBase):
    """Public Task schema returned in API responses."""
    pass

class TaskListResponse(BaseModel):
    """Paginated response for task listing endpoints."""
    items: List[Task]
    total: int
    limit: int
    offset: int
    next_offset: Optional[int] = None

