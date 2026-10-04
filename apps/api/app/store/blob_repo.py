"""Blob reads/writes for the concept graph file: `gs://bucket/path` or a local path."""

import asyncio
from pathlib import Path

from google.cloud import storage

from app.config import get_settings


def _split_gs(uri: str) -> tuple[str, str]:
    bucket, _, name = uri.removeprefix("gs://").partition("/")
    if not bucket or not name:
        raise ValueError(f"invalid GCS URI: {uri}")
    return bucket, name


def _blob(uri: str) -> storage.Blob:
    bucket, name = _split_gs(uri)
    client = storage.Client(project=get_settings().gcp_project or None)
    return client.bucket(bucket).blob(name)


async def read_bytes(uri: str) -> bytes:
    if uri.startswith("gs://"):
        return await asyncio.to_thread(lambda: _blob(uri).download_as_bytes())
    return await asyncio.to_thread(Path(uri).read_bytes)


async def write_bytes(uri: str, data: bytes, content_type: str = "application/json") -> None:
    if uri.startswith("gs://"):
        await asyncio.to_thread(
            lambda: _blob(uri).upload_from_string(data, content_type=content_type)
        )
        return
    await asyncio.to_thread(Path(uri).write_bytes, data)
