"""File serving API — thumbnails, originals, and batch operations."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, File
from database.models import OperationLog

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/{file_id}/thumbnail")
async def get_thumbnail(file_id: int, db: AsyncSession = Depends(get_db)):
    file = await db.get(File, file_id)
    if not file:
        raise HTTPException(404, "File not found")
    if not file.thumbnail_path or not Path(file.thumbnail_path).exists():
        raise HTTPException(404, "Thumbnail not available")
    response = FileResponse(file.thumbnail_path, media_type="image/jpeg")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/{file_id}/original")
async def get_original(file_id: int, db: AsyncSession = Depends(get_db)):
    file = await db.get(File, file_id)
    if not file:
        raise HTTPException(404, "File not found")
    if not Path(file.file_path).exists():
        raise HTTPException(404, "Original file not found")
    response = FileResponse(file.file_path)
    response.headers["Cache-Control"] = "no-store"
    return response


class DeleteByExtensionRequest(BaseModel):
    extension: str  # e.g. ".jpg", ".cr2"


@router.post("/delete-by-extension/{task_id}")
async def delete_by_extension(
    task_id: int,
    body: DeleteByExtensionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Move all files with the given extension to recycle bin."""
    from send2trash import send2trash

    ext = body.extension.lower()
    if not ext.startswith("."):
        ext = "." + ext

    result = await db.execute(
        select(File.id, File.file_path, File.file_size)
        .where(File.task_id == task_id)
        .where(func.lower(File.extension) == ext)
    )
    rows = result.all()

    if not rows:
        raise HTTPException(404, f"No files with extension {ext} found")

    deleted = 0
    freed = 0
    errors = []

    for file_id, file_path, file_size in rows:
        try:
            send2trash(file_path)
            deleted += 1
            freed += file_size or 0

            db.add(OperationLog(
                task_id=task_id,
                operation_type="delete",
                file_path=file_path,
                detail=f'{{"source": "scan_extension_filter", "extension": "{ext}", "file_size": {file_size or 0}}}',
            ))
        except Exception as e:
            errors.append({"file_path": file_path, "error": str(e)})

    await db.commit()

    return {
        "deleted": deleted,
        "freed_bytes": freed,
        "total_requested": len(rows),
        "errors": errors[:10] if errors else [],
    }
