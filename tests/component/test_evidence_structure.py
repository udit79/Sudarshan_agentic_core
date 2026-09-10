import pytest

from ingestion_pipelines.contracts import EvidenceBlock, EvidenceLocation
from ingestion_pipelines.structure import compile_evidence_structure


SOURCE_HASH = "sha256:" + "c" * 64


def _block(
    evidence_id: str,
    *,
    parent_id: str | None = None,
    start: float | None = None,
    metadata: dict[str, object] | None = None,
):
    return EvidenceBlock(
        evidence_id=evidence_id,
        document_id="doc-structure",
        parent_id=parent_id,
        modality="audio_transcript" if start is not None else "video_scene",
        content=evidence_id,
        location=EvidenceLocation(start_seconds=start, end_seconds=start),
        confidence=0.9,
        source_hash=SOURCE_HASH,
        extractor_version="test@1",
        provenance={"source": "test"},
        metadata=metadata or {},
    )


def test_structure_compiler_builds_parent_temporal_graph_and_complete_chunks():
    scene = _block("scene-1")
    first = _block("audio-1", parent_id="scene-1", start=1.0)
    second = _block("audio-2", parent_id="scene-1", start=2.0)

    compilation = compile_evidence_structure([scene, first, second], max_chunk_chars=128)

    assert compilation.source_map_complete is True
    assert {relation.relation_type for relation in compilation.relationships} == {
        "contains",
        "temporal_next",
    }
    assert len(compilation.chunks) == 1
    assert compilation.chunks[0].evidence_ids == ["scene-1", "audio-1", "audio-2"]
    assert compilation.chunks[0].estimated_tokens > 0


def test_structure_compiler_rejects_orphan_parent():
    with pytest.raises(ValueError, match="missing parent"):
        compile_evidence_structure([_block("child", parent_id="missing")])


def test_structure_compiler_keeps_nested_evidence_and_explicit_references():
    scene = _block("scene-1")
    diagram = _block("diagram-1", parent_id="scene-1")
    label = _block(
        "label-1",
        parent_id="diagram-1",
        metadata={"related_evidence_ids": ["scene-1"]},
    )

    compilation = compile_evidence_structure([scene, diagram, label], max_chunk_chars=128)

    assert compilation.source_map_complete is True
    assert {relation.relation_type for relation in compilation.relationships} == {
        "contains",
        "references",
    }
    assert compilation.chunks[0].evidence_ids == ["scene-1", "diagram-1", "label-1"]
