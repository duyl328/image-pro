"""Empty folder cleanup API."""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, Task

router = APIRouter(prefix="/api/tasks/{task_id}/empty-folders", tags=["empty-folders"])


def _get_task_root(task: Task) -> Path:
    root = Path(task.folder_path).resolve()
    if not root.is_dir():
        raise HTTPException(400, f"Task folder not found: {task.folder_path}")
    return root


def _find_deletable_empty_dirs(root: Path) -> list[Path]:
    removable: list[Path] = []
    removable_set: set[Path] = set()

    for current_root, dirnames, filenames in os.walk(root, topdown=False):
        current_path = Path(current_root).resolve()
        if current_path == root:
            continue

        remaining_child_dirs = [
            current_path / dirname
            for dirname in dirnames
            if (current_path / dirname).resolve() not in removable_set
        ]

        if filenames or remaining_child_dirs:
            continue

        removable.append(current_path)
        removable_set.add(current_path)

    return removable


def _serialize_empty_dir(root: Path, path: Path) -> dict:
    return {
        "relative_path": str(path.relative_to(root)),
        "absolute_path": str(path),
        "depth": len(path.relative_to(root).parts),
    }


@router.get("")
async def list_empty_folders(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    root = _get_task_root(task)
    items = [_serialize_empty_dir(root, path) for path in _find_deletable_empty_dirs(root)]
    items.sort(key=lambda item: (item["relative_path"].lower(), item["relative_path"]))

    return {
        "task_id": task_id,
        "root_path": str(root),
        "total": len(items),
        "items": items,
    }


@router.delete("")
async def delete_empty_folders(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    root = _get_task_root(task)
    candidates = _find_deletable_empty_dirs(root)
    deleted = 0
    errors = []

    for path in candidates:
        try:
            path.rmdir()
            deleted += 1
        except OSError as exc:
            errors.append({
                "relative_path": str(path.relative_to(root)),
                "error": str(exc),
            })

    return {
        "task_id": task_id,
        "root_path": str(root),
        "deleted": deleted,
        "total_requested": len(candidates),
        "errors": errors[:20],
    }
