from injestion.models import IngestedDocument
from injestion.extract import extract_text_from_txt

def ingest_text_file(file_path: str, user_id=None, case_id=None) -> IngestedDocument:
    raw_text = extract_text_from_txt(file_path)
    return IngestedDocument.create(
        source_path=file_path,
        raw_text=raw_text,
        doc_type="text",
        user_id=user_id,
        case_id=case_id,
    )