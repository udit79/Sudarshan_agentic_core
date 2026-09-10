"""Deterministic structure and chunk compilation for typed evidence."""

from __future__ import annotations

import hashlib
from collections import defaultdict

from ingestion_pipelines.contracts import (
    EvidenceBlock,
    EvidenceChunk,
    EvidenceCompilation,
    EvidenceRelationship,
)

STRUCTURE_COMPILER_VERSION = "evidence-structure@1.0.0"


def _stable_id(prefix: str, *parts: str) -> str:
    value = "|".join(parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(value).hexdigest()[:20]}"


def _location_key(block: EvidenceBlock) -> tuple[float, float, str]:
    location = block.location
    page_or_slide = float(location.page or location.slide or 0)
    timestamp = float(location.start_seconds or 0.0)
    return page_or_slide, timestamp, block.evidence_id


def _heading_path(block: EvidenceBlock) -> list[str]:
    configured = block.metadata.get("heading_path")
    if isinstance(configured, list) and all(isinstance(item, str) for item in configured):
        return list(configured)
    location = block.location
    if location.page is not None:
        return [f"Page {location.page}"]
    if location.slide is not None:
        return [f"Slide {location.slide}"]
    if location.start_seconds is not None:
        return [block.modality.replace("_", " ").title()]
    return [block.modality.replace("_", " ").title()]


