import hashlib
import hmac
import time
from pathlib import Path
from urllib.parse import quote, urlencode

import boto3
from botocore.exceptions import ClientError

from app.settings import settings

API_ROOT = Path(__file__).resolve().parent.parent


def _bucket() -> str:
    if not settings.s3_bucket:
        raise RuntimeError("S3_BUCKET is not set")
    return settings.s3_bucket


def local_path(key: str) -> Path:
    root = (API_ROOT / settings.local_files_dir).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise ValueError("key leaves the files folder")
    return path


def local_signature(key: str, expires: int) -> str:
    return hmac.new(settings.jwt_secret.encode(), f"{key}|{expires}".encode(), hashlib.sha256).hexdigest()


def local_link_valid(key: str, expires: int, signature: str) -> bool:
    return expires > time.time() and hmac.compare_digest(local_signature(key, expires), signature)


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    if not settings.s3_bucket:
        path = local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    boto3.client("s3").put_object(Bucket=_bucket(), Key=key, Body=data, ContentType=content_type)


def upload_url(key: str, content_type: str, ttl_seconds: int) -> str:
    return boto3.client("s3").generate_presigned_url(
        "put_object", Params={"Bucket": _bucket(), "Key": key, "ContentType": content_type}, ExpiresIn=ttl_seconds
    )


def download_url(key: str, ttl_seconds: int) -> str:
    if not settings.s3_bucket:
        expires = int(time.time()) + ttl_seconds
        query = urlencode({"expires": expires, "signature": local_signature(key, expires)})
        return f"{settings.api_base_url.rstrip('/')}/v1/files/local/{quote(key)}?{query}"
    return boto3.client("s3").generate_presigned_url(
        "get_object", Params={"Bucket": _bucket(), "Key": key}, ExpiresIn=ttl_seconds
    )


def exists(key: str) -> bool:
    if not settings.s3_bucket:
        return local_path(key).is_file()
    try:
        boto3.client("s3").head_object(Bucket=_bucket(), Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise
    return True


def delete(key: str) -> None:
    if not settings.s3_bucket:
        local_path(key).unlink(missing_ok=True)
        return
    boto3.client("s3").delete_object(Bucket=_bucket(), Key=key)
