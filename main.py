from injestion.ingest import ingest_text_file

doc = ingest_text_file("sample_data/sample_text.txt", user_id="udit", case_id="sih-demo-case-1")
print(doc)