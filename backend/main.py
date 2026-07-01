"""Wedding AI Tool - FastAPI Entry"""
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Ensure backend package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import settings
from backend.routers import upload, task, result, asset
from backend.services.task_queue import init_queue

allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if origin.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle"""
    # Startup
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.output_dir, exist_ok=True)
    await init_queue()
    print(f"[OK] Server started: http://0.0.0.0:{settings.port}")
    print(f"[OK] Upload dir: {settings.upload_dir}")
    print(f"[OK] Output dir: {settings.output_dir}")
    yield
    # Shutdown
    print("[INFO] Server shutting down")


app = FastAPI(
    title="婚纱AI换装工具",
    description="为婚纱电商打造的一站式AI换装+换脸+场景生成工具",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - allow frontend cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes FIRST (before static mount to ensure precedence)
app.include_router(upload.router)
app.include_router(task.router)
app.include_router(result.router)
app.include_router(asset.router)


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "version": "1.0.0",
        "upload_dir_exists": os.path.exists(settings.upload_dir),
        "output_dir_exists": os.path.exists(settings.output_dir),
    }


# Static file serving for frontend (must be last - catches all remaining paths)
frontend_root = Path(__file__).parent.parent / "frontend"
frontend_dir = frontend_root / "dist" if (frontend_root / "dist").exists() else frontend_root
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
