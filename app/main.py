"""FarmIQ application factory."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.knowledge import crops, diseases
from app.routers import advisor, community, market, scan, site, twin, weather
from app.services import advisor as advisor_service
from app.services import vision

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("farmiq")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    crops(); diseases()
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, vision.warm)  # warm the CNN without blocking startup
    log.info("%s %s ready (env=%s, advisor=%s)", settings.app_name, settings.version, settings.env, advisor_service.mode())
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def timing(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - start) * 1000:.1f}"
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Something failed on the server. Try again; if it persists, check the server log."}, status_code=500)


@app.get("/api/health", tags=["meta"])
def health():
    return {
        "status": "ok", "version": settings.version, "env": settings.env,
        "vision_ready": vision.ready(), "advisor": advisor_service.mode(),
        "crops": len(crops()), "diseases": len(diseases()),
    }


for r in (site, weather, twin, market, scan, advisor, community):
    app.include_router(r.router)

app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")
app.mount("/assets", StaticFiles(directory=settings.web_dir / "assets"), name="assets")
app.mount("/css", StaticFiles(directory=settings.web_dir / "css"), name="css")
app.mount("/js", StaticFiles(directory=settings.web_dir / "js"), name="js")


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(settings.web_dir / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(settings.web_dir / "sw.js", media_type="application/javascript", headers={"Service-Worker-Allowed": "/"})


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    """Single-page app: every non-API route serves the shell; the client router takes over."""
    return FileResponse(settings.web_dir / "index.html", headers={"Cache-Control": "no-cache"})
