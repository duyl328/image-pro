"""Task management API."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, Task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    folder_path: str
    name: Optional[str] = None


class TaskResponse(BaseModel):
    id: int
    folder_path: str
    name: Optional[str]
    status: str
    file_count: int
    image_count: int
    video_count: int
    other_count: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


@router.post("", response_model=TaskResponse)
async def create_task(body: TaskCreate, db: AsyncSession = Depends(get_db)):
    from pathlib import Path
    folder = Path(body.folder_path)
    if not folder.is_dir():
        raise HTTPException(400, f"Directory not found: {body.folder_path}")

    task = Task(
        folder_path=str(folder.resolve()),
        name=body.name or folder.name,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.get("", response_model=list[TaskResponse])
async def list_tasks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).order_by(Task.created_at.desc()))
    return result.scalars().all()


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@router.delete("/{task_id}")
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    await db.delete(task)
    await db.commit()
    return {"ok": True}
