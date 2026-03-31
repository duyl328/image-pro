# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Image Pro (照片整理工具) is a local, offline photo/media organization workbench. Users process folders as independent "tasks" — scanning, deduplicating, fixing metadata, matching GPX tracks, and AI-assisted photo filtering. All destructive operations require user confirmation before execution.

Design documents (in Chinese):
- `photo_tool_requirements_design_cn_detailed.md` — requirements and product spec
- `photo_tool_technical_design_cn.md` — technical architecture and API design

## Tech Stack

- **Backend**: Python 3.11+ / FastAPI, SQLAlchemy + SQLite, async via `asyncio` + `ThreadPoolExecutor`
- **Frontend**: Vue 3 + Vite + TypeScript, Naive UI component library, Pinia state management
- **Image Processing**: Pillow, OpenCV, piexif, exifread, imagehash
- **AI/ML**: PyTorch + OpenCLIP (ViT-L/14), local GPU inference (CUDA)
- **Real-time**: WebSocket for progress updates during long-running operations

## Development Commands

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev          # Vite dev server, proxies API to port 8000

# Production build
cd frontend && npm run build
cd backend && python main.py   # Serves static files + API on :8000
```

## Architecture

### Backend (`backend/`)

Entry point: `main.py` (FastAPI + uvicorn).

- `api/` — Route handlers, one file per module: `tasks.py`, `scan.py`, `duplicates.py`, `exif.py`, `organize.py`, `gpx.py`, `ai.py`, `logs.py`, `files.py`
- `services/` — Core business logic: `scanner.py`, `hasher.py`, `duplicate_detector.py`, `exif_service.py`, `time_service.py`, `organizer.py`, `gpx_service.py`, `ai_service.py`, `thumbnail.py`, `operation_log.py`
- `database/` — SQLAlchemy ORM models (`models.py`), connection management, migrations
- `config.py` — Global configuration (DB path, model path, etc.)

### Frontend (`frontend/src/`)

- `views/` — One view per module: `HomeView`, `ScanView`, `DuplicateView`, `ExifView`, `OrganizeView`, `GpxView`, `AiFilterView`, `LogView`
- `stores/` — Pinia stores: `task.ts` (current task state), `app.ts` (global state)
- `api/` — Backend API call wrappers
- `components/` — Organized by feature (`layout/`, `common/`, `scan/`, `duplicate/`, `exif/`, `gpx/`, `ai/`)

### Data Flow

Each task follows: **Analyze → Preview → User Confirm → Execute → Log**. No file modification happens without explicit user confirmation.

Real-time progress for heavy operations (scanning, hashing, AI training) is pushed via WebSocket at `/ws/tasks/{id}/progress`.

## Key Modules

1. **Task Scan** — Recursive folder scan, file type classification, async with progress
2. **Duplicate Detection** — Two parallel pipelines:
   - Pipeline A (exact duplicates): file size grouping → xxHash (first+last 8KB) → full SHA-256
   - Pipeline B (similar images): dHash (8×8, 64-bit) → numpy hamming distance → Union-Find clustering
3. **EXIF/Time** — Time anomaly detection, manual correction, batch offset, organize into `YYYY/MM/` structure
4. **GPX Matching** — Binary search on GPX trackpoints, linear interpolation, ≤5min = good, >5min = warning
5. **AI Filtering** — OpenCLIP ViT-L/14 feature extraction (768-dim, cached in DB) → 2-layer MLP classifier (768→256→1, Focal Loss), cold-start requires ~200 labeled samples
6. **Operation Log** — All file modifications recorded with before/after state

## Concurrency Model

- I/O-bound tasks (file hashing): `ThreadPoolExecutor` (16 workers) — hashlib/xxhash release GIL
- CPU-bound tasks (image decoding for dHash): `ProcessPoolExecutor` (8-12 workers) — Pillow doesn't release GIL
- Hash results are cached in the `files` table and reused on re-scan if `(file_path, file_size, file_modified)` unchanged

## Database

SQLite via SQLAlchemy. Core tables: `tasks`, `files` (with hash/EXIF/CLIP feature columns), `duplicate_groups`, `duplicate_group_members`, `gpx_matches`, `ai_labels`, `ai_model_versions`, `operation_logs`.

Runtime data (DB, thumbnails, AI models) stored in `data/` — not version controlled.

## Important Conventions

- All times are UTC+8 (China Standard Time)
- File deletion uses `send2trash` (system recycle bin), never permanent delete
- AI model versioning: auto-backup before training, max 15 versions with circular overwrite in `data/models/`
- Duplicate group "recommended keep" priority: resolution → file size → has EXIF → standard filename → shortest path
- Similarity thresholds (hamming distance): loose ≤4, standard ≤8, strict ≤12
- Video support is limited: scan, stats, exact dedup, organize by date only — no EXIF fix, no GPS, no AI
- Target platform: Windows only (i7-13700K + RTX 4070 Ti Super)
