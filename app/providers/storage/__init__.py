"""File storage providers (local filesystem for dev, S3-compatible for prod)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Protocol

from app.config import Settings, get_settings


class StorageError(RuntimeError):
    pass


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def delete_prefix(self, prefix: str) -> int: ...


def _safe_key(key: str) -> str:
    key = key.lstrip("/")
    if ".." in Path(key).parts:
        raise StorageError("Invalid storage key")
    return key


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / _safe_key(key)).resolve()
        if self.root not in path.parents:
            raise StorageError("Invalid storage key")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise StorageError("File not found")
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(lambda: path.unlink(missing_ok=True))

    async def delete_prefix(self, prefix: str) -> int:
        base = self._path(prefix)

        def _rm() -> int:
            count = 0
            if base.is_dir():
                for p in sorted(base.rglob("*"), reverse=True):
                    if p.is_file():
                        p.unlink()
                        count += 1
                    else:
                        p.rmdir()
                base.rmdir()
            return count

        return await asyncio.to_thread(_rm)


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint or None,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=_safe_key(key),
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )

    async def get(self, key: str) -> bytes:
        try:
            obj = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=_safe_key(key))
        except Exception as exc:
            raise StorageError("File not found") from exc
        return await asyncio.to_thread(obj["Body"].read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=_safe_key(key))

    async def delete_prefix(self, prefix: str) -> int:
        def _rm() -> int:
            count = 0
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=_safe_key(prefix)):
                objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
                if objects:
                    self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})
                    count += len(objects)
            return count

        return await asyncio.to_thread(_rm)


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        settings = get_settings()
        _storage = S3Storage(settings) if settings.storage_backend == "s3" else LocalStorage(settings.local_storage_path)
    return _storage


def set_storage(storage: Storage | None) -> None:
    """Override storage (tests)."""
    global _storage
    _storage = storage


def user_prefix(user_id: int) -> str:
    return f"users/{user_id}/"
