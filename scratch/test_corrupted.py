import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import pytest
from ingestion_pipelines.extract_pdf import extract_text_from_pdf
from ingestion_pipelines.extract_pptx import extract_text_from_pptx
from ingestion_pipelines.extract_video import extract_text_from_video

def test_corrupted_files():
    print("=== Testing Corrupted / Zero-byte / Malformed Files ===")
    
    # 1. Zero byte PDF
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        zero_pdf = f.name
    try:
        try:
            extract_text_from_pdf(zero_pdf)
        except Exception as e:
            print(f"[Corrupted PDF Result] Raised: {type(e).__name__}: {e}")
    finally:
        Path(zero_pdf).unlink(missing_ok=True)

    # 2. Garbage text in PPTX
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
        f.write(b"NOT A REAL PPTX FILE HEADER")
        garbage_pptx = f.name
    try:
        try:
            extract_text_from_pptx(garbage_pptx)
        except Exception as e:
            print(f"[Corrupted PPTX Result] Raised: {type(e).__name__}: {e}")
    finally:
        Path(garbage_pptx).unlink(missing_ok=True)

    # 3. Garbage text in MP4
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"NOT A REAL MP4 FILE HEADER")
        garbage_mp4 = f.name
    try:
        try:
            res = extract_text_from_video(garbage_mp4)
            print(f"[Corrupted Video Result] Returned safely: {res!r}")
        except Exception as e:
            print(f"[Corrupted Video Result] Raised: {type(e).__name__}: {e}")
    finally:
        Path(garbage_mp4).unlink(missing_ok=True)

if __name__ == "__main__":
    test_corrupted_files()
