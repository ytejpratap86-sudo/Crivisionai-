"""Real VideoProcessor built on ffprobe/ffmpeg (these steps are genuinely executed)."""
from __future__ import annotations

import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from .interfaces import PipelineError, PreparedVideo, VideoMeta

SAMPLE_FPS = 10      # frames/second extracted for downstream models
FRAME_WIDTH = 640


def _fps(s: str | None) -> float:
    try:
        f = float(Fraction(s)) if s and s != "0/0" else 0.0
        return round(f, 3)
    except Exception:
        return 0.0


class FFmpegVideoProcessor:
    def __init__(self, timeout: int = 60):
        if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg/ffprobe must be installed on the server")
        self.timeout = timeout

    def probe(self, video_path: str) -> VideoMeta:
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", video_path],
                capture_output=True, timeout=30, check=True,
            ).stdout
            data = json.loads(out)
        except Exception as e:  # corrupt / not a video
            raise PipelineError("INVALID_VIDEO", str(e)[:200])
        vs = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        if not vs:
            raise PipelineError("INVALID_VIDEO", "no video stream")
        w, h = int(vs.get("width") or 0), int(vs.get("height") or 0)
        rot = 0
        for sd in vs.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = abs(int(sd["rotation"]))
        if str((vs.get("tags") or {}).get("rotate", "0")) in ("90", "270"):
            rot = 90
        if rot in (90, 270):
            w, h = h, w
        dur = float(data.get("format", {}).get("duration") or vs.get("duration") or 0)
        return VideoMeta(
            duration_seconds=round(dur, 3), width=w, height=h,
            fps=_fps(vs.get("avg_frame_rate")) or _fps(vs.get("r_frame_rate")),
            codec=vs.get("codec_name"),
            has_audio=any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
        )

    def prepare(self, video_path: str, work_dir: str) -> PreparedVideo:
        meta = self.probe(video_path)
        frames = Path(work_dir) / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", video_path,
                 "-vf", f"fps={SAMPLE_FPS},scale={FRAME_WIDTH}:-2", "-q:v", "4", str(frames / "f_%05d.jpg")],
                capture_output=True, timeout=self.timeout, check=True,
            )
        except subprocess.TimeoutExpired:
            raise PipelineError("VIDEO_PROCESSING_FAILED", "ffmpeg timeout")
        except subprocess.CalledProcessError as e:
            raise PipelineError("VIDEO_PROCESSING_FAILED", e.stderr.decode(errors="ignore")[:200])
        count = len(list(frames.glob("f_*.jpg")))
        if count == 0:
            raise PipelineError("VIDEO_PROCESSING_FAILED", "no frames decoded")
        return PreparedVideo(path=video_path, meta=meta, frames_dir=str(frames), frame_count=count, sample_fps=SAMPLE_FPS)
