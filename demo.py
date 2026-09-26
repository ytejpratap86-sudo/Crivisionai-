"""DEVELOPMENT-ONLY demo components (enabled with DEMO_MODE=true).

They return a static sample report so the UI flow can be built and tested end-to-end.
Every demo report carries mode="demo" and the UI labels it "Demo analysis".
Nothing here is derived from the uploaded video's pixels.
"""
from __future__ import annotations

import time

from ..config import settings
from .interfaces import Detections, PoseAnalysis, ShotEvents, TechniqueAssessment

DEMO_REPORTS = {
    "batting": {
        "overallScore": 81, "shot": "Cover drive", "delta": 6,
        "issues": [
            {"id": "front_knee", "title": "Front knee kam bend", "summary": "Weight peeche reh raha hai.",
             "evidence": "Contact frame par hip–knee–ankle angle (sample frame 088).",
             "measurement": {"value": 126, "unit": "°", "target": "140°", "delta": "14° kam bend"},
             "explanation": "Front knee kam mudne se weight back foot par reh jaata hai aur ball uthne ka chance badhta hai.",
             "drill": "Cone ke upar front-foot stride — 10 reps × 3 sets.", "timestamp": 3.52},
            {"id": "bat_face", "title": "Bat face thoda open", "summary": "Contact par bat face open hai.",
             "evidence": "Contact frame par bat-face direction (sample).",
             "measurement": {"value": 8, "unit": "°", "target": "0–3°", "delta": "8° open"},
             "explanation": "Open face se ball cover ke bajaye point/air mein ja sakti hai.",
             "drill": "Top-hand control drill — 3 × 12 throwdowns.", "timestamp": 3.64},
            {"id": "head", "title": "Head stability", "summary": "Head position stable rakhein — aankh ball ki line mein.",
             "evidence": "Backlift se contact tak head movement.",
             "measurement": None,
             "explanation": "Measurement tabhi dikhega jab computer-vision data available ho.",
             "drill": "Mirror stance hold — 3 × 30 sec.", "timestamp": 2.80},
        ],
    },
    "bowling": {
        "overallScore": 72, "shot": "Fast bowling action", "delta": 9,
        "issues": [
            {"id": "front_arm", "title": "Front arm jaldi gir raha hai", "summary": "Body jaldi khulti hai aur line bigadti hai.",
             "evidence": "Release se pehle front elbow shoulder line se neeche (sample frames 135–138).",
             "measurement": {"value": -3, "unit": " frames", "target": "Release tak upar", "delta": "Release se pehle gir raha"},
             "explanation": "Front arm jaldi girne se chest jaldi khulta hai aur accuracy kam hoti hai.",
             "drill": "Wall-target front arm hold — 10 deliveries (bina ball).", "timestamp": 4.60},
            {"id": "front_foot", "title": "Front-foot landing thoda open", "summary": "Toe fine leg ki taraf.",
             "evidence": "Front-foot contact frame (sample).",
             "measurement": {"value": 18, "unit": "°", "target": "0–10°", "delta": "18° open"},
             "explanation": "Open landing se momentum side mein jaata hai.",
             "drill": "Line drill — crease par tape, 3 × 8 run-ups.", "timestamp": 4.40},
            {"id": "elbow", "title": "Bowling arm elbow", "summary": "Single phone camera se elbow extension ka legal test nahi hota.",
             "evidence": "—", "measurement": None,
             "explanation": "Elbow legality ke liye lab/multi-camera test chahiye. Hum iska number nahi dikhate.",
             "drill": "Coach se action review karwayein.", "timestamp": 4.73},
        ],
    },
}


def _step():
    time.sleep(settings.demo_step_seconds)


class DemoObjectDetector:
    def detect(self, video):
        _step(); return Detections()


class DemoPoseEstimator:
    def analyze(self, video, detections):
        _step(); return PoseAnalysis()


class DemoShotDetector:
    def detect(self, video, pose, analysis_type):
        _step(); return ShotEvents(shot=DEMO_REPORTS[analysis_type]["shot"])


class DemoTechniqueAnalyzer:
    def analyze(self, pose, shot, analysis_type, camera_angle, profile):
        _step()
        r = DEMO_REPORTS[analysis_type]
        return TechniqueAssessment(score=r["overallScore"], issues=r["issues"])


class DemoCoachingGenerator:
    def __init__(self, analysis_type: str):
        self.analysis_type = analysis_type

    def generate(self, assessment, shot, meta, language="hi"):
        _step()
        r = DEMO_REPORTS[self.analysis_type]
        return {"overallScore": r["overallScore"], "shot": r["shot"], "delta": r["delta"], "issues": r["issues"]}
