import hashlib
import os
import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import Release

_VERSION_RE = re.compile(r"^[A-Za-z0-9._\-+]+$")
_PE_HEADER = b"MZ"
_ZIP_HEADER = b"PK\x03\x04"


class ReleaseService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self, release_type: str) -> list[Release]:
        result = await self.db.execute(
            select(Release)
            .where(Release.type == release_type)
            .order_by(Release.published_at.desc())
        )
        return list(result.scalars().all())

    async def get_latest(self, release_type: str) -> Release | None:
        result = await self.db.execute(
            select(Release).where(
                Release.type == release_type,
                Release.is_latest == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get(self, release_type: str, version: str) -> Release | None:
        result = await self.db.execute(
            select(Release).where(
                Release.type == release_type,
                Release.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def publish(self, release_type: str, version: str, file_content: bytes, release_notes: str) -> Release:
        self._validate_version(version)
        self._validate_signature(release_type, file_content)

        result = await self.db.execute(
            select(Release).where(
                Release.type == release_type,
                Release.version == version,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise ValueError(f"A {release_type} release with version {version} already exists.")

        sha256 = hashlib.sha256(file_content).hexdigest().lower()
        file_name = "AshenLauncher.exe" if release_type == "Launcher" else "modpack.zip"
        relative_dir = f"{release_type.lower()}/{version}"
        relative_path = f"{relative_dir}/{file_name}"

        # Save to local storage
        base_path = settings.storage_path
        full_dir = os.path.normpath(os.path.join(base_path, relative_dir))
        full_path = os.path.normpath(os.path.join(base_path, relative_path))

        # Path traversal prevention
        if not full_path.startswith(os.path.normpath(base_path) + os.sep):
            raise ValueError("Invalid path.")

        os.makedirs(full_dir, exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(file_content)

        # Unmark previous latest
        await self.db.execute(
            Release.__table__.update()
            .where(Release.type == release_type, Release.is_latest == True)  # noqa: E712
            .values(is_latest=False)
        )

        release = Release(
            id=uuid4(),
            type=release_type,
            version=version,
            file_path=relative_path,
            sha256=sha256,
            release_notes=release_notes,
            published_at=datetime.now(timezone.utc),
            is_latest=True,
        )
        self.db.add(release)
        await self.db.flush()
        return release

    async def delete(self, release_type: str, version: str) -> bool:
        result = await self.db.execute(
            select(Release).where(
                Release.type == release_type,
                Release.version == version,
            )
        )
        release = result.scalar_one_or_none()
        if release is None:
            return False

        # Delete file
        base_path = settings.storage_path
        full_path = os.path.normpath(os.path.join(base_path, release.file_path))
        if full_path.startswith(os.path.normpath(base_path) + os.sep) and os.path.exists(full_path):
            os.remove(full_path)

        await self.db.delete(release)
        await self.db.flush()
        return True

    async def get_file(self, release_type: str, version: str) -> bytes | None:
        result = await self.db.execute(
            select(Release).where(
                Release.type == release_type,
                Release.version == version,
            )
        )
        release = result.scalar_one_or_none()
        if release is None:
            return None

        base_path = settings.storage_path
        full_path = os.path.normpath(os.path.join(base_path, release.file_path))
        if not full_path.startswith(os.path.normpath(base_path) + os.sep):
            return None
        if not os.path.exists(full_path):
            return None

        with open(full_path, "rb") as f:
            return f.read()

    @staticmethod
    def _validate_version(version: str | None) -> None:
        if not version or not version.strip():
            raise ValueError("Version is required.")
        if len(version) > 64:
            raise ValueError(f"Version is too long ({len(version)} characters; max 64).")
        if ".." in version:
            raise ValueError("Version may not contain '..' (path traversal).")
        if not _VERSION_RE.match(version):
            raise ValueError("Version may only contain letters, digits, '.', '_', '-', '+'.")

    @staticmethod
    def _validate_signature(release_type: str, content: bytes) -> None:
        if len(content) < 4:
            raise ValueError("Release file is too short.")
        if release_type == "Launcher":
            if content[:2] != _PE_HEADER:
                raise ValueError("Launcher releases must be a Windows PE executable (MZ header).")
        elif release_type == "Modpack":
            if content[:4] != _ZIP_HEADER:
                raise ValueError("Modpack releases must be a ZIP archive (PK header).")
        else:
            raise ValueError(f"Release type {release_type} does not have a defined file signature.")
