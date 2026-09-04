from injestion.ingest import ingest_file
from injestion.adapter import to_knowledge_unit
doc = ingest_file("sample_data/dsaqueue.pdf", user_id="udit", case_id="sih-demo-case-1")
unit = to_knowledge_unit(doc)
print(unit)
print(doc)