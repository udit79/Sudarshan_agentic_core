"""Multi-user, multi-case, and multi-task isolation tests.

The scenario uses the real EvidenceIndex, MemoryManager, and ArtifactStore
boundaries.  A small backend double replaces Cognee so the assertions remain
deterministic and never require provider credentials.
"""

from __future__ import annotations

from hashlib import sha256
import re

import pytest
from fastapi.testclient import TestClient

from api.artifacts import ArtifactStore
from ingestion_pipelines.contracts import EvidenceBlock, EvidenceChunk, EvidenceLocation
from ingestion_pipelines.evidence_index import EvidenceIndex, EvidenceNotFoundError
from ingestion_pipelines.models import IngestedDocument
from memory import AccessContext, KnowledgeUnit, MemoryManager, MemoryType, ScopeType, Source, SourceType


class ScopedBackend:
    """Deterministic provider double that honors the node sets it receives."""

    def __init__(self) -> None:
        self.writes: list[dict] = []

    def remember(self, **kwargs):
        self.writes.append(kwargs)
        return {"status": "accepted"}

    def recall(self, *, query, node_sets, dataset_name, top_k, session_id=None):
        terms = set(re.findall(r"[a-z0-9-]{3,}", query.casefold()))
        matches = []
        for item in self.writes:
            if not set(node_sets).intersection(item["node_sets"]):
                continue
            content_terms = set(re.findall(r"[a-z0-9-]{3,}", item["content"].casefold()))
            if terms.intersection(content_terms):
                matches.append({
                    "content": item["content"],
                    "metadata": item["metadata"],
                    "score": 1.0,
                })
        return matches[:top_k]


SCENARIO = (
    ("evidence-a1", "doc-a1", "user-a", "case-a", "task-a1", "case-a evidence-a1 confirms harbor route"),
    ("evidence-a2", "doc-a2", "user-a", "case-a", "task-a2", "case-a evidence-a2 confirms radar timing"),
    ("evidence-b1", "doc-b1", "user-a", "case-b", "task-b1", "case-b evidence-b1 confirms inland route"),
    ("evidence-b2", "doc-b2", "user-a", "case-b", "task-b2", "case-b evidence-b2 confirms satellite timing"),
    ("evidence-c1", "doc-c1", "user-b", "case-c", "task-c1", "case-c evidence-c1 confirms alternate route"),
)


