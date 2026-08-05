"""Optional Alibaba Cloud OSS adapter.

``oss2`` is intentionally an optional dependency. Importing ArtFlow in local
mode therefore stays fast and does not require any cloud packages.
"""

from __future__ import annotations

from app.storage.base import StoredArtifact


class OSSBlobStore:
    name = "oss"

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key_id: str,
        access_key_secret: str,
        prefix: str = "artflow",
    ) -> None:
        if not all((endpoint, bucket, access_key_id, access_key_secret)):
            raise RuntimeError("OSS backend requires endpoint, bucket and access keys")
        self.endpoint = endpoint
        self.bucket_name = bucket
        self.prefix = prefix.strip("/")
        self._credentials = (access_key_id, access_key_secret)
        self._bucket = None

    def _client(self):
        if self._bucket is None:
            try:
                import oss2
            except ImportError as exc:
                raise RuntimeError("OSS backend requires: pip install oss2") from exc
            auth = oss2.Auth(*self._credentials)
            self._bucket = oss2.Bucket(auth, self.endpoint, self.bucket_name)
        return self._bucket

    def _object_key(self, key: str) -> str:
        clean = key.replace("\\", "/").lstrip("/")
        if ".." in clean.split("/"):
            raise ValueError("invalid OSS artifact key")
        return f"{self.prefix}/{clean}" if self.prefix else clean

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredArtifact:
        object_key = self._object_key(key)
        self._client().put_object(
            object_key,
            data,
            headers={"Content-Type": content_type},
        )
        return StoredArtifact(
            backend=self.name,
            uri=f"oss://{self.bucket_name}/{object_key}",
            size_bytes=len(data),
            content_type=content_type,
        )

    def get_bytes(self, uri: str) -> bytes:
        prefix = f"oss://{self.bucket_name}/"
        if not uri.startswith(prefix):
            raise ValueError("artifact URI belongs to another OSS bucket")
        return self._client().get_object(uri.removeprefix(prefix)).read()

    def health(self) -> dict:
        try:
            self._client().get_bucket_info()
            return {"available": True, "backend": self.name, "bucket": self.bucket_name}
        except Exception as exc:  # Cloud SDK errors differ between versions.
            return {
                "available": False,
                "backend": self.name,
                "bucket": self.bucket_name,
                "error": type(exc).__name__,
            }
