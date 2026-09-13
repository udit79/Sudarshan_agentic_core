"""Immutable local artifact manifests for the application boundary."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api.storage import ObjectStore, build_object_store_from_env
from pipelines.orchestrator.contracts import ArtifactManifest, QualityStatus


class ArtifactNotFound(FileNotFoundError):
    """Raised when an artifact manifest or source file is unavailable."""


class ArtifactPreviewUnavailable(ArtifactNotFound):
    """Raised when a registered artifact has no safe preview representation."""


@dataclass(frozen=True, slots=True)
class CheckedArtifact:
    """The result of render selection, integrity inspection, and registration."""

    manifest: ArtifactManifest
    quality_report_id: str
    renderer_version: str
    degraded: bool
    quality_issues: tuple[str, ...]


class ArtifactStore:
    """Register files under the controlled artifact root and verify integrity."""

    def __init__(self, root: str | Path = "artifacts", *, object_store: ObjectStore | None = None) -> None:
        self.root = Path(root).resolve()
        self.manifest_root = self.root / ".state" / "manifests"
        self.preview_root = self.root / ".state" / "previews"
        self.quality_report_root = self.root / ".state" / "quality_reports"
        self.manifest_root.mkdir(parents=True, exist_ok=True)
        self.preview_root.mkdir(parents=True, exist_ok=True)
        self.quality_report_root.mkdir(parents=True, exist_ok=True)
        self.object_store = object_store or build_object_store_from_env(self.root)

    def _safe_source(self, path: str | Path) -> Path:
        resolved = Path(path).resolve()
        if resolved == self.root or self.root not in resolved.parents:
            raise PermissionError("artifact path is outside the controlled artifact root")
        if not resolved.is_file():
            raise ArtifactNotFound(str(resolved))
        return resolved

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _build_preview(self, source: Path, artifact_id: str) -> Path | None:
        """Create or select a bounded, deterministic preview representation."""

        suffix = source.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".webm", ".txt", ".md", ".json"}:
            return source
        if suffix != ".pdf":
            return None

        preview = self.preview_root / f"{artifact_id}.png"
        if preview.is_file():
            return preview
        try:
            import fitz

            document = fitz.open(str(source))
            if document.page_count < 1:
                document.close()
                return None
            page = document.load_page(0)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            pixmap.save(str(preview))
            document.close()
            return preview
        except Exception:
            preview.unlink(missing_ok=True)
            return None

    def _preview_uri(self, artifact_id: str, source: Path) -> str | None:
        return (
            f"/artifacts/{artifact_id}/preview"
            if self._build_preview(source, artifact_id) is not None
            else None
        )

    def register(
        self,
        path: str | Path,
        *,
        run_id: str,
        kind: str,
        classification_level: str,
        quality_status: QualityStatus = "pending",
        renderer_version: str = "unknown",
        schema_version: str = "1",
        evidence_ids: list[str] | None = None,
        source_ir_hash: str | None = None,
        quality_report_id: str | None = None,
        quality_issues: list[str] | None = None,
        degraded: bool = False,
        fallback_renderer: str | None = None,
    ) -> ArtifactManifest:
        source = self._safe_source(path)
        digest = self._sha256(source)
        artifact_id = "artifact-" + hashlib.sha256(
            f"{run_id}:{kind}:{digest}".encode("utf-8")
        ).hexdigest()[:32]
        sidecar_path = self.manifest_root / f"{artifact_id}.json"
        if sidecar_path.exists():
            return self._read_sidecar(sidecar_path)[0]

        object_id: str | None = None
        if self.object_store is not None:
            stored = self.object_store.put_file(
                source,
                kind=f"artifact:{kind}",
                media_type="application/octet-stream",
                classification_level=classification_level,
                run_id=run_id,
                retention_class="artifact",
            )
            source = stored.path
            object_id = stored.object_id

        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            run_id=run_id,
            kind=kind,
            name=source.name,
            uri=f"/artifacts/{artifact_id}/download",
            preview_uri=self._preview_uri(artifact_id, source),
            sha256=digest,
            size_bytes=source.stat().st_size,
            classification_level=classification_level,
            quality_status=quality_status,
            quality_report_id=quality_report_id,
            quality_issues=list(quality_issues or []),
            degraded=degraded,
            fallback_renderer=fallback_renderer,
            source_ir_hash=source_ir_hash,
            renderer_version=renderer_version,
            schema_version=schema_version,
            evidence_ids=evidence_ids or [],
        )
        sidecar_path.write_text(
            json.dumps(
                {
                    "manifest": manifest.model_dump(mode="json"),
                    "source_path": str(source),
                    "object_id": object_id,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return manifest

    def register_checked(
        self,
        path: str | Path,
        *,
        run_id: str,
        kind: str,
        artifact_kind: str,
        renderer_id: str,
        classification_level: str,
        schema_version: str = "1",
        evidence_ids: list[str] | None = None,
        source_ir_hash: str | None = None,
        required_text: tuple[str, ...] = (),
    ) -> CheckedArtifact:
        """Resolve a renderer, run its integrity gate, save the QA report, and register.

        This is the common post-render process. A failed gate still registers
        the candidate for diagnostics, but its manifest is marked failed and
        cannot be treated as a deliverable.
        """

        from pipelines.common.renderers import default_renderer_registry

        registry = default_renderer_registry()
        selection = registry.resolve(renderer_id, artifact_kind, "inspect")
        report = registry.inspect(selection.selected_renderer_id, path, required_text=required_text)
        quality_report_id = "quality-" + hashlib.sha256(
            f"{run_id}:{kind}:{selection.renderer_version}:{source_ir_hash or Path(path).name}".encode("utf-8")
        ).hexdigest()[:24]
        report_path = self.quality_report_root / f"{quality_report_id}.json"
        report_path.write_text(
            json.dumps(
                {"quality_report_id": quality_report_id, "report": report.model_dump(mode="json")},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        manifest = self.register(
            path,
            run_id=run_id,
            kind=kind,
            classification_level=classification_level,
            quality_status="passed" if report.approved else "failed",
            renderer_version=selection.renderer_version,
            schema_version=schema_version,
            evidence_ids=evidence_ids,
            source_ir_hash=source_ir_hash,
            quality_report_id=quality_report_id,
            quality_issues=report.issues,
            degraded=selection.degraded,
            fallback_renderer=selection.selected_renderer_id if selection.degraded else None,
        )
        return CheckedArtifact(
            manifest=manifest,
            quality_report_id=quality_report_id,
            renderer_version=selection.renderer_version,
            degraded=selection.degraded,
            quality_issues=tuple(report.issues),
        )

    def _read_sidecar(self, path: Path) -> tuple[ArtifactManifest, Path]:
        if not path.is_file():
            raise ArtifactNotFound(str(path))
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        manifest = ArtifactManifest.model_validate(payload["manifest"])
        try:
            source = self._safe_source(payload["source_path"])
        except (ArtifactNotFound, PermissionError):
            object_id = payload.get("object_id")
            if not object_id or self.object_store is None:
                raise
            source = self.object_store.get(
                str(object_id), access_level="TOP SECRET", include_path=True
            ).path
        if self._sha256(source) != manifest.sha256:
            raise ValueError("artifact checksum does not match its manifest")
        return manifest, source

    def get(self, artifact_id: str) -> tuple[ArtifactManifest, Path]:
        return self._read_sidecar(self.manifest_root / f"{artifact_id}.json")

    def preview(self, artifact_id: str) -> tuple[ArtifactManifest, Path]:
        """Return a verified preview path without exposing the source path."""

        manifest, source = self.get(artifact_id)
        if not manifest.preview_uri:
            raise ArtifactPreviewUnavailable(artifact_id)
        preview = self._build_preview(source, manifest.artifact_id)
        if preview is None or not preview.is_file():
            raise ArtifactPreviewUnavailable(artifact_id)
        return manifest, preview