def compile_evidence_structure(
    blocks: list[EvidenceBlock],
    *,
    max_chunk_chars: int = 2400,
) -> EvidenceCompilation:
    """Build parent/temporal edges and source-mapped retrieval chunks.

    This stage is intentionally deterministic. It does not infer facts or
    relationships with an LLM; model-based enrichment can be added later as a
    bounded, provenance-bearing plugin.
    """

    if max_chunk_chars < 128:
        raise ValueError("max_chunk_chars must be at least 128")
    if not blocks:
        raise ValueError("at least one evidence block is required")

    document_id = blocks[0].document_id
    source_hash = blocks[0].source_hash
    if any(block.document_id != document_id for block in blocks):
        raise ValueError("all evidence blocks must belong to one document")
    if any(block.source_hash != source_hash for block in blocks):
        raise ValueError("all evidence blocks must share one source hash")

    by_id = {block.evidence_id: block for block in blocks}
    if len(by_id) != len(blocks):
        raise ValueError("evidence IDs must be unique")

    relationships: list[EvidenceRelationship] = []
    relationship_keys: set[tuple[str, str, str]] = set()

    def add_relationship(
        source_id: str,
        target_id: str,
        relation_type: str,
        confidence: float,
        parser_step: str,
    ) -> None:
        key = (source_id, target_id, relation_type)
        if key in relationship_keys:
            return
        relationship_keys.add(key)
        relationships.append(
            EvidenceRelationship(
                relation_id=_stable_id(
                    "rel", document_id, source_id, target_id, relation_type
                ),
                document_id=document_id,
                source_evidence_id=source_id,
                target_evidence_id=target_id,
                relation_type=relation_type,
                confidence=confidence,
                provenance={
                    "compiler": STRUCTURE_COMPILER_VERSION,
                    "parser_step": parser_step,
                },
            )
        )

    for block in blocks:
        if block.parent_id:
            if block.parent_id not in by_id:
                raise ValueError(f"missing parent evidence block: {block.parent_id}")
            add_relationship(
                block.parent_id,
                block.evidence_id,
                "contains",
                1.0,
                "explicit-parent",
            )

        related_ids = block.metadata.get("related_evidence_ids")
        if isinstance(related_ids, list):
            for related_id in related_ids:
                target_id = str(related_id).strip()
                if not target_id:
                    continue
                if target_id not in by_id:
                    raise ValueError(f"missing referenced evidence block: {target_id}")
                if target_id != block.evidence_id:
                    add_relationship(
                        block.evidence_id,
                        target_id,
                        "references",
                        0.8,
                        "explicit-evidence-reference",
                    )

    temporal_blocks = [
        block
        for block in blocks
        if block.location.start_seconds is not None and block.modality != "video_scene"
    ]
    temporal_blocks.sort(key=_location_key)
    for previous, current in zip(temporal_blocks, temporal_blocks[1:]):
        if previous.parent_id != current.parent_id:
            continue
        add_relationship(
            previous.evidence_id,
            current.evidence_id,
            "temporal_next",
            1.0,
            "timestamp-order",
        )

    page_or_slide_blocks = [
        block
        for block in blocks
        if block.location.page is not None or block.location.slide is not None
    ]
    page_or_slide_blocks.sort(key=_location_key)
    for previous, current in zip(page_or_slide_blocks, page_or_slide_blocks[1:]):
        if previous.modality != current.modality:
            continue
        add_relationship(
            previous.evidence_id,
            current.evidence_id,
            "sequence_next",
            1.0,
            "page-slide-order",
        )

    children: dict[str, list[EvidenceBlock]] = defaultdict(list)
    roots: list[EvidenceBlock] = []
    for block in sorted(blocks, key=_location_key):
        if block.parent_id:
            children[block.parent_id].append(block)
        else:
            roots.append(block)

    chunks: list[EvidenceChunk] = []
    chunk_index = 0
    def descendants(root: EvidenceBlock) -> list[EvidenceBlock]:
        result = [root]
        for child in sorted(children.get(root.evidence_id, []), key=_location_key):
            result.extend(descendants(child))
        return result

    for root in roots:
        group = descendants(root)
        current_blocks: list[EvidenceBlock] = []
        current_length = 0
        root_chunk_id: str | None = None
        for block in group:
            rendered = f"[{block.modality}] {block.content.strip()}"
            separator = 1 if current_blocks else 0
            if current_blocks and current_length + separator + len(rendered) > max_chunk_chars:
                chunk = _make_chunk(
                    document_id=document_id,
                    source_hash=source_hash,
                    blocks=current_blocks,
                    chunk_index=chunk_index,
                    parent_chunk_id=root_chunk_id,
                )
                chunks.append(chunk)
                root_chunk_id = root_chunk_id or chunk.chunk_id
                chunk_index += 1
                current_blocks = []
                current_length = 0
                separator = 0
            current_blocks.append(block)
            current_length += separator + len(rendered)
        if current_blocks:
            chunks.append(
                _make_chunk(
                    document_id=document_id,
                    source_hash=source_hash,
                    blocks=current_blocks,
                    chunk_index=chunk_index,
                    parent_chunk_id=root_chunk_id,
                )
            )
            chunk_index += 1

    mapped_ids = [evidence_id for chunk in chunks for evidence_id in chunk.evidence_ids]
    source_map_complete = sorted(mapped_ids) == sorted(by_id)
    return EvidenceCompilation(
        document_id=document_id,
        relationships=relationships,
        chunks=chunks,
        source_map_complete=source_map_complete,
    )


def _make_chunk(
    *,
    document_id: str,
    source_hash: str,
    blocks: list[EvidenceBlock],
    chunk_index: int,
    parent_chunk_id: str | None,
) -> EvidenceChunk:
    content = "\n".join(f"[{block.modality}] {block.content.strip()}" for block in blocks)
    evidence_ids = [block.evidence_id for block in blocks]
    chunk_id = _stable_id("chunk", document_id, str(chunk_index), *evidence_ids)
    return EvidenceChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        content=content,
        evidence_ids=evidence_ids,
        parent_chunk_id=parent_chunk_id,
        heading_path=_heading_path(blocks[0]),
        source_hash=source_hash,
        chunk_index=chunk_index,
        estimated_tokens=max(1, (len(content) + 3) // 4),
    )


__all__ = ["STRUCTURE_COMPILER_VERSION", "compile_evidence_structure"]
