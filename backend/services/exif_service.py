"""EXIF/时间修正服务。

读取 EXIF 时间、推断 best_time、检测时间异常、写入 EXIF（JPEG）。
所有时间在数据库中存储为 UTC，展示时转 UTC+8。
"""
import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Awaitable

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import File, OperationLog
from services import operation_log as op_log

# ── 常量 ────────────────────────────────────────────────────────────────────

TZ_OFFSET = timedelta(hours=8)  # UTC+8
UTC8 = timezone(TZ_OFFSET)

# 文件名中时间的正则（按优先级排列）
_FILENAME_PATTERNS = [
    re.compile(r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})[-_T](\d{2})[-_:](\d{2})[-_:](\d{2})'),  # 20230815_143022 / 2023-08-15T14:30:22
    re.compile(r'(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})'),  # 20230815143022
]

ANOMALY_THRESHOLD = timedelta(hours=24)
TOO_OLD = datetime(2000, 1, 1)
JPEG_EXTENSIONS = {'.jpg', '.jpeg', '.JPG', '.JPEG'}

_EXIF_TIME_FMT = '%Y:%m:%d %H:%M:%S'


# ── 同步辅助函数（在线程池中调用）──────────────────────────────────────────────

def _read_exif_time_sync(file_path: str) -> tuple[datetime | None, bool]:
    """读取文件 EXIF 时间（同步）。

    返回 (exif_datetime_utc, has_exif)。
    相机写入的时间视为 UTC+8，转换为 UTC 存储。
    """
    try:
        import exifread
        with open(file_path, 'rb') as f:
            tags = exifread.process_file(f, stop_tag='DateTimeOriginal', details=False)

        has_exif = bool(tags)

        # 按优先级查找时间字段
        for tag_key in ('EXIF DateTimeOriginal', 'Image DateTime', 'EXIF DateTimeDigitized'):
            if tag_key in tags:
                time_str = str(tags[tag_key]).strip()
                try:
                    local_dt = datetime.strptime(time_str, _EXIF_TIME_FMT)
                    # 视为 UTC+8，转为 UTC
                    utc_dt = local_dt - TZ_OFFSET
                    return utc_dt, True
                except ValueError:
                    continue

        return None, has_exif

    except Exception:
        return None, False


def _parse_time_from_filename(file_name: str) -> datetime | None:
    """从文件名解析时间（同步）。

    匹配成功视为 UTC+8，减 8h 返回 UTC datetime。
    """
    for pattern in _FILENAME_PATTERNS:
        m = pattern.search(file_name)
        if m:
            try:
                y, mo, d, h, mi, s = (int(x) for x in m.groups())
                if 2000 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
                    local_dt = datetime(y, mo, d, h, mi, s)
                    return local_dt - TZ_OFFSET
            except (ValueError, OverflowError):
                continue
    return None


def _infer_best_time(
    exif_time: datetime | None,
    file_created: datetime | None,
    file_modified: datetime | None,
    file_name: str,
) -> tuple[datetime, str]:
    """推断最佳时间及来源标记。

    优先级：exif > filename > file_modified > file_created。
    file_created/file_modified 由 scanner 写入，在 UTC+8 环境下是本地时间，
    存储时未做时区处理，直接当作 UTC+8 使用（减 8h 转 UTC）。
    """
    if exif_time is not None:
        return exif_time, 'exif'

    filename_time = _parse_time_from_filename(file_name)
    if filename_time is not None:
        return filename_time, 'filename'

    # file_created/file_modified 在 UTC+8 系统上是本地时间，需减 8h
    if file_modified is not None:
        return file_modified - TZ_OFFSET, 'fs'

    if file_created is not None:
        return file_created - TZ_OFFSET, 'fs'

    # 兜底：使用当前时间
    return datetime.utcnow(), 'unknown'


def _detect_anomalies(
    exif_time: datetime | None,
    file_modified: datetime | None,
    best_time: datetime,
    has_exif: bool,
) -> str | None:
    """检测时间异常，返回逗号分隔的异常类型字符串，无异常返回 None。"""
    anomalies = []

    if not has_exif:
        anomalies.append('no_exif')

    now_utc = datetime.utcnow()
    if best_time > now_utc + timedelta(days=1):
        anomalies.append('future_time')

    if best_time < TOO_OLD:
        anomalies.append('too_old')

    if exif_time is not None and file_modified is not None:
        # file_modified 是 UTC+8 本地时间，减 8h 转 UTC 再比较
        file_modified_utc = file_modified - TZ_OFFSET
        if abs(exif_time - file_modified_utc) > ANOMALY_THRESHOLD:
            anomalies.append('exif_fs_mismatch')

    return ','.join(anomalies) if anomalies else None


def _write_exif_time_to_jpeg(file_path: str, new_time_utc: datetime) -> None:
    """将时间写入 JPEG 文件的 EXIF（同步）。

    new_time_utc 转为 UTC+8 后格式化写入。
    """
    import piexif

    # 转为 UTC+8 展示时间
    local_dt = new_time_utc + TZ_OFFSET
    time_bytes = local_dt.strftime(_EXIF_TIME_FMT).encode('ascii')

    try:
        exif_dict = piexif.load(file_path)
    except Exception:
        exif_dict = {'0th': {}, 'Exif': {}, 'GPS': {}, '1st': {}, 'thumbnail': None}

    exif_dict.setdefault('Exif', {})
    exif_dict.setdefault('0th', {})

    exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = time_bytes
    exif_dict['Exif'][piexif.ExifIFD.DateTimeDigitized] = time_bytes
    exif_dict['0th'][piexif.ImageIFD.DateTime] = time_bytes

    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, file_path)


