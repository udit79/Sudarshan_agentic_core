import os
import tempfile
import pytest
from pipelines.common.audit_logger import AuditLogger


@pytest.fixture
def temp_audit_logger():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit_log.db")
        logger = AuditLogger(db_path=db_path)
        yield logger


def test_audit_log_write_and_read(temp_audit_logger):
    # Log a run start
    entry_id = temp_audit_logger.log_run_start(
        operator_id="op-123",
        case_id="case-456",
        task_id="task-789",
        run_id="run-000",
        classification="SECRET",
        pipeline="advisory",
        query="Test query"
    )
    
    # Query by run
    entries = temp_audit_logger.query_by_run("run-000")
    assert len(entries) == 1
    entry = entries[0]
    
    assert entry["id"] == entry_id
    assert entry["operator_id"] == "op-123"
    assert entry["classification"] == "SECRET"
    assert entry["status"] == "queued"
    assert "Test query" in entry["detail"]


def test_audit_integrity(temp_audit_logger):
    temp_audit_logger.log_cancellation(
        operator_id="op-cancel",
        run_id="run-cancel",
        task_id="task-cancel",
        case_id="case-cancel",
        classification="RESTRICTED"
    )
    
    entries = temp_audit_logger.query_by_run("run-cancel")
    entry = entries[0]
    
    # Validate integrity hash
    assert temp_audit_logger.verify_integrity(entry) is True
    
    # Tamper with the data
    entry["status"] = "succeeded"
    assert temp_audit_logger.verify_integrity(entry) is False


def test_query_by_case(temp_audit_logger):
    temp_audit_logger.log_run_start(
        operator_id="op", case_id="C1", task_id="T1", run_id="R1", classification="RESTRICTED"
    )
    temp_audit_logger.log_run_start(
        operator_id="op", case_id="C2", task_id="T2", run_id="R2", classification="RESTRICTED"
    )
    temp_audit_logger.log_run_complete(
        operator_id="op", case_id="C1", task_id="T1", run_id="R1", classification="RESTRICTED", pipeline="p", status="succeeded"
    )
    
    c1_entries = temp_audit_logger.query_by_case("C1")
    assert len(c1_entries) == 2
    
    c2_entries = temp_audit_logger.query_by_case("C2")
    assert len(c2_entries) == 1
