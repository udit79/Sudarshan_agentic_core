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
        renderer_version="ppt-test@1",
    )
    loaded, resolved = store.get(manifest.artifact_id)

    assert loaded == manifest
    assert resolved == source.resolve()
    assert manifest.uri.endswith(f"{manifest.artifact_id}/download")


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
    )
    monkeypatch.setenv("SUDARSHAN_ARTIFACT_ROOT", str(root))

    result = object.__new__(SudarshanApplication).get_artifact(manifest.artifact_id)

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
    )
    loaded, preview = store.preview(manifest.artifact_id)

    assert loaded.preview_uri == f"/artifacts/{manifest.artifact_id}/preview"
    assert preview == source.resolve()
