from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db_session
from app.schemas.release import ReleaseDto, ReleaseListDto
from app.services.release_service import ReleaseService

router = APIRouter(prefix="/api", tags=["Releases"])


@router.get("/launcher/version")
async def get_launcher_version(db: AsyncSession = Depends(get_db_session)):
    service = ReleaseService(db)
    release = await service.get_latest("Launcher")
    if release is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No launcher release found.")

    base_url = settings.base_url.strip("/")
    download_url = f"{base_url}/api/files/launcher/{release.version}/AshenLauncher.exe"

    return ReleaseDto(
        version=release.version,
        download_url=download_url,
        sha256=release.sha256,
        release_notes=release.release_notes,
        published_at=release.published_at,
    )


@router.get("/modpack/version")
async def get_modpack_version(db: AsyncSession = Depends(get_db_session)):
    service = ReleaseService(db)
    release = await service.get_latest("Modpack")
    if release is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No modpack release found.")

    base_url = settings.base_url.strip("/")
    download_url = f"{base_url}/api/files/modpack/{release.version}/modpack.zip"

    return ReleaseDto(
        version=release.version,
        download_url=download_url,
        sha256=release.sha256,
        release_notes=release.release_notes,
        published_at=release.published_at,
    )


@router.get("/files/{release_type}/{version}/{file_name}")
async def download_file(release_type: str, version: str, file_name: str, db: AsyncSession = Depends(get_db_session)):
    service = ReleaseService(db)
    # Normalize the release_type from URL (e.g. "modpack") to match the
    # canonical DB casing ("Modpack") used by the publish and version
    # endpoints. Without this, the file download always 404s because
    # the DB stores "Modpack" / "Launcher" with capital first letter.
    normalized_type = release_type.capitalize()
    content = await service.get_file(normalized_type, version)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")

    media_type = "application/octet-stream" if release_type == "launcher" else "application/zip"
    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{file_name}"',
    })
