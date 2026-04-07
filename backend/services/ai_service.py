"""AI filtering service — OpenCLIP feature extraction + MLP classifier."""

import asyncio
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset, WeightedRandomSampler
from PIL import Image
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    CLIP_MODEL_NAME, CLIP_PRETRAINED, CLIP_FEATURE_DIM, CLIP_BATCH_SIZE,
    MODEL_DIR, MODEL_CURRENT_DIR, MODEL_HISTORY_DIR, MAX_MODEL_VERSIONS,
    AI_HIDDEN_DIM, AI_DROPOUT, AI_LEARNING_RATE, AI_BATCH_SIZE,
    AI_MAX_EPOCHS, AI_EARLY_STOP_PATIENCE, AI_FOCAL_GAMMA, AI_MIN_SAMPLES,
)
from database.models import File, AiLabel, AiModelVersion

# ---------------------------------------------------------------------------
#  MLP Classifier
# ---------------------------------------------------------------------------

class MLPClassifier(nn.Module):
    def __init__(self, input_dim: int = CLIP_FEATURE_DIM,
                 hidden_dim: int = AI_HIDDEN_DIM,
                 dropout: float = AI_DROPOUT):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, x):
        return self.net(x)


class FocalLoss(nn.Module):
    def __init__(self, gamma: float = AI_FOCAL_GAMMA):
        super().__init__()
        self.gamma = gamma

    def forward(self, logits: torch.Tensor, targets: torch.Tensor):
        probs = torch.sigmoid(logits)
        pt = targets * probs + (1 - targets) * (1 - probs)
        loss = -((1 - pt) ** self.gamma) * torch.log(pt + 1e-8)
        return loss.mean()


# ---------------------------------------------------------------------------
#  CLIP model management (load / unload)
# ---------------------------------------------------------------------------

_clip_model = None
_clip_preprocess = None
_clip_device = None


def _load_clip():
    print(f"[AI Service] _load_clip() called")
    global _clip_model, _clip_preprocess, _clip_device
    if _clip_model is not None:
        print(f"[AI Service] Model already loaded, skipping")
        return

    print(f"[AI Service] Starting model load process...")
    import open_clip
    from pathlib import Path
    import os

    # Disable HuggingFace offline mode to prevent hanging
    os.environ['HF_HUB_OFFLINE'] = '1'

    _clip_device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[AI Service] Device: {_clip_device}")

    try:
        print(f"[AI Service] Creating model architecture for {CLIP_MODEL_NAME}...")
        model, _, preprocess = open_clip.create_model_and_transforms(
            CLIP_MODEL_NAME,
            device=_clip_device,
        )
        print(f"[AI Service] Model architecture created")

        # Load weights from local file
        local_model_file = Path(__file__).parent.parent / "model" / "CLIP-ViT-L-14-laion2B-s32B-b82K" / "open_clip_pytorch_model.bin"
        print(f"[AI Service] Checking for weights at: {local_model_file}")
        if not local_model_file.exists():
            error_msg = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  CLIP 模型文件未找到                                                          ║
╚══════════════════════════════════════════════════════════════════════════════╝

请手动下载模型文件并放置到以下位置：

  路径: {local_model_file.absolute()}

下载地址:
  https://huggingface.co/laion/CLIP-ViT-L-14-laion2B-s32B-b82K/resolve/main/open_clip_pytorch_model.bin

或使用命令下载:
  mkdir -p {local_model_file.parent}
  wget -O {local_model_file} https://huggingface.co/laion/CLIP-ViT-L-14-laion2B-s32B-b82K/resolve/main/open_clip_pytorch_model.bin

