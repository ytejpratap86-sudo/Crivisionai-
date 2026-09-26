"""REST API v1. Every private resource is looked up by (id AND user_id from the token)."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .auth import current_user, hash_password, issue_token, verify_password
from .config import ALLOWED_EXT, ALLOWED_MIME, ANALYSIS_TYPES, CAMERA_ANGLES, settings
from .db import db, new_id, now, row
from .errors import JOB_ERRORS, ApiError
from .pipeline.interfaces import PipelineError
from .pipeline.video_processor import FFmpegVideoProcessor
from .storage import get_storage
from . import worker

router = APIRouter(prefix="/api/v1")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


# ---------------- config / auth ----------------
@router.get("/config")
def config():
    return {"demo_mode": settings.demo_mode, "max_upload_mb": settings.max_upload_mb,
            "max_duration_seconds": settings.max_duration_seconds,
            "allowed_mime_types": sorted(ALLOWED_MIME), "storage": get_storage().name}


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: str = Field(max_length=200)
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


def _user_out(u: dict) -> dict:
    return {"id": u["id"], "name": u["name"], "email": u["email"]}


@router.post("/auth/signup", status_code=201)
def signup(body: SignupIn):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise ApiError(422, "INVALID_EMAIL", "Sahi email daalein.")
    with db() as c:
        if row(c, "SELECT id FROM users WHERE email = ?", email):
            raise ApiError(409, "EMAIL_TAKEN", "Is email se account pehle se hai. Login karein.")
        uid, t = new_id(), now()
        c.execute("INSERT INTO users (id,email,name,password_hash,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                  (uid, email, body.name.strip(), hash_password(body.password), t, t))
    return {"token": issue_token(uid), "user": {"id": uid, "name": body.name.strip(), "email": email}}


@router.post("/auth/login")
def login(body: LoginIn):
    with db() as c:
        u = row(c, "SELECT * FROM users WHERE email = ?", body.email.strip().lower())
    if not u or not verify_password(body.password, u["password_hash"]):
        raise ApiError(401, "BAD_CREDENTIALS", "Email ya password galat hai.")
    return {"token": issue_token(u["id"]), "user": _user_out(u)}


@router.get("/me")
def me(user=Depends(current_user)):
    return {"user": _user_out(user)}


# ---------------- videos ----------------
class VideoIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(max_length=100)
    file_size: int = Field(gt=0)
    analysis_type: str = "batting"


class CompleteIn(BaseModel):
    # client-side hints only; the server re-probes the stored file
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None


class AnalyzeIn(BaseModel):
    camera_angle: str = "auto"
    analysis_type: str | None = None
    player_profile: dict | None = None


def _own_video(c, vid: str, uid: str) -> dict:
    v = row(c, "SELECT * FROM videos WHERE id = ? AND user_id = ?", vid, uid)
    if not v:   # same response for "not found" and "not yours"
        raise ApiError(404, "VIDEO_NOT_FOUND", "Ye video nahi mila.")
    return v


def _video_out(v: dict, with_playback: bool = False) -> dict:
    out = {k: v[k] for k in ("id", "original_filename", "mime_type", "file_size", "duration_seconds", "width",
                              "height", "fps", "analysis_type", "camera_angle", "status", "created_at", "updated_at")}
    if with_playback and v["status"] == "UPLOADED":
        out["playback_url"] = get_storage().create_download_url(v["storage_key"], 3600)
    return out


def _upload_target(v: dict) -> dict:
    return get_storage().create_upload(v["storage_key"], v["mime_type"], settings.max_upload_bytes,
                                       settings.upload_url_ttl_seconds).to_dict()


@router.post("/videos", status_code=201)
def create_video(body: VideoIn, user=Depends(current_user)):
    ext = os.path.splitext(body.filename.lower())[1]
    mime = body.mime_type.lower().split(";")[0].strip()
    if not mime and ext in ALLOWED_EXT:   # some mobile browsers send an empty type for .mov
        mime = ALLOWED_EXT[ext]
    if mime not in ALLOWED_MIME or ext not in ALLOWED_EXT or ALLOWED_EXT[ext] != mime:
        raise ApiError(415, "UNSUPPORTED_FORMAT", "Ye format support nahi hai. MP4, MOV ya WebM video chunein.")
    if body.file_size > settings.max_upload_bytes:
        raise ApiError(413, "FILE_TOO_LARGE", f"Video {settings.max_upload_mb} MB se chhota hona chahiye. 5–20 second ka clip best hai.")
    if body.analysis_type not in ANALYSIS_TYPES:
        raise ApiError(422, "INVALID_TYPE", "Batting ya bowling chunein.")
    vid, t = new_id(), now()
    key = f"videos/{user['id']}/{vid}{ALLOWED_MIME[mime]}"
    safe_name = re.sub(r"[^\w.\- ()]+", "_", body.filename)[:200]
    with db() as c:
        c.execute("INSERT INTO videos (id,user_id,original_filename,storage_key,mime_type,file_size,analysis_type,status,created_at,updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)", (vid, user["id"], safe_name, key, mime, body.file_size, body.analysis_type, "PENDING_UPLOAD", t, t))
        v = row(c, "SELECT * FROM videos WHERE id = ?", vid)
    return {"video": _video_out(v), "upload": _upload_target(v)}


@router.post("/videos/{vid}/upload-url")
def refresh_upload_url(vid: str, user=Depends(current_user)):
    """Fresh signed URL for retries or when the previous one expired."""
    with db() as c:
        v = _own_video(c, vid, user["id"])
    if v["status"] != "PENDING_UPLOAD":
        raise ApiError(409, "ALREADY_UPLOADED", "Ye video pehle hi upload ho chuka hai.")
    return {"upload": _upload_target(v)}


@router.post("/videos/{vid}/complete")
def complete_upload(vid: str, body: CompleteIn, user=Depends(current_user)):
    storage = get_storage()
    with db() as c:
        v = _own_video(c, vid, user["id"])
    if v["status"] == "UPLOADED":
        return {"video": _video_out(v, True)}
    if v["status"] == "REJECTED":
        raise ApiError(422, "INVALID_VIDEO", "Ye video process nahi ho sakta. Dusra clip chunein.")
    info = storage.stat(v["storage_key"])
    if not info:
        raise ApiError(409, "UPLOAD_MISSING", "Video upload poora nahi hua. Dobara try karein.")

    def reject(code, msg, status=422):
        storage.delete(v["storage_key"])
        with db() as c2:
            c2.execute("UPDATE videos SET status='REJECTED', updated_at=? WHERE id=?", (now(), vid))
        raise ApiError(status, code, msg)

    if info.size != v["file_size"] or info.size > settings.max_upload_bytes:
        reject("SIZE_MISMATCH", "Upload adhoora laga. Video dobara upload karein.")
    try:
        with storage.local_copy(v["storage_key"]) as path:
            meta = FFmpegVideoProcessor().probe(path)          # server-side validation, client hints are not trusted
    except PipelineError:
        reject("INVALID_VIDEO", "Ye file valid video nahi lag rahi. MP4, MOV ya WebM video chunein.")
    if meta.duration_seconds <= 0.5:
        reject("VIDEO_TOO_SHORT", "Video bahut chhota hai. Kam se kam 2–3 second ka clip chunein.")
    if meta.duration_seconds > settings.max_duration_seconds:
        reject("VIDEO_TOO_LONG", f"Video {int(settings.max_duration_seconds)} second se chhota hona chahiye. 5–20 second best hai.")
    with db() as c:
        c.execute("UPDATE videos SET status='UPLOADED', duration_seconds=?, width=?, height=?, fps=?, updated_at=? WHERE id=?",
                  (meta.duration_seconds, meta.width, meta.height, meta.fps, now(), vid))
        v = row(c, "SELECT * FROM videos WHERE id = ?", vid)
    return {"video": _video_out(v, True)}


@router.get("/videos/{vid}")
def get_video(vid: str, user=Depends(current_user)):
    with db() as c:
        v = _own_video(c, vid, user["id"])
    return {"video": _video_out(v, True)}


@router.delete("/videos/{vid}", status_code=204)
def delete_video(vid: str, user=Depends(current_user)):
    with db() as c:
        v = _own_video(c, vid, user["id"])
        busy = row(c, "SELECT id FROM analyses WHERE video_id=? AND status NOT IN ('COMPLETED','FAILED')", vid)
        if busy:
            raise ApiError(409, "VIDEO_IN_USE", "Is video ka analysis chal raha hai.")
        get_storage().delete(v["storage_key"])
        c.execute("DELETE FROM videos WHERE id=?", (vid,))


@router.post("/videos/{vid}/analyze", status_code=201)
def analyze(vid: str, body: AnalyzeIn, user=Depends(current_user)):
    if body.camera_angle not in CAMERA_ANGLES:
        raise ApiError(422, "INVALID_ANGLE", "Camera angle chunein.")
    if body.analysis_type and body.analysis_type not in ANALYSIS_TYPES:
        raise ApiError(422, "INVALID_TYPE", "Batting ya bowling chunein.")
    profile = {k: str(v)[:40] for k, v in (body.player_profile or {}).items() if k in ("hand", "level", "role")}
    with db() as c:
        v = _own_video(c, vid, user["id"])                       # 1. ownership
        if v["status"] != "UPLOADED":                           # 2. valid, verified video
            raise ApiError(409, "VIDEO_NOT_READY", "Pehle video upload poora hone dein.")
        c.execute("UPDATE videos SET camera_angle=?, analysis_type=?, updated_at=? WHERE id=?",
                  (body.camera_angle, body.analysis_type or v["analysis_type"], now(), vid))
        aid, t = new_id(), now()
        c.execute("INSERT INTO analyses (id,video_id,user_id,mode,status,stage,progress,player_profile,created_at,updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",                # 3-4. record, QUEUED
                  (aid, vid, user["id"], "demo" if settings.demo_mode else "real", "QUEUED", "QUEUED",
                   worker.PROGRESS["QUEUED"], json.dumps(profile), t, t))
    worker.enqueue(aid)                                          # 5. background job
    return {"analysis_id": aid}                                  # 6. client redirects to processing


# ---------------- analyses ----------------
def _own_analysis(c, aid: str, uid: str) -> dict:
    a = row(c, "SELECT * FROM analyses WHERE id = ? AND user_id = ?", aid, uid)
    if not a:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "Ye analysis nahi mila.")
    return a


def _check_timeout(c, a: dict) -> dict:
    if a["status"] in worker.TERMINAL:
        return a
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(a["updated_at"])).total_seconds()
    if age > settings.job_timeout_seconds:
        c.execute("UPDATE analyses SET status='FAILED', error_code='TIMEOUT', updated_at=? WHERE id=? AND status NOT IN ('COMPLETED','FAILED')",
                  (now(), a["id"]))
        a = row(c, "SELECT * FROM analyses WHERE id = ?", a["id"])
    return a


def _analysis_out(a: dict, v: dict) -> dict:
    err = None
    if a["status"] == "FAILED":
        code = a["error_code"] or "INTERNAL"
        err = {"code": code, "message": JOB_ERRORS.get(code, JOB_ERRORS["INTERNAL"])}
    return {"id": a["id"], "status": a["status"], "stage": a["stage"], "progress": a["progress"], "mode": a["mode"],
            "error": err, "created_at": a["created_at"], "updated_at": a["updated_at"], "completed_at": a["completed_at"],
            "video": _video_out(v)}


@router.get("/analyses")
def list_analyses(user=Depends(current_user)):
    with db() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT a.id, a.status, a.mode, a.progress, a.created_at, v.analysis_type, v.original_filename "
            "FROM analyses a JOIN videos v ON v.id=a.video_id WHERE a.user_id=? ORDER BY a.created_at DESC LIMIT 50", (user["id"],))]
    return {"analyses": rows}


@router.get("/analyses/{aid}")
def get_analysis(aid: str, user=Depends(current_user)):
    with db() as c:
        a = _check_timeout(c, _own_analysis(c, aid, user["id"]))
        v = row(c, "SELECT * FROM videos WHERE id = ?", a["video_id"])
    return _analysis_out(a, v)


@router.get("/analyses/{aid}/report")
def get_report(aid: str, user=Depends(current_user)):
    with db() as c:
        a = _check_timeout(c, _own_analysis(c, aid, user["id"]))
        v = row(c, "SELECT * FROM videos WHERE id = ?", a["video_id"])
    if a["status"] == "FAILED":
        code = a["error_code"] or "INTERNAL"
        raise ApiError(409, "ANALYSIS_FAILED", JOB_ERRORS.get(code, JOB_ERRORS["INTERNAL"]))
    if a["status"] != "COMPLETED":
        raise ApiError(409, "REPORT_NOT_READY", "Report abhi taiyaar nahi hai.")
    if not a["report_json"]:
        raise ApiError(404, "REPORT_MISSING", "Report nahi mili. Analysis dobara chalaayein.")
    return {"analysis_id": a["id"], "mode": a["mode"], "report": json.loads(a["report_json"]),
            "video": _video_out(v, True)}
