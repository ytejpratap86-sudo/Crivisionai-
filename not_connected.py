"""Production placeholders: the CV models are NOT connected yet. They never return fake data."""
from __future__ import annotations

from .interfaces import ModelNotConnected


class NotConnectedObjectDetector:
    def detect(self, video):
        raise ModelNotConnected("ObjectDetector: NOT_IMPLEMENTED")


class NotConnectedPoseEstimator:
    def analyze(self, video, detections):
        raise ModelNotConnected("PoseEstimator: NOT_IMPLEMENTED")


class NotConnectedShotDetector:
    def detect(self, video, pose, analysis_type):
        raise ModelNotConnected("ShotDetector: NOT_IMPLEMENTED")


class NotConnectedTechniqueAnalyzer:
    def analyze(self, pose, shot, analysis_type, camera_angle, profile):
        raise ModelNotConnected("TechniqueAnalyzer: NOT_IMPLEMENTED")


class NotConnectedCoachingGenerator:
    def generate(self, assessment, shot, meta, language="hi"):
        raise ModelNotConnected("CoachingGenerator: NOT_IMPLEMENTED")
