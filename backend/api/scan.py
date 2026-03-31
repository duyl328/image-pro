"""File scan API."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, Task, File
from services.scanner import scan_folder, get_scan_summary
from services.thumbnail import generate_thumbnails

router = APIRouter(prefix="/api/tasks/{task_id}", tags=["scan"])


@router.post("/scan")
async def start_scan(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status == "scanning":
        raise HTTPException(409, "Scan already in progress")

    # Clear existing files if re-scanning
    old_files = (await db.execute(select(File).where(File.task_id == task_id))).scalars().all()
    for f in old_files:
        await db.delete(f)
    await db.flush()

    # Run scan in background
    async def _run():
        async with (await _get_session()) as session:
            t = await session.get(Task, task_id)
            await scan_folder(session, t)
            # Generate thumbnails
            result = await session.execute(
                select(File.id, File.file_path, File.file_type)
                .where(File.task_id == task_id)
                .where(File.file_type.in_(["image", "video"]))
            )
            file_tuples = [(r[0], r[1], r[2]) for r in result.all()]
            thumb_map = await generate_thumbnails(file_tuples, task_id)
            for file_id, thumb_path in thumb_map.items():
                await session.execute(
                    File.__table__.update()
                    .where(File.id == file_id)
                    .values(thumbnail_path=thumb_path)
                )
            await session.commit()

    from database.connection import async_session as _get_session
    asyncio.create_task(_run())
    return {"message": "Scan started", "task_id": task_id}


@router.get("/scan/status")
async def scan_status(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {
        "status": task.status,
        "file_count": task.file_count,
        "image_count": task.image_count,
        "video_count": task.video_count,
        "other_count": task.other_count,
    }


@router.get("/scan/summary")
async def scan_summary(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return await get_scan_summary(db, task_id)


@router.get("/files")
async def list_files(
    task_id: int,
    file_type: str = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: str = "file_name",
    sort_order: str = "asc",
    db: AsyncSession = Depends(get_db),
):
    query = select(File).where(File.task_id == task_id)

    if file_type:
        query = query.where(File.file_type == file_type)

    # Sorting
    sort_col = getattr(File, sort_by, File.file_name)
    if sort_order == "desc":
        query = query.order_by(sort_col.desc())
    else:
        query = query.order_by(sort_col.asc())

    # Count
    count_query = select(func.count()).select_from(
        query.subquery()
    )
    total = (await db.execute(count_query)).scalar()

    # Paginate
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    files = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": f.id,
                "file_name": f.file_name,
                "relative_path": f.relative_path,
                "extension": f.extension,
                "file_size": f.file_size,
                "file_type": f.file_type,
                "mime_type": f.mime_type,
                "has_exif": f.has_exif,
                "file_modified": f.file_modified.isoformat() if f.file_modified else None,
                "thumbnail_path": f.thumbnail_path,
            }
            for f in files
        ],
    }
