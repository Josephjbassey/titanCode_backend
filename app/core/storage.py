"""
TitanCode Technologies — File Storage System
==============================================
This module provides a pluggable file storage interface with a concrete
LocalStorage implementation and an S3-ready placeholder.

Architecture:
    ┌──────────────┐
    │ BaseStorage  │  ◀── Abstract interface (save, get, delete)
    └──────┬───────┘
           │
     ┌─────┴──────┐
     │            │
  ┌──▼───┐   ┌────▼───┐
  │Local │   │  S3    │  ◀── Future cloud implementation
  │Storage│  │Storage │
  └──────┘   └────────┘

Design Decisions:
    - Abstract base class ensures all storage backends share the same API.
    - LocalStorage saves files to a configurable `uploads/` directory.
    - Files are stored with UUID filenames to prevent collisions.
    - Original filename and metadata are preserved for retrieval.
    - Swapping to S3 requires implementing 3 methods — no endpoint changes.

Usage:
    from app.core.storage import storage

    file_path = await storage.save(file, folder="kyc")
    file_data = await storage.get(file_path)
    await storage.delete(file_path)
"""

import os
import uuid
import shutil
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import UploadFile

# Logger for storage operations
logger = logging.getLogger(__name__)

# ── Base directory for local file uploads ──────────────────────────────
# Files are stored relative to the project root in an `uploads/` folder.
# Each subfolder (e.g. uploads/kyc/, uploads/portfolio/) keeps things organized.
UPLOAD_DIR = Path("uploads")


class BaseStorage(ABC):
    """
    Abstract base class for file storage backends.

    Any storage implementation (local disk, AWS S3, Google Cloud Storage,
    Cloudinary, etc.) must implement these three methods.

    This abstraction lets us swap storage backends without changing any
    endpoint code — just change which class is instantiated at the bottom.
    """

    @abstractmethod
    async def save(
        self,
        file: UploadFile,
        folder: str = "general",
        custom_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Save an uploaded file and return its metadata.

        Args:
            file:            The FastAPI UploadFile object from the request.
            folder:          Subfolder to organize files (e.g. "kyc", "portfolio").
            custom_filename: Optional custom name. If None, a UUID is generated.

        Returns:
            A dictionary with file metadata:
            {
                "filename": "uuid-name.pdf",
                "original_filename": "my_resume.pdf",
                "content_type": "application/pdf",
                "size": 102400,
                "path": "uploads/portfolio/uuid-name.pdf",
                "folder": "portfolio",
            }
        """
        pass

    @abstractmethod
    async def get(self, file_path: str) -> Optional[str]:
        """
        Get the absolute path or URL for a stored file.

        Args:
            file_path: The relative path returned by save().

        Returns:
            The absolute file path (local) or a signed URL (S3),
            or None if the file doesn't exist.
        """
        pass

    @abstractmethod
    async def delete(self, file_path: str) -> bool:
        """
        Delete a file from storage.

        Args:
            file_path: The relative path returned by save().

        Returns:
            True if the file was deleted, False if it didn't exist.
        """
        pass


class LocalStorage(BaseStorage):
    """
    Stores files on the local filesystem in the `uploads/` directory.

    This is the default storage backend for development and testing.
    For production, swap this out with S3Storage or CloudinaryStorage.

    File Organization:
        uploads/
        ├── kyc/
        │   ├── a1b2c3d4-id-card.pdf
        │   └── e5f6g7h8-passport.jpg
        ├── portfolio/
        │   └── i9j0k1l2-website-screenshot.png
        └── general/
            └── m3n4o5p6-document.docx
    """

    def __init__(self, base_dir: Path = UPLOAD_DIR):
        """
        Initialize LocalStorage with a base directory.

        Args:
            base_dir: Root directory for all uploads. Created automatically.
        """
        self.base_dir = base_dir
        # Ensure the base upload directory exists
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save(
        self,
        file: UploadFile,
        folder: str = "general",
        custom_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Save an uploaded file to the local filesystem.

        Files are renamed with a UUID prefix to prevent filename collisions.
        The original filename is preserved in the returned metadata.

        Args:
            file:            The uploaded file from the HTTP request.
            folder:          Subfolder name (e.g. "kyc", "portfolio").
            custom_filename: Override the auto-generated filename.

        Returns:
            Dictionary with file metadata (filename, path, size, etc.).
        """
        # Create the subfolder if it doesn't exist
        folder_path = self.base_dir / folder
        folder_path.mkdir(parents=True, exist_ok=True)

        # Generate a unique filename: uuid-originalname.ext
        # This prevents collisions when two users upload "resume.pdf"
        original_filename = file.filename or "unnamed"
        if custom_filename:
            safe_filename = custom_filename
        else:
            file_ext = Path(original_filename).suffix  # e.g. ".pdf"
            safe_filename = f"{uuid.uuid4().hex[:12]}{file_ext}"

        # Full path where the file will be saved
        file_path = folder_path / safe_filename

        # Write the file to disk in chunks (memory-efficient for large files)
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        finally:
            # Always close the upload file handle
            await file.close()

        # Get the file size after writing
        file_size = os.path.getsize(file_path)

        logger.info(f"File saved: {file_path} ({file_size} bytes)")

        # Return metadata about the saved file
        return {
            "filename": safe_filename,
            "original_filename": original_filename,
            "content_type": file.content_type or "application/octet-stream",
            "size": file_size,
            "path": str(file_path),  # Relative path for storage reference
            "folder": folder,
        }

    async def get(self, file_path: str) -> Optional[str]:
        """
        Get the absolute path for a locally stored file.

        Args:
            file_path: The relative path from save() metadata.

        Returns:
            The absolute path string, or None if the file is missing.
        """
        absolute_path = Path(file_path).resolve()
        if absolute_path.exists():
            return str(absolute_path)
        return None

    async def delete(self, file_path: str) -> bool:
        """
        Delete a file from the local filesystem.

        Args:
            file_path: The relative path from save() metadata.

        Returns:
            True if deleted successfully, False if the file didn't exist.
        """
        target = Path(file_path)
        if target.exists():
            target.unlink()
            logger.info(f"File deleted: {file_path}")
            return True
        return False


class S3Storage(BaseStorage):
    """
    AWS S3 storage backend (placeholder for future implementation).

    To activate S3 storage:
        1. Install boto3: `pip install boto3`
        2. Add AWS credentials to .env: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET
        3. Implement the save/get/delete methods below.
        4. Change the singleton at the bottom of this file.

    Example .env additions:
        AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
        AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
        S3_BUCKET=titancode-uploads
        S3_REGION=us-east-1
    """

    async def save(
        self,
        file: UploadFile,
        folder: str = "general",
        custom_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload a file to S3 (not yet implemented)."""
        raise NotImplementedError(
            "S3Storage is not yet implemented. "
            "Install boto3 and configure AWS credentials to use S3."
        )

    async def get(self, file_path: str) -> Optional[str]:
        """Generate a pre-signed URL for an S3 object (not yet implemented)."""
        raise NotImplementedError("S3Storage.get() is not yet implemented.")

    async def delete(self, file_path: str) -> bool:
        """Delete an object from S3 (not yet implemented)."""
        raise NotImplementedError("S3Storage.delete() is not yet implemented.")


# ═══════════════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════
# To switch to S3, change this line to: storage = S3Storage()
storage = LocalStorage()
