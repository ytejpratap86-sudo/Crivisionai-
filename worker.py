"""Background analysis jobs. State lives in the DB; the UI polls it.

Single in-process worker thread for this phase. For scale, replace `enqueue` with a real queue
(Redis/RQ, Celery, SQS) — `run_analysis(analysis_id)` is already the self-contained job body.
"""
from __future__ import annotations

import json
import logging
import queue
import shutil
import threading
from pathlib import Path

from .config import settings
from .db import db, now, row
from .pipeline.interfaces import ModelNotConnected, PipelineError
from .pipeline.video_processor import FFmpegVideoProcessor
from .storage import get_storage

log = logging.getLogger("cricvision.worker")

# status -> default progress (progress always comes from backend state)
PROGRESS = {"QUEUED": 5, "PROCESSING": 20, "ANALYZING": 50, "GENERATING_REPORT": 85, "COMPLETED": 100}
TERMINAL = {"COMPLETED", "FAILED"}

_q: "queue.Queue[str]" = queue.Queue()
_thread: threading.Thread | None = None


def set_state(aid: str, status: str, stage: str, progress: int | None = None, **extra) -> None:
    cols = {"status": status, "stage": stage, "progress": PROGRESS.get(status, 0) if progress is None else progress,
            "updated_at": now(), **extra}
    sets = ", ".join(f"{k} = ?" for k in cols)
    with db() as c:
        # never overwrite a terminal state (e.g. timeout watchdog already failed it)
        c.execute(f"UPDATE analyses SET {sets} WHERE id = ? AND status NOT IN ('COMPLETED','FAILED')", (*cols.values(), aid))


def _components(mode: str, analysis_type: str):
    if mode == "demo":
        from .pipeline import demo as d
        return d.DemoObjectDetector(), d.DemoPoseEstimator(), d.DemoShotDetector(), d.DemoTechniqueAnalyzer(), d.DemoCoachingGenerator(analysis_type)
    from .pipeline import not_connected as n
    return n.NotConnectedObjectDetector(), n.NotConnectedPoseEstimator(), n.NotConnectedShotDetector(), n.NotConnectedTechniqueAnalyzer(), n.NotConnectedCoachingGenerator()


def run_analysis(aid: str) -> None:
    with db() as c:
        a = row(c, "SELECT * FROM analyses WHERE id = ?", aid)
        v = row(c, "SELECT * FROM videos WHERE id = ?", a["video_id"]) if a else None
    if not a or not v or a["status"] != "QUEUED":
        return
    work = Path(settings.work_dir) / aid
    profile = json.loads(a["player_profile"] or "{}")
    try:
        detector, pose_est, shot_det, tech, coach = _components(a["mode"], v["analysis_type"])
        storage = get_storage()

        set_state(aid, "PROCESSING", "PREPARING")
        with storage.local_copy(v["storage_key"]) as path:
            prepared = FFmpegVideoProcessor().prepare(path, str(work))          # REAL: decode + frame sampling
            log.info("analysis %s: %d frames prepared", aid, prepared.frame_count)

            set_state(aid, "ANALYZING", "PLAYER_DETECTION", 40)
            detections = detector.detect(prepared)
            set_state(aid, "ANALYZING", "POSE_ANALYSIS", 50)
            pose = pose_est.analyze(prepared, detections)
            set_state(aid, "ANALYZING", "TECHNIQUE_ANALYSIS", 65)
            shot = shot_det.detect(prepared, pose, v["analysis_type"])
            assessment = tech.analyze(pose, shot, v["analysis_type"], v["camera_angle"], profile)

            set_state(aid, "GENERATING_REPORT", "REPORT")
            report = coach.generate(assessment, shot, prepared.meta)

        report = {**report, "mode": a["mode"], "analysisType": v["analysis_type"], "cameraAngle": v["camera_angle"],
                  "video": {"duration": v["duration_seconds"], "width": v["width"], "height": v["height"], "fps": v["fps"]},
                  "framesSampled": prepared.frame_count}
        set_state(aid, "COMPLETED", "DONE", report_json=json.dumps(report), completed_at=now())
    except ModelNotConnected as e:
        log.info("analysis %s: %s", aid, e)
        with db() as c:
            stage = row(c, "SELECT stage FROM analyses WHERE id = ?", aid)["stage"]
        set_state(aid, "FAILED", stage, None, error_code="AI_NOT_CONNECTED")
    except PipelineError as e:
        log.warning("analysis %s pipeline error: %s", aid, e)
        code = e.code if e.code in ("VIDEO_PROCESSING_FAILED", "PLAYER_NOT_FOUND") else "VIDEO_PROCESSING_FAILED"
        with db() as c:
            stage = row(c, "SELECT stage FROM analyses WHERE id = ?", aid)["stage"]
        set_state(aid, "FAILED", stage, None, error_code=code)
    except Exception:
        log.exception("analysis %s crashed", aid)
        with db() as c:
            stage = row(c, "SELECT stage FROM analyses WHERE id = ?", aid)["stage"]
        set_state(aid, "FAILED", stage, None, error_code="AI_FAILED")
    finally:
        shutil.rmtree(work, ignore_errors=True)   # frames are regenerated when real models are connected


def _loop() -> None:
    while True:
        aid = _q.get()
        try:
            run_analysis(aid)
        finally:
            _q.task_done()


def start_worker() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    # recovery after restart: re-queue queued jobs, fail jobs that were mid-flight
    with db() as c:
        c.execute("UPDATE analyses SET status='FAILED', error_code='AI_FAILED', updated_at=? "
                  "WHERE status IN ('PROCESSING','ANALYZING','GENERATING_REPORT')", (now(),))
        pending = [r["id"] for r in c.execute("SELECT id FROM analyses WHERE status='QUEUED' ORDER BY created_at")]
    _thread = threading.Thread(target=_loop, name="analysis-worker", daemon=True)
    _thread.start()
    for aid in pending:
        _q.put(aid)


def enqueue(aid: str) -> None:
    _q.put(aid)
