"""Duplicate & similarity detection — Pipeline A (exact) + Pipeline B (similar)."""

import asyncio
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from datetime import datetime
from typing import Optional

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    HASH_THREAD_WORKERS, DHASH_PROCESS_WORKERS, SIMILARITY_THRESHOLDS,
    IMAGE_EXTENSIONS,
)
from database.models import File, DuplicateGroup, DuplicateGroupMember
from services.hasher import compute_xxhash_partial, compute_sha256, compute_dhash, hamming_distance
from services import ws_manager


# ── Union-Find ──────────────────────────────────────────────────────────────

class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> bool:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1
        return True


# ── Recommend which file to keep ────────────────────────────────────────────

def _recommend_keep(files: list[File]) -> int:
    """Pick the best file to keep based on priority rules.

    Priority: resolution (via size as proxy) > file_size > has_exif > shorter path.
    """
    def sort_key(f: File):
        return (
            -(f.file_size or 0),
            -(1 if f.has_exif else 0),
            len(f.file_path),
        )

    ranked = sorted(files, key=sort_key)
    return ranked[0].id


# ── Pipeline A: Exact Duplicates ────────────────────────────────────────────

async def _pipeline_a_exact(
    db: AsyncSession,
    task_id: int,
    files: list[File],
) -> list[list[File]]:
    """Multi-stage exact duplicate detection.

    Stage 1: Group by file size
    Stage 2: Quick hash (xxHash of first+last 8KB)
    Stage 3: Full SHA-256
    """
    loop = asyncio.get_event_loop()

    # Stage 1: Group by file size
    size_groups: dict[int, list[File]] = defaultdict(list)
    for f in files:
        if f.file_size is not None:
            size_groups[f.file_size].append(f)

    # Keep only groups with 2+ files
    candidates = [g for g in size_groups.values() if len(g) >= 2]
    candidate_files = [f for group in candidates for f in group]

    await ws_manager.broadcast(task_id, "dup_pipeline_a_progress", {
        "stage": "size_group",
        "candidates": len(candidate_files),
        "total": len(files),
    })

    if not candidate_files:
        return []

    # Stage 2: Quick hash
    need_quick_hash = [f for f in candidate_files if not f.xxhash_partial]
    if need_quick_hash:
        with ThreadPoolExecutor(max_workers=HASH_THREAD_WORKERS) as pool:
            quick_futures = {
                f.id: loop.run_in_executor(pool, compute_xxhash_partial, f.file_path)
                for f in need_quick_hash
            }
            for f in need_quick_hash:
                try:
                    f.xxhash_partial = await quick_futures[f.id]
                except Exception:
                    pass
        await db.flush()

    await ws_manager.broadcast(task_id, "dup_pipeline_a_progress", {
        "stage": "quick_hash",
        "hashed": len(need_quick_hash),
    })

    # Group by (size, quick_hash)
    quick_groups: dict[tuple, list[File]] = defaultdict(list)
    for f in candidate_files:
        if f.xxhash_partial:
            quick_groups[(f.file_size, f.xxhash_partial)].append(f)
    sha_candidates = [g for g in quick_groups.values() if len(g) >= 2]
    sha_files = [f for group in sha_candidates for f in group]

    if not sha_files:
        return []

    # Stage 3: Full SHA-256
    need_sha = [f for f in sha_files if not f.sha256]
    if need_sha:
        with ThreadPoolExecutor(max_workers=HASH_THREAD_WORKERS) as pool:
            sha_futures = {
                f.id: loop.run_in_executor(pool, compute_sha256, f.file_path)
                for f in need_sha
            }
            for f in need_sha:
                try:
                    f.sha256 = await sha_futures[f.id]
                except Exception:
                    pass
        await db.flush()

    await ws_manager.broadcast(task_id, "dup_pipeline_a_progress", {
        "stage": "full_hash",
        "hashed": len(need_sha),
    })

    # Final grouping by SHA-256
    sha_groups: dict[str, list[File]] = defaultdict(list)
    for f in sha_files:
        if f.sha256:
            sha_groups[f.sha256].append(f)

    return [g for g in sha_groups.values() if len(g) >= 2]


# ── Pipeline B: Similar Images ──────────────────────────────────────────────

