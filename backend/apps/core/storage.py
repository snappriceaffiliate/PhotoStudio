"""Object storage access (SeaweedFS locally, Cloudflare R2 in staging and production).

Two clients are needed: the internal one reaches storage from the server, and the
public one signs URLs for the host the browser uses.
"""

from functools import cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings


def _client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


@cache
def internal_client():
    return _client(settings.S3_ENDPOINT_INTERNAL)


@cache
def public_client():
    return _client(settings.S3_ENDPOINT_PUBLIC)


def signed_upload_url(key: str, content_type: str) -> str:
    return public_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=settings.SIGNED_URL_SECONDS,
    )


def signed_download_url(key: str) -> str:
    return public_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": key},
        ExpiresIn=settings.SIGNED_URL_SECONDS,
    )


def object_size(key: str) -> int | None:
    """Return the stored object's size in bytes, or None if it does not exist."""
    try:
        head = internal_client().head_object(Bucket=settings.S3_BUCKET, Key=key)
    except ClientError:
        return None
    return head["ContentLength"]


def copy_object(source: str, target: str) -> None:
    internal_client().copy_object(
        Bucket=settings.S3_BUCKET,
        Key=target,
        CopySource={"Bucket": settings.S3_BUCKET, "Key": source},
        ContentType="image/webp",
        MetadataDirective="REPLACE",
    )


def delete_object(key: str) -> None:
    internal_client().delete_object(Bucket=settings.S3_BUCKET, Key=key)


def read_prefix(key: str, length: int = 12) -> bytes:
    """The first bytes of a stored object, to check what kind of file it really is."""
    try:
        obj = internal_client().get_object(
            Bucket=settings.S3_BUCKET, Key=key, Range=f"bytes=0-{length - 1}"
        )
    except ClientError:
        return b""
    return obj["Body"].read()


def is_webp(prefix: bytes) -> bool:
    return len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP"