文件大小: 约 1.7 GB
特征维度: 768 维
"""
            print(error_msg)
            raise FileNotFoundError(error_msg)

        print(f"[AI Service] Loading weights...")
        checkpoint = torch.load(local_model_file, map_location=_clip_device)
        model.load_state_dict(checkpoint)
        print(f"[AI Service] Weights loaded successfully")

        model.eval()
        _clip_model = model
        _clip_preprocess = preprocess
        print(f"[AI Service] CLIP model ready")
    except Exception as e:
        print(f"[AI Service] ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise


def _unload_clip():
    global _clip_model, _clip_preprocess, _clip_device
    if _clip_model is None:
        return
    del _clip_model
    _clip_model = None
    _clip_preprocess = None
    if _clip_device == "cuda":
        torch.cuda.empty_cache()
    _clip_device = None


# ---------------------------------------------------------------------------
#  Feature extraction
# ---------------------------------------------------------------------------

async def extract_features(
    session: AsyncSession,
    task_id: int,
    progress_cb: Optional[Callable] = None,
) -> int:
    """Extract OpenCLIP features for all images in a task. Returns count."""
    print(f"[AI Service] Starting feature extraction for task_id={task_id}")
    result = await session.execute(
        select(File.id, File.file_path)
        .where(File.task_id == task_id)
        .where(File.file_type == "image")
        .where(File.clip_feature.is_(None))
    )
    rows = result.all()
    total = len(rows)
    print(f"[AI Service] Found {total} images without features")
    if total == 0:
        return 0

    print(f"[AI Service] Loading OpenCLIP model...")
    await asyncio.to_thread(_load_clip)
    print(f"[AI Service] Model loaded, starting extraction...")
    batch_size = CLIP_BATCH_SIZE
    processed = 0

    def _process_batch(batch_rows):
        """Load images and run CLIP inference in a thread (CPU/GPU bound)."""
        images = []
        valid_ids = []
        for file_id, file_path in batch_rows:
            try:
                img = Image.open(file_path).convert("RGB")
                tensor = _clip_preprocess(img).unsqueeze(0)
                images.append(tensor)
                valid_ids.append(file_id)
            except Exception:
                continue

        if not images:
            return valid_ids, None

        batch_tensor = torch.cat(images).to(_clip_device)
        with torch.no_grad():
            features = _clip_model.encode_image(batch_tensor)
            features = features / features.norm(dim=-1, keepdim=True)
            features = features.cpu().numpy().astype(np.float32)
        return valid_ids, features

    try:
        for start in range(0, total, batch_size):
            batch_rows = rows[start : start + batch_size]

            valid_ids, features = await asyncio.to_thread(_process_batch, batch_rows)

            if features is not None:
                for i, file_id in enumerate(valid_ids):
                    blob = features[i].tobytes()
                    await session.execute(
                        update(File).where(File.id == file_id).values(clip_feature=blob)
                    )

            processed += len(batch_rows)
            if progress_cb:
                await progress_cb(processed, total)

        await session.commit()
    except torch.cuda.OutOfMemoryError:
        if batch_size > 1:
            await asyncio.to_thread(_unload_clip)
            torch.cuda.empty_cache()
            await asyncio.to_thread(_load_clip)
            raise
    finally:
        await asyncio.to_thread(_unload_clip)

    return processed


# ---------------------------------------------------------------------------
#  Labeling
# ---------------------------------------------------------------------------

async def label_files(
    session: AsyncSession,
    task_id: int,
    file_ids: list[int],
    label: str,
    source: str = "manual",
) -> int:
    """Label files as keep/delete. Returns count of labeled files."""
    print(f"[AI Service] Labeling {len(file_ids)} files: task_id={task_id}, label={label}, source={source}")
    now = datetime.now()
    count = 0
    for file_id in file_ids:
        existing = (await session.execute(
            select(AiLabel).where(AiLabel.file_id == file_id, AiLabel.task_id == task_id)
        )).scalar_one_or_none()

        if existing:
            existing.user_label = label
            existing.labeled_at = now
            existing.label_source = source
            existing.is_training_data = True
            print(f"[AI Service] Updated existing label for file_id={file_id}")
        else:
            session.add(AiLabel(
                file_id=file_id,
                task_id=task_id,
                user_label=label,
                labeled_at=now,
                label_source=source,
                is_training_data=True,
            ))
            print(f"[AI Service] Created new label for file_id={file_id}")
        count += 1

    await session.commit()
    print(f"[AI Service] Committed {count} labels to database")
    return count


async def get_label_stats(session: AsyncSession) -> dict:
    """Global label stats across all tasks."""
    result = await session.execute(
        select(
            func.count().label("total"),
            func.count(AiLabel.user_label).filter(AiLabel.user_label == "keep").label("keep"),
            func.count(AiLabel.user_label).filter(AiLabel.user_label == "delete").label("delete_"),
        ).where(AiLabel.user_label.isnot(None))
    )
    row = result.one()
    total = row.total
    keep = row.keep
    delete = row.delete_
    print(f"[AI Service] Label stats query result: total={total}, keep={keep}, delete={delete}")
    model_exists = (MODEL_CURRENT_DIR / "classifier.pt").exists()
    return {
        "total": total,
        "keep": keep,
        "delete": delete,
        "min_required": AI_MIN_SAMPLES,
        "ready": total >= AI_MIN_SAMPLES and keep > 0 and delete > 0,
        "model_exists": model_exists,
    }


# ---------------------------------------------------------------------------
#  Training
# ---------------------------------------------------------------------------

async def collect_training_data(session: AsyncSession):
    """Collect all labeled (feature, label) pairs across tasks."""
    result = await session.execute(
        select(File.clip_feature, AiLabel.user_label)
        .join(AiLabel, File.id == AiLabel.file_id)
        .where(AiLabel.user_label.isnot(None))
        .where(File.clip_feature.isnot(None))
    )
    rows = result.all()

    # Debug: check how many labeled files have features
    total_labeled = (await session.execute(
        select(func.count()).select_from(AiLabel).where(AiLabel.user_label.isnot(None))
    )).scalar()
    print(f"[AI Service] Collect training data: {len(rows)} files with features out of {total_labeled} labeled")

    if not rows:
        return None, None

    features = np.stack([np.frombuffer(r[0], dtype=np.float32) for r in rows])
    labels = np.array([1.0 if r[1] == "keep" else 0.0 for r in rows], dtype=np.float32)
    return features, labels


def _train_mlp(
    features: np.ndarray,
    labels: np.ndarray,
    progress_cb=None,
) -> dict:
    """Train MLP classifier synchronously. Returns metrics dict + state_dict."""
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Stratified split: 80/20
    keep_idx = np.where(labels == 1.0)[0]
    del_idx = np.where(labels == 0.0)[0]
    np.random.shuffle(keep_idx)
    np.random.shuffle(del_idx)

    val_keep = max(1, len(keep_idx) // 5)
    val_del = max(1, len(del_idx) // 5)
    val_indices = np.concatenate([keep_idx[:val_keep], del_idx[:val_del]])
    train_indices = np.concatenate([keep_idx[val_keep:], del_idx[val_del:]])

    X_train = torch.tensor(features[train_indices], dtype=torch.float32)
    y_train = torch.tensor(labels[train_indices], dtype=torch.float32).unsqueeze(1)
    X_val = torch.tensor(features[val_indices], dtype=torch.float32)
    y_val = torch.tensor(labels[val_indices], dtype=torch.float32).unsqueeze(1)

    # Balanced sampling
    train_labels = labels[train_indices]
    class_counts = np.bincount(train_labels.astype(int), minlength=2)
    weights = 1.0 / np.maximum(class_counts[train_labels.astype(int)], 1)
    sampler = WeightedRandomSampler(weights, num_samples=len(weights), replacement=True)

    train_ds = TensorDataset(X_train, y_train)
    train_loader = DataLoader(train_ds, batch_size=AI_BATCH_SIZE, sampler=sampler)

    model = MLPClassifier().to(device)
    criterion = FocalLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=AI_LEARNING_RATE)

    best_val_loss = float("inf")
    best_state = None
    best_metrics = {}
    patience_counter = 0

    for epoch in range(AI_MAX_EPOCHS):
        # Train
        model.train()
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()

        # Validate
        model.eval()
        with torch.no_grad():
            val_logits = model(X_val.to(device))
            val_loss = criterion(val_logits, y_val.to(device)).item()
            val_probs = torch.sigmoid(val_logits).cpu().numpy().flatten()
            val_preds = (val_probs > 0.5).astype(int)
            val_true = y_val.numpy().flatten().astype(int)

            acc = (val_preds == val_true).mean()
            tp = ((val_preds == 1) & (val_true == 1)).sum()
            fp = ((val_preds == 1) & (val_true == 0)).sum()
            fn = ((val_preds == 0) & (val_true == 1)).sum()
            precision = tp / max(tp + fp, 1)
            recall = tp / max(tp + fn, 1)
            f1 = 2 * precision * recall / max(precision + recall, 1e-8)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            best_metrics = {
                "val_accuracy": float(acc),
                "val_precision": float(precision),
                "val_recall": float(recall),
                "val_f1": float(f1),
            }
            patience_counter = 0
        else:
            patience_counter += 1

        if progress_cb:
            progress_cb(epoch + 1, AI_MAX_EPOCHS, float(acc), best_metrics.get("val_accuracy", 0))

        if patience_counter >= AI_EARLY_STOP_PATIENCE:
            break

    return {
        "state_dict": best_state,
        "metrics": best_metrics,
        "keep_samples": int((labels == 1.0).sum()),
        "delete_samples": int((labels == 0.0).sum()),
        "total_samples": len(labels),
        "epochs_run": epoch + 1,
    }


def _backup_current_model():
    """Backup current model to history, maintain max versions."""
    current_file = MODEL_CURRENT_DIR / "classifier.pt"
    if not current_file.exists():
        return

    MODEL_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    # Find next version number from existing history files
    existing = sorted(MODEL_HISTORY_DIR.glob("classifier_v*.pt"))
    if existing:
        last_num = int(existing[-1].stem.split("_v")[1])
        next_num = last_num + 1
    else:
        next_num = 1

    dest = MODEL_HISTORY_DIR / f"classifier_v{next_num:03d}.pt"
    shutil.copy2(current_file, dest)

    # Circular overwrite: remove oldest if exceeding max
    existing = sorted(MODEL_HISTORY_DIR.glob("classifier_v*.pt"))
    while len(existing) > MAX_MODEL_VERSIONS:
        existing[0].unlink()
        existing.pop(0)


async def train_model(
    session: AsyncSession,
    progress_cb=None,
) -> dict:
    """Full training pipeline. Returns version info."""
    features, labels = await collect_training_data(session)
    if features is None or len(features) < AI_MIN_SAMPLES:
        raise ValueError(f"Not enough labeled data: need {AI_MIN_SAMPLES}, got {len(features) if features is not None else 0}")

    keep_count = int((labels == 1.0).sum())
    delete_count = int((labels == 0.0).sum())
    if keep_count == 0 or delete_count == 0:
        raise ValueError("Need both 'keep' and 'delete' labels to train")

    # Backup existing model
    _backup_current_model()

    # Train
    t0 = time.time()
    result = _train_mlp(features, labels, progress_cb=progress_cb)
    training_time = time.time() - t0

    # Save model
    MODEL_CURRENT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_CURRENT_DIR / "classifier.pt"
    torch.save(result["state_dict"], model_path)

    # Determine version number
    last_version = (await session.execute(
        select(func.max(AiModelVersion.version))
    )).scalar() or 0
    new_version = last_version + 1

    # Clear old is_current flags
    await session.execute(
        update(AiModelVersion).values(is_current=False)
    )

    # Record version
    version_record = AiModelVersion(
        version=new_version,
        model_path=str(model_path),
        training_samples=result["total_samples"],
        keep_samples=result["keep_samples"],
        delete_samples=result["delete_samples"],
        val_accuracy=result["metrics"]["val_accuracy"],
        val_precision=result["metrics"]["val_precision"],
        val_recall=result["metrics"]["val_recall"],
        val_f1=result["metrics"]["val_f1"],
        training_time_sec=training_time,
        is_current=True,
    )
    session.add(version_record)
    await session.commit()

    return {
        "version": new_version,
        "accuracy": result["metrics"]["val_accuracy"],
        "precision": result["metrics"]["val_precision"],
        "recall": result["metrics"]["val_recall"],
        "f1": result["metrics"]["val_f1"],
        "training_samples": result["total_samples"],
        "keep_samples": result["keep_samples"],
        "delete_samples": result["delete_samples"],
        "training_time_sec": round(training_time, 1),
        "epochs_run": result["epochs_run"],
    }


# ---------------------------------------------------------------------------
#  Prediction / Inference
# ---------------------------------------------------------------------------

_classifier: Optional[MLPClassifier] = None


def _load_classifier():
    global _classifier
    model_path = MODEL_CURRENT_DIR / "classifier.pt"
    if not model_path.exists():
        raise FileNotFoundError("No trained model found. Please train first.")
    _classifier = MLPClassifier()
    _classifier.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
    _classifier.eval()


async def predict(
    session: AsyncSession,
    task_id: int,
    progress_cb: Optional[Callable] = None,
) -> dict:
    """Run inference on all images in a task. Returns summary."""
    _load_classifier()

    # Get current model version
    current_version = (await session.execute(
        select(AiModelVersion.version).where(AiModelVersion.is_current == True)
    )).scalar() or 0

    # Get all images with features that haven't been predicted by this version
    result = await session.execute(
        select(File.id, File.clip_feature)
        .where(File.task_id == task_id)
        .where(File.file_type == "image")
        .where(File.clip_feature.isnot(None))
    )
    rows = result.all()
    if not rows:
        return {"predicted": 0, "keep": 0, "delete": 0}

    file_ids = [r[0] for r in rows]
    features = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])

    # Batch inference
    with torch.no_grad():
        X = torch.tensor(features, dtype=torch.float32)
        logits = _classifier(X)
        probs = torch.sigmoid(logits).numpy().flatten()

    now = datetime.now()
    keep_count = 0
    delete_count = 0

    for i, file_id in enumerate(file_ids):
        raw_score = float(probs[i])
        prediction = "keep" if raw_score > 0.5 else "delete"
        confidence = abs(raw_score - 0.5) * 2

        if prediction == "keep":
            keep_count += 1
        else:
            delete_count += 1

        existing = (await session.execute(
            select(AiLabel).where(AiLabel.file_id == file_id, AiLabel.task_id == task_id)
        )).scalar_one_or_none()

        if existing:
            existing.ai_prediction = prediction
            existing.ai_confidence = confidence
            existing.ai_raw_score = raw_score
            existing.predicted_at = now
            existing.model_version = current_version
        else:
            session.add(AiLabel(
                file_id=file_id,
                task_id=task_id,
                ai_prediction=prediction,
                ai_confidence=confidence,
                ai_raw_score=raw_score,
                predicted_at=now,
                model_version=current_version,
            ))

        if progress_cb and (i + 1) % 500 == 0:
            await progress_cb(i + 1, len(file_ids))

    await session.commit()

    if progress_cb:
        await progress_cb(len(file_ids), len(file_ids))

    return {"predicted": len(file_ids), "keep": keep_count, "delete": delete_count}


# ---------------------------------------------------------------------------
#  Model management
# ---------------------------------------------------------------------------

async def get_model_versions(session: AsyncSession) -> list[dict]:
    result = await session.execute(
        select(AiModelVersion).order_by(AiModelVersion.version.desc())
    )
    versions = result.scalars().all()
    return [
        {
            "version": v.version,
            "training_samples": v.training_samples,
            "keep_samples": v.keep_samples,
            "delete_samples": v.delete_samples,
            "val_accuracy": v.val_accuracy,
            "val_precision": v.val_precision,
            "val_recall": v.val_recall,
            "val_f1": v.val_f1,
            "training_time_sec": v.training_time_sec,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "is_current": v.is_current,
        }
        for v in versions
    ]


async def rollback_model(session: AsyncSession, version: int) -> bool:
    """Rollback to a specific historical model version."""
    target = (await session.execute(
        select(AiModelVersion).where(AiModelVersion.version == version)
    )).scalar_one_or_none()
    if not target:
        return False

    # Find the backup file in history
    history_file = MODEL_HISTORY_DIR / f"classifier_v{version:03d}.pt"
    if not history_file.exists():
        return False

    # Backup current before rollback
    _backup_current_model()

    # Restore
    MODEL_CURRENT_DIR.mkdir(parents=True, exist_ok=True)
    dest = MODEL_CURRENT_DIR / "classifier.pt"
    shutil.copy2(history_file, dest)

    # Update is_current flags
    await session.execute(update(AiModelVersion).values(is_current=False))
    target.is_current = True
    await session.commit()

    # Reload classifier
    global _classifier
    _classifier = None

    return True


# ---------------------------------------------------------------------------
#  Extract status tracking (in-memory)
# ---------------------------------------------------------------------------

_extract_status: dict = {}
_train_status: dict = {}


def get_extract_status(task_id: int) -> dict:
    return _extract_status.get(task_id, {"status": "idle", "progress": 0, "total": 0})


def set_extract_status(task_id: int, status: str, progress: int = 0, total: int = 0):
    _extract_status[task_id] = {"status": status, "progress": progress, "total": total}


def get_train_status() -> dict:
    return _train_status.copy() if _train_status else {"status": "idle"}


def set_train_status(status: str, **kwargs):
    _train_status.update({"status": status, **kwargs})
