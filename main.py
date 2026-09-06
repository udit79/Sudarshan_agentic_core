import sys
from pathlib import Path
from ingestion_pipelines import ingest_file, to_knowledge_unit


def run_ingestion_demo(
    file_path: str,
    user_id: str = "operator_001",
    case_id: str = "sih-case-26154",
) -> None:
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found at '{file_path}'")
        return

    print(f"--> Ingesting file: {file_path}")
    doc = ingest_file(str(path), user_id=user_id, case_id=case_id)
    unit = to_knowledge_unit(doc)

    print("\n=== [1] INGESTED DOCUMENT OBJECT ===")
    print(f"ID               : {doc.id}")
    print(f"Detected Type    : {doc.doc_type}")
    print(f"Ingested At      : {doc.ingested_at}")
    print(f"Tenant Context   : user='{doc.user_id}', case='{doc.case_id}', task='{doc.task_id}'")

    print("\n=== [2] KNOWLEDGE UNIT (MEMORY COMPATIBLE) ===")
    print(f"Unit ID          : {unit.unit_id}")
    print(f"Source Type      : {unit.source.source_type}")
    print(f"Source Reference : {unit.source.source_reference}")

    print("\n=== [3] EXTRACTED CONTENT ===")
    preview = doc.raw_text.strip()
    if len(preview) > 600:
        print(preview[:600] + f"\n... [truncated, total {len(preview)} characters]")
    else:
        print(preview)


if __name__ == "__main__":
    # You can pass any file path as an argument, or default to the test PPTX
    target_file = sys.argv[1] if len(sys.argv) > 1 else "sample_data/dummy_presentation.pptx"
    run_ingestion_demo(target_file)

