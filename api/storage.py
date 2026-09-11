"""Restart-safe object storage for sources, evidence, and artifacts.

The local implementation is intentionally boring: immutable files live below a
controlled root and a SQLite catalog owns their metadata.  Production object
stores can implement the same small interface without changing callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from threading import Lock
from typing import Any, Mapping, Protocol
from uuid import uuid4

from pipelines.common.ntro_policy import require_classification_access


class ObjectNotFound(FileNotFoundError):
    """Raised when an opaque object ID is not present in the catalog."""


class ObjectAuthorizationError(PermissionError):
    """Raised when scope or classification does not authorize object access."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_id: str
    kind: str
    path: Path
    sha256: str
    size_bytes: int
    media_type: str
    classification_level: str
    owner_id: str | None
    case_id: str | None
    task_id: str | None
    run_id: str | None
    retention_class: str
    parent_object_ids: tuple[str, ...]
    created_at: str
    expires_at: str | None


class ObjectStore(Protocol):
    """Backend contract shared by local and S3-compatible object stores."""

    def put_file(self, source_path: str | Path, **metadata: Any) -> StoredObject:
        ...

    def put_bytes(self, content: bytes, **metadata: Any) -> StoredObject:
        ...

    def get(self, object_id: str, *, access_level: str, **scope: Any) -> StoredObject:
        ...

    def purge_expired(self, *, now: str | None = None, dry_run: bool = True) -> tuple[str, ...]:
        ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalObjectStore:
    """Immutable, metadata-indexed local object store.

    ``path`` is an implementation detail and is never returned by the public
    application boundary.  Callers receive an opaque object ID and can ask
    this store for a verified stream after authorization.
    """

    def __init__(self, root: str | Path = "artifacts/.state/object-store", *, db_path: str | Path | None = None) -> None:
        self.root = Path(root).resolve()
        self.object_root = self.root / "objects"
        self.object_root.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_path or self.root / "catalog.db")
        Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS objects (
                    object_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    classification_level TEXT NOT NULL,
                    owner_id TEXT,
                    case_id TEXT,
                    task_id TEXT,
                    run_id TEXT,
                    retention_class TEXT NOT NULL,
                    parent_object_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_objects_scope ON objects(owner_id, case_id, task_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_objects_expiry ON objects(expires_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def put_file(
        self,
        source_path: str | Path,
        *,
        kind: str,
        media_type: str = "application/octet-stream",
        classification_level: str = "RESTRICTED",
        owner_id: str | None = None,
        case_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        retention_class: str = "standard",
        parent_object_ids: tuple[str, ...] | list[str] = (),
        expires_at: str | None = None,
    ) -> StoredObject:
        source = Path(source_path).resolve()
        if not source.is_file():
            raise ObjectNotFound(str(source))
        if not kind.strip() or not media_type.strip():
            raise ValueError("kind and media_type must be non-empty")
        digest = self._sha256(source)
        object_id = f"obj-{uuid4().hex}"
        relative_path = f"objects/{object_id}{source.suffix.lower()}"
        destination = self.root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        created_at = _utc_now()
        parents = tuple(str(item) for item in parent_object_ids if str(item).strip())
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO objects(
                    object_id, kind, relative_path, sha256, size_bytes, media_type,
                    classification_level, owner_id, case_id, task_id, run_id,
                    retention_class, parent_object_ids_json, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    object_id,
                    kind.strip(),
                    relative_path,
                    digest,
                    destination.stat().st_size,
                    media_type.strip(),
                    classification_level.strip().upper(),
                    owner_id,
                    case_id,
                    task_id,
                    run_id,
                    retention_class.strip() or "standard",
                    json.dumps(parents),
                    created_at,
                    expires_at,
                ),
            )
        return self.get(object_id, access_level="TOP SECRET", include_path=True)

    def put_bytes(self, content: bytes, *, name: str = "object.bin", **metadata: Any) -> StoredObject:
        staging = self.root / ".staging" / f"{uuid4().hex}-{Path(name).name}"
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.write_bytes(content)
        try:
            return self.put_file(staging, **metadata)
        finally:
            staging.unlink(missing_ok=True)

    def get(
        self,
        object_id: str,
        *,
        access_level: str,
        owner_id: str | None = None,
        case_id: str | None = None,
        task_id: str | None = None,
        include_path: bool = True,
    ) -> StoredObject:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM objects WHERE object_id = ?", (str(object_id),)
            ).fetchone()
        if row is None:
            raise ObjectNotFound(str(object_id))
        require_classification_access(access_level, row["classification_level"])
        for supplied, stored, label in (
            (owner_id, row["owner_id"], "owner_id"),
            (case_id, row["case_id"], "case_id"),
            (task_id, row["task_id"], "task_id"),
        ):
            if supplied is not None and stored is not None and str(supplied) != str(stored):
                raise ObjectAuthorizationError(f"{label} scope does not match object")
        path = self._path_for(row["relative_path"])
        if not path.is_file() or self._sha256(path) != row["sha256"]:
            raise ValueError("object checksum does not match catalog metadata")
        return StoredObject(
            object_id=row["object_id"],
            kind=row["kind"],
            path=path if include_path else Path(row["relative_path"]),
            sha256=row["sha256"],
            size_bytes=int(row["size_bytes"]),
            media_type=row["media_type"],
            classification_level=row["classification_level"],
            owner_id=row["owner_id"],
            case_id=row["case_id"],
            task_id=row["task_id"],
            run_id=row["run_id"],
            retention_class=row["retention_class"],
            parent_object_ids=tuple(json.loads(row["parent_object_ids_json"])),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )

    def _path_for(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        if path == self.root or self.root not in path.parents:
            raise PermissionError("catalog path escapes object store root")
        return path

    def retention_candidates(self, *, now: str | None = None) -> tuple[StoredObject, ...]:
        cutoff = now or _utc_now()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM objects WHERE expires_at IS NOT NULL AND expires_at <= ? ORDER BY object_id",
                (cutoff,),
            ).fetchall()
        return tuple(self._row_to_object(row) for row in rows)

    def purge_expired(self, *, now: str | None = None, dry_run: bool = True) -> tuple[str, ...]:
        candidates = self.retention_candidates(now=now)
        ids = tuple(item.object_id for item in candidates)
        if dry_run:
            return ids
        with self._lock, self._connect() as connection:
            for item in candidates:
                item.path.unlink(missing_ok=True)
                connection.execute("DELETE FROM objects WHERE object_id = ?", (item.object_id,))
        return ids

    def _row_to_object(self, row: sqlite3.Row) -> StoredObject:
        return StoredObject(
            object_id=row["object_id"], kind=row["kind"], path=self._path_for(row["relative_path"]),
            sha256=row["sha256"], size_bytes=int(row["size_bytes"]),
            media_type=row["media_type"], classification_level=row["classification_level"],
            owner_id=row["owner_id"], case_id=row["case_id"], task_id=row["task_id"],
            run_id=row["run_id"], retention_class=row["retention_class"],
            parent_object_ids=tuple(json.loads(row["parent_object_ids_json"])),
            created_at=row["created_at"], expires_at=row["expires_at"],
        )


class S3CompatibleObjectStore:
    """Optional S3-compatible backend with local materialization for consumers.

    ``client`` is injectable, so MinIO, AWS S3, and test doubles use the same
    adapter. boto3 is imported only when a client is not supplied.
    """

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "sudarshan/objects",
        cache_root: str | Path = "artifacts/.state/object-cache",
        client: Any | None = None,
        endpoint_url: str | None = None,
        region_name: str | None = None,
    ) -> None:
        if not str(bucket).strip():
            raise ValueError("S3 object store bucket must be non-empty")
        self.bucket = str(bucket).strip()
        self.prefix = str(prefix).strip("/")
        self.cache_root = Path(cache_root).resolve()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        if client is None:
            try:
                import boto3  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise RuntimeError("S3 mode requires boto3 or an injected S3-compatible client") from exc
            client = boto3.client("s3", endpoint_url=endpoint_url or None, region_name=region_name or None)
        self.client = client

    def _key(self, object_id: str, suffix: str = "") -> str:
        return "/".join(item for item in (self.prefix, f"{object_id}{suffix}") if item)

    @staticmethod
    def _metadata(metadata: Mapping[str, Any], digest: str, size_bytes: int, media_type: str) -> dict[str, str]:
        parents = metadata.get("parent_object_ids", ())
        return {
            "sha256": digest,
            "size-bytes": str(size_bytes),
            "kind": str(metadata.get("kind", "object")),
            "media-type": str(media_type),
            "classification-level": str(metadata.get("classification_level", "RESTRICTED")).upper(),
            "owner-id": str(metadata.get("owner_id") or ""),
            "case-id": str(metadata.get("case_id") or ""),
            "task-id": str(metadata.get("task_id") or ""),
            "run-id": str(metadata.get("run_id") or ""),
            "retention-class": str(metadata.get("retention_class", "standard")),
            "parent-object-ids": json.dumps([str(item) for item in parents]),
            "created-at": _utc_now(),
            "expires-at": str(metadata.get("expires_at") or ""),
            "source-suffix": str(metadata.get("source_suffix", "")),
        }

    @staticmethod
    def _scope_check(metadata: Mapping[str, Any], *, access_level: str, owner_id: str | None, case_id: str | None, task_id: str | None) -> None:
        require_classification_access(access_level, str(metadata.get("classification-level", "RESTRICTED")))
        for supplied, key, label in (
            (owner_id, "owner-id", "owner_id"),
            (case_id, "case-id", "case_id"),
            (task_id, "task-id", "task_id"),
        ):
            stored = str(metadata.get(key, "")) or None
            if supplied is not None and stored is not None and str(supplied) != stored:
                raise ObjectAuthorizationError(f"{label} scope does not match object")

    def put_file(self, source_path: str | Path, **metadata: Any) -> StoredObject:
        source = Path(source_path).resolve()
        if not source.is_file():
            raise ObjectNotFound(str(source))
        digest = LocalObjectStore._sha256(source)
        object_id = f"obj-{uuid4().hex}"
        media_type = str(metadata.get("media_type", "application/octet-stream"))
        object_metadata = self._metadata(
            {**metadata, "source_suffix": source.suffix.lower()},
            digest,
            source.stat().st_size,
            media_type,
        )
        upload_args: dict[str, Any] = {
            "ContentType": media_type,
            "Metadata": object_metadata,
        }
        server_side_encryption = os.getenv("SUDARSHAN_OBJECT_STORE_S3_SERVER_SIDE_ENCRYPTION", "").strip()
        if server_side_encryption:
            upload_args["ServerSideEncryption"] = server_side_encryption
        kms_key_id = os.getenv("SUDARSHAN_OBJECT_STORE_S3_KMS_KEY_ID", "").strip()
        if kms_key_id:
            upload_args["SSEKMSKeyId"] = kms_key_id
        self.client.upload_file(
            str(source), self.bucket, self._key(object_id),
            ExtraArgs=upload_args,
        )
        return StoredObject(
            object_id=object_id, kind=object_metadata["kind"], path=source,
            sha256=digest, size_bytes=source.stat().st_size, media_type=media_type,
            classification_level=object_metadata["classification-level"],
            owner_id=object_metadata["owner-id"] or None, case_id=object_metadata["case-id"] or None,
            task_id=object_metadata["task-id"] or None, run_id=object_metadata["run-id"] or None,
            retention_class=object_metadata["retention-class"],
            parent_object_ids=tuple(json.loads(object_metadata["parent-object-ids"])),
            created_at=object_metadata["created-at"], expires_at=object_metadata["expires-at"] or None,
        )

    def put_bytes(self, content: bytes, *, name: str = "object.bin", **metadata: Any) -> StoredObject:
        staging = self.cache_root / f"upload-{uuid4().hex}-{Path(name).name}"
        staging.write_bytes(content)
        try:
            return self.put_file(staging, **metadata)
        finally:
            staging.unlink(missing_ok=True)

    def get(
        self,
        object_id: str,
        *,
        access_level: str,
        owner_id: str | None = None,
        case_id: str | None = None,
        task_id: str | None = None,
        include_path: bool = True,
    ) -> StoredObject:
        head = self.client.head_object(Bucket=self.bucket, Key=self._key(str(object_id)))
        metadata = dict(head.get("Metadata") or {})
        self._scope_check(metadata, access_level=access_level, owner_id=owner_id, case_id=case_id, task_id=task_id)
        suffix = str(metadata.get("source-suffix", ""))
        destination = self.cache_root / f"{object_id}{suffix}"
        if not destination.is_file() or LocalObjectStore._sha256(destination) != metadata.get("sha256"):
            self.client.download_file(self.bucket, self._key(str(object_id)), str(destination))
        if LocalObjectStore._sha256(destination) != metadata.get("sha256"):
            raise ValueError("object checksum does not match S3 metadata")
        return StoredObject(
            object_id=str(object_id), kind=metadata.get("kind", "object"),
            path=destination if include_path else Path(str(object_id)),
            sha256=metadata.get("sha256", ""), size_bytes=int(metadata.get("size-bytes", destination.stat().st_size)),
            media_type=metadata.get("media-type", head.get("ContentType", "application/octet-stream")),
            classification_level=metadata.get("classification-level", "RESTRICTED"),
            owner_id=metadata.get("owner-id") or None, case_id=metadata.get("case-id") or None,
            task_id=metadata.get("task-id") or None, run_id=metadata.get("run-id") or None,
            retention_class=metadata.get("retention-class", "standard"),
            parent_object_ids=tuple(json.loads(metadata.get("parent-object-ids", "[]"))),
            created_at=metadata.get("created-at", ""), expires_at=metadata.get("expires-at") or None,
        )

    def retention_candidates(self, *, now: str | None = None) -> tuple[StoredObject, ...]:
        cutoff = now or _utc_now()
        response = self.client.list_objects_v2(Bucket=self.bucket, Prefix=f"{self.prefix}/" if self.prefix else "")
        candidates: list[StoredObject] = []
        for item in response.get("Contents", []):
            key = str(item.get("Key", ""))
            object_id = Path(key).stem
            try:
                stored = self.get(object_id, access_level="TOP SECRET")
            except (ObjectNotFound, KeyError, ValueError):
                continue
            if stored.expires_at and stored.expires_at <= cutoff:
                candidates.append(stored)
        return tuple(candidates)

    def purge_expired(self, *, now: str | None = None, dry_run: bool = True) -> tuple[str, ...]:
        candidates = self.retention_candidates(now=now)
        if not dry_run:
            for item in candidates:
                self.client.delete_object(Bucket=self.bucket, Key=self._key(item.object_id))
                item.path.unlink(missing_ok=True)
        return tuple(item.object_id for item in candidates)


