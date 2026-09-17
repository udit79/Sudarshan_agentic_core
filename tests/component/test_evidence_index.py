from ingestion_pipelines import ingest_file
from ingestion_pipelines.evidence_index import EvidenceIndex, EvidenceNotFoundError
from memory import AccessContext, MemoryManager
from api.storage import LocalObjectStore


class _Backend:
    def __init__(self):
        self.writes = []

    def remember(self, **kwargs):
        self.writes.append(kwargs)
        return {"status": "accepted"}

    def recall(self, **kwargs):
        return []


def test_evidence_index_searches_by_scope_and_projects_bounded_memory(tmp_path):
    document = ingest_file(
        "sample_data/sample_text.txt",
        user_id="operator-1",
        case_id="case-1",
        task_id="task-1",
        source_reference="brief.txt",
    )
    index = EvidenceIndex(tmp_path / "evidence.db")
    receipt = index.index_document(document)

    assert receipt["indexed"] is True
    assert receipt["evidence_count"] == 1
    assert receipt["chunk_count"] == 1
    context = AccessContext(user_id="operator-1", case_id="case-1", task_id="task-1")
    results = index.search_text("incident report", context)
    assert results and results[0]["document_id"] == document.id
    assert results[0]["source_reference"] == "brief.txt"

    backend = _Backend()
    projection = index.project_to_memory(
        document,
        MemoryManager(backend),
        max_summary_chars=800,
    )
    assert projection["projected"] is True
    assert backend.writes[0]["metadata"]["projection"] == "evidence-summary"
    assert "exact_evidence_store" in backend.writes[0]["metadata"]["provenance"]


def test_evidence_index_blocks_cross_case_lookup(tmp_path):
    document = ingest_file(
        "sample_data/sample_text.txt",
        user_id="operator-1",
        case_id="case-1",
        task_id="task-1",
    )
    index = EvidenceIndex(tmp_path / "evidence.db")
    index.index_document(document)

    foreign = AccessContext(user_id="operator-2", case_id="case-2")
    assert index.search_text("incident", foreign) == []
    try:
        index.get_evidence(document.evidence_blocks[0].evidence_id, foreign)
        assert False, "cross-case evidence access should fail"
    except EvidenceNotFoundError:
        pass


def test_evidence_index_can_register_opaque_evidence_objects(tmp_path):
    document = ingest_file(
        "sample_data/sample_text.txt",
        user_id="operator-1",
        case_id="case-1",
        task_id="task-1",
    )
    object_store = LocalObjectStore(tmp_path / "objects")
    index = EvidenceIndex(tmp_path / "evidence.db", object_store=object_store)
    index.index_document(document, classification_level="RESTRICTED")

    result = index.get_evidence(
        document.evidence_blocks[0].evidence_id,
        AccessContext(user_id="operator-1", case_id="case-1", task_id="task-1"),
    )
    stored = object_store.get(result["object_id"], access_level="RESTRICTED", case_id="case-1")
    assert result["object_id"].startswith("obj-")
    assert stored.path.read_text(encoding="utf-8") == document.evidence_blocks[0].content


def test_evidence_index_reindex_idempotent(tmp_path):
    document1 = ingest_file(
        "sample_data/sample_text.txt",
        user_id="operator-1",
        case_id="case-1",
        task_id="task-1",
    )
    index = EvidenceIndex(tmp_path / "evidence.db")
    receipt1 = index.index_document(document1)
    assert receipt1["indexed"] is True

    # Re-uploading or re-indexing same source for a new task/document
    document2 = ingest_file(
        "sample_data/sample_text.txt",
        user_id="operator-1",
        case_id="case-1",
        task_id="task-2",
    )
    receipt2 = index.index_document(document2)
    assert receipt2["indexed"] is True
    assert receipt2["evidence_count"] == receipt1["evidence_count"]


def test_evidence_index_replaces_prior_source_version(tmp_path):
    first_source = tmp_path / "first.txt"
    second_source = tmp_path / "second.txt"
    first_source.write_text("old incident assessment", encoding="utf-8")
    second_source.write_text("new incident assessment", encoding="utf-8")
    index = EvidenceIndex(tmp_path / "evidence.db")
    first = ingest_file(
        str(first_source), user_id="operator-1", case_id="case-1",
        task_id="task-1", source_reference="case-brief.txt",
    )
    second = ingest_file(
        str(second_source), user_id="operator-1", case_id="case-1",
        task_id="task-1", source_reference="case-brief.txt",
    )

    index.index_document(first)
    index.index_document(second)
    context = AccessContext(user_id="operator-1", case_id="case-1", task_id="task-1")

    assert index.search_text("old", context) == []
    assert index.search_text("new", context)


def test_projected_memory_identity_is_stable_across_source_versions(tmp_path):
    first_source = tmp_path / "first.txt"
    second_source = tmp_path / "second.txt"
    first_source.write_text("old case summary", encoding="utf-8")
    second_source.write_text("new case summary", encoding="utf-8")
    index = EvidenceIndex(tmp_path / "evidence.db")
    first = ingest_file(
        str(first_source), user_id="operator-1", case_id="case-1",
        task_id="task-1", source_reference="case-brief.txt",
    )
    second = ingest_file(
        str(second_source), user_id="operator-1", case_id="case-1",
        task_id="task-1", source_reference="case-brief.txt",
    )
    index.index_document(first)
    backend = _Backend()
    manager = MemoryManager(backend)
    first_projection = index.project_to_memory(first, manager)
    index.index_document(second)
    second_projection = index.project_to_memory(second, manager)

    assert first_projection["memory_id"] == second_projection["memory_id"]
    assert backend.writes[0]["metadata"]["source_version"] == 1
    assert backend.writes[1]["metadata"]["source_version"] == 2
    assert "new case summary" in manager.store.get_memory(second_projection["memory_id"]).content
    assert "old case summary" not in manager.store.get_memory(second_projection["memory_id"]).content

