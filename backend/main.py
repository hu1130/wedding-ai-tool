"""Wedding AI Tool - FastAPI Entry"""
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Ensure backend package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import settings
from backend.logging_config import configure_logging
from backend.routers import upload, task, result, asset, quality_review, auth
from backend.services.cleanup import run_cleanup
from backend.services.task_queue import init_queue
from backend.storage import database

configure_logging()
logger = logging.getLogger(__name__)

allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if origin.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle"""
    # Startup
    if settings.app_env == "production" and not database.is_mysql_url():
        raise RuntimeError("Production requires DATABASE_URL with mysql+pymysql")
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.output_dir, exist_ok=True)
    database.initialize()
    if settings.cleanup_enabled:
        cleanup_result = run_cleanup(dry_run=False)
        logger.info("Startup cleanup summary=%s", cleanup_result.get("summary", {}))
    await init_queue()
    logger.info("Server started host=0.0.0.0 port=%s", settings.port)
    logger.info("Upload dir=%s", settings.upload_dir)
    logger.info("Output dir=%s", settings.output_dir)
    logger.info("Object storage mode=%s", settings.object_storage_mode)
    logger.info("Auth enabled=%s rate_limit_enabled=%s", settings.auth_enabled, settings.rate_limit_enabled)
    yield
    # Shutdown
    logger.info("Server shutting down")


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
    allow_credentials=settings.auth_enabled,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes FIRST (before static mount to ensure precedence)
app.include_router(upload.router)
app.include_router(task.router)
app.include_router(result.router)
app.include_router(asset.router)
app.include_router(quality_review.router)
app.include_router(auth.router)
app.include_router(auth.platform_router)


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "version": "1.0.0",
        "upload_dir_exists": os.path.exists(settings.upload_dir),
        "output_dir_exists": os.path.exists(settings.output_dir),
        "object_storage_mode": settings.object_storage_mode,
        "auth_enabled": settings.auth_enabled,
        "auth_mode": settings.auth_mode,
        "rate_limit_enabled": settings.rate_limit_enabled,
        "database": "mysql" if database.is_mysql_url() else "sqlite-local",
    }


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return await health_check()


# Static file serving for frontend (must be last - catches all remaining paths)
frontend_root = Path(__file__).parent.parent / "frontend"
frontend_dir = frontend_root / "dist" if (frontend_root / "dist").exists() else frontend_root


def frontend_index_response():
    """Serve the SPA entry for browser routes."""
    index_path = frontend_dir / "index.html"
    return FileResponse(index_path)


@app.get("/works", include_in_schema=False)
async def frontend_works_route():
    return frontend_index_response()


@app.get("/help", include_in_schema=False)
async def frontend_help_route():
    return frontend_index_response()


@app.get("/studio", include_in_schema=False)
async def frontend_studio_route():
    return frontend_index_response()


@app.get("/test", include_in_schema=False)
async def frontend_test_route():
    """Serve the SPA entry for the test studio route."""
    return frontend_index_response()


if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
