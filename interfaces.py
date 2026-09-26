"""AI pipeline contracts. Real computer-vision models plug in here.

Nothing in this package fabricates measurements. Components that are not connected raise
ModelNotConnected, and the job fails honestly with AI_NOT_CONNECTED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ModelNotConnected(Exception):
    """Raised by a pipeline component whose model has not been connected yet (NOT_IMPLEMENTED)."""
    code = "AI_NOT_CONNECTED"


class PipelineError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


@dataclass
class VideoMeta:
    duration_seconds: float
    width: int
    height: int
    fps: float
    codec: str | None = None
    has_audio: bool = False


@dataclass
class PreparedVideo:
    path: str
    meta: VideoMeta
    frames_dir: str
    frame_count: int
    sample_fps: float


@dataclass
class Detections:        # per-frame boxes for player / bat / ball / stumps
    frames: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PoseAnalysis:      # per-frame 2D/3D keypoints + derived joint angles
    keypoints: list[dict[str, Any]] = field(default_factory=list)
    joint_angles: list[dict[str, float]] = field(default_factory=list)


@dataclass
class ShotEvents:        # e.g. stance / backlift / front-foot landing / contact / release
    shot: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TechniqueAssessment:
    score: int | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)


class VideoProcessor(Protocol):
    def probe(self, video_path: str) -> VideoMeta: ...
    def prepare(self, video_path: str, work_dir: str) -> PreparedVideo: ...


class ObjectDetector(Protocol):
    def detect(self, video: PreparedVideo) -> Detections: ...


class PoseEstimator(Protocol):
    def analyze(self, video: PreparedVideo, detections: Detections) -> PoseAnalysis: ...


class ShotDetector(Protocol):
    def detect(self, video: PreparedVideo, pose: PoseAnalysis, analysis_type: str) -> ShotEvents: ...


class TechniqueAnalyzer(Protocol):
    def analyze(self, pose: PoseAnalysis, shot: ShotEvents, analysis_type: str, camera_angle: str, profile: dict) -> TechniqueAssessment: ...


class CoachingGenerator(Protocol):
    def generate(self, assessment: TechniqueAssessment, shot: ShotEvents, meta: VideoMeta, language: str = "hi") -> dict: ...
