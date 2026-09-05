from __future__ import annotations

import os
from pathlib import Path
import shutil

TEXT_EXTENSIONS = {".txt"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}

SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS | IMAGE_EXTENSIONS


def _find_tesseract_binary() -> str | None:
    """Finds tesseract executable in PATH or standard install directories."""
    in_path = shutil.which("tesseract")
    if in_path:
        return in_path

    env_cmd = os.environ.get("TESSERACT_CMD")
    if env_cmd and Path(env_cmd).is_file():
        return env_cmd

    candidates = [
        Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Tesseract-OCR" / "tesseract.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "Tesseract-OCR" / "tesseract.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Tesseract-OCR" / "tesseract.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    return None


def validate_source(file_path: str) -> str:
    """Confirms the file exists and is a type we support.
    Returns the file extension (without the dot) as the raw type.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {file_path}")
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")
    return ext.lstrip(".")


def extract_text_from_txt(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def extract_text_from_pdf(file_path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(file_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text_from_image(file_path: str) -> str:
    """Extracts text from an image using pytesseract OCR."""
    from PIL import Image
    import pytesseract

    tesseract_path = _find_tesseract_binary()
    if tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = tesseract_path

    try:
        with Image.open(file_path) as image:
            return pytesseract.image_to_string(image)
    except (pytesseract.pytesseract.TesseractNotFoundError, FileNotFoundError) as err:
        raise RuntimeError(
            "Tesseract OCR engine was not found on the system. "
            "Please install Tesseract OCR (e.g. run 'winget install --id UB-Mannheim.TesseractOCR' "
            "in an administrator terminal) or set the TESSERACT_CMD environment variable."
        ) from err


def extract_text(file_path: str) -> tuple[str, str]:
    """WHERE this is called from ingest.py.
    Validates, then dispatches to the right extractor.
    Returns (raw_text, doc_type).
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    validate_source(file_path)

    if ext in TEXT_EXTENSIONS:
        return extract_text_from_txt(file_path), "text"
    if ext in PDF_EXTENSIONS:
        return extract_text_from_pdf(file_path), "pdf"
    if ext in IMAGE_EXTENSIONS:
        return extract_text_from_image(file_path), "image"

    raise ValueError(f"Unhandled file extension: {ext}")