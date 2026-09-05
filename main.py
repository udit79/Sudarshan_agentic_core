from ingestion_pipelines import ingest_file, to_knowledge_unit

# Test with any image path (.png, .jpg, .jpeg, .tiff, etc.)
image_path = "sample_data/test_dum.jpg"

doc = ingest_file(image_path, user_id="udit", case_id="sih-demo-case-1")
unit = to_knowledge_unit(doc)

print("=== [1] INGESTED DOCUMENT OBJECT ===")
print(doc)

print("\n=== [2] KNOWLEDGE UNIT (MEMORY COMPATIBLE) ===")
print(unit)

print("\n=== [3] VERIFICATION SUMMARY ===")
print(f"Doc Type         : {doc.doc_type}")
print(f"Source Type      : {unit.source.source_type}")
print(f"Extracted Text   : {doc.raw_text.strip()!r}")
print(f"Source Reference : {unit.source.source_reference}")
