from injestion.models import IngestedDocument
from injestion.extract import extract_text

def ingest_file(file_path: str, user_id=None, case_id=None) -> IngestedDocument:
    raw_text, doc_type = extract_text(file_path)
    return IngestedDocument.create(
        source_path=file_path,
        raw_text=raw_text,
        doc_type=doc_type,
        user_id=user_id,
        case_id=case_id,
    )