from ingestion_pipelines.evidence import build_evidence_blocks


SOURCE_HASH = "sha256:" + "b" * 64


def test_pdf_and_pptx_delimiters_preserve_source_locations():
    pdf = build_evidence_blocks(
        "--- Page 1 ---\nOpening facts\n\n--- Page 2 [Scanned OCR] ---\nHandwritten facts",
        doc_type="pdf",
        document_id="doc-1",
        source_reference="brief.pdf",
        source_hash=SOURCE_HASH,
    )
    pptx = build_evidence_blocks(
        "--- Slide 1 ---\nTitle\n\n--- Slide 2 ---\n[Speaker Notes]: Decision",
        doc_type="pptx",
        document_id="doc-2",
        source_reference="brief.pptx",
        source_hash=SOURCE_HASH,
    )

    assert [block.location.page for block in pdf] == [1, 2]
    assert pdf[0].confidence > pdf[1].confidence
    assert pdf[1].metadata["ocr_fallback"] is True
    assert [block.location.slide for block in pptx] == [1, 2]
    assert "Decision" in (pptx[1].content or "")


def test_text_and_image_adapters_return_one_retrievable_block():
    for doc_type, modality in (("text", "text_document"), ("image", "image_ocr")):
        blocks = build_evidence_blocks(
            "A verified observation.",
            doc_type=doc_type,
            document_id=f"doc-{doc_type}",
            source_reference=f"brief.{doc_type}",
            source_hash=SOURCE_HASH,
        )
        assert len(blocks) == 1
        assert blocks[0].modality == modality
        assert blocks[0].content == "A verified observation."
        assert blocks[0].provenance["parser_step"] == "legacy-delimiter-adapter"


def test_image_provider_marker_becomes_partial_evidence():
    blocks = build_evidence_blocks(
        "(Image OCR unavailable: OPENAI_API_KEY is not configured)",
        doc_type="image",
        document_id="doc-image-fallback",
        source_reference="brief.png",
        source_hash=SOURCE_HASH,
    )

    assert blocks[0].metadata["ocr_fallback"] is True
    assert blocks[0].metadata["fallback_reason"] == "vision_provider_unavailable"
