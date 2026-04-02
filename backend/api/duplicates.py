"""Duplicate & similarity detection API."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from send2trash import send2trash

from database import get_db, Task, File, DuplicateGroup, DuplicateGroupMember
from services.duplicate_detector import detect_duplicates
from services.operation_log import record

router = APIRouter(prefix="/api/tasks/{task_id}/duplicates", tags=["duplicates"])


@router.post("/detect")
async def start_detection(
    task_id: int,
    similarity_level: str = Query("standard", pattern="^(loose|standard|strict)$"),
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status not in ("ready", "completed"):
        raise HTTPException(400, "Task must be scanned first")

    async def _run():
        from database.connection import async_session
        async with async_session() as session:
            await detect_duplicates(session, task_id, similarity_level)

    asyncio.create_task(_run())
    return {"message": "Detection started", "task_id": task_id}


@router.get("/groups")
async def list_groups(
    task_id: int,
    group_type: str = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(DuplicateGroup)
        .where(DuplicateGroup.task_id == task_id)
        .order_by(DuplicateGroup.file_count.desc())
    )
    if group_type:
        query = query.where(DuplicateGroup.group_type == group_type)

    result = await db.execute(query)
    all_groups = result.scalars().all()
    total = len(all_groups)
    groups = all_groups[(page - 1) * page_size: page * page_size]

    items = []
    for g in groups:
        # Load members with file info
        members_result = await db.execute(
            select(DuplicateGroupMember, File)
            .join(File, DuplicateGroupMember.file_id == File.id)
            .where(DuplicateGroupMember.group_id == g.id)
        )
        members = []
        for member, file in members_result.all():
            members.append({
                "member_id": member.id,
                "file_id": file.id,
                "file_name": file.file_name,
                "relative_path": file.relative_path,
                "file_size": file.file_size,
                "extension": file.extension,
                "has_exif": file.has_exif,
                "file_modified": file.file_modified.isoformat() if file.file_modified else None,
                "is_recommended": member.is_recommended,
                "user_action": member.user_action,
                "thumbnail_path": file.thumbnail_path,
            })
        items.append({
            "id": g.id,
            "group_type": g.group_type,
            "similarity": g.similarity,
            "file_count": g.file_count,
            "recommended_keep_id": g.recommended_keep_id,
            "members": members,
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


class MemberAction(BaseModel):
    action: str  # keep / delete


@router.put("/groups/{group_id}/members/{member_id}")
async def set_member_action(
    task_id: int,
    group_id: int,
    member_id: int,
    body: MemberAction,
    db: AsyncSession = Depends(get_db),
):
    member = await db.get(DuplicateGroupMember, member_id)
    if not member or member.group_id != group_id:
        raise HTTPException(404, "Member not found")
    if body.action not in ("keep", "delete"):
        raise HTTPException(400, "Action must be 'keep' or 'delete'")
    member.user_action = body.action
    await db.commit()
    return {"ok": True}


@router.post("/execute")
async def execute_deletions(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Execute confirmed deletions — move files to system recycle bin."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    # Find all members marked for deletion
    result = await db.execute(
        select(DuplicateGroupMember, File)
        .join(File, DuplicateGroupMember.file_id == File.id)
        .join(DuplicateGroup, DuplicateGroupMember.group_id == DuplicateGroup.id)
        .where(DuplicateGroup.task_id == task_id)
        .where(DuplicateGroupMember.user_action == "delete")
    )

    deleted = 0
    errors = []
    for member, file in result.all():
        try:
            send2trash(file.file_path)
            await record(db, task_id, "delete", file.file_path, detail={
                "reason": "duplicate_detection",
                "group_id": member.group_id,
            })
            deleted += 1
        except Exception as e:
            errors.append({"file": file.file_path, "error": str(e)})

    await db.commit()
    return {"deleted": deleted, "errors": errors}