def build_object_store_from_env(root: str | Path = "artifacts") -> ObjectStore | None:
    """Build the configured backend; return ``None`` for legacy local mode."""

    mode = os.getenv("SUDARSHAN_OBJECT_STORE_MODE", "local").strip().lower()
    if mode in {"durable", "filesystem"}:
        configured_root = os.getenv("SUDARSHAN_OBJECT_STORE_ROOT", "").strip()
        return LocalObjectStore(configured_root or Path(root) / ".state" / "object-store")
    if mode == "s3":
        return S3CompatibleObjectStore(
            os.getenv("SUDARSHAN_OBJECT_STORE_S3_BUCKET", ""),
            prefix=os.getenv("SUDARSHAN_OBJECT_STORE_S3_PREFIX", "sudarshan/objects"),
            cache_root=Path(root) / ".state" / "object-cache",
            endpoint_url=os.getenv("SUDARSHAN_OBJECT_STORE_S3_ENDPOINT") or None,
            region_name=os.getenv("SUDARSHAN_OBJECT_STORE_S3_REGION") or None,
        )
    if mode not in {"", "local"}:
        raise ValueError(f"unsupported SUDARSHAN_OBJECT_STORE_MODE: {mode}")
    return None


__all__ = [
    "ObjectStore",
    "build_object_store_from_env",
    "LocalObjectStore",
    "ObjectAuthorizationError",
    "ObjectNotFound",
    "StoredObject",
    "S3CompatibleObjectStore",
]
