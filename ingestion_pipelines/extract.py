from __future__ import annotations

from pathlib import Path

TEXT_EXTENSIONS = {".txt"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}

SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS | IMAGE_EXTENSIONS


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


def extract_text(file_path: str) -> tuple[str, str]:
    """Validates, then dispatches to the right extractor.
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
        from ingestion_pipelines.extract_image import extract_text_from_image_gemini
        return extract_text_from_image_gemini(file_path), "image"

    raise ValueError(f"Unhandled file extension: {ext}")