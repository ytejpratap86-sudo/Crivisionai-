# CricVision AI — Backend (Phase 2)

FastAPI backend: auth, signed-URL video upload, storage abstraction (local / S3-compatible),
ffprobe validation, ffmpeg frame extraction, background analysis jobs and report API.

## Run
```bash
pip install -r requirements.txt
cp .env.example .env   # values export karein
DEMO_MODE=true AUTH_SECRET=dev-secret python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Frontend (`../frontend`) isi server se serve hota hai: http://localhost:8000/ , flow: /analysis.
Requirements: Python 3.11+, ffmpeg + ffprobe PATH me.

## Tests
```bash
python3 -m pytest -q tests
```

## API (prefix /api/v1)
| Method | Path | Kaam |
|---|---|---|
| POST | /auth/signup, /auth/login | token |
| GET | /me, /config | user, mode |
| POST | /videos | video record + signed upload URL (file JSON se nahi jaati) |
| POST | /videos/{id}/upload-url | expired URL refresh |
| POST | /videos/{id}/complete | size + ffprobe verify, duration limit |
| POST | /videos/{id}/analyze | ownership + validity check, analysis QUEUED, job start |
| GET | /analyses, /analyses/{id} | status, stage, progress (backend se) |
| GET | /analyses/{id}/report | sirf COMPLETED par |

Status: QUEUED → PROCESSING(20) → ANALYZING(40–65) → GENERATING_REPORT(85) → COMPLETED(100) | FAILED.

## Real vs demo
- Real: upload, validation, ffmpeg prep, job states, ownership checks.
- `app/pipeline/interfaces.py` me ObjectDetector, PoseEstimator, ShotDetector, TechniqueAnalyzer,
  CoachingGenerator abhi `ModelNotConnected` dete hain → real mode me job honestly
  `AI_NOT_CONNECTED` par fail hota hai. Koi fake score nahi.
- DEMO_MODE=true: report static JSON (`app/pipeline/demo.py`), `mode=demo` ke saath save hota hai
  aur UI "Demo analysis" dikhata hai. Production me DEMO_MODE refuse hota hai.
