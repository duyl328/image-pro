"""Thumbnail generation service."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from config import THUMBNAIL_DIR, THUMBNAIL_SIZE, THUMBNAIL_QUALITY


try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass


def _generate_thumbnail(file_path: str, task_id: int, file_id: int) -> str | None:
    """Generate a JPEG thumbnail. Returns the thumbnail path or None on failure."""
    try:
        out_dir = THUMBNAIL_DIR / str(task_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{file_id}.jpg"

        if out_path.exists():
            return str(out_path)

        img = Image.open(file_path)
        img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)

        # Convert to RGB if needed (e.g. RGBA, P mode)
        if img.mode not in ("RGB",):
            img = img.convert("RGB")

        img.save(str(out_path), "JPEG", quality=THUMBNAIL_QUALITY)
        return str(out_path)
    except Exception:
        return None


def _generate_video_thumbnail(file_path: str, task_id: int, file_id: int) -> str | None:
    """Extract first frame from video as thumbnail."""
    try:
        import cv2

        out_dir = THUMBNAIL_DIR / str(task_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{file_id}.jpg"

        if out_path.exists():
            return str(out_path)

        cap = cv2.VideoCapture(file_path)
        ret, frame = cap.read()
        cap.release()

        if not ret:
            return None

        # Convert BGR to RGB, then to PIL
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)
        img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
        img.save(str(out_path), "JPEG", quality=THUMBNAIL_QUALITY)
        return str(out_path)
    except Exception:
        return None


async def generate_thumbnails(
    files: list[tuple[int, str, str]],  # (file_id, file_path, file_type)
    task_id: int,
) -> dict[int, str]:
    """Generate thumbnails for a batch of files. Returns {file_id: thumbnail_path}."""
    loop = asyncio.get_event_loop()
    results: dict[int, str] = {}

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {}
        for file_id, file_path, file_type in files:
            if file_type == "video":
                fut = loop.run_in_executor(
                    pool, _generate_video_thumbnail, file_path, task_id, file_id
                )
            else:
                fut = loop.run_in_executor(
                    pool, _generate_thumbnail, file_path, task_id, file_id
                )
            futures[file_id] = fut

        for file_id, fut in futures.items():
            path = await fut
            if path:
                results[file_id] = path

    return results