def make_document(evidence_id: str, document_id: str, user_id: str, case_id: str,
                  task_id: str, content: str) -> IngestedDocument:
    source_reference = f"evidence://{case_id}/{document_id}"
    source_hash = "sha256:" + sha256(content.encode("utf-8")).hexdigest()
    block = EvidenceBlock(
        evidence_id=evidence_id,
        document_id=document_id,
        modality="text_document",
        content=content,
        location=EvidenceLocation(page=1),
        confidence=0.95,
        source_hash=source_hash,
        extractor_version="isolation-test-extractor@1",
        provenance={"fixture": "case-isolation"},
    )
    chunk = EvidenceChunk(
        chunk_id=f"chunk-{document_id}",
        document_id=document_id,
        content=content,
        evidence_ids=[evidence_id],
        heading_path=[case_id],
        source_hash=source_hash,
        chunk_index=0,
        estimated_tokens=max(1, len(content) // 4),
    )
    return IngestedDocument.create(
        source_path=source_reference,
        raw_text=content,
        doc_type="text",
        user_id=user_id,
        case_id=case_id,
        task_id=task_id,
        document_id=document_id,
        evidence_blocks=[block],
        chunks=[chunk],
    )


def build_scenario(tmp_path):
    index = EvidenceIndex(tmp_path / "evidence.db")
    backend = ScopedBackend()
    manager = MemoryManager(backend)
    documents = [make_document(*item) for item in SCENARIO]
    for document in documents:
        index.index_document(document)
        index.project_to_memory(document, manager)
    contexts = {
        "case_a": AccessContext(user_id="user-a", case_id="case-a"),
        "case_b": AccessContext(user_id="user-a", case_id="case-b"),
        "case_c": AccessContext(user_id="user-b", case_id="case-c"),
        "task_a1": AccessContext(user_id="user-a", case_id="case-a", task_id="task-a1"),
        "task_a2": AccessContext(user_id="user-a", case_id="case-a", task_id="task-a2"),
    }
    return index, backend, manager, documents, contexts


def test_case_requests_return_only_authorized_evidence_content(tmp_path) -> None:
    index, _backend, _manager, _documents, contexts = build_scenario(tmp_path)

    case_a = index.search_text("confirms route", contexts["case_a"])
    case_b = index.search_text("confirms route", contexts["case_b"])
    case_c = index.search_text("confirms route", contexts["case_c"])

    assert {item["evidence_id"] for item in case_a} == {"evidence-a1", "evidence-a2"}
    assert {item["evidence_id"] for item in case_b} == {"evidence-b1", "evidence-b2"}
    assert {item["evidence_id"] for item in case_c} == {"evidence-c1"}
    assert "case-b" not in repr(case_a) and "evidence-b1" not in repr(case_a)
    assert "case-c" not in repr(case_a) and "evidence-c1" not in repr(case_a)
    assert "case-a" not in repr(case_b) and "evidence-a1" not in repr(case_b)
    assert "case-c" not in repr(case_b) and "evidence-c1" not in repr(case_b)


def test_deliberate_cross_case_and_cross_user_evidence_access_is_denied(tmp_path) -> None:
    index, _backend, _manager, _documents, contexts = build_scenario(tmp_path)

    assert index.search_text("evidence-b1", contexts["case_a"]) == []
    assert index.search_text("evidence-a1", contexts["case_b"]) == []
    assert index.search_text("evidence-a1", contexts["case_c"]) == []

    with pytest.raises(EvidenceNotFoundError):
        index.get_evidence("evidence-b1", contexts["case_a"])
    with pytest.raises(EvidenceNotFoundError):
        index.get_evidence("evidence-a1", contexts["case_b"])
    with pytest.raises(EvidenceNotFoundError):
        index.get_evidence("evidence-a1", contexts["case_c"])


def test_task_requests_do_not_receive_sibling_task_evidence(tmp_path) -> None:
    index, _backend, manager, _documents, contexts = build_scenario(tmp_path)

    task_a1_evidence = index.search_text("confirms", contexts["task_a1"])
    task_a2_evidence = index.search_text("confirms", contexts["task_a2"])
    manager.remember(
        KnowledgeUnit(
            unit_id="task-note-a1",
            content="task-a1 private handoff note",
            source=Source("task-note-a1", SourceType.USER, "task://task-a1"),
            provenance={"fixture": "task-isolation"},
        ),
        contexts["task_a1"],
        scope_type=ScopeType.TASK,
        memory_type=MemoryType.EVENT,
    )
    task_memory = manager.recall("private handoff note", contexts["task_a1"])
    sibling_memory = manager.recall("private handoff note", contexts["task_a2"])

    assert {item["evidence_id"] for item in task_a1_evidence} == {"evidence-a1"}
    assert {item["evidence_id"] for item in task_a2_evidence} == {"evidence-a2"}
    assert "task-a1 private handoff note" in task_memory.context.text
    assert "task-a1 private handoff note" not in sibling_memory.context.text


def test_memory_resolver_returns_case_a_content_without_case_b_or_user_b(tmp_path) -> None:
    _index, _backend, manager, _documents, contexts = build_scenario(tmp_path)

    response = manager.recall("confirms route", contexts["case_a"])
    content = response.context.text

    assert "evidence-a1" in content and "evidence-a2" in content
    assert "evidence-b1" not in content and "evidence-b2" not in content
    assert "evidence-c1" not in content
    assert all(item.scope_id == "case-a" for item in response.context.items)


def test_memory_writes_use_the_exact_case_node_set(tmp_path) -> None:
    _index, backend, _manager, _documents, _contexts = build_scenario(tmp_path)

    writes_by_case = {}
    for write in backend.writes:
        scope_id = write["metadata"].get("scope_id")
        writes_by_case.setdefault(scope_id, []).append(write)

    assert set(writes_by_case) == {"case-a", "case-b", "case-c"}
    assert all(
        write["node_sets"] == [f"sudarshan:scope:case:{case_id}"]
        for case_id, writes in writes_by_case.items()
        for write in writes
    )
    assert all(
        write["metadata"]["case_id"] == write["metadata"]["scope_id"]
        for writes in writes_by_case.values()
        for write in writes
    )


def test_case_a_generated_artifact_contains_only_case_a_evidence(tmp_path) -> None:
    index, _backend, _manager, _documents, contexts = build_scenario(tmp_path)
    authorized = index.search_text("evidence-a1", contexts["task_a1"])
    output = "Case A generated report\n" + "\n".join(item["content"] for item in authorized)

    artifact_root = tmp_path / "artifacts"
    source = artifact_root / "case-a-report.txt"
    source.parent.mkdir(parents=True)
    source.write_text(output, encoding="utf-8")
    store = ArtifactStore(artifact_root, evidence_scope_verifier=index)
    manifest = store.register(
        source,
        run_id="run-case-a",
        kind="text-report",
        classification_level="RESTRICTED",
        user_id="user-a",
        case_id="case-a",
        task_id="task-a1",
        evidence_ids=["evidence-a1"],
    )
    _manifest, stored_path = store.get(manifest.artifact_id)
    artifact_text = stored_path.read_text(encoding="utf-8")

    assert manifest.case_id == "case-a"
    assert manifest.evidence_ids == ["evidence-a1"]
    assert "evidence-a1" in artifact_text
    assert "evidence-a2" not in artifact_text
    assert "evidence-b1" not in artifact_text and "evidence-b2" not in artifact_text
    assert "evidence-c1" not in artifact_text


def test_public_artifact_access_denies_wrong_case_and_user(tmp_path, monkeypatch) -> None:
    import api.server as api_server

    artifact_root = tmp_path / "artifacts"
    source = artifact_root / "case-a-report.txt"
    source.parent.mkdir(parents=True)
    source.write_text("case-a evidence-a1 only", encoding="utf-8")
    store = ArtifactStore(artifact_root)
    manifest = store.register(
        source,
        run_id="run-case-a-access",
        kind="text-report",
        classification_level="RESTRICTED",
        user_id="user-a",
        case_id="case-a",
        task_id="task-a1",
    )
    monkeypatch.setattr(api_server, "ARTIFACT_STORE", store)
    client = TestClient(api_server.app)

    allowed = client.get(
        f"/artifacts/{manifest.artifact_id}/download",
        headers={"x-operator-id": "user-a", "x-case-id": "case-a", "x-task-id": "task-a1"},
    )
    wrong_case = client.get(
        f"/artifacts/{manifest.artifact_id}/download",
        headers={"x-operator-id": "user-a", "x-case-id": "case-b", "x-task-id": "task-b1"},
    )
    wrong_user = client.get(
        f"/artifacts/{manifest.artifact_id}/download",
        headers={"x-operator-id": "user-b", "x-case-id": "case-c", "x-task-id": "task-c1"},
    )

    assert allowed.status_code == 200
    assert allowed.content == b"case-a evidence-a1 only"
    assert wrong_case.status_code == 403
    assert wrong_user.status_code == 403
    assert b"case-a evidence-a1 only" not in wrong_case.content
    assert b"case-a evidence-a1 only" not in wrong_user.content


def test_artifact_registration_rejects_foreign_evidence_ids(tmp_path) -> None:
    index = EvidenceIndex(tmp_path / "evidence.db")
    foreign_document = make_document(
        "evidence-b1",
        "doc-b1",
        "user-a",
        "case-b",
        "task-b1",
        "case-b evidence-b1 confirms inland route",
    )
    index.index_document(foreign_document)
    artifact_root = tmp_path / "artifacts"
    source = artifact_root / "case-a-report.txt"
    source.parent.mkdir(parents=True)
    source.write_text("case-a report", encoding="utf-8")
    store = ArtifactStore(artifact_root, evidence_scope_verifier=index)

    with pytest.raises(PermissionError):
        store.register(
            source,
            run_id="run-foreign-evidence",
            kind="text-report",
            classification_level="RESTRICTED",
            user_id="user-a",
            case_id="case-a",
            task_id="task-a1",
            evidence_ids=["evidence-b1"],
        )
    assert list(store.manifest_root.glob("*.json")) == []
