"""Local and S3-compatible object storage backends."""

from __future__ import annotations

import contextlib
import mimetypes
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import boto3
from flask import current_app
from werkzeug.utils import secure_filename


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    content_type: str | None
    original_filename: str


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save_upload(self, uploaded_file, prefix: str) -> StoredObject:
        key = _object_key(prefix, uploaded_file.filename or "upload.bin")
        destination = (self.root / key).resolve()
        if self.root not in destination.parents:
            raise ValueError("Invalid storage key.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        uploaded_file.save(destination)
        return StoredObject(
            key=key,
            size_bytes=destination.stat().st_size,
            content_type=uploaded_file.mimetype,
            original_filename=secure_filename(uploaded_file.filename or "upload.bin"),
        )

    def save_file(self, local_path: str | Path, prefix: str, content_type: str | None = None) -> StoredObject:
        source = Path(local_path).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Result artifact does not exist: {source.name}")
        key = _object_key(prefix, source.name)
        destination = (self.root / key).resolve()
        if self.root not in destination.parents:
            raise ValueError("Invalid storage key.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        resolved_type = content_type or mimetypes.guess_type(source.name)[0]
        return StoredObject(
            key=key,
            size_bytes=destination.stat().st_size,
            content_type=resolved_type,
            original_filename=secure_filename(source.name),
        )

    @contextlib.contextmanager
    def materialize(self, key: str):
        candidate = (self.root / key).resolve()
        if self.root not in candidate.parents or not candidate.is_file():
            raise FileNotFoundError("Stored object does not exist.")
        yield candidate


class S3Storage:
    def __init__(self):
        self.bucket = str(current_app.config.get("S3_BUCKET", "")).strip()
        if not self.bucket:
            raise RuntimeError("S3_BUCKET is required when STORAGE_BACKEND=s3.")
        self.client = boto3.client(
            "s3",
            endpoint_url=current_app.config.get("S3_ENDPOINT_URL") or None,
            region_name=current_app.config.get("S3_REGION") or None,
            aws_access_key_id=current_app.config.get("S3_ACCESS_KEY_ID") or None,
            aws_secret_access_key=current_app.config.get("S3_SECRET_ACCESS_KEY") or None,
        )

    def save_upload(self, uploaded_file, prefix: str) -> StoredObject:
        key = _object_key(prefix, uploaded_file.filename or "upload.bin")
        uploaded_file.stream.seek(0, os.SEEK_END)
        size_bytes = uploaded_file.stream.tell()
        uploaded_file.stream.seek(0)
        extra_args = {"ContentType": uploaded_file.mimetype} if uploaded_file.mimetype else None
        self.client.upload_fileobj(uploaded_file.stream, self.bucket, key, ExtraArgs=extra_args or {})
        return StoredObject(
            key=key,
            size_bytes=size_bytes,
            content_type=uploaded_file.mimetype,
            original_filename=secure_filename(uploaded_file.filename or "upload.bin"),
        )

    def save_file(self, local_path: str | Path, prefix: str, content_type: str | None = None) -> StoredObject:
        source = Path(local_path).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Result artifact does not exist: {source.name}")
        key = _object_key(prefix, source.name)
        resolved_type = content_type or mimetypes.guess_type(source.name)[0]
        extra_args = {"ContentType": resolved_type} if resolved_type else {}
        self.client.upload_file(str(source), self.bucket, key, ExtraArgs=extra_args)
        return StoredObject(
            key=key,
            size_bytes=source.stat().st_size,
            content_type=resolved_type,
            original_filename=secure_filename(source.name),
        )

    @contextlib.contextmanager
    def materialize(self, key: str):
        suffix = Path(key).suffix
        temp_dir = Path(tempfile.mkdtemp(prefix="audiobook-object-"))
        temp_path = temp_dir / f"source{suffix}"
        try:
            self.client.download_file(self.bucket, key, str(temp_path))
            yield temp_path
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _object_key(prefix: str, filename: str) -> str:
    safe_name = secure_filename(filename) or "upload.bin"
    suffix = Path(safe_name).suffix.lower()[:16]
    clean_prefix = "/".join(part for part in prefix.strip("/").split("/") if part and part not in {".", ".."})
    return f"{clean_prefix}/{uuid.uuid4().hex}{suffix}"


def get_storage():
    backend = str(current_app.config.get("STORAGE_BACKEND", "local")).strip().lower()
    if backend == "s3":
        return S3Storage()
    root_value = str(current_app.config.get("STORAGE_LOCAL_ROOT", "instance/storage"))
    root = Path(root_value)
    if not root.is_absolute():
        root = Path(current_app.root_path) / root
    return LocalStorage(root)
