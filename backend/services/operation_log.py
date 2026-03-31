import json
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import OperationLog


async def record(
    db: AsyncSession,
    task_id: int,
    operation_type: str,
    file_path: str,
    target_path: str = None,
    detail: dict = None,
):
    log = OperationLog(
        task_id=task_id,
        operation_type=operation_type,
        file_path=file_path,
        target_path=target_path,
        detail=json.dumps(detail, ensure_ascii=False) if detail else None,
        created_at=datetime.now(),
    )
    db.add(log)
    await db.flush()
