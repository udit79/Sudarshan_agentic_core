"""Generate a deterministic, source-grounded PPT artifact without an LLM.

This is an operator-facing Phase 11 verification tool, not a replacement for
the provider-backed presentation pipeline. It proves the backend path from a
real local file and prompt through ingestion, evidence indexing, deterministic
rendering, quality inspection, and manifest registration while provider
credentials are disabled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

# Support both ``python -m scripts.run_phase11_offline_artifact`` and the
# beginner-friendly ``python scripts\\run_phase11_offline_artifact.py`` form.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from api.artifacts import ArtifactStore
from ingestion_pipelines import EvidenceIndex, ingest_file
from pipelines.common.renderers import default_renderer_registry
from pipelines.orchestrator.contracts import RequestConstraints
from pipelines.ppt.presentation_quality import inspect_presentation
from pipelines.ppt.renderer import render_presentation
from pipelines.ppt.schemas import PresentationOutput, SlideContent, resolve_presentation_theme


def _bounded_lines(text: str, *, limit: int = 5) -> list[str]:
    """Keep readable, non-empty source lines without inventing content."""

    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    return lines[:limit] or ["No extractable text was found."]


def build_offline_artifact(
    source_path: str | Path,
    operator_request: str,
    *,
    output_root: str | Path = "artifacts/phase11-offline",
    user_id: str,
    case_id: str,
    task_id: str,
    source_reference: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Ingest a local file and register a deterministic presentation artifact."""

    source = Path(source_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(str(source))
    if not operator_request.strip():
        raise ValueError("operator_request must be non-empty")
    if not all(value.strip() for value in (user_id, case_id, task_id)):
        raise ValueError("user_id, case_id, and task_id are required")

    artifact_root = Path(output_root).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    resolved_run_id = run_id or f"offline-g01-{uuid4().hex[:12]}"
    reference = source_reference or source.name

    document = ingest_file(
        str(source),
        user_id=user_id,
        case_id=case_id,
        task_id=task_id,
        source_reference=reference,
    )
    if not document.evidence_blocks:
        raise ValueError("ingestion produced no evidence blocks")

    evidence_index = EvidenceIndex(artifact_root / ".state" / "evidence_index.db")
    indexed = evidence_index.index_document(document, classification_level="RESTRICTED")
    evidence_ids = [block.evidence_id for block in document.evidence_blocks]

    slides = [
        SlideContent(
            slide_id="cover",
            order=1,
            title="Offline source-grounded briefing",
            bullets=[reference, "Deterministic backend verification"],
            speaker_notes=operator_request,
            layout="cover",
        ),
        SlideContent(
            slide_id="request",
            order=2,
            title="Operator request",
            bullets=[operator_request, "Pipeline: presentation"],
            speaker_notes="The user request is preserved as a request input, not treated as evidence.",
            layout="content",
        ),
        SlideContent(
            slide_id="evidence",
            order=3,
            title="Ingested evidence",
            bullets=_bounded_lines(document.raw_text),
            speaker_notes=f"Source reference: {reference}",
            layout="content",
        ),
        SlideContent(
            slide_id="provenance",
            order=4,
            title="Scope and provenance",
            bullets=[
                f"User: {user_id}",
                f"Case: {case_id}",
                f"Task: {task_id}",
                f"Evidence blocks: {len(document.evidence_blocks)}",
                f"Document: {document.id}",
            ],
            speaker_notes="Ownership is recorded in the manifest; no provider call was made.",
            layout="closing",
        ),
    ]
    output = PresentationOutput(
        presentation_id=resolved_run_id,
        title=f"Source-grounded briefing — {reference}",
        classification_level="RESTRICTED",
        distribution="Authorized NTRO personnel",
        slides=slides,
    )
    constraints = RequestConstraints(slide_count=len(slides), theme_id="ntro-briefing")
    source_ir_hash = hashlib.sha256(
        json.dumps(
            {"request": operator_request, "output": output.model_dump(mode="json")},
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    original_cwd = Path.cwd()
    try:
        # The native renderer writes relative to the current working directory.
        # Keep the generated candidate inside the requested controlled root.
        os.chdir(artifact_root)
        rendered = render_presentation(
            output,
            theme=resolve_presentation_theme(constraints),
        )
        quality = inspect_presentation(
            output,
            rendered_artifacts=[rendered.path],
            constraints=constraints,
        )
        if not quality.approved:
            raise RuntimeError(
                "offline presentation quality gate failed: "
                + "; ".join(issue.message for issue in quality.issues)
            )

        store = ArtifactStore(artifact_root, evidence_scope_verifier=evidence_index)
        checked = store.register_checked(
            rendered.path,
            run_id=resolved_run_id,
            kind="presentation",
            artifact_kind="pptx",
            renderer_id="presentation.pptx",
            classification_level="RESTRICTED",
            user_id=user_id,
            case_id=case_id,
            task_id=task_id,
            schema_version="offline-presentation@1",
            evidence_ids=evidence_ids,
            source_ir_hash=source_ir_hash,
            # The quality gate checks visible slide text.  ``output.title`` is
            # manifest metadata; the cover title and source reference are the
            # actual rendered identifiers.
            required_text=(slides[0].title, reference),
        )
        manifest = checked.manifest.model_dump(mode="json")
    finally:
        os.chdir(original_cwd)

    return {
        "status": "succeeded",
        "mode": "offline_deterministic_preview",
        "provider_called": False,
        "memory_backend_called": False,
        "run_id": resolved_run_id,
        "request": operator_request,
        "ingestion": {
            "document_id": document.id,
            "source_reference": reference,
            "source_hash": document.evidence_blocks[0].source_hash,
            "evidence_count": len(document.evidence_blocks),
            "indexed": bool(indexed.get("indexed")),
        },
        "artifact": manifest,
        "quality": {
            "approved": quality.approved,
            "slide_count": quality.slide_count,
            "issues": [issue.message for issue in quality.issues],
        },
        "renderer": default_renderer_registry().get("presentation.pptx").version,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_path")
    parser.add_argument("operator_request")
    parser.add_argument("--output-root", default="artifacts/phase11-offline")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--source-reference")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    result = build_offline_artifact(
        args.source_path,
        args.operator_request,
        output_root=args.output_root,
        user_id=args.user_id,
        case_id=args.case_id,
        task_id=args.task_id,
        source_reference=args.source_reference,
        run_id=args.run_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
