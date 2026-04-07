"""GPX 地理匹配 API。"""
import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, Task, File
from database.models import GpxMatch
from services import ws_manager
from services import gpx_service

router = APIRouter(tags=["gpx"])


class MatchRequest(BaseModel):
    gpx_paths: list[str]


class ExecuteWriteRequest(BaseModel):
    file_ids: list[int]
    mode: str = "fill_only"  # 'overwrite' | 'fill_only'


# ── 启动 GPX 匹配 ────────────────────────────────────────────────────────────

@router.post("/api/tasks/{task_id}/gpx/match")
async def start_gpx_match(
    task_id: int,
    body: MatchRequest,
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status not in ("ready", "completed"):
        raise HTTPException(400, "Task must be scanned first")
    if not body.gpx_paths:
        raise HTTPException(400, "gpx_paths must not be empty")

    # 验证文件存在
    missing = [p for p in body.gpx_paths if not os.path.isfile(p)]
    if missing:
        raise HTTPException(400, f"GPX files not found: {missing}")

    async def _run():
        from database.connection import async_session
        async with async_session() as session:
            # 先查文件总数
            count_result = await session.execute(
                select(func.count()).where(
                    File.task_id == task_id,
                    File.file_type == "image",
                    File.best_time.is_not(None),
                )
            )
            total = count_result.scalar_one()
            await ws_manager.broadcast(task_id, "gpx_start", {"total": total})

            async def progress_cb(current: int, total: int):
                await ws_manager.broadcast(
                    task_id, "gpx_progress", {"current": current, "total": total}
                )

            try:
                stats = await gpx_service.match_gpx_for_task(
                    session, task_id, body.gpx_paths, progress_cb
                )
                await session.commit()
                await ws_manager.broadcast(task_id, "gpx_complete", stats)
            except Exception as e:
                await session.rollback()
                await ws_manager.broadcast(task_id, "gpx_error", {"message": str(e)})

    asyncio.create_task(_run())
    return {"message": "GPX matching started", "task_id": task_id}


# ── 获取匹配结果列表 ─────────────────────────────────────────────────────────

@router.get("/api/tasks/{task_id}/gpx/results")
async def list_gpx_results(
    task_id: int,
    filter: str = Query("all", pattern="^(all|good|warning|no_match)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    base_q = (
        select(GpxMatch, File)
        .join(File, GpxMatch.file_id == File.id)
        .where(GpxMatch.task_id == task_id)
    )
    if filter != "all":
        base_q = base_q.where(GpxMatch.match_quality == filter)

    result = await db.execute(base_q.order_by(File.file_name))
    all_rows = result.all()
    total = len(all_rows)
    page_rows = all_rows[(page - 1) * page_size: page * page_size]

    # 统计（全量）
    stats_result = await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(GpxMatch.match_quality == "good").label("good"),
            func.count().filter(GpxMatch.match_quality == "warning").label("warning"),
            func.count().filter(GpxMatch.match_quality == "no_match").label("no_match"),
        ).where(GpxMatch.task_id == task_id)
    )
    sr = stats_result.one()

    def fmt_dt(dt):
        return dt.isoformat() if dt else None

    matches_data = [
        {
            "id": m.id,
            "file_id": m.file_id,
            "file_name": f.file_name,
            "relative_path": f.relative_path,
            "extension": f.extension,
            "best_time": fmt_dt(f.best_time),
            "matched_lat": m.matched_lat,
            "matched_lng": m.matched_lng,
            "time_offset_sec": m.time_offset_sec,
            "match_quality": m.match_quality,
            "user_confirmed": m.user_confirmed,
            "original_has_gps": m.original_has_gps,
        }
        for m, f in page_rows
    ]

    return {
        "matches": matches_data,
        "stats": {
            "total": sr[0] or 0,
            "good": sr[1] or 0,
            "warning": sr[2] or 0,
            "no_match": sr[3] or 0,
        },
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ── 执行写入 GPS 到物理文件 ──────────────────────────────────────────────────

@router.post("/api/tasks/{task_id}/gpx/execute")
async def execute_gps_write(
    task_id: int,
    body: ExecuteWriteRequest,
    db: AsyncSession = Depends(get_db),
):
    if not body.file_ids:
        raise HTTPException(400, "file_ids must not be empty")
    if body.mode not in ("overwrite", "fill_only"):
        raise HTTPException(400, "mode must be 'overwrite' or 'fill_only'")

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    try:
        result = await gpx_service.execute_gps_write(
            db, task_id, body.file_ids, body.mode
        )
        await db.commit()
        return result
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, str(e))


