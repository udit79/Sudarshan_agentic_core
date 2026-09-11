"""Lineage-aware cleanup for derived files and expired metadata."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
import time
from typing import Any

from api.storage import ObjectStore


@dataclass(frozen=True, slots=True)
class CleanupCandidate:
    kind: str
    identifier: str
    path: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class CleanupReport:
    dry_run: bool
    candidates: tuple[CleanupCandidate, ...]
    removed: tuple[str, ...]
    skipped: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "candidate_count": len(self.candidates),
            "removed_count": len(self.removed),
            "skipped_count": len(self.skipped),
            "candidates": [asdict(item) for item in self.candidates],
            "removed": list(self.removed),
            "skipped": list(self.skipped),
        }


class LifecycleCleaner:
    """Discover safe cleanup candidates before optionally deleting them.

    Audit databases and manifest files are never deleted. A manifest or an
    object referenced by a manifest is protected; only orphaned previews,
    expired staging files, cache metadata, and object-store expiry candidates
    are eligible.
    """

    def __init__(
        self,
        artifact_root: str | Path = "artifacts",
        *,
        object_store: ObjectStore | None = None,
        staging_root: str | Path | None = None,
        cache_store: Any | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root).resolve()
        self.manifest_root = self.artifact_root / ".state" / "manifests"
        self.preview_root = self.artifact_root / ".state" / "previews"
        self.staging_root = Path(staging_root or self.artifact_root / ".state" / "ingestion_sources").resolve()
        self.object_store = object_store
        self.cache_store = cache_store

    def discover(self, *, older_than_seconds: float = 86_400, now: float | None = None) -> tuple[CleanupCandidate, ...]:
        if older_than_seconds < 0:
            raise ValueError("older_than_seconds must not be negative")
        current = time.time() if now is None else float(now)
        candidates: list[CleanupCandidate] = []
        referenced_previews: set[str] = set()
        referenced_objects: set[str] = set()
        if self.manifest_root.is_dir():
            for manifest_path in self.manifest_root.glob("*.json"):
                try:
                    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                    artifact_id = str(payload.get("manifest", {}).get("artifact_id", ""))
                    if artifact_id:
                        referenced_previews.add(f"{artifact_id}.png")
                    object_id = payload.get("object_id")
                    if object_id:
                        referenced_objects.add(str(object_id))
                except (OSError, ValueError, TypeError):
                    continue
        if self.preview_root.is_dir():
            for path in self.preview_root.iterdir():
                if path.is_file() and path.name not in referenced_previews:
                    candidates.append(CleanupCandidate("orphan_preview", path.name, str(path), "not referenced by a manifest"))

        if self.staging_root.is_dir():
            cutoff = current - older_than_seconds
            for path in self.staging_root.rglob("*"):
                if path.is_file() and path.stat().st_mtime <= cutoff:
                    candidates.append(CleanupCandidate("staged_source", str(path.relative_to(self.staging_root)), str(path), "expired staging lease"))

        if self.object_store is not None:
            for item in self.object_store.retention_candidates():
                if item.object_id in referenced_objects:
                    continue
                candidates.append(CleanupCandidate("object", item.object_id, str(item.path), "retention expired"))
        return tuple(candidates)

    def cleanup(
        self,
        *,
        older_than_seconds: float = 86_400,
        dry_run: bool = True,
        now: float | None = None,
    ) -> CleanupReport:
        candidates = self.discover(older_than_seconds=older_than_seconds, now=now)
        if dry_run:
            return CleanupReport(True, candidates, (), ())
        removed: list[str] = []
        skipped: list[str] = []
        object_ids = [item.identifier for item in candidates if item.kind == "object"]
        if self.object_store is not None and object_ids:
            removed.extend(self.object_store.purge_expired(dry_run=False))
        for item in candidates:
            if item.kind == "object":
                continue
            if not item.path:
                skipped.append(item.identifier)
                continue
            path = Path(item.path).resolve()
            root = self.preview_root.resolve() if item.kind == "orphan_preview" else self.staging_root
            if path != root and root not in path.parents:
                skipped.append(item.identifier)
                continue
            try:
                path.unlink(missing_ok=True)
                removed.append(item.identifier)
            except OSError:
                skipped.append(item.identifier)
        if self.cache_store is not None:
            cleanup = getattr(self.cache_store, "cleanup_expired", None)
            if callable(cleanup):
                cleanup(now=now)
        return CleanupReport(False, candidates, tuple(removed), tuple(skipped))


__all__ = ["CleanupCandidate", "CleanupReport", "LifecycleCleaner"]
