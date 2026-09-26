import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

TMP = tempfile.mkdtemp(prefix="cv-test-")
os.environ.update({
    "DATABASE_PATH": f"{TMP}/test.db", "LOCAL_STORAGE_DIR": f"{TMP}/uploads", "WORK_DIR": f"{TMP}/work",
    "AUTH_SECRET": "test-secret", "DEMO_MODE": "true", "DEMO_STEP_SECONDS": "0.05", "MAX_UPLOAD_MB": "5",
    "FRONTEND_DIR": f"{TMP}/nofront",
})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def sample_video():
    p = f"{TMP}/clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25", "-t", "3",
                    "-pix_fmt", "yuv420p", p], check=True)
    return p


_n = [0]


def make_user(client):
    _n[0] += 1
    r = client.post("/api/v1/auth/signup", json={"name": f"P{_n[0]}", "email": f"p{_n[0]}@test.in", "password": "password123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