# ── 清空匹配记录 ─────────────────────────────────────────────────────────────

@router.delete("/api/tasks/{task_id}/gpx/matches")
async def clear_gpx_matches(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    try:
        await db.execute(delete(GpxMatch).where(GpxMatch.task_id == task_id))
        # 重置 files GPS 字段
        result = await db.execute(
            select(File).where(File.task_id == task_id, File.has_gps.is_(True))
        )
        files = result.scalars().all()
        for f in files:
            f.has_gps = False
            f.gps_lat = None
            f.gps_lng = None
        await db.commit()
        return {"message": "GPX matches cleared"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, str(e))


# ── 获取轨迹图数据 ───────────────────────────────────────────────────────────

@router.get("/api/tasks/{task_id}/gpx/track")
async def get_gpx_track(
    task_id: int,
    max_points: int = Query(2000, ge=100, le=10000),
    db: AsyncSession = Depends(get_db),
):
    """
    返回轨迹线坐标（降采样）和照片匹配点，供前端 SVG 渲染。
    轨迹点来自第一个 gpx_file_path（从 gpx_matches 取样），
    照片点来自 gpx_matches 表中所有 match_quality != 'no_match' 的记录。
    """
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    # 取所有匹配记录（用于获取 gpx_file_path）
    match_result = await db.execute(
        select(GpxMatch, File)
        .join(File, GpxMatch.file_id == File.id)
        .where(GpxMatch.task_id == task_id)
        .order_by(File.best_time)
    )
    rows = match_result.all()

    if not rows:
        return {"track": [], "photos": []}

    # 照片匹配点
    def fmt_dt(dt):
        if not dt:
            return None
        from datetime import timezone, timedelta
        shifted = dt.replace(tzinfo=timezone.utc) + timedelta(hours=8)
        return shifted.strftime("%Y-%m-%d %H:%M:%S")

    photos = [
        {
            "file_id": m.file_id,
            "file_name": f.file_name,
            "lat": m.matched_lat,
            "lng": m.matched_lng,
            "time_offset_sec": m.time_offset_sec,
            "match_quality": m.match_quality,
            "best_time": fmt_dt(f.best_time),
        }
        for m, f in rows
        if m.match_quality != "no_match"
    ]

    # 解析轨迹线（在 executor 中读取 GPX 文件）
    gpx_path = rows[0][0].gpx_file_path
    track_points = []
    if gpx_path:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            raw_points = await loop.run_in_executor(
                None, gpx_service.parse_gpx_file, gpx_path
            )
            # 降采样：均匀取样到 max_points
            total = len(raw_points)
            if total <= max_points:
                track_points = [[p[1], p[2]] for p in raw_points]
            else:
                step = total / max_points
                track_points = [
                    [raw_points[int(i * step)][1], raw_points[int(i * step)][2]]
                    for i in range(max_points)
                ]
                # 确保末尾点包含
                track_points.append([raw_points[-1][1], raw_points[-1][2]])
        except Exception:
            track_points = []

    return {"track": track_points, "photos": photos}


# ── 获取匹配统计 ─────────────────────────────────────────────────────────────

@router.get("/api/tasks/{task_id}/gpx/stats")
async def get_gpx_stats(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    result = await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(GpxMatch.match_quality == "good").label("good"),
            func.count().filter(GpxMatch.match_quality == "warning").label("warning"),
            func.count().filter(GpxMatch.match_quality == "no_match").label("no_match"),
            func.count().filter(GpxMatch.user_confirmed.is_(True)).label("confirmed"),
        ).where(GpxMatch.task_id == task_id)
    )
    row = result.one()
    return {
        "total": row[0] or 0,
        "good": row[1] or 0,
        "warning": row[2] or 0,
        "no_match": row[3] or 0,
        "confirmed": row[4] or 0,
    }
