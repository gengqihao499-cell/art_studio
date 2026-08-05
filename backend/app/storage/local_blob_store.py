"""Filesystem blob adapter used by default and as the remote fallback."""

from __future__ import annotations

from pathlib import Path

from app.storage.base import StoredArtifact


class LocalBlobStore:
    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _resolve_key(self, key: str) -> Path:
        # Never trust an artifact key as a filesystem path. Resolving and then
        # checking ``relative_to`` prevents ``../`` from escaping storage.
        destination = (self.root / key.lstrip("/\\")).resolve()
        try:
            destination.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("artifact key escapes the configured storage root") from exc
        return destination

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredArtifact:
        destination = self._resolve_key(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(destination)
        relative = destination.relative_to(self.root).as_posix()
        return StoredArtifact(
            backend=self.name,
            uri=f"local://{relative}",
            size_bytes=len(data),
            content_type=content_type,
        )

    def get_bytes(self, uri: str) -> bytes:
        key = uri.removeprefix("local://")
        return self._resolve_key(key).read_bytes()

    def health(self) -> dict:
        return {"available": True, "backend": self.name, "root": str(self.root)}
