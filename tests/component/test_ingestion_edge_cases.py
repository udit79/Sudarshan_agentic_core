"""Component regression tests for corrupted file handling, OS file locks, and error responses."""

import os
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from api.server import app
from ingestion_pipelines.extract_pdf import extract_text_from_pdf
from ingestion_pipelines.extract_pptx import extract_text_from_pptx
from ingestion_pipelines.extract_video import extract_text_from_video


@pytest.fixture
def client():
    return TestClient(app)


def test_corrupted_pdf_raises_value_error():
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"")  # Empty zero-byte file
        zero_pdf = f.name
    try:
        with pytest.raises(ValueError) as exc_info:
            extract_text_from_pdf(zero_pdf)
        assert "Corrupted or unreadable PDF file" in str(exc_info.value)
    finally:
        Path(zero_pdf).unlink(missing_ok=True)


def test_corrupted_pptx_raises_value_error():
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
        f.write(b"NOT_A_VALID_PPTX_ZIP_FILE")
        bad_pptx = f.name
    try:
        with pytest.raises(ValueError) as exc_info:
            extract_text_from_pptx(bad_pptx)
        assert "Corrupted or unreadable PowerPoint presentation" in str(exc_info.value)
    finally:
        Path(bad_pptx).unlink(missing_ok=True)


def test_corrupted_video_does_not_crash():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"GARBAGE_BYTES")
        bad_video = f.name
    try:
        # Must return clean fallback transcript, not crash or leak cv2 handle
        text = extract_text_from_video(bad_video)
        assert "VIDEO INTELLIGENCE TRANSCRIPT" in text
        assert "(No audible speech or on-screen text detected)" in text
    finally:
        Path(bad_video).unlink(missing_ok=True)


def test_pdf_extractor_closes_doc_and_prevents_file_lock():
    import fitz
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        test_pdf = f.name
    try:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 72), "Tactical surveillance test for Windows file handle closure.")
        doc.save(test_pdf)
        doc.close()

        # Extract
        extracted = extract_text_from_pdf(test_pdf)
        assert "Tactical surveillance test" in extracted

        # Immediate deletion must succeed without WinError 32
        Path(test_pdf).unlink()
        assert not os.path.exists(test_pdf)
    finally:
        Path(test_pdf).unlink(missing_ok=True)


def test_server_ingest_corrupted_file_returns_422_not_502(client):
    # Uploading a corrupt or unsupported payload should result in 415 or 422, never 502
    corrupt_content = b"Not a real PDF structure"
    response = client.post(
        "/ingest",
        headers={
            "X-Operator-Id": "operator-1",
            "X-Case-Id": "case-test-edge",
            "X-Classification-Level": "RESTRICTED",
        },
        files={"file": ("corrupt.pdf", corrupt_content, "application/pdf")},
    )
    # Magic bytes check rejects as 415 or parser rejects as 422
    assert response.status_code in (415, 422)
    assert response.status_code != 502
    assert "error" in response.json() or "detail" in response.json()

