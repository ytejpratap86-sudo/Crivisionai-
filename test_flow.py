import time
from urllib.parse import urlparse, parse_qs, urlencode

from conftest import make_user
from app import config
from app.db import db


def upload(client, h, path, mime="video/mp4", name="clip.mp4"):
    data = open(path, "rb").read()
    r = client.post("/api/v1/videos", headers=h, json={"filename": name, "mime_type": mime, "file_size": len(data), "analysis_type": "batting"})
    assert r.status_code == 201, r.text
    j = r.json()
    up = j["upload"]
    assert up["method"] == "PUT" and up["url"].startswith("/storage/upload?")
    r2 = client.put(up["url"], content=data, headers=up["headers"])
    return j["video"]["id"], r2


def wait_done(client, h, aid, timeout=20):
    t = time.time()
    seen = []
    while time.time() - t < timeout:
        j = client.get(f"/api/v1/analyses/{aid}", headers=h).json()
        if not seen or seen[-1] != j["status"]:
            seen.append(j["status"])
        if j["status"] in ("COMPLETED", "FAILED"):
            return j, seen
        time.sleep(0.05)
    raise AssertionError("timeout")


def test_happy_path_demo(client, sample_video):
    h = make_user(client)
    vid, r = upload(client, h, sample_video)
    assert r.status_code == 200
    r = client.post(f"/api/v1/videos/{vid}/complete", headers=h, json={})
    assert r.status_code == 200, r.text
    v = r.json()["video"]
    assert v["status"] == "UPLOADED" and v["width"] == 320 and v["height"] == 240 and 2.5 < v["duration_seconds"] < 3.5
    assert v["playback_url"].startswith("/storage/object?")
    assert client.get(v["playback_url"]).status_code == 200
    r = client.post(f"/api/v1/videos/{vid}/analyze", headers=h, json={"camera_angle": "side", "player_profile": {"hand": "right", "level": "club"}})
    assert r.status_code == 201
    aid = r.json()["analysis_id"]
    assert client.get(f"/api/v1/analyses/{aid}/report", headers=h).status_code in (409, 200)
    j, seen = wait_done(client, h, aid)
    assert j["status"] == "COMPLETED" and j["progress"] == 100 and j["mode"] == "demo"
    rep = client.get(f"/api/v1/analyses/{aid}/report", headers=h).json()
    assert rep["mode"] == "demo" and rep["report"]["mode"] == "demo" and rep["report"]["overallScore"] == 81
    assert rep["report"]["framesSampled"] > 0


def test_real_mode_fails_honestly(client, sample_video, monkeypatch):
    monkeypatch.setattr(config.settings, "demo_mode", False)
    h = make_user(client)
    vid, _ = upload(client, h, sample_video)
    client.post(f"/api/v1/videos/{vid}/complete", headers=h, json={})
    aid = client.post(f"/api/v1/videos/{vid}/analyze", headers=h, json={"camera_angle": "auto"}).json()["analysis_id"]
    j, _ = wait_done(client, h, aid)
    assert j["status"] == "FAILED" and j["mode"] == "real"
    assert j["error"]["code"] == "AI_NOT_CONNECTED" and j["stage"] == "PLAYER_DETECTION"
    r = client.get(f"/api/v1/analyses/{aid}/report", headers=h)
    assert r.status_code == 409 and "Traceback" not in r.text


def test_invalid_mime_and_size(client):
    h = make_user(client)
    r = client.post("/api/v1/videos", headers=h, json={"filename": "a.avi", "mime_type": "video/x-msvideo", "file_size": 10})
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_FORMAT"
    r = client.post("/api/v1/videos", headers=h, json={"filename": "a.mp4", "mime_type": "image/png", "file_size": 10})
    assert r.status_code == 415
    r = client.post("/api/v1/videos", headers=h, json={"filename": "a.mp4", "mime_type": "video/mp4", "file_size": 50 * 1024 * 1024})
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_fake_video_rejected(client, tmp_path):
    h = make_user(client)
    f = tmp_path / "fake.mp4"
    f.write_bytes(b"this is not a video at all" * 10)
    _, r = upload(client, h, str(f))
    assert r.status_code == 415 and r.json()["error"]["code"] == "INVALID_VIDEO"


