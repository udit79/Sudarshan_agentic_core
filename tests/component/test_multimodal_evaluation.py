from ingestion_pipelines import (
    BenchmarkCase,
    BenchmarkSignals,
    EvidenceBlock,
    EvidenceIndex,
    EvidenceLocation,
    IngestedDocument,
    PromotionThresholds,
    run_multimodal_benchmark,
)
from memory import AccessContext


def _document(document_id: str, source_hash: str, blocks: list[EvidenceBlock]) -> IngestedDocument:
    return IngestedDocument.create(
        source_path=f"fixtures/{document_id}",
        raw_text="\n".join(block.content or "" for block in blocks),
        doc_type="synthetic",
        user_id="operator-1",
        case_id="case-1",
        task_id="task-1",
        document_id=document_id,
        evidence_blocks=blocks,
    )


def _block(
    document_id: str,
    evidence_id: str,
    source_hash: str,
    modality: str,
    content: str,
    *,
    page: int | None = None,
    slide: int | None = None,
    start_seconds: float | None = None,
    bbox: list[float] | None = None,
    metadata: dict | None = None,
) -> EvidenceBlock:
    return EvidenceBlock(
        evidence_id=evidence_id,
        document_id=document_id,
        modality=modality,
        content=content,
        location=EvidenceLocation(page=page, slide=slide, start_seconds=start_seconds, bbox=bbox),
        confidence=0.98,
        source_hash=source_hash,
        extractor_version="benchmark-fixture@1.0.0",
        provenance={"fixture": True},
        metadata=metadata or {},
    )


def _corpus() -> tuple[list[IngestedDocument], list[BenchmarkCase]]:
    pdf_hash = "sha256:" + "1" * 64
    ppt_hash = "sha256:" + "2" * 64
    infographic_hash = "sha256:" + "3" * 64
    video_hash = "sha256:" + "4" * 64
    documents = [
        _document(
            "pdf-brief",
            pdf_hash,
            [
                _block("pdf-brief", "pdf-page-1", pdf_hash, "pdf_page", "Scanned operational readiness brief.", page=1),
                _block(
                    "pdf-brief",
                    "pdf-table-1",
                    pdf_hash,
                    "pdf_table",
                    "Failure rate is 12 percent after the second inspection.",
                    page=2,
                ),
            ],
        ),
        _document(
            "ppt-deck",
            ppt_hash,
            [_block("ppt-deck", "slide-3", ppt_hash, "pptx_slide", "Air surveillance architecture and decision points.", slide=3)],
        ),
        _document(
            "infographic",
            infographic_hash,
            [_block("infographic", "visual-1", infographic_hash, "image_ocr", "Radar coverage expands along the northern corridor.", bbox=[0.1, 0.2, 0.8, 0.7])],
        ),
        _document(
            "long-video",
            video_hash,
            [
                _block("long-video", "scene-12", video_hash, "video_scene", "Interdiction sequence begins near the checkpoint.", start_seconds=720.0),
                _block(
                    "long-video",
                    "transcript-12",
                    video_hash,
                    "audio_transcript",
                    "The patrol confirms the interdiction sequence and records the handoff.",
                    start_seconds=724.0,
                    metadata={"fallback": "audio-only"},
                ),
            ],
        ),
    ]
    cases = [
        BenchmarkCase("table-query", "failure rate", "pdf-brief", ("pdf-table-1",), modalities=("pdf_table",)),
        BenchmarkCase("slide-query", "surveillance architecture", "ppt-deck", ("slide-3",), modalities=("pptx_slide",)),
        BenchmarkCase("visual-query", "radar coverage", "infographic", ("visual-1",), modalities=("image_ocr",)),
        BenchmarkCase("video-query", "interdiction sequence", "long-video", ("transcript-12",), modalities=("audio_transcript",)),
    ]
    return documents, cases


def test_multimodal_benchmark_compares_flat_text_and_typed_evidence(tmp_path):
    documents, cases = _corpus()
    index = EvidenceIndex(tmp_path / "evidence.db")
    for document in documents:
        index.index_document(document)

    report = run_multimodal_benchmark(
        index,
        documents,
        cases,
        AccessContext(user_id="operator-1", case_id="case-1", task_id="task-1"),
        signals={case.case_id: BenchmarkSignals(estimated_tokens=20, cache_hits=1) for case in cases},
        thresholds=PromotionThresholds(max_p95_latency_multiplier=250.0),
    )

    assert report.baseline.document_recall_at_k == 1.0
    assert report.baseline.retrieval_recall_at_k == 0.0
    assert report.typed_evidence.retrieval_recall_at_k == 1.0
    assert report.typed_evidence.evidence_faithfulness == 1.0
    assert report.typed_evidence.cache_hit_rate == 1.0
    assert report.promotion.passed is True
    assert report.to_dict()["typed_evidence"]["query_count"] == 4


def test_promotion_gate_rejects_incomplete_evidence_and_repairs(tmp_path):
    documents, cases = _corpus()
    index = EvidenceIndex(tmp_path / "evidence.db")
    for document in documents:
        index.index_document(document)
    cases = [
        BenchmarkCase(
            "partial-video",
            "interdiction sequence",
            "long-video",
            ("transcript-12",),
            expected_evidence_count=3,
            modalities=("audio_transcript",),
        )
    ]

    report = run_multimodal_benchmark(
        index,
        documents,
        cases,
        AccessContext(user_id="operator-1", case_id="case-1", task_id="task-1"),
        signals={"partial-video": BenchmarkSignals(repairs=1)},
        thresholds=PromotionThresholds(max_p95_latency_multiplier=100.0),
    )

    assert report.promotion.passed is False
    assert "extraction coverage" in " ".join(report.promotion.reasons)
    assert "repair rate" in " ".join(report.promotion.reasons)
