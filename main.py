"""CricVision AI backend: API + local signed storage endpoints + (optionally) the static frontend."""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import router
from .config import settings
from .db import migrate
from .errors import ApiError
from .storage import get_storage
from . import worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cricvision")


@asynccontextmanager
async def lifespan(app: FastAPI):
    applied = migrate()
    if applied:
        log.info("migrations applied: %s", applied)
    worker.start_worker()
    log.info("CricVision backend ready (storage=%s, demo_mode=%s)", get_storage().name, settings.demo_mode)
    yield


app = FastAPI(title="CricVision AI API", version="0.2.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(ApiError)
async def api_error(_, e: ApiError):
    return _err(e.status, e.code, e.message)


@app.exception_handler(RequestValidationError)
async def validation_error(_, e):
    return _err(422, "INVALID_REQUEST", "Kuch details sahi nahi hain. Form check karke dobara try karein.")


@app.exception_handler(StarletteHTTPException)
async def http_error(_, e: StarletteHTTPException):
    return _err(e.status_code, "NOT_FOUND" if e.status_code == 404 else "HTTP_ERROR",
                "Ye page nahi mila." if e.status_code == 404 else "Request poori nahi ho payi.")


@app.exception_handler(Exception)
async def unhandled(_, e: Exception):
    log.exception("unhandled error")          # details stay in server logs
    return _err(500, "INTERNAL", "Kuch gadbad ho gayi. Thodi der baad dobara try karein.")


app.include_router(router)


# ---------------- local signed storage (dev / single-server) ----------------
@app.put("/storage/upload")
async def storage_upload(request: Request, key: str, ct: str, max: str, exp: str, sig: str):
    storage = get_storage()
    if storage.name != "local":
        raise ApiError(404, "NOT_FOUND", "Ye page nahi mila.")
    bad = storage.verify_upload(key, ct, max, exp, sig)
    if bad == "URL_EXPIRED":
        raise ApiError(403, "UPLOAD_URL_EXPIRED", "Upload link expire ho gaya. Dobara try karein.")
    if bad:
        raise ApiError(403, "UPLOAD_FORBIDDEN", "Upload allowed nahi hai.")
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != ct:
        raise ApiError(415, "UNSUPPORTED_FORMAT", "Ye format support nahi hai. MP4, MOV ya WebM video chunein.")
    limit = int(max)
    declared = request.headers.get("content-length")
    if declared and int(declared) > limit:
        raise ApiError(413, "FILE_TOO_LARGE", "Video bahut bada hai.")
    dest = storage.path(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    size, head = 0, b""
    try:
        with open(part, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise ApiError(413, "FILE_TOO_LARGE", "Video bahut bada hai.")
                if len(head) < 16:
                    head += chunk[:16]
                f.write(chunk)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    if size == 0 or not _looks_like_video(head, ct):
        part.unlink(missing_ok=True)
        raise ApiError(415, "INVALID_VIDEO", "Ye file valid video nahi lag rahi.")
    part.replace(dest)
    storage.write_meta(key, ct)
    return Response(status_code=200)


def _looks_like_video(head: bytes, ct: str) -> bool:
    """Magic-byte check so a renamed .exe/.jpg can't pose as a video."""
    if ct == "video/webm":
        return head[:4] == b"\x1a\x45\xdf\xa3"
    return head[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip")


@app.get("/storage/object")
def storage_object(key: str, exp: str, sig: str):
    storage = get_storage()
    if storage.name != "local" or storage.verify_download(key, exp, sig):
        raise ApiError(403, "FORBIDDEN", "Is video ko dekhne ki permission nahi hai.")
    p = storage.path(key)
    if not p.exists():
        raise ApiError(404, "NOT_FOUND", "Video nahi mila.")
    info = storage.stat(key)
    return FileResponse(p, media_type=info.content_type or "video/mp4")


# ---------------- frontend (clean routes) ----------------
FRONT = Path(settings.frontend_dir)
PAGES = {
    "/analysis": "analysis.html",
    "/login": "analysis.html",        # auth view lives inside the analysis app shell
    "/dashboard": "app.html",
}


def _page(name: str) -> HTMLResponse:
    html = (FRONT / name).read_text()
    # clean nested routes need a base so relative asset links resolve from the site root
    html = html.replace("<head>", '<head>\n<base href="/">', 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


if FRONT.exists():
    for route, file in PAGES.items():
        app.add_api_route(route, (lambda f=file: _page(f)), methods=["GET"], include_in_schema=False)

    @app.get("/analysis/{aid}/processing", include_in_schema=False)
    def processing_page(aid: str):
        return _page("analysis.html")

    @app.get("/analysis/{aid}/report", include_in_schema=False)
    def report_page(aid: str):
        return _page("analysis.html")

    app.mount("/", StaticFiles(directory=str(FRONT), html=True), name="frontend")
