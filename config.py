"""All runtime configuration comes from environment variables. Secrets never reach the frontend."""
from __future__ import annotations

import os
import secrets
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("cricvision")
BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "cricvision.db")))
    auth_secret: str = field(default_factory=lambda: os.getenv("AUTH_SECRET", ""))
    token_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("AUTH_TOKEN_TTL_SECONDS", str(7 * 24 * 3600))))

    # Demo mode: isolated, development-only. NEXT_PUBLIC_DEMO_MODE is accepted as an alias.
    demo_mode: bool = field(default_factory=lambda: _bool("DEMO_MODE", _bool("NEXT_PUBLIC_DEMO_MODE", False)))
    demo_step_seconds: float = field(default_factory=lambda: float(os.getenv("DEMO_STEP_SECONDS", "1.2")))

    # Storage
    storage_provider: str = field(default_factory=lambda: os.getenv("STORAGE_PROVIDER", "local"))  # local | s3
    storage_endpoint: str = field(default_factory=lambda: os.getenv("STORAGE_ENDPOINT", ""))
    storage_bucket: str = field(default_factory=lambda: os.getenv("STORAGE_BUCKET", ""))
    storage_access_key: str = field(default_factory=lambda: os.getenv("STORAGE_ACCESS_KEY", ""))
    storage_secret_key: str = field(default_factory=lambda: os.getenv("STORAGE_SECRET_KEY", ""))
    storage_region: str = field(default_factory=lambda: os.getenv("STORAGE_REGION", "auto"))
    local_storage_dir: str = field(default_factory=lambda: os.getenv("LOCAL_STORAGE_DIR", str(BASE_DIR / "data" / "uploads")))
    work_dir: str = field(default_factory=lambda: os.getenv("WORK_DIR", str(BASE_DIR / "data" / "work")))
    upload_url_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("UPLOAD_URL_TTL_SECONDS", "900")))

    # Limits
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "200")))
    max_duration_seconds: float = field(default_factory=lambda: float(os.getenv("MAX_DURATION_SECONDS", "60")))
    job_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("JOB_TIMEOUT_SECONDS", "600")))

    frontend_dir: str = field(default_factory=lambda: os.getenv("FRONTEND_DIR", str(BASE_DIR.parent / "frontend")))
    cors_origins: str = field(default_factory=lambda: os.getenv("CORS_ORIGINS", "*"))

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.auth_secret:
            if self.env == "production":
                raise RuntimeError("AUTH_SECRET is required in production")
            self.auth_secret = secrets.token_urlsafe(32)
            log.warning("AUTH_SECRET not set — using a random dev secret (sessions reset on restart).")
        if self.demo_mode and self.env == "production":
            raise RuntimeError("DEMO_MODE must not be enabled in production")


ALLOWED_MIME = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}
ALLOWED_EXT = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".m4v": "video/mp4"}
ANALYSIS_TYPES = {"batting", "bowling"}
CAMERA_ANGLES = {"side", "front", "behind", "auto"}

settings = Settings()
