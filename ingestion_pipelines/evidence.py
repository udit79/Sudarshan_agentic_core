"""Deterministic adapters from legacy extractor text to typed evidence.

The existing modality extractors remain responsible for parsing and OCR. This
module gives their structured delimiters a common evidence boundary without
making the Harness or a model re-parse source content.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ingestion_pipelines.contracts import EvidenceBlock, EvidenceLocation

EVIDENCE_ADAPTER_VERSION = "legacy-delimiter-adapter@1.0.0"
_PAGE_RE = re.compile(r"(?:^|\n)--- Page (\d+)(?:[^-]*) ---\n?(.*?)(?=\n--- Page \d+|\Z)", re.S)
_SLIDE_RE = re.compile(r"(?:^|\n)--- Slide (\d+) ---\n?(.*?)(?=\n--- Slide \d+|\Z)", re.S)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _evidence_id(source_hash: str, modality: str, index: int) -> str:
    digest = hashlib.sha256(
        f"{source_hash}|{modality}|{index}".encode("utf-8")
    ).hexdigest()[:20]
    return f"{modality}-{digest}"


def _block(
    *,
    source_hash: str,
    document_id: str,
    source_reference: str,
    modality: str,
    index: int,
    content: str,
    location: EvidenceLocation | None = None,
    confidence: float = 0.85,
    metadata: dict[str, object] | None = None,
) -> EvidenceBlock:
    return EvidenceBlock(
        evidence_id=_evidence_id(source_hash, modality, index),
        document_id=document_id,
        modality=modality,
        content=content.strip(),
        location=location or EvidenceLocation(),
        confidence=confidence,
        source_hash=source_hash,
        extractor_version=EVIDENCE_ADAPTER_VERSION,
        provenance={
            "source_reference": source_reference,
            "parser_step": "legacy-delimiter-adapter",
        },
        metadata=metadata or {},
    )


def build_evidence_blocks(
    raw_text: str,
    *,
    doc_type: str,
    document_id: str,
    source_reference: str,
    source_hash: str,
) -> list[EvidenceBlock]:
    """Build typed evidence while preserving the existing extractor output."""

    text = str(raw_text or "").strip()
    if not text:
        return []

    normalized_type = str(doc_type).strip().lower()
    if normalized_type == "pdf":
        matches = list(_PAGE_RE.finditer(text))
        if matches:
            blocks: list[EvidenceBlock] = []
            for index, match in enumerate(matches):
                page_number = int(match.group(1))
                content = match.group(2).strip() or "(Empty Page)"
                ocr_page = "[Scanned OCR]" in match.group(0) or "[OCR Failed]" in match.group(0)
                blocks.append(
                    _block(
                        source_hash=source_hash,
                        document_id=document_id,
                        source_reference=source_reference,
                        modality="pdf_page",
                        index=index,
                        content=content,
                        location=EvidenceLocation(page=page_number),
                        confidence=0.65 if ocr_page else 0.95,
                        metadata={
                            "page": page_number,
                            "ocr_fallback": ocr_page,
                            "fallback_reason": "ocr_unavailable_or_failed" if ocr_page else None,
                        },
                    )
                )
            return blocks

    if normalized_type == "pptx":
        matches = list(_SLIDE_RE.finditer(text))
        if matches:
            blocks = []
            for index, match in enumerate(matches):
                slide_number = int(match.group(1))
                content = match.group(2).strip() or "(Empty Slide)"
                blocks.append(
                    _block(
                        source_hash=source_hash,
                        document_id=document_id,
                        source_reference=source_reference,
                        modality="pptx_slide",
                        index=index,
                        content=content,
                        location=EvidenceLocation(slide=slide_number),
                        confidence=0.95,
                        metadata={"slide": slide_number},
                    )
                )
            return blocks

    modality = {
        "text": "text_document",
        "image": "image_ocr",
    }.get(normalized_type, f"{normalized_type}_document")
    return [
        _block(
            source_hash=source_hash,
            document_id=document_id,
            source_reference=source_reference,
            modality=modality,
            index=0,
            content=text,
            confidence=0.8 if normalized_type == "image" else 0.95,
            metadata={
                "legacy_extractor": True,
                "ocr_fallback": normalized_type == "image" and "OCR unavailable" in text,
                "fallback_reason": "vision_provider_unavailable" if normalized_type == "image" and "OCR unavailable" in text else None,
            },
        )
    ]


def build_evidence_from_file(
    raw_text: str,
    *,
    file_path: str,
    doc_type: str,
    document_id: str,
    source_reference: str,
) -> list[EvidenceBlock]:
    """Convenience wrapper that derives the immutable source hash locally."""

    return build_evidence_blocks(
        raw_text,
        doc_type=doc_type,
        document_id=document_id,
        source_reference=source_reference,
        source_hash=_sha256_file(Path(file_path)),
    )


__all__ = ["EVIDENCE_ADAPTER_VERSION", "build_evidence_blocks", "build_evidence_from_file"]
