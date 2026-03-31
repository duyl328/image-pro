"""File serving API — thumbnails and originals."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, File

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/{file_id}/thumbnail")
async def get_thumbnail(file_id: int, db: AsyncSession = Depends(get_db)):
    file = await db.get(File, file_id)
    if not file:
        raise HTTPException(404, "File not found")
    if not file.thumbnail_path or not Path(file.thumbnail_path).exists():
        raise HTTPException(404, "Thumbnail not available")
    return FileResponse(file.thumbnail_path, media_type="image/jpeg")


@router.get("/{file_id}/original")
async def get_original(file_id: int, db: AsyncSession = Depends(get_db)):
    file = await db.get(File, file_id)
    if not file:
        raise HTTPException(404, "File not found")
    if not Path(file.file_path).exists():
        raise HTTPException(404, "Original file not found")
    return FileResponse(file.file_path)
