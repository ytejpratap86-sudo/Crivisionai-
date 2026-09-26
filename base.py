"""Storage abstraction. Swap providers (local dev, S3, R2, MinIO, GCS-interop...) without touching API code."""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class UploadTarget:
    """What the browser needs to upload the file DIRECTLY to storage (bypassing the JSON API)."""
    method: str                       # "PUT" (raw body) or "POST" (multipart form, e.g. S3 presigned POST)
    url: str                          # absolute, or a path starting with "/" relative to the API base
    expires_at: int                   # unix seconds
    headers: dict[str, str] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)   # form fields for POST uploads

    def to_dict(self) -> dict:
        return {"method": self.method, "url": self.url, "expires_at": self.expires_at, "headers": self.headers, "fields": self.fields}


@dataclass
class ObjectInfo:
    size: int
    content_type: str | None


class StorageProvider(ABC):
    name: str = "base"

    @abstractmethod
    def create_upload(self, key: str, content_type: str, max_bytes: int, expires_in: int) -> UploadTarget: ...

    @abstractmethod
    def create_download_url(self, key: str, expires_in: int) -> str: ...

    @abstractmethod
    def stat(self, key: str) -> ObjectInfo | None: ...

    @abstractmethod
    @contextmanager
    def local_copy(self, key: str) -> Iterator[str]:
        """Yield a local filesystem path to the object (downloads to temp for remote providers)."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None: ...
