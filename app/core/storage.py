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


# ═══════════════════════════════════════════════════════════════════════
# S3 CLOUD STORAGE IMPLEMENTATION
# ═══════════════════════════════════════════════════════════════════════

class S3Storage(BaseStorage):
    """
    AWS S3 storage backend — used for production cloud hosting.

    This implementation allows the application to scale beyond a single 
    server by storing files in a global Amazon S3 bucket.

    Requirements:
        - boto3 library (installed via requirements.txt)
        - AWS credentials (configured in .env)
    """

    def __init__(self):
        import boto3
        from app.core.config import settings

        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.S3_REGION,
        )
        self.bucket = settings.S3_BUCKET

    async def save(
        self,
        file: UploadFile,
        folder: str = "general",
        custom_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload a file to S3."""
        original_filename = file.filename or "unnamed"
        if custom_filename:
            safe_filename = custom_filename
        else:
            file_ext = Path(original_filename).suffix
            safe_filename = f"{uuid.uuid4().hex[:12]}{file_ext}"

        s3_path = f"{folder}/{safe_filename}"

        try:
            # Upload to S3
            # We use upload_fileobj which is thread-safe and efficient
            self.s3.upload_fileobj(
                file.file,
                self.bucket,
                s3_path,
                ExtraArgs={"ContentType": file.content_type or "application/octet-stream"},
            )
        finally:
            await file.close()

        # Get file size (S3 head object)
        response = self.s3.head_object(Bucket=self.bucket, Key=s3_path)
        file_size = response.get("ContentLength", 0)

        logger.info(f"File uploaded to S3: {s3_path} ({file_size} bytes)")

        return {
            "filename": safe_filename,
            "original_filename": original_filename,
            "content_type": file.content_type or "application/octet-stream",
            "size": file_size,
            "path": s3_path,
            "folder": folder,
        }

    async def get(self, file_path: str) -> Optional[str]:
        """Generate a pre-signed URL for an S3 object."""
        try:
            url = self.s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": file_path},
                ExpiresIn=3600,  # 1 hour
            )
            return url
        except Exception as e:
            logger.error(f"Error generating S3 URL: {e}")
            return None

    async def delete(self, file_path: str) -> bool:
        """Delete an object from S3."""
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=file_path)
            logger.info(f"File deleted from S3: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error deleting S3 object: {e}")
            return False


# ═══════════════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════
from app.core.config import settings

if settings.USE_S3:
    storage = S3Storage()
else:
    storage = LocalStorage()
