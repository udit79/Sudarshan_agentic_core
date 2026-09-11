from __future__ import annotations

import json
import os
import time

from api.lifecycle import LifecycleCleaner
from api.storage import LocalObjectStore


def test_lifecycle_dry_run_protects_manifest_preview_and_parents(tmp_path):
    root = tmp_path / "artifacts"
    manifest_root = root / ".state" / "manifests"
    preview_root = root / ".state" / "previews"
    staging = root / ".state" / "ingestion_sources"
    for path in (manifest_root, preview_root, staging):
        path.mkdir(parents=True)
    (manifest_root / "artifact-1.json").write_text(
        json.dumps({"manifest": {"artifact_id": "artifact-1"}}), encoding="utf-8"
    )
    (preview_root / "artifact-1.png").write_bytes(b"keep")
    orphan = preview_root / "orphan.png"
    orphan.write_bytes(b"remove")
    staged = staging / "old-upload.bin"
    staged.write_bytes(b"remove")
    old = time.time() - 3600
    os.utime(staged, (old, old))

    store = LocalObjectStore(root / ".state" / "object-store")
    expired = store.put_bytes(b"expired", kind="evidence", expires_at="2000-01-01T00:00:00+00:00")
    cleaner = LifecycleCleaner(root, object_store=store, staging_root=staging)
    report = cleaner.cleanup(older_than_seconds=60, dry_run=True)
    identifiers = {(item.kind, item.identifier) for item in report.candidates}
    assert ("orphan_preview", "orphan.png") in identifiers
    assert ("staged_source", "old-upload.bin") in identifiers
    assert ("object", expired.object_id) in identifiers
    assert orphan.exists() and staged.exists() and expired.path.exists()

    cleaned = cleaner.cleanup(older_than_seconds=60, dry_run=False)
    assert "orphan.png" in cleaned.removed
    assert "old-upload.bin" in cleaned.removed
    assert not orphan.exists() and not staged.exists()
    assert store.purge_expired(dry_run=True) == ()
    assert (preview_root / "artifact-1.png").exists()
