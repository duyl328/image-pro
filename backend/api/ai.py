"""AI filtering API routes."""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, File, AiLabel, AiModelVersion
from database.connection import async_session
from services import ai_service, ws_manager

router = APIRouter(tags=["ai"])


# ── Request models ──────────────────────────────────────────────────────────

class LabelRequest(BaseModel):
    label: str  # keep / delete

class BatchLabelRequest(BaseModel):
    file_ids: list[int]
    label: str  # keep / delete


# ── Feature extraction ──────────────────────────────────────────────────────

@router.post("/api/tasks/{task_id}/ai/extract")
async def start_extract(task_id: int, db: AsyncSession = Depends(get_db)):
    """Start feature extraction for a task (async)."""
    # Count pending
    total = (await db.execute(
        select(func.count()).select_from(File)
        .where(File.task_id == task_id, File.file_type == "image", File.clip_feature.is_(None))
    )).scalar() or 0
    already = (await db.execute(
        select(func.count()).select_from(File)
        .where(File.task_id == task_id, File.file_type == "image", File.clip_feature.isnot(None))
    )).scalar() or 0

    if total == 0:
        return {"total": 0, "already_extracted": already, "message": "All features already extracted"}

    ai_service.set_extract_status(task_id, "running", 0, total)

    async def _run():
        async with async_session() as session:
            try:
                async def progress_cb(done, total_):
                    ai_service.set_extract_status(task_id, "running", done, total_)
                    await ws_manager.broadcast(task_id, "extract_progress", {
                        "progress": done, "total": total_,
                    })

                count = await ai_service.extract_features(session, task_id, progress_cb)
                ai_service.set_extract_status(task_id, "completed", count, total)
                await ws_manager.broadcast(task_id, "extract_completed", {
                    "extracted": count, "total": total,
                })
            except Exception as e:
                ai_service.set_extract_status(task_id, "failed", 0, total)
                await ws_manager.broadcast(task_id, "extract_failed", {"error": str(e)})

    asyncio.create_task(_run())
    return {"total": total, "already_extracted": already}


@router.get("/api/tasks/{task_id}/ai/extract/status")
async def extract_status(task_id: int):
    return ai_service.get_extract_status(task_id)


# ── Labeling ────────────────────────────────────────────────────────────────

@router.put("/api/files/{file_id}/ai/label")
async def label_file(file_id: int, body: LabelRequest, db: AsyncSession = Depends(get_db)):
    """Label a single file."""
    if body.label not in ("keep", "delete"):
        raise HTTPException(400, "Label must be 'keep' or 'delete'")
    file = await db.get(File, file_id)
    if not file:
        raise HTTPException(404, "File not found")
    await ai_service.label_files(db, file.task_id, [file_id], body.label, "manual")
    return {"success": True}


@router.put("/api/tasks/{task_id}/ai/labels/batch")
async def batch_label(task_id: int, body: BatchLabelRequest, db: AsyncSession = Depends(get_db)):
    """Batch label files."""
    print(f"[AI] Batch label request: task_id={task_id}, file_ids={body.file_ids}, label={body.label}")
    if body.label not in ("keep", "delete"):
        raise HTTPException(400, "Label must be 'keep' or 'delete'")
    count = await ai_service.label_files(db, task_id, body.file_ids, body.label, "manual")
    print(f"[AI] Labeled {count} files")
    return {"labeled": count}


@router.get("/api/ai/labels/stats")
async def label_stats(db: AsyncSession = Depends(get_db)):
    stats = await ai_service.get_label_stats(db)
    print(f"[AI] Label stats: {stats}")
    return stats


# ── Training ────────────────────────────────────────────────────────────────

@router.post("/api/ai/train")
async def start_training(db: AsyncSession = Depends(get_db)):
    """Trigger model training (async)."""
    stats = await ai_service.get_label_stats(db)
    print(f"[AI] Training request, stats: {stats}")
    if not stats["ready"]:
        raise HTTPException(400, f"Not enough data: {stats['total']}/{stats['min_required']} labeled")
    if stats["keep"] == 0 or stats["delete"] == 0:
        raise HTTPException(400, "Need both 'keep' and 'delete' labels")

    ai_service.set_train_status("training", epoch=0, max_epochs=0, val_accuracy=0, best_accuracy=0)

    async def _run():
        async with async_session() as session:
            try:
                def progress_cb(epoch, max_epochs, acc, best_acc):
                    ai_service.set_train_status(
                        "training",
                        epoch=epoch, max_epochs=max_epochs,
                        val_accuracy=round(acc, 4), best_accuracy=round(best_acc, 4),
                    )

                result = await ai_service.train_model(session, progress_cb)
                ai_service.set_train_status("completed", **result)
            except Exception as e:
                ai_service.set_train_status("failed", error=str(e))

    asyncio.create_task(_run())
    return {"message": "Training started", "samples": stats["total"]}


@router.get("/api/ai/train/status")
async def train_status():
    return ai_service.get_train_status()


# ── Prediction ──────────────────────────────────────────────────────────────

@router.post("/api/tasks/{task_id}/ai/predict")
async def start_predict(task_id: int, db: AsyncSession = Depends(get_db)):
    """Run inference on task images."""
    async def progress_cb(done, total):
        await ws_manager.broadcast(task_id, "predict_progress", {
            "progress": done, "total": total,
        })

    result = await ai_service.predict(db, task_id, progress_cb)
    return result


