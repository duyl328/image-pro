"""Operation log API."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, OperationLog

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def list_logs(
    task_id: int = None,
    operation_type: str = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(OperationLog).order_by(OperationLog.created_at.desc())

    if task_id:
        query = query.where(OperationLog.task_id == task_id)
    if operation_type:
        query = query.where(OperationLog.operation_type == operation_type)

    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar()

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": log.id,
                "task_id": log.task_id,
                "operation_type": log.operation_type,
                "file_path": log.file_path,
                "target_path": log.target_path,
                "detail": log.detail,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }
