"""S3 storage backend."""

from __future__ import annotations
from abc import ABC, abstractmethod

class StorageBackend(ABC):
    @abstractmethod
    async def read(self, key: str) -> bytes: ...
    @abstractmethod
    async def write(self, key: str, data: bytes) -> None: ...
    @abstractmethod
    async def delete(self, key: str) -> None: ...

class S3Storage(StorageBackend):
    """S3-compatible storage."""

    def __init__(self, bucket: str, endpoint_url: str = None):
        self.bucket = bucket
        self.client = None
        try:
            import boto3
            self.client = boto3.client('s3', endpoint_url=endpoint_url)
        except ImportError:
            pass

    async def read(self, key: str) -> bytes:
        if not self.client:
            raise RuntimeError("boto3 not installed")
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.client.get_object(Bucket=self.bucket, Key=key)['Body'].read()
        )

    async def write(self, key: str, data: bytes) -> None:
        if not self.client:
            raise RuntimeError("boto3 not installed")
        import asyncio
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        )

    async def delete(self, key: str) -> None:
        if not self.client:
            raise RuntimeError("boto3 not installed")
        import asyncio
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.client.delete_object(Bucket=self.bucket, Key=key)
        )
