"""S3-compatible storage (AWS S3, Cloudflare R2, MinIO, Backblaze B2, DigitalOcean Spaces...).

Browser uploads use a presigned POST so size and content-type are enforced by the storage
service itself (content-length-range + Content-Type conditions). Remember to configure bucket
CORS to allow POST/GET from your frontend origin.
"""
from __future__ import annotations

import os
import tempfile
import time
from contextlib import contextmanager
from typing import Iterator

from .base import ObjectInfo, StorageProvider, UploadTarget


class S3Storage(StorageProvider):
    name = "s3"

    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str, region: str):
        import boto3
        from botocore.config import Config

        if not (bucket and access_key and secret_key):
            raise RuntimeError("STORAGE_BUCKET, STORAGE_ACCESS_KEY and STORAGE_SECRET_KEY are required for s3 storage")
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=None if region in ("", "auto") and not endpoint else region,
            config=Config(signature_version="s3v4"),
        )

    def create_upload(self, key, content_type, max_bytes, expires_in) -> UploadTarget:
        post = self.client.generate_presigned_post(
            Bucket=self.bucket, Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, max_bytes]],
            ExpiresIn=expires_in,
        )
        return UploadTarget(method="POST", url=post["url"], fields=post["fields"], expires_at=int(time.time()) + expires_in)

    def create_download_url(self, key, expires_in) -> str:
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in)

    def stat(self, key):
        from botocore.exceptions import ClientError
        try:
            h = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return None
        return ObjectInfo(size=h["ContentLength"], content_type=h.get("ContentType"))

    @contextmanager
    def local_copy(self, key) -> Iterator[str]:
        fd, path = tempfile.mkstemp(suffix=os.path.splitext(key)[1])
        os.close(fd)
        try:
            self.client.download_file(self.bucket, key, path)
            yield path
        finally:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)
