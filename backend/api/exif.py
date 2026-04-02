"""EXIF/时间修正 API。"""
import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, Task, File
from services import ws_manager
from services import exif_service

router = APIRouter(tags=["exif"])

TZ_OFFSET = timedelta(hours=8)


class SetTimeRequest(BaseModel):
    new_time: str  # ISO 格式，前端传 UTC+8 展示时间（如 "2023-08-15T14:30:00"）


class BatchOffsetRequest(BaseModel):
    file_ids: list[int]
    offset_seconds: int


# ── 启动 EXIF 分析 ──────────────────────────────────────────────────────────

@router.post("/api/tasks/{task_id}/exif/analyze")
async def start_exif_analyze(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status not in ("ready", "completed"):
        raise HTTPException(400, "Task must be scanned first")

    async def _run():
        from database.connection import async_session
        async with async_session() as session:
            # 先查总数广播 start 事件
            count_result = await session.execute(
                select(func.count()).where(
                    File.task_id == task_id, File.file_type == "image"
                )
            )
            total = count_result.scalar_one()
            await ws_manager.broadcast(task_id, "exif_start", {"total": total})

            async def progress_cb(current: int, total: int):
                await ws_manager.broadcast(
                    task_id, "exif_progress", {"current": current, "total": total}
                )

            try:
                stats = await exif_service.analyze_exif_for_task(session, task_id, progress_cb)
                await session.commit()
                await ws_manager.broadcast(task_id, "exif_complete", stats)
            except Exception as e:
                await session.rollback()
                await ws_manager.broadcast(task_id, "exif_error", {"message": str(e)})

    asyncio.create_task(_run())
    return {"message": "EXIF analysis started", "task_id": task_id}


# ── 获取文件 EXIF 列表 ──────────────────────────────────────────────────────

@router.get("/api/tasks/{task_id}/exif/files")
async def list_exif_files(
    task_id: int,
    filter: str = Query("all", pattern="^(all|anomaly)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    base_query = select(File).where(File.task_id == task_id, File.file_type == "image")
    if filter == "anomaly":
        base_query = base_query.where(File.time_anomaly.is_not(None))

    result = await db.execute(base_query.order_by(File.file_name))
    all_files = result.scalars().all()
    total = len(all_files)
    page_files = all_files[(page - 1) * page_size: page * page_size]

    # 统计（全量，忽略 filter）
    stats_result = await db.execute(
        select(
            func.count().label("total_files"),
            func.sum(File.has_exif).label("has_exif"),
            func.count().filter(File.time_anomaly.is_not(None)).label("has_anomaly"),
        ).where(File.task_id == task_id, File.file_type == "image")
    )
    row = stats_result.one()
    total_img = row[0] or 0
    has_exif_count = int(row[1] or 0)
    has_anomaly_count = int(row[2] or 0)

    def fmt_dt(dt):
        return dt.isoformat() if dt else None

    files_data = [
        {
            "id": f.id,
            "file_name": f.file_name,
            "relative_path": f.relative_path,
            "extension": f.extension,
            "file_type": f.file_type,
            "has_exif": f.has_exif,
            "exif_time": fmt_dt(f.exif_time),
            "file_created": fmt_dt(f.file_created),
            "file_modified": fmt_dt(f.file_modified),
            "best_time": fmt_dt(f.best_time),
            "time_source": f.time_source,
            "time_anomaly": f.time_anomaly,
        }
        for f in page_files
    ]

    return {
        "files": files_data,
        "stats": {
            "total_files": total_img,
            "has_exif": has_exif_count,
            "no_exif": total_img - has_exif_count,
            "has_anomaly": has_anomaly_count,
        },
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ── 单文件修正时间 ──────────────────────────────────────────────────────────

@router.put("/api/files/{file_id}/exif/time")
async def set_file_exif_time(
    file_id: int,
    body: SetTimeRequest,
    db: AsyncSession = Depends(get_db),
):
    # 前端传入 UTC+8 展示时间，减 8h 转 UTC
    try:
        local_dt = datetime.fromisoformat(body.new_time)
    except ValueError:
        raise HTTPException(400, "Invalid datetime format")

    new_time_utc = local_dt - TZ_OFFSET

    try:
        result = await exif_service.set_file_time(db, file_id, new_time_utc)
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, str(e))


# ── 批量时间偏移 ────────────────────────────────────────────────────────────

@router.post("/api/tasks/{task_id}/exif/batch-offset")
async def batch_offset(
    task_id: int,
    body: BatchOffsetRequest,
    db: AsyncSession = Depends(get_db),
):
    if not body.file_ids:
        raise HTTPException(400, "file_ids must not be empty")
    if abs(body.offset_seconds) > 365 * 24 * 3600:
        raise HTTPException(400, "offset_seconds out of range")

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    try:
        result = await exif_service.apply_time_offset_to_files(
            db, task_id, body.file_ids, body.offset_seconds
        )
        await db.commit()
        return result
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, str(e))
