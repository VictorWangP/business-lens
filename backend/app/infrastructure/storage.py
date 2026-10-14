"""Artifact adapters. Database locations are opaque and checked before filesystem access."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
from app.config import settings

class LocalArtifactStore:
    def path(self, key: str) -> Path:
        root = settings.USER_STORAGE_DIR.resolve()
        target = (root / key).resolve()
        if not target.is_relative_to(root):
            raise ValueError('非法文件路径')
        return target

    def put(self, key: str, content: bytes) -> str:
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + '.tmp')
        temporary.write_bytes(content)
        temporary.replace(target)
        return str(target)

    def read(self, location: str) -> bytes:
        return self.path(location).read_bytes()

    def delete(self, location: str):
        self.path(location).unlink(missing_ok=True)

    def delete_prefix(self, key: str):
        # Only application-generated document artifact directories are accepted.
        target = self.path(key)
        if target.exists():
            shutil.rmtree(target)

    @contextmanager
    def materialize(self, location: str):
        yield self.path(location)

class S3ArtifactStore:
    def __init__(self):
        import boto3
        from botocore.config import Config
        if not settings.S3_BUCKET:
            raise ValueError('请配置 S3_BUCKET')
        self.client = boto3.client('s3', endpoint_url=settings.S3_ENDPOINT or None,
                                   region_name=settings.S3_REGION,
                                   aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
                                   aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
                                   aws_session_token=settings.AWS_SESSION_TOKEN or None,
                                   config=Config(connect_timeout=5, read_timeout=60,
                                                 retries={'max_attempts': 2}, s3={'addressing_style':'path'}))

    def key(self, location: str) -> str:
        prefix = f's3://{settings.S3_BUCKET}/'
        if not location.startswith(prefix) or '..' in location[len(prefix):].split('/'):
            raise ValueError('非法对象存储位置')
        return location[len(prefix):]

    def put(self, key: str, content: bytes) -> str:
        if key.startswith('/') or '..' in key.split('/'):
            raise ValueError('非法对象键')
        self.client.put_object(Bucket=settings.S3_BUCKET, Key=key, Body=content)
        return f's3://{settings.S3_BUCKET}/{key}'

    def read(self, location: str) -> bytes:
        response = self.client.get_object(Bucket=settings.S3_BUCKET, Key=self.key(location))
        with response['Body'] as body:
            return body.read()

    def delete(self, location: str):
        self.client.delete_object(Bucket=settings.S3_BUCKET, Key=self.key(location))

    def delete_prefix(self, key: str):
        prefix = key.rstrip('/') + '/'
        self.key(f's3://{settings.S3_BUCKET}/{prefix}')
        for page in self.client.get_paginator('list_objects_v2').paginate(Bucket=settings.S3_BUCKET, Prefix=prefix):
            for item in page.get('Contents', []):
                self.client.delete_object(Bucket=settings.S3_BUCKET, Key=item['Key'])

    @contextmanager
    def materialize(self, location: str):
        with TemporaryDirectory(prefix='rag-document-') as directory:
            path = Path(directory) / Path(self.key(location)).name
            path.write_bytes(self.read(location))
            yield path

class ArtifactStore:
    def backend(self):
        if settings.STORAGE_BACKEND == 'local':
            return LocalArtifactStore()
        if settings.STORAGE_BACKEND == 's3':
            return S3ArtifactStore()
        raise ValueError('未知 STORAGE_BACKEND')

    def put(self, key, content):
        return self.backend().put(key, content)

    def read(self, location):
        # Legacy local documents remain accessible during explicit migration to S3.
        backend = S3ArtifactStore() if location.startswith('s3://') else LocalArtifactStore()
        return backend.read(location)

    def materialize(self, location):
        backend = S3ArtifactStore() if location.startswith('s3://') else LocalArtifactStore()
        return backend.materialize(location)

    def delete(self, location):
        backend = S3ArtifactStore() if location.startswith('s3://') else LocalArtifactStore()
        backend.delete(location)

    def delete_artifacts(self, user_id: str, doc_id: str, version: str = ''):
        import uuid
        for value in (user_id, doc_id, version):
            if value:
                uuid.UUID(value)
        key = f'{user_id}/artifacts/{doc_id}' + (f'/{version}' if version else '')
        LocalArtifactStore().delete_prefix(key)
        if settings.S3_BUCKET:
            S3ArtifactStore().delete_prefix(key)

store = ArtifactStore()
