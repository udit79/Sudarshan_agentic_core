from api.release import run_release_checks


def test_release_preflight_reports_missing_files_and_failed_tests(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "release-runbook.md").write_text("ok", encoding="utf-8")
    report = run_release_checks(
        tmp_path,
        release_id="rc-1",
        required_files=("docs/release-runbook.md", "docs/rollback-runbook.md"),
        test_results={"python": True, "a2a": False},
    )
    assert report.passed is False
    assert "file:docs/rollback-runbook.md" in report.failed_checks
    assert "test:a2a" in report.failed_checks


def test_release_preflight_is_green_when_evidence_is_present(tmp_path):
    for relative in ("docs/release-runbook.md", "docs/rollback-runbook.md"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok", encoding="utf-8")
    report = run_release_checks(
        tmp_path,
        release_id="rc-2",
        required_files=("docs/release-runbook.md", "docs/rollback-runbook.md"),
        test_results={"python": True},
    )
    assert report.passed is True