def _process_file_exif(file_path: str, file_name: str, file_created, file_modified) -> dict:
    """在线程池中处理单个文件的 EXIF（同步）。"""
    exif_time, has_exif = _read_exif_time_sync(file_path)
    best_time, time_source = _infer_best_time(exif_time, file_created, file_modified, file_name)
    time_anomaly = _detect_anomalies(exif_time, file_modified, best_time, has_exif)
    return {
        'exif_time': exif_time,
        'has_exif': has_exif,
        'best_time': best_time,
        'time_source': time_source,
        'time_anomaly': time_anomaly,
    }


# ── 异步主入口 ──────────────────────────────────────────────────────────────

async def analyze_exif_for_task(
    db: AsyncSession,
    task_id: int,
    progress_cb: Callable[[int, int], Awaitable[None]],
) -> dict:
    """批量分析任务下所有图片的 EXIF 信息。

    使用 ThreadPoolExecutor 并发读取，每 200 条 flush 一次。
    返回统计摘要：{total, has_exif, no_exif, has_anomaly}
    """
    result = await db.execute(
        select(File).where(File.task_id == task_id, File.file_type == 'image')
    )
    files = result.scalars().all()
    total = len(files)

    if total == 0:
        return {'total': 0, 'has_exif': 0, 'no_exif': 0, 'has_anomaly': 0}

    await progress_cb(0, total)

    loop = asyncio.get_event_loop()
    stats = {'has_exif': 0, 'no_exif': 0, 'has_anomaly': 0}

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            loop.run_in_executor(
                pool,
                _process_file_exif,
                f.file_path,
                f.file_name,
                f.file_created,
                f.file_modified,
            )
            for f in files
        ]

        for i, (f, future) in enumerate(zip(files, futures)):
            data = await future
            f.has_exif = data['has_exif']
            f.exif_time = data['exif_time']
            f.best_time = data['best_time']
            f.time_source = data['time_source']
            f.time_anomaly = data['time_anomaly']

            if data['has_exif']:
                stats['has_exif'] += 1
            else:
                stats['no_exif'] += 1
            if data['time_anomaly']:
                stats['has_anomaly'] += 1

            if (i + 1) % 200 == 0:
                await db.flush()
                await progress_cb(i + 1, total)

    await db.flush()
    await progress_cb(total, total)

    return {'total': total, **stats}


async def set_file_time(
    db: AsyncSession,
    file_id: int,
    new_time_utc: datetime,
) -> dict:
    """单文件手动修正时间。

    JPEG 文件写入物理 EXIF，其他格式仅更新 DB。
    """
    result = await db.execute(select(File).where(File.id == file_id))
    f = result.scalar_one_or_none()
    if f is None:
        raise ValueError(f'File {file_id} not found')

    old_time = f.best_time
    is_jpeg = Path(f.file_path).suffix.lower() in {'.jpg', '.jpeg'}

    if is_jpeg and Path(f.file_path).exists():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_exif_time_to_jpeg, f.file_path, new_time_utc)

    f.exif_time = new_time_utc
    f.best_time = new_time_utc
    f.time_source = 'manual'
    f.has_exif = True
    f.time_anomaly = _detect_anomalies(new_time_utc, f.file_modified, new_time_utc, True)

    await op_log.record(
        db, f.task_id, 'exif_write', f.file_path,
        detail={
            'old_time': old_time.isoformat() if old_time else None,
            'new_time': new_time_utc.isoformat(),
            'format': 'jpeg' if is_jpeg else 'db_only',
        },
    )
    await db.flush()

    return {'ok': True, 'file_id': file_id, 'new_time': new_time_utc.isoformat()}


async def apply_time_offset_to_files(
    db: AsyncSession,
    task_id: int,
    file_ids: list[int],
    offset_seconds: int,
) -> dict:
    """批量时间偏移。

    JPEG 写入物理 EXIF，其他格式仅改 DB。
    """
    offset = timedelta(seconds=offset_seconds)
    loop = asyncio.get_event_loop()
    updated = 0
    errors = []

    result = await db.execute(
        select(File).where(File.id.in_(file_ids), File.task_id == task_id)
    )
    files = result.scalars().all()

    for f in files:
        try:
            old_exif = f.exif_time
            old_best = f.best_time

            if f.exif_time:
                f.exif_time = f.exif_time + offset
            if f.best_time:
                f.best_time = f.best_time + offset
            else:
                f.best_time = datetime.utcnow() + offset

            is_jpeg = Path(f.file_path).suffix.lower() in {'.jpg', '.jpeg'}
            if is_jpeg and f.exif_time and Path(f.file_path).exists():
                await loop.run_in_executor(None, _write_exif_time_to_jpeg, f.file_path, f.exif_time)

            # 重新检测异常
            f.time_anomaly = _detect_anomalies(f.exif_time, f.file_modified, f.best_time, f.has_exif)

            await op_log.record(
                db, task_id, 'exif_write', f.file_path,
                detail={
                    'old_time': old_best.isoformat() if old_best else None,
                    'new_time': f.best_time.isoformat(),
                    'offset_seconds': offset_seconds,
                    'format': 'jpeg' if is_jpeg else 'db_only',
                },
            )
            updated += 1

        except Exception as e:
            errors.append(f'{f.file_name}: {e}')

    await db.flush()
    return {'updated': updated, 'errors': errors}
