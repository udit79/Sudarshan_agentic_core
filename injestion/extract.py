from pathlib import Path

SUPPORTED_EXTENSIONS = {".txt", ".pdf"}

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
    """WHERE this is called from ingest.py.
    Validates, then dispatches to the right extractor.
    Returns (raw_text, doc_type).
    """
    kind = validate_source(file_path)
    if kind == "txt":
        return extract_text_from_txt(file_path), "text"
    if kind == "pdf":
        return extract_text_from_pdf(file_path), "pdf"