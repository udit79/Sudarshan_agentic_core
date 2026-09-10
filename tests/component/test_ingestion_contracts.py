from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ingestion_pipelines import (
    EvidenceBlock,
    EvidenceLocation,
    ExtractionEvent,
    IngestionManifest,
    IngestionQualityReport,
)


FIXTURES = Path(__file__).resolve().parents[1] / "contracts"


def test_ingestion_contract_fixtures_validate() -> None:
    manifest = IngestionManifest.model_validate(
        json.loads((FIXTURES / "ingestion-manifest.json").read_text(encoding="utf-8"))
    )
    payload = json.loads(
        (FIXTURES / "ingestion-event-and-quality.json").read_text(encoding="utf-8")
    )
    event = ExtractionEvent.model_validate(payload["event"])
    quality = IngestionQualityReport.model_validate(payload["quality"])
    evidence = EvidenceBlock.model_validate(
        json.loads((FIXTURES / "evidence-block.json").read_text(encoding="utf-8"))
    )

    assert manifest.status == "accepted"
    assert event.evidence_ids == ["page-1"]
    assert quality.status == "partial"
    assert evidence.location.slide == 4
    assert evidence.provenance["parser_step"] == "table-extraction"


def test_ingestion_status_fixture_covers_terminal_and_processing_states() -> None:
    statuses = json.loads(
        (FIXTURES / "ingestion-statuses.json").read_text(encoding="utf-8")
    )
    for status in statuses:
        manifest = IngestionManifest(
            ingestion_id=f"ing-{status}",
            document_id="doc-1",
            source_reference="source.bin",
            source_hash="sha256:" + "b" * 64,
            media_type="application/octet-stream",
            modality="binary",
            classification_level="RESTRICTED",
            extractor_version="test@1",
            model_policy="local-first",
            configuration_hash="config-1",
            status=status,
        )
        assert manifest.status == status


def test_ingestion_contracts_reject_unknown_fields_and_invalid_provenance() -> None:
    manifest = json.loads(
        (FIXTURES / "ingestion-manifest.json").read_text(encoding="utf-8")
    )
    with pytest.raises(ValidationError):
        IngestionManifest(**manifest, unexpected="reject-me")

    with pytest.raises(ValidationError):
        EvidenceBlock(
            evidence_id="empty",
            document_id="doc-1",
            modality="text",
            confidence=0.5,
            source_hash="sha256:" + "a" * 64,
            extractor_version="test@1",
        )


def test_evidence_location_rejects_invalid_geometry_and_time() -> None:
    with pytest.raises(ValidationError):
        EvidenceLocation(bbox=[0.1, 0.2, 1.2, 0.8])
    with pytest.raises(ValidationError):
        EvidenceLocation(start_seconds=5, end_seconds=2)
