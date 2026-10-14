import pytest
from app.infrastructure.storage import LocalArtifactStore, S3ArtifactStore
from app.config import settings

def test_local_store_rejects_traversal_and_preserves_bytes():
    store=LocalArtifactStore()
    location=store.put('u/originals/doc/policy.txt', '实际政策'.encode())
    assert store.read(location).decode()=='实际政策'
    for key in ('../../outside','/etc/passwd'):
        with pytest.raises(ValueError): store.read(key)


def test_s3_adapter_uses_opaque_locations(monkeypatch):
    from io import BytesIO
    objects={}
    class Client:
        def put_object(self,**kwargs): objects[(kwargs['Bucket'],kwargs['Key'])]=kwargs['Body']
        def get_object(self,**kwargs): return {'Body':BytesIO(objects[(kwargs['Bucket'],kwargs['Key'])])}
    import boto3
    monkeypatch.setattr(settings,'S3_BUCKET','test-bucket')
    monkeypatch.setattr(boto3,'client',lambda *args,**kwargs:Client())
    store=S3ArtifactStore()
    location=store.put('u/doc/policy.md',b'# policy')
    assert location=='s3://test-bucket/u/doc/policy.md'
    with store.materialize(location) as path:
        assert path.read_bytes()==b'# policy'
    with pytest.raises(ValueError): store.read('s3://another-bucket/private')
