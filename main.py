from injestion.ingest import ingest_file

doc = ingest_file("sample_data/dsaqueue.pdf", user_id="udit", case_id="sih-demo-case-1")
print(doc)