async def _pipeline_b_similar(
    db: AsyncSession,
    task_id: int,
    image_files: list[File],
    threshold: int,
) -> list[list[File]]:
    """Perceptual hash based similarity detection.

    Stage 1: Compute dHash for all images
    Stage 2: Numpy vectorized hamming distance
    Stage 3: Union-Find clustering
    """
    loop = asyncio.get_event_loop()

    if len(image_files) < 2:
        return []

    # Stage 1: Compute dHash (in process pool because Pillow doesn't release GIL)
    need_dhash = [f for f in image_files if not f.dhash]
    if need_dhash:
        with ProcessPoolExecutor(max_workers=DHASH_PROCESS_WORKERS) as pool:
            dhash_futures = {
                f.id: loop.run_in_executor(pool, compute_dhash, f.file_path)
                for f in need_dhash
            }
            for f in need_dhash:
                try:
                    result = await dhash_futures[f.id]
                    if result:
                        f.dhash = result
                except Exception:
                    pass
        await db.flush()

    await ws_manager.broadcast(task_id, "dup_pipeline_b_progress", {
        "stage": "dhash",
        "hashed": len(need_dhash),
        "total": len(image_files),
    })

    # Filter to files with valid dhash
    valid = [f for f in image_files if f.dhash]
    if len(valid) < 2:
        return []

    # Stage 2: Numpy vectorized hamming distance
    n = len(valid)
    # Convert hex hashes to integer array
    hash_ints = np.array([int(f.dhash, 16) for f in valid], dtype=np.uint64)

    # Stage 3: Union-Find
    uf = UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            xor = int(hash_ints[i]) ^ int(hash_ints[j])
            dist = bin(xor).count("1")
            if dist <= threshold:
                uf.union(i, j)

    # Build groups
    groups_map: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups_map[uf.find(i)].append(i)

    result = []
    for indices in groups_map.values():
        if len(indices) >= 2:
            result.append([valid[i] for i in indices])

    await ws_manager.broadcast(task_id, "dup_pipeline_b_progress", {
        "stage": "clustering",
        "groups": len(result),
    })

    return result


# ── Main Entry Point ────────────────────────────────────────────────────────

async def detect_duplicates(
    db: AsyncSession,
    task_id: int,
    similarity_level: str = "standard",
):
    """Run both pipelines and save results."""
    threshold = SIMILARITY_THRESHOLDS.get(similarity_level, 8)

    # Load all files for this task
    result = await db.execute(select(File).where(File.task_id == task_id))
    all_files = list(result.scalars().all())
    image_files = [f for f in all_files if f.file_type == "image"]

    await ws_manager.broadcast(task_id, "dup_start", {
        "total_files": len(all_files),
        "image_files": len(image_files),
        "similarity_level": similarity_level,
    })

    # Clear old results
    await db.execute(
        select(DuplicateGroup).where(DuplicateGroup.task_id == task_id)
    )
    old_groups = (await db.execute(
        select(DuplicateGroup).where(DuplicateGroup.task_id == task_id)
    )).scalars().all()
    for g in old_groups:
        await db.delete(g)
    await db.flush()

    # Run both pipelines concurrently
    exact_task = _pipeline_a_exact(db, task_id, all_files)
    similar_task = _pipeline_b_similar(db, task_id, image_files, threshold)

    exact_groups, similar_groups = await asyncio.gather(exact_task, similar_task)

    # Deduplicate: remove similar groups whose files are already fully covered by exact groups
    exact_file_ids: set[int] = set()
    for group in exact_groups:
        for f in group:
            exact_file_ids.add(f.id)

    filtered_similar: list[list[File]] = []
    for group in similar_groups:
        group_ids = {f.id for f in group}
        if not group_ids.issubset(exact_file_ids):
            filtered_similar.append(group)

    # Save exact groups
    for files_in_group in exact_groups:
        keep_id = _recommend_keep(files_in_group)
        group = DuplicateGroup(
            task_id=task_id,
            group_type="exact",
            similarity=1.0,
            file_count=len(files_in_group),
            recommended_keep_id=keep_id,
        )
        db.add(group)
        await db.flush()
        for f in files_in_group:
            member = DuplicateGroupMember(
                group_id=group.id,
                file_id=f.id,
                is_recommended=(f.id == keep_id),
            )
            db.add(member)

    # Save similar groups
    for files_in_group in filtered_similar:
        keep_id = _recommend_keep(files_in_group)
        group = DuplicateGroup(
            task_id=task_id,
            group_type="similar",
            file_count=len(files_in_group),
            recommended_keep_id=keep_id,
        )
        db.add(group)
        await db.flush()
        for f in files_in_group:
            member = DuplicateGroupMember(
                group_id=group.id,
                file_id=f.id,
                is_recommended=(f.id == keep_id),
            )
            db.add(member)

    await db.commit()

    summary = {
        "exact_groups": len(exact_groups),
        "similar_groups": len(filtered_similar),
        "exact_files": sum(len(g) for g in exact_groups),
        "similar_files": sum(len(g) for g in filtered_similar),
    }
    await ws_manager.broadcast(task_id, "dup_complete", summary)
    return summary
