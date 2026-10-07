"""
TitanCode Technologies — Integration Registry Admin Endpoints
==============================================================
Provides admin-only CRUD for IntegrationConfig and read access to
IntegrationEvent audit logs.

Endpoints:
    GET  /api/v1/admin/integrations                          — list all configs
    PUT  /api/v1/admin/integrations/{service_name}           — update config
    GET  /api/v1/admin/integrations/{service_name}/events    — list events (paginated)
"""

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.api.v1.endpoints.auth import RoleChecker
from app.db.database import get_db
from app.db.models import IntegrationConfig, IntegrationEvent

router = APIRouter()
allow_admin = RoleChecker(["CEO", "Admin"])


# ──────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────────────────────────────

class IntegrationConfigOut(BaseModel):
    id: int
    service_name: str
    is_active: bool
    credentials_json: Optional[str] = None
    metadata_json: Optional[str] = None
    last_synced_at: Optional[Any] = None
    created_at: Any

    class Config:
        from_attributes = True


class IntegrationConfigUpdate(BaseModel):
    is_active: Optional[bool] = None
    credentials_json: Optional[str] = None
    metadata_json: Optional[str] = None


class IntegrationEventOut(BaseModel):
    id: int
    integration_id: int
    event_type: str
    payload_json: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    created_at: Any

    class Config:
        from_attributes = True


class IntegrationEventListResponse(BaseModel):
    items: List[IntegrationEventOut]
    total: int
    limit: int
    offset: int


# ──────────────────────────────────────────────────────────────────────
# GET /  — list all integration configs
# ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[IntegrationConfigOut])
async def list_integrations(
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(allow_admin),
) -> Any:
    """Return all registered integration configurations."""
    result = await db.execute(select(IntegrationConfig).order_by(IntegrationConfig.service_name))
    return result.scalars().all()


# ──────────────────────────────────────────────────────────────────────
# PUT /{service_name}  — update config
# ──────────────────────────────────────────────────────────────────────

@router.put("/{service_name}", response_model=IntegrationConfigOut)
async def update_integration(
    service_name: str,
    body: IntegrationConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(allow_admin),
) -> Any:
    """Toggle or update credentials for a named integration."""
    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.service_name == service_name)
    )
    config = result.scalars().first()
    if not config:
        raise HTTPException(status_code=404, detail=f"Integration '{service_name}' not found")

    if body.is_active is not None:
        config.is_active = body.is_active
    if body.credentials_json is not None:
        config.credentials_json = body.credentials_json
    if body.metadata_json is not None:
        config.metadata_json = body.metadata_json

    await db.commit()
    await db.refresh(config)
    return config


# ──────────────────────────────────────────────────────────────────────
# GET /{service_name}/events  — paginated event audit log
# ──────────────────────────────────────────────────────────────────────

@router.get("/{service_name}/events", response_model=IntegrationEventListResponse)
async def list_integration_events(
    service_name: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(allow_admin),
) -> Any:
    """Return recent audit events for a given integration service."""
    config_result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.service_name == service_name)
    )
    config = config_result.scalars().first()
    if not config:
        raise HTTPException(status_code=404, detail=f"Integration '{service_name}' not found")

    total = (
        await db.execute(
            select(func.count(IntegrationEvent.id)).where(IntegrationEvent.integration_id == config.id)
        )
    ).scalar_one()

    events_result = await db.execute(
        select(IntegrationEvent)
        .where(IntegrationEvent.integration_id == config.id)
        .order_by(IntegrationEvent.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = events_result.scalars().all()

    return {"items": items, "total": total, "limit": limit, "offset": offset}
