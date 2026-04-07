"""GPX 地理匹配服务。"""
import asyncio
import bisect
from datetime import datetime, timezone, timedelta

import gpxpy
import piexif

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import File, GpxMatch
from services import operation_log

TZ8 = timezone(timedelta(hours=8))
GOOD_THRESHOLD_SEC = 300  # 5 分钟


# ── GPX 解析 ──────────────────────────────────────────────────────────────────

def parse_gpx_file(gpx_path: str) -> list[tuple[datetime, float, float]]:
    """解析单个 GPX 文件，返回 [(utc_time, lat, lng), ...] 按时间升序。"""
    points = []
    with open(gpx_path, "r", encoding="utf-8", errors="ignore") as f:
        gpx = gpxpy.parse(f)
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                if point.time is None:
                    continue
                # gpxpy 返回 aware datetime（UTC），统一转为 UTC naive
                pt_utc = point.time.astimezone(timezone.utc).replace(tzinfo=None)
                points.append((pt_utc, point.latitude, point.longitude))
    for route in gpx.routes:
        for point in route.points:
            if point.time is None:
                continue
            pt_utc = point.time.astimezone(timezone.utc).replace(tzinfo=None)
            points.append((pt_utc, point.latitude, point.longitude))
    points.sort(key=lambda x: x[0])
    return points


def merge_trackpoints(
    all_points_lists: list[list[tuple[datetime, float, float]]]
) -> list[tuple[datetime, float, float]]:
    """合并多个 GPX 轨迹点列表，排序并去重（同一时间戳取第一个）。"""
    merged = []
    for pts in all_points_lists:
        merged.extend(pts)
    merged.sort(key=lambda x: x[0])
    # 去重：同一秒内只保留一个
    deduped = []
    for pt in merged:
        if deduped and (pt[0] - deduped[-1][0]).total_seconds() == 0:
            continue
        deduped.append(pt)
    return deduped


# ── 匹配算法 ──────────────────────────────────────────────────────────────────

def _interpolate(
    p1: tuple[datetime, float, float],
    p2: tuple[datetime, float, float],
    target: datetime,
) -> tuple[float, float]:
    """在两轨迹点之间线性插值，返回 (lat, lng)。"""
    total = (p2[0] - p1[0]).total_seconds()
    if total == 0:
        return p1[1], p1[2]
    ratio = (target - p1[0]).total_seconds() / total
    ratio = max(0.0, min(1.0, ratio))
    lat = p1[1] + ratio * (p2[1] - p1[1])
    lng = p1[2] + ratio * (p2[2] - p1[2])
    return lat, lng


def match_time_to_trackpoints(
    photo_time_utc: datetime,
    trackpoints: list[tuple[datetime, float, float]],
) -> tuple[float | None, float | None, int | None, str]:
    """
    对单张照片做二分查找 + 线性插值匹配。
    返回 (lat, lng, time_offset_sec, match_quality)。
    match_quality: 'good' | 'warning' | 'no_match'
    """
    if not trackpoints:
        return None, None, None, "no_match"

    times = [pt[0] for pt in trackpoints]
    idx = bisect.bisect_left(times, photo_time_utc)

    if idx == 0:
        # 早于所有轨迹点，取第一个
        p = trackpoints[0]
        offset = int((photo_time_utc - p[0]).total_seconds())
        lat, lng = p[1], p[2]
    elif idx >= len(trackpoints):
        # 晚于所有轨迹点，取最后一个
        p = trackpoints[-1]
        offset = int((photo_time_utc - p[0]).total_seconds())
        lat, lng = p[1], p[2]
    else:
        # 在两点之间，线性插值
        p_before = trackpoints[idx - 1]
        p_after = trackpoints[idx]
        lat, lng = _interpolate(p_before, p_after, photo_time_utc)
        # 偏差取到较近点的距离
        off1 = abs((photo_time_utc - p_before[0]).total_seconds())
        off2 = abs((photo_time_utc - p_after[0]).total_seconds())
        offset = int(min(off1, off2))
        if photo_time_utc < p_before[0]:
            offset = -offset

    quality = "good" if abs(offset) <= GOOD_THRESHOLD_SEC else "warning"
    return lat, lng, offset, quality


# ── GPS 写入 JPEG ─────────────────────────────────────────────────────────────

def _deg_to_dms_rational(deg: float) -> list[tuple[int, int]]:
    """十进制度 → DMS 有理数列表（piexif 格式）。"""
    d = int(abs(deg))
    m_float = (abs(deg) - d) * 60
    m = int(m_float)
    s = round((m_float - m) * 60 * 10000)
    return [(d, 1), (m, 1), (s, 10000)]


def _write_gps_to_jpeg_sync(file_path: str, lat: float, lng: float) -> None:
    """同步：将 GPS 坐标写入 JPEG EXIF（在 executor 中调用）。"""
    try:
        exif_dict = piexif.load(file_path)
    except Exception:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

    gps_ifd = {
        piexif.GPSIFD.GPSVersionID: (2, 0, 0, 0),
        piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
        piexif.GPSIFD.GPSLatitude: _deg_to_dms_rational(lat),
        piexif.GPSIFD.GPSLongitudeRef: b"E" if lng >= 0 else b"W",
        piexif.GPSIFD.GPSLongitude: _deg_to_dms_rational(lng),
    }
    exif_dict["GPS"] = gps_ifd
    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, file_path)


