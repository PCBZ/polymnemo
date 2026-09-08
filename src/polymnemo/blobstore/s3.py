"""S3-compatible blob store — Cloudflare R2 (and AWS S3 / MinIO / B2).

R2 chosen for its zero egress fees + bigger free tier (media is download-heavy).
It speaks the S3 API, so one boto3 client covers all of them — only the endpoint
+ credentials differ. Imported lazily by ``context`` only when selected, so the
base install doesn't need boto3 (it's the ``blob`` extra).
"""

from __future__ import annotations

from .base import BlobError


class S3BlobStore:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
        url_ttl: int = 900,
    ) -> None:
        if not (bucket and endpoint_url and access_key_id and secret_access_key):
            raise BlobError(
                "S3/R2 blob store needs POLYMNEMO_BLOB_BUCKET, _ENDPOINT_URL, "
                "_ACCESS_KEY_ID and _SECRET_ACCESS_KEY."
            )
        import boto3  # lazy: only needed for the s3 backend (the `blob` extra)

        self._bucket = bucket
        self._ttl = url_ttl
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )

    def presign_put(self, object_key: str, content_type: str) -> str:
        return self._client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket,
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=self._ttl,
        )

    def presign_get(self, object_key: str) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": object_key},
            ExpiresIn=self._ttl,
        )

    def delete(self, object_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=object_key)
