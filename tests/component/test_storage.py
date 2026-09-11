from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from api.storage import LocalObjectStore, ObjectAuthorizationError, S3CompatibleObjectStore


def test_local_object_store_is_opaque_restart_safe_and_scope_checked(tmp_path):
    root = tmp_path / "objects"
    source = tmp_path / "source.txt"
    source.write_text("classified source", encoding="utf-8")
    store = LocalObjectStore(root)
    stored = store.put_file(
        source,
        kind="source",
        media_type="text/plain",
        classification_level="RESTRICTED",
        owner_id="user-1",
        case_id="case-1",
        task_id="task-1",
        retention_class="case",
    )

    assert stored.object_id.startswith("obj-")
    assert stored.path != source.resolve()
    assert stored.path.read_text(encoding="utf-8") == "classified source"
    with pytest.raises(ObjectAuthorizationError):
        store.get(stored.object_id, access_level="RESTRICTED", case_id="case-2")

    restarted = LocalObjectStore(root)
    loaded = restarted.get(
        stored.object_id,
        access_level="RESTRICTED",
        owner_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )
    assert loaded.sha256 == stored.sha256
    assert loaded.path.read_bytes() == source.read_bytes()


def test_local_object_store_retention_supports_dry_run_and_purge(tmp_path):
    store = LocalObjectStore(tmp_path / "objects")
    expires = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    stored = store.put_bytes(
        b"temporary",
        name="temporary.bin",
        kind="evidence",
        classification_level="RESTRICTED",
        expires_at=expires,
    )

    assert store.purge_expired(dry_run=True) == (stored.object_id,)
    assert stored.path.is_file()
    assert store.purge_expired(dry_run=False) == (stored.object_id,)
    assert not stored.path.exists()


def test_s3_compatible_adapter_round_trips_with_injected_client(tmp_path):
    class FakeS3:
        def __init__(self):
            self.objects = {}

        def upload_file(self, filename, bucket, key, ExtraArgs):
            self.objects[(bucket, key)] = (Path(filename).read_bytes(), dict(ExtraArgs))

        def head_object(self, *, Bucket, Key):
            body, args = self.objects[(Bucket, Key)]
            return {"Metadata": args["Metadata"], "ContentType": args["ContentType"]}

        def download_file(self, bucket, key, filename):
            Path(filename).write_bytes(self.objects[(bucket, key)][0])

        def list_objects_v2(self, *, Bucket, Prefix):
            return {"Contents": [{"Key": key} for current_bucket, key in self.objects if current_bucket == Bucket and key.startswith(Prefix)]}

        def delete_object(self, *, Bucket, Key):
            self.objects.pop((Bucket, Key), None)

    source = tmp_path / "source.txt"
    source.write_text("remote", encoding="utf-8")
    store = S3CompatibleObjectStore("bucket", prefix="case", cache_root=tmp_path / "cache", client=FakeS3())
    stored = store.put_file(source, kind="source", media_type="text/plain", case_id="case-1")
    source.unlink()
    restored = store.get(stored.object_id, access_level="TOP SECRET", case_id="case-1")
    assert restored.path.read_text(encoding="utf-8") == "remote"
    assert restored.path.suffix == ".txt"
    assert restored.sha256 == stored.sha256
