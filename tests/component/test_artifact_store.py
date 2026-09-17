from __future__ import annotations

from api.artifacts import ArtifactStore
from integrations.deepseek_harness.application import SudarshanApplication
from PIL import Image


def test_artifact_store_registers_and_verifies_immutable_manifest(tmp_path) -> None:
    root = tmp_path / "artifacts"
    source = root / "presentations" / "brief.pptx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"deterministic artifact")
    store = ArtifactStore(root)

    manifest = store.register(
        source,
        run_id="run-1",
        kind="presentation",
        classification_level="RESTRICTED",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
        renderer_version="ppt-test@1",
    )
    loaded, resolved = store.get(manifest.artifact_id)

    assert loaded == manifest
    assert resolved == source.resolve()
    assert manifest.uri.endswith(f"{manifest.artifact_id}/download")


def test_artifact_store_register_checked_saves_quality_report_and_renderer_metadata(tmp_path) -> None:
    root = tmp_path / "artifacts"
    source = root / "preview.svg"
    source.parent.mkdir(parents=True)
    source.write_text('<svg width="10" height="10"><text>ok</text></svg>', encoding="utf-8")
    store = ArtifactStore(root)

    checked = store.register_checked(
        source,
        run_id="run-checked",
        kind="diagram-svg",
        artifact_kind="svg",
        renderer_id="diagram.native-svg",
        classification_level="RESTRICTED",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
        required_text=("ok",),
    )

    assert checked.manifest.quality_status == "passed"
    assert checked.manifest.quality_report_id == checked.quality_report_id
    assert checked.renderer_version == "diagram.native-svg@1"
    assert (store.quality_report_root / f"{checked.quality_report_id}.json").is_file()


def test_artifact_store_rejects_source_outside_root(tmp_path) -> None:
    root = tmp_path / "artifacts"
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"not controlled")
    store = ArtifactStore(root)

    try:
        store.register(
            outside,
            run_id="run-1",
            kind="binary",
            classification_level="RESTRICTED",
            user_id="user-1",
            case_id="case-1",
            task_id="task-1",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("artifact store accepted a path outside its root")


def test_application_returns_verified_manifest_without_filesystem_path(tmp_path, monkeypatch) -> None:
    root = tmp_path / "artifacts"
    source = root / "brief.txt"
    source.parent.mkdir(parents=True)
    source.write_text("verified draft", encoding="utf-8")
    manifest = ArtifactStore(root).register(
        source,
        run_id="run-1",
        kind="text",
        classification_level="RESTRICTED",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )
    monkeypatch.setenv("SUDARSHAN_ARTIFACT_ROOT", str(root))

    result = object.__new__(SudarshanApplication).get_artifact(
        manifest.artifact_id,
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )

    assert result["artifact_id"] == manifest.artifact_id
    assert result["integrity_verified"] is True
    assert result["download_uri"].endswith(f"/{manifest.artifact_id}/download")
    assert "source_path" not in result
    assert str(source) not in str(result)


def test_artifact_store_creates_direct_image_preview(tmp_path) -> None:
    root = tmp_path / "artifacts"
    source = root / "preview.png"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), color=(10, 20, 30)).save(source)
    store = ArtifactStore(root)

    manifest = store.register(
        source,
        run_id="run-preview",
        kind="image",
        classification_level="RESTRICTED",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )
    loaded, preview = store.preview(manifest.artifact_id)

    assert loaded.preview_uri == f"/artifacts/{manifest.artifact_id}/preview"
    assert preview == source.resolve()


def test_artifact_manifest_preserves_user_case_task_ownership(tmp_path) -> None:
    root = tmp_path / "artifacts"
    source = root / "brief.txt"
    source.parent.mkdir(parents=True)
    source.write_text("case-owned artifact", encoding="utf-8")

    manifest = ArtifactStore(root).register(
        source,
        run_id="run-owned",
        kind="text",
        classification_level="RESTRICTED",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )

    assert manifest.user_id == "user-1"
    assert manifest.case_id == "case-1"
    assert manifest.task_id == "task-1"


def test_artifact_store_can_copy_into_restart_safe_object_store(tmp_path, monkeypatch) -> None:
    root = tmp_path / "artifacts"
    source = root / "brief.txt"
    source.parent.mkdir(parents=True)
    source.write_text("durable artifact", encoding="utf-8")
    monkeypatch.setenv("SUDARSHAN_OBJECT_STORE_MODE", "durable")

    manifest = ArtifactStore(root).register(
        source,
        run_id="run-durable",
        kind="text",
        classification_level="RESTRICTED",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )
    loaded, resolved = ArtifactStore(root).get(manifest.artifact_id)

    assert loaded == manifest
    assert resolved != source.resolve()
    assert resolved.read_text(encoding="utf-8") == "durable artifact"

    source.unlink()
    _, restored = ArtifactStore(root).get(manifest.artifact_id)
    assert restored.read_text(encoding="utf-8") == "durable artifact"