# ── 主要业务函数 ──────────────────────────────────────────────────────────────

async def match_gpx_for_task(
    db: AsyncSession,
    task_id: int,
    gpx_paths: list[str],
    progress_cb,
) -> dict:
    """
    解析所有 GPX 文件，对 task 下所有有 best_time 的 image 文件进行匹配，
    结果写入 gpx_matches 表（先清空再写入），更新 files.has_gps/gps_lat/gps_lng。
    返回 {total, matched_good, matched_warning, no_match}
    """
    loop = asyncio.get_event_loop()

    # 1. 解析并合并所有 GPX 文件
    all_points_lists = []
    parse_errors = []
    for gpx_path in gpx_paths:
        try:
            pts = await loop.run_in_executor(None, parse_gpx_file, gpx_path)
            all_points_lists.append(pts)
        except Exception as e:
            parse_errors.append({"path": gpx_path, "error": str(e)})

    trackpoints = merge_trackpoints(all_points_lists)

    # 2. 查询 task 下所有有 best_time 的 image 文件
    result = await db.execute(
        select(File).where(
            File.task_id == task_id,
            File.file_type == "image",
            File.best_time.is_not(None),
        )
    )
    files = result.scalars().all()
    total = len(files)

    # 3. 清空旧匹配记录
    await db.execute(delete(GpxMatch).where(GpxMatch.task_id == task_id))

    # 4. 匹配并写入
    stats = {"total": total, "matched_good": 0, "matched_warning": 0, "no_match": 0}

    batch = []
    for i, file in enumerate(files):
        lat, lng, offset, quality = match_time_to_trackpoints(
            file.best_time, trackpoints
        )

        match = GpxMatch(
            task_id=task_id,
            file_id=file.id,
            gpx_file_path=gpx_paths[0] if gpx_paths else None,
            matched_lat=lat,
            matched_lng=lng,
            time_offset_sec=offset,
            match_quality=quality,
            user_confirmed=False,
            original_has_gps=bool(file.has_gps),
        )
        batch.append(match)

        # 更新 File GPS 字段（DB 层面）
        if quality != "no_match":
            file.has_gps = True
            file.gps_lat = lat
            file.gps_lng = lng
        else:
            file.has_gps = False
            file.gps_lat = None
            file.gps_lng = None

        if quality == "good":
            stats["matched_good"] += 1
        elif quality == "warning":
            stats["matched_warning"] += 1
        else:
            stats["no_match"] += 1

        # 每 50 条 flush + 进度回调
        if (i + 1) % 50 == 0:
            for m in batch:
                db.add(m)
            batch = []
            await db.flush()
            await progress_cb(i + 1, total)

    # 写入剩余
    for m in batch:
        db.add(m)
    await db.flush()
    if total % 50 != 0:
        await progress_cb(total, total)

    return stats


async def execute_gps_write(
    db: AsyncSession,
    task_id: int,
    file_ids: list[int],
    mode: str,
) -> dict:
    """
    将匹配结果写入 JPEG EXIF 物理文件，记录 operation_log。
    mode: 'overwrite'（覆盖）或 'fill_only'（仅无 GPS 文件）
    返回 {written, skipped, errors}
    """
    loop = asyncio.get_event_loop()

    # 查询 gpx_matches 和关联文件
    result = await db.execute(
        select(GpxMatch, File)
        .join(File, GpxMatch.file_id == File.id)
        .where(
            GpxMatch.task_id == task_id,
            GpxMatch.file_id.in_(file_ids),
            GpxMatch.match_quality != "no_match",
        )
    )
    rows = result.all()

    written = 0
    skipped = 0
    errors = []

    for gpx_match, file in rows:
        # fill_only 模式跳过原本已有 GPS 的文件
        if mode == "fill_only" and gpx_match.original_has_gps:
            skipped += 1
            continue

        ext = (file.extension or "").lower()
        if ext in ("jpg", "jpeg"):
            try:
                await loop.run_in_executor(
                    None,
                    _write_gps_to_jpeg_sync,
                    file.file_path,
                    gpx_match.matched_lat,
                    gpx_match.matched_lng,
                )
                gpx_match.user_confirmed = True
                await operation_log.record(
                    db,
                    task_id=task_id,
                    operation_type="gps_write",
                    file_path=file.file_path,
                    detail={
                        "lat": gpx_match.matched_lat,
                        "lng": gpx_match.matched_lng,
                        "mode": mode,
                        "time_offset_sec": gpx_match.time_offset_sec,
                        "match_quality": gpx_match.match_quality,
                    },
                )
                written += 1
            except Exception as e:
                errors.append({"file": file.file_name, "error": str(e)})
        else:
            # 非 JPEG 只更新 DB，不写物理文件
            gpx_match.user_confirmed = True
            written += 1

    await db.flush()
    return {"written": written, "skipped": skipped, "errors": errors}
