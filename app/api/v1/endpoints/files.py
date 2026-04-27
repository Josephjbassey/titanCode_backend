"""
TitanCode Technologies — File Upload & Download Endpoints
==========================================================
This module provides REST endpoints for uploading, downloading,
listing, and deleting files.

Endpoints:
    POST   /files/upload       — Upload a file (any authenticated user).
    GET    /files/{filename}   — Download a file by its stored filename.
    DELETE /files/{filename}   — Delete a file (Admin/CEO only).

Supported File Categories (folder parameter):
    - "kyc"       — Identity documents for KYC verification.
    - "portfolio" — Portfolio items, screenshots, demos.
    - "general"   — Miscellaneous documents.

RBAC Summary:
    ┌─────────────────────┬──────┬───────┬─────────┬────────┐
    │ Action              │ CEO  │ Admin │ Manager │ Member │
    ├─────────────────────┼──────┼───────┼─────────┼────────┤
    │ Upload file         │  ✅  │  ✅   │   ✅    │   ✅   │
    │ Download file       │  ✅  │  ✅   │   ✅    │   ✅   │
    │ Delete file         │  ✅  │  ✅   │   ❌    │   ❌   │
    └─────────────────────┴──────┴───────┴─────────┴────────┘

File Size Limit:
    Files larger than 10 MB are rejected to prevent abuse.
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.storage import storage
from app.db.database import get_db
from app.db.models import User, StoredFile
from app.api.v1.endpoints.auth import get_current_active_user

# Logger for file operations
logger = logging.getLogger(__name__)

# Create the router — all routes here will be prefixed with /api/v1/files
router = APIRouter()

# ── Constants ──────────────────────────────────────────────────────────
MAX_FILE_SIZE = 10 * 1024 * 1024   # 10 MB in bytes
ALLOWED_FOLDERS = {"kyc", "portfolio", "general"}
ALLOWED_VISIBILITY = {"private", "public"}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "text/plain",
    "application/json",
    "text/csv",
}


def _normalize_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    return content_type.split(";")[0].strip().lower()


def _detect_content_type(filename: str, sample: bytes) -> str:
    if sample.startswith(b"%PDF-"):
        return "application/pdf"
    if sample.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if sample.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if sample.lstrip().startswith((b"{", b"[")):
        return "application/json"
    if b"\x00" in sample:
        return "application/octet-stream"

    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return "text/csv"
    return "text/plain"


async def _validate_size_and_content_type(file: UploadFile) -> str:
    size = 0
    sample = bytearray()
    chunk_size = 1024 * 1024

    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        size += len(chunk)
        if len(sample) < 1024:
            sample.extend(chunk[: 1024 - len(sample)])
        if size > MAX_FILE_SIZE:
            await file.seek(0)
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB.",
            )

    await file.seek(0)

    detected_type = _detect_content_type(file.filename or "", bytes(sample))
    declared_type = _normalize_content_type(file.content_type)
    if detected_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported file type.")
    if declared_type and declared_type != detected_type:
        raise HTTPException(
            status_code=415,
            detail=f"Invalid content type. Declared '{declared_type}' does not match file content.",
        )

    return detected_type


def _can_access_file(record: StoredFile, current_user: User) -> bool:
    if record.visibility == "public":
        return True
    if record.owner_id == current_user.id:
        return True
    if current_user.role in {"CEO", "Admin"}:
        return True
    return False


def _can_delete_file(record: StoredFile, current_user: User) -> bool:
    if record.owner_id == current_user.id:
        return True
    if current_user.role in {"CEO", "Admin"}:
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINT: Upload a file
# ═══════════════════════════════════════════════════════════════════════
@router.post("/upload")
async def upload_file(
    file: UploadFile = File(..., description="The file to upload"),
    folder: str = Form(
        default="general",
        description="Category folder: 'kyc', 'portfolio', or 'general'",
    ),
    visibility: str = Form(default="private", description="File visibility: 'private' or 'public'"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Upload a file to the storage system.

    Any authenticated user can upload files. Files are organized into
    category folders (kyc, portfolio, general) and stored with UUID
    filenames to prevent collisions.

    Args:
        file:         The uploaded file (multipart/form-data).
        folder:       Category folder to store the file in.
        current_user: The authenticated user (injected by FastAPI).

    Returns:
        File metadata including stored filename, original name, size, etc.

    Raises:
        400: If the folder name is invalid.
        413: If the file exceeds the 10 MB size limit.
    """
    # ── Step 1: Validate the folder name ───────────────────────────────
    if folder not in ALLOWED_FOLDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid folder '{folder}'. Allowed: {', '.join(ALLOWED_FOLDERS)}",
        )

    if visibility not in ALLOWED_VISIBILITY:
        raise HTTPException(status_code=400, detail=f"Invalid visibility '{visibility}'.")

    # ── Step 2: Check file size + validate content type server-side ────
    validated_content_type = await _validate_size_and_content_type(file)

    # ── Step 3: Save the file via the storage backend ──────────────────
    try:
        metadata = await storage.save(file, folder=folder)
    except Exception as e:
        logger.error(f"File upload failed: {e}")
        raise HTTPException(status_code=500, detail="File upload failed. Please try again.")

    # ── Step 4: Persist file metadata for authorization ────────────────
    record = StoredFile(
        filename=metadata["filename"],
        original_filename=metadata["original_filename"],
        path=metadata["path"],
        content_type=validated_content_type,
        size=metadata["size"],
        folder=folder,
        visibility=visibility,
        owner_id=current_user.id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    logger.info(f"User {current_user.id} uploaded file: {metadata['filename']} to {folder}/")

    return {
        **metadata,
        "content_type": validated_content_type,
        "owner_id": record.owner_id,
        "visibility": record.visibility,
        "created_at": record.created_at,
    }


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINT: Download / retrieve a file
# ═══════════════════════════════════════════════════════════════════════
@router.get("/{folder}/{filename}")
async def download_file(
    folder: str,
    filename: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """
    Download a file by its folder and filename.

    The response streams the file directly to the client with the
    correct Content-Type header. The browser will either display it
    inline (images, PDFs) or trigger a download.

    Args:
        folder:       The category folder (kyc, portfolio, general).
        filename:     The stored filename (UUID-based, from upload metadata).
        current_user: The authenticated user (injected by FastAPI).

    Returns:
        A FileResponse that streams the file to the client.

    Raises:
        400: If the folder name is invalid.
        404: If the file doesn't exist.
    """
    # Validate folder
    if folder not in ALLOWED_FOLDERS:
        raise HTTPException(status_code=400, detail=f"Invalid folder '{folder}'.")

    stmt = select(StoredFile).where(StoredFile.folder == folder, StoredFile.filename == filename)
    result = await db.execute(stmt)
    record = result.scalars().first()

    if record is None:
        raise HTTPException(status_code=404, detail="File not found.")
    if not _can_access_file(record, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to access this file.")

    absolute_path = await storage.get(record.path)
    if absolute_path is None:
        raise HTTPException(status_code=404, detail="File not found.")

    logger.info(f"User {current_user.id} downloaded file: {folder}/{filename}")

    return FileResponse(
        path=absolute_path,
        filename=record.original_filename,
        media_type=record.content_type,
    )


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINT: Delete a file (Admin/CEO only)
# ═══════════════════════════════════════════════════════════════════════
@router.delete(
    "/{folder}/{filename}",
)
async def delete_file(
    folder: str,
    filename: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Delete a file from storage (Admin/CEO only).

    This permanently removes the file from the storage backend.
    Non-admin users cannot delete files to prevent accidental data loss.

    Args:
        folder:       The category folder (kyc, portfolio, general).
        filename:     The stored filename to delete.
        current_user: The authenticated user (must be CEO or Admin).

    Returns:
        Confirmation message with the deleted filename.

    Raises:
        400: If the folder name is invalid.
        404: If the file doesn't exist.
    """
    if folder not in ALLOWED_FOLDERS:
        raise HTTPException(status_code=400, detail=f"Invalid folder '{folder}'.")

    stmt = select(StoredFile).where(StoredFile.folder == folder, StoredFile.filename == filename)
    result = await db.execute(stmt)
    record = result.scalars().first()
    if record is None:
        raise HTTPException(status_code=404, detail="File not found.")
    if not _can_delete_file(record, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to delete this file.")

    deleted = await storage.delete(record.path)
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found.")

    await db.delete(record)
    await db.commit()

    logger.info(f"User {current_user.id} deleted file: {folder}/{filename}")

    return {"detail": f"File '{filename}' deleted successfully.", "folder": folder}
