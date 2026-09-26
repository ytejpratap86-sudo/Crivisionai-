"""Local development storage that behaves like object storage with signed, expiring URLs.

Uploads go to a dedicated streaming endpoint (/storage/upload), not the JSON API, exactly like a
presigned PUT to S3. Use S3Storage (STORAGE_PROVIDER=s3) in production.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlencode

from ..config import settings
from .base import ObjectInfo, StorageProvider, UploadTarget


def _sig(*parts: str) -> str:
    return hmac.new(settings.auth_secret.encode(), ("stor:" + "|".join(parts)).encode(), hashlib.sha256).hexdigest()


class LocalStorage(StorageProvider):
    name = "local"

    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise ValueError("bad key")
        return p

    # ----- signed URLs -----
    def create_upload(self, key, content_type, max_bytes, expires_in) -> UploadTarget:
        exp = str(int(time.time()) + expires_in)
        q = {"key": key, "ct": content_type, "max": str(max_bytes), "exp": exp,
             "sig": _sig("put", key, content_type, str(max_bytes), exp)}
        return UploadTarget(method="PUT", url="/storage/upload?" + urlencode(q), expires_at=int(exp),
                            headers={"Content-Type": content_type})

    def create_download_url(self, key, expires_in) -> str:
        exp = str(int(time.time()) + expires_in)
        return "/storage/object?" + urlencode({"key": key, "exp": exp, "sig": _sig("get", key, exp)})

    @staticmethod
    def verify_upload(key, ct, max_bytes, exp, sig) -> str | None:
        """Returns an error code, or None if valid."""
        if not hmac.compare_digest(sig or "", _sig("put", key, ct, max_bytes, exp)):
            return "BAD_SIGNATURE"
        if int(exp) < time.time():
            return "URL_EXPIRED"
        return None

    @staticmethod
    def verify_download(key, exp, sig) -> str | None:
        if not hmac.compare_digest(sig or "", _sig("get", key, exp)):
            return "BAD_SIGNATURE"
        if int(exp) < time.time():
            return "URL_EXPIRED"
        return None

    # ----- object ops -----
    def stat(self, key):
        p = self.path(key)
        if not p.exists():
            return None
        ct = None
        meta = p.with_suffix(p.suffix + ".ct")
        if meta.exists():
            ct = meta.read_text().strip()
        return ObjectInfo(size=p.stat().st_size, content_type=ct)

    def write_meta(self, key: str, content_type: str) -> None:
        p = self.path(key)
        p.with_suffix(p.suffix + ".ct").write_text(content_type)

    @contextmanager
    def local_copy(self, key) -> Iterator[str]:
        yield str(self.path(key))

    def delete(self, key):
        p = self.path(key)
        for f in (p, p.with_suffix(p.suffix + ".ct"), p.with_suffix(p.suffix + ".part")):
            try:
                os.remove(f)
            except FileNotFoundError:
                pass