@router.get("/api/tasks/{task_id}/ai/predictions")
async def get_predictions(
    task_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    prediction: str = Query(None),  # keep / delete / all
    confidence_min: float = Query(None, ge=0, le=1),
    confidence_max: float = Query(None, ge=0, le=1),
    label_status: str = Query(None),  # labeled / unlabeled / corrected / all
    sort_by: str = Query("confidence"),  # confidence / filename / size / score / time
    sort_order: str = Query("asc"),
    db: AsyncSession = Depends(get_db),
):
    """Get prediction results with filtering and sorting."""
    query = (
        select(
            File.id, File.file_name, File.file_size, File.relative_path,
            File.thumbnail_path, File.file_path,
            AiLabel.ai_prediction, AiLabel.ai_confidence,
            AiLabel.ai_raw_score, AiLabel.user_label,
            AiLabel.model_version,
        )
        .outerjoin(AiLabel, (File.id == AiLabel.file_id) & (AiLabel.task_id == task_id))
        .where(File.task_id == task_id, File.file_type == "image")
    )

    # Filters
    if prediction and prediction != "all":
        query = query.where(AiLabel.ai_prediction == prediction)

    if confidence_min is not None:
        query = query.where(AiLabel.ai_confidence >= confidence_min)
    if confidence_max is not None:
        query = query.where(AiLabel.ai_confidence <= confidence_max)

    if label_status == "labeled":
        query = query.where(AiLabel.user_label.isnot(None))
    elif label_status == "unlabeled":
        query = query.where(
            (AiLabel.user_label.is_(None)) | (AiLabel.id.is_(None))
        )
    elif label_status == "corrected":
        query = query.where(
            AiLabel.user_label.isnot(None),
            AiLabel.ai_prediction.isnot(None),
            AiLabel.user_label != AiLabel.ai_prediction,
        )

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Sort
    if sort_by == "confidence":
        sort_col = AiLabel.ai_confidence
    elif sort_by == "filename":
        sort_col = File.file_name
    elif sort_by == "size":
        sort_col = File.file_size
    elif sort_by == "score":
        sort_col = AiLabel.ai_raw_score
    elif sort_by == "time":
        sort_col = File.file_modified
    else:
        sort_col = AiLabel.ai_confidence

    if sort_order == "desc":
        query = query.order_by(sort_col.desc().nullslast())
    else:
        query = query.order_by(sort_col.asc().nullsfirst())

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = result.all()

    items = []
    for r in rows:
        is_corrected = (
            r.user_label is not None
            and r.ai_prediction is not None
            and r.user_label != r.ai_prediction
        )
        items.append({
            "file_id": r.id,
            "file_name": r.file_name,
            "file_size": r.file_size,
            "relative_path": r.relative_path,
            "thumbnail_path": r.thumbnail_path,
            "ai_prediction": r.ai_prediction,
            "ai_confidence": r.ai_confidence,
            "ai_raw_score": r.ai_raw_score,
            "user_label": r.user_label,
            "is_corrected": is_corrected,
        })

    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ── Model management ───────────────────────────────────────────────────────

@router.get("/api/ai/models")
async def list_models(db: AsyncSession = Depends(get_db)):
    return await ai_service.get_model_versions(db)


@router.post("/api/ai/models/{version}/rollback")
async def rollback(version: int, db: AsyncSession = Depends(get_db)):
    ok = await ai_service.rollback_model(db, version)
    if not ok:
        raise HTTPException(404, "Version not found or backup file missing")
    return {"success": True, "rolled_back_to": version}


# ── Execute delete ──────────────────────────────────────────────────────────

@router.post("/api/tasks/{task_id}/ai/execute-delete")
async def execute_delete(task_id: int, db: AsyncSession = Depends(get_db)):
    """Move all files marked as delete to recycle bin."""
    from send2trash import send2trash
    from database.models import OperationLog

    # Files labeled delete by user OR predicted delete by AI (not overridden by user)
    result = await db.execute(
        select(File.id, File.file_path, File.file_size)
        .join(AiLabel, (File.id == AiLabel.file_id) & (AiLabel.task_id == task_id))
        .where(File.task_id == task_id)
        .where(
            # User explicitly marked delete
            (AiLabel.user_label == "delete") |
            # AI predicted delete and user didn't override
            ((AiLabel.ai_prediction == "delete") & (AiLabel.user_label.is_(None)))
        )
    )
    rows = result.all()

    deleted = 0
    freed = 0
    errors = []
    deleted_file_ids = []

    for file_id, file_path, file_size in rows:
        try:
            send2trash(file_path)
            deleted += 1
            freed += file_size or 0
            deleted_file_ids.append(file_id)

            db.add(OperationLog(
                task_id=task_id,
                operation_type="delete",
                file_path=file_path,
                detail=f'{{"source": "ai_filter", "file_size": {file_size or 0}}}',
            ))
        except Exception as e:
            errors.append({"file_path": file_path, "error": str(e)})

        if deleted % 50 == 0:
            await ws_manager.broadcast(task_id, "delete_progress", {
                "progress": deleted, "total": len(rows),
            })

    # Remove DB records for deleted files
    if deleted_file_ids:
        await db.execute(
            AiLabel.__table__.delete().where(AiLabel.file_id.in_(deleted_file_ids))
        )
        await db.execute(
            File.__table__.delete().where(File.id.in_(deleted_file_ids))
        )

    await db.commit()

    return {
        "deleted": deleted,
        "freed_bytes": freed,
        "total_requested": len(rows),
        "errors": errors[:10] if errors else [],
    }
