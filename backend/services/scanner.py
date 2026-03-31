"""File scanning service — recursive folder scan with type detection."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, RAW_EXTENSIONS
from database.models import Task, File
from services import ws_manager

# Try python-magic for unknown extensions
try:
    import magic
    _magic_instance = magic.Magic(mime=True)

    def _guess_mime(path: str) -> Optional[str]:
        try:
            return _magic_instance.from_file(path)
        except Exception:
            return None
except ImportError:
    def _guess_mime(path: str) -> Optional[str]:
        return None


def _classify_file(file_path: Path) -> tuple[str, str]:
    """Return (file_type, mime_type) for a file."""
    ext = file_path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image", f"image/{ext.lstrip('.')}"
    if ext in VIDEO_EXTENSIONS:
        return "video", f"video/{ext.lstrip('.')}"
    if ext in RAW_EXTENSIONS:
        return "raw", f"image/{ext.lstrip('.')}"

    # Fallback: try magic bytes
    mime = _guess_mime(str(file_path))
    if mime:
        if mime.startswith("image/"):
            return "image", mime
        if mime.startswith("video/"):
            return "video", mime
    return "other", mime or "application/octet-stream"


def _scan_entry(file_path: Path, folder_root: Path) -> dict:
    """Collect metadata for a single file (runs in thread pool)."""
    stat = file_path.stat()
    file_type, mime_type = _classify_file(file_path)

    return {
        "file_path": str(file_path),
        "relative_path": str(file_path.relative_to(folder_root)),
        "file_name": file_path.name,
        "extension": file_path.suffix.lower() if file_path.suffix else None,
        "file_size": stat.st_size,
        "file_type": file_type,
        "mime_type": mime_type,
        "file_created": datetime.fromtimestamp(stat.st_ctime),
        "file_modified": datetime.fromtimestamp(stat.st_mtime),
    }


async def scan_folder(db: AsyncSession, task: Task):
    """Recursively scan a folder and populate the files table."""
    folder = Path(task.folder_path)
    if not folder.is_dir():
        raise ValueError(f"Not a directory: {folder}")

    task.status = "scanning"
    await db.commit()

    # Collect all file paths first
    all_paths: list[Path] = []
    for root, _dirs, files in os.walk(folder):
        for fname in files:
            all_paths.append(Path(root) / fname)

    total = len(all_paths)
    await ws_manager.broadcast(task.id, "scan_start", {"total": total})

    # Process in thread pool
    loop = asyncio.get_event_loop()
    image_count = 0
    video_count = 0
    other_count = 0
    batch: list[File] = []
    BATCH_SIZE = 200

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = []
        for fp in all_paths:
            futures.append(loop.run_in_executor(pool, _scan_entry, fp, folder))

        for i, future in enumerate(asyncio.as_completed(futures), 1):
            entry = await future
            file_obj = File(task_id=task.id, **entry)
            batch.append(file_obj)

            if entry["file_type"] == "image":
                image_count += 1
            elif entry["file_type"] == "video":
                video_count += 1
            else:
                other_count += 1

            if len(batch) >= BATCH_SIZE:
                db.add_all(batch)
                await db.flush()
                batch.clear()

            if i % 100 == 0 or i == total:
                await ws_manager.broadcast(task.id, "scan_progress", {
                    "current": i,
                    "total": total,
                    "images": image_count,
                    "videos": video_count,
                    "others": other_count,
                })

    if batch:
        db.add_all(batch)
        await db.flush()

    task.status = "ready"
    task.file_count = total
    task.image_count = image_count
    task.video_count = video_count
    task.other_count = other_count
    task.updated_at = datetime.now()
    await db.commit()

    await ws_manager.broadcast(task.id, "scan_complete", {
        "total": total,
        "images": image_count,
        "videos": video_count,
        "others": other_count,
    })


async def get_scan_summary(db: AsyncSession, task_id: int) -> dict:
    """Return file type statistics for a task."""
    result = await db.execute(
        select(File.extension, File.file_type)
        .where(File.task_id == task_id)
    )
    rows = result.all()

    by_type = {"image": 0, "video": 0, "raw": 0, "other": 0}
    by_ext: dict[str, int] = {}
    for ext, ftype in rows:
        by_type[ftype] = by_type.get(ftype, 0) + 1
        ext_key = ext or "(no extension)"
        by_ext[ext_key] = by_ext.get(ext_key, 0) + 1

    return {
        "total": len(rows),
        "by_type": by_type,
        "by_extension": dict(sorted(by_ext.items(), key=lambda x: -x[1])),
    }
