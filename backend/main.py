"""Image Pro — FastAPI application entry point."""

import sys
from pathlib import Path

# Ensure backend/ is on the import path
sys.path.insert(0, str(Path(__file__).parent))

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import HOST, PORT, PROJECT_ROOT
from database.connection import init_db
from services import ws_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Image Pro", version="0.1.0", lifespan=lifespan)

# CORS — allow Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register API Routers ────────────────────────────────────────────────────
from api.tasks import router as tasks_router
from api.scan import router as scan_router
from api.duplicates import router as duplicates_router
from api.files import router as files_router
from api.logs import router as logs_router
from api.ai import router as ai_router

app.include_router(tasks_router)
app.include_router(scan_router)
app.include_router(duplicates_router)
app.include_router(files_router)
app.include_router(logs_router)
app.include_router(ai_router)


# ── WebSocket ───────────────────────────────────────────────────────────────
@app.websocket("/ws/tasks/{task_id}/progress")
async def ws_progress(websocket: WebSocket, task_id: int):
    await ws_manager.connect(task_id, websocket)
    try:
        while True:
            # Keep connection alive; client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(task_id, websocket)


# ── Serve frontend static files (production) ───────────────────────────────
frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


# ── Direct startup ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