def test_upload_url_tampered_and_expired(client, sample_video):
    h = make_user(client)
    data = open(sample_video, "rb").read()
    j = client.post("/api/v1/videos", headers=h, json={"filename": "c.mp4", "mime_type": "video/mp4", "file_size": len(data)}).json()
    u = urlparse(j["upload"]["url"])
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    bad = dict(q, max=str(10 ** 12))
    assert client.put("/storage/upload?" + urlencode(bad), content=data, headers={"Content-Type": "video/mp4"}).status_code == 403
    from app.storage.local import _sig
    exp = str(int(time.time()) - 10)
    expired = dict(q, exp=exp, sig=_sig("put", q["key"], q["ct"], q["max"], exp))
    r = client.put("/storage/upload?" + urlencode(expired), content=data, headers={"Content-Type": "video/mp4"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "UPLOAD_URL_EXPIRED"
    # fresh URL works
    up = client.post(f"/api/v1/videos/{j['video']['id']}/upload-url", headers=h).json()["upload"]
    assert client.put(up["url"], content=data, headers=up["headers"]).status_code == 200


def test_cross_user_access_blocked(client, sample_video):
    a, b = make_user(client), make_user(client)
    vid, _ = upload(client, a, sample_video)
    client.post(f"/api/v1/videos/{vid}/complete", headers=a, json={})
    aid = client.post(f"/api/v1/videos/{vid}/analyze", headers=a, json={}).json()["analysis_id"]
    assert client.get(f"/api/v1/videos/{vid}", headers=b).status_code == 404
    assert client.post(f"/api/v1/videos/{vid}/analyze", headers=b, json={}).status_code == 404
    assert client.get(f"/api/v1/analyses/{aid}", headers=b).status_code == 404
    assert client.get(f"/api/v1/analyses/{aid}/report", headers=b).status_code == 404
    assert client.get(f"/api/v1/analyses/{aid}").status_code == 401
    assert client.get(f"/api/v1/analyses/{aid}", headers={"Authorization": "Bearer forged.token"}).status_code == 401


def test_analyze_requires_uploaded_video(client):
    h = make_user(client)
    j = client.post("/api/v1/videos", headers=h, json={"filename": "c.mp4", "mime_type": "video/mp4", "file_size": 1000}).json()
    r = client.post(f"/api/v1/videos/{j['video']['id']}/analyze", headers=h, json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "VIDEO_NOT_READY"
    r = client.post(f"/api/v1/videos/{j['video']['id']}/complete", headers=h, json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "UPLOAD_MISSING"


def test_timeout_watchdog(client, sample_video, monkeypatch):
    h = make_user(client)
    vid, _ = upload(client, h, sample_video)
    client.post(f"/api/v1/videos/{vid}/complete", headers=h, json={})
    aid = client.post(f"/api/v1/videos/{vid}/analyze", headers=h, json={}).json()["analysis_id"]
    wait_done(client, h, aid)
    with db() as c:  # simulate a stuck job
        c.execute("UPDATE analyses SET status='ANALYZING', updated_at='2000-01-01T00:00:00+00:00' WHERE id=?", (aid,))
    j = client.get(f"/api/v1/analyses/{aid}", headers=h).json()
    assert j["status"] == "FAILED" and j["error"]["code"] == "TIMEOUT"


def test_migrations_recorded(client):
    with db() as c:
        names = [r["name"] for r in c.execute("SELECT name FROM schema_migrations")]
        idx = [r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")]
    assert "001_init.sql" in names
    for i in ("idx_videos_user_id", "idx_videos_status", "idx_videos_created_at"):
        assert i in idx
