from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import ObjectInfo, StorageProvider, UploadTarget


@lru_cache(maxsize=1)
def get_storage() -> StorageProvider:
    if settings.storage_provider == "s3":
        from .s3 import S3Storage
        return S3Storage(settings.storage_endpoint, settings.storage_bucket, settings.storage_access_key,
                         settings.storage_secret_key, settings.storage_region)
    from .local import LocalStorage
    return LocalStorage(settings.local_storage_dir)


__all__ = ["get_storage", "StorageProvider", "UploadTarget", "ObjectInfo"]
