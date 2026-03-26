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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import storage
from app.db.database import get_db
from app.db.models import User
from app.api.v1.endpoints.auth import get_current_active_user, RoleChecker

# Logger for file operations
logger = logging.getLogger(__name__)

# Create the router — all routes here will be prefixed with /api/v1/files
router = APIRouter()

# ── Constants ──────────────────────────────────────────────────────────
MAX_FILE_SIZE = 10 * 1024 * 1024   # 10 MB in bytes
ALLOWED_FOLDERS = {"kyc", "portfolio", "general"}


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
    current_user: User = Depends(get_current_active_user),
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

    # ── Step 2: Check file size ────────────────────────────────────────
    # Read the file content to check its size
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB.",
        )
    # Reset the file pointer so the storage backend can read it again
    await file.seek(0)

    # ── Step 3: Save the file via the storage backend ──────────────────
    try:
        metadata = await storage.save(file, folder=folder)
    except Exception as e:
        logger.error(f"File upload failed: {e}")
        raise HTTPException(status_code=500, detail="File upload failed. Please try again.")

    # ── Step 4: Add uploader info to the metadata ──────────────────────
    metadata["uploaded_by"] = current_user.id

    logger.info(f"User {current_user.id} uploaded file: {metadata['filename']} to {folder}/")

    return metadata


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINT: Download / retrieve a file
# ═══════════════════════════════════════════════════════════════════════
@router.get("/{folder}/{filename}")
async def download_file(
    folder: str,
    filename: str,
    current_user: User = Depends(get_current_active_user),
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

    # Build the relative path and resolve it
    file_path = f"uploads/{folder}/{filename}"
    absolute_path = await storage.get(file_path)

    if absolute_path is None:
        raise HTTPException(status_code=404, detail="File not found.")

    logger.info(f"User {current_user.id} downloaded file: {folder}/{filename}")

    return FileResponse(
        path=absolute_path,
        filename=filename,  # Suggested download filename
        media_type="application/octet-stream",
    )


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINT: Delete a file (Admin/CEO only)
# ═══════════════════════════════════════════════════════════════════════
@router.delete(
    "/{folder}/{filename}",
    dependencies=[Depends(RoleChecker(["CEO", "Admin"]))],
)
async def delete_file(
    folder: str,
    filename: str,
    current_user: User = Depends(get_current_active_user),
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

    file_path = f"uploads/{folder}/{filename}"
    deleted = await storage.delete(file_path)

    if not deleted:
        raise HTTPException(status_code=404, detail="File not found.")

    logger.info(f"Admin {current_user.id} deleted file: {folder}/{filename}")

    return {"detail": f"File '{filename}' deleted successfully.", "folder": folder}
