"""S3BlobStore against a mocked S3 (moto) — offline, no real R2/AWS.

The rest of the suite uses a FakeBlobStore; this exercises the real boto3-backed
store (presign / head / delete) so that code path is actually covered.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from polymnemo.blobstore.base import BlobError
from polymnemo.blobstore.s3 import S3BlobStore

_BUCKET = "test-bucket"
_CFG = {
    "bucket": _BUCKET,
    # An AWS-looking endpoint so moto intercepts it (moto only mocks AWS hosts;
    # a real R2 host like *.r2.cloudflarestorage.com would hit the network). We're
    # testing the store's logic, not R2-endpoint specifics.
    "endpoint_url": "https://s3.us-east-1.amazonaws.com",
    "access_key_id": "test-key",
    "secret_access_key": "test-secret",
    "region": "us-east-1",  # moto-friendly; real R2 uses "auto"
}


@mock_aws
def test_head_and_delete_round_trip():
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=_BUCKET)
    store = S3BlobStore(**_CFG)
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=_BUCKET, Key="alice/1/cat.png", Body=b"hello", ContentType="image/png"
    )

    size, etag = store.head("alice/1/cat.png")
    assert size == 5
    assert etag  # opaque, but present

    store.delete("alice/1/cat.png")
    with pytest.raises(BlobError, match="not found"):
        store.head("alice/1/cat.png")  # gone -> ClientError -> BlobError


@mock_aws
def test_presign_urls_contain_key():
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=_BUCKET)
    store = S3BlobStore(**_CFG)

    put = store.presign_put("alice/1/cat.png", "image/png")
    get = store.presign_get("alice/1/cat.png")
    for url in (put, get):
        assert url.startswith("https://")
        assert "alice/1/cat.png" in url
