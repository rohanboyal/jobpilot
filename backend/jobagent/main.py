"""FastAPI application. Serves the API under /api and the built React app (web/dist) at /."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import scheduler
from .api import (
    applications,
    companies,
    jobs,
    pipeline,
    profile,
    profiles,
    resumes,
    runs,
    settings,
    stats,
    today,
)
from .bootstrap import bootstrap
from .config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap(recover=True)
    scheduler.start()
    try:
        yield
    finally:
        scheduler.stop()


app = FastAPI(title="JobPilot", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (jobs.router, companies.router, applications.router, profile.router, profiles.router, resumes.router,
          settings.router, runs.router, pipeline.router, stats.router, today.router):
    app.include_router(r, prefix="/api")


@app.get("/api")
def api_root():
    return {"name": "jobpilot", "docs": "/docs"}


_dist = get_settings().web_dist
if _dist.exists() and (_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = _dist / full_path
        if full_path and candidate.is_file() and Path(candidate).resolve().is_relative_to(_dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
