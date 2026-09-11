from pipelines.common.renderers import RendererCapability, RendererRegistry, default_renderer_registry


def test_default_registry_describes_native_and_fallback_renderers(tmp_path):
    registry = default_renderer_registry()
    assert registry.supports("diagram.native-svg", "inspect", "svg")
    assert registry.get("diagram.pptx").fallback_renderer_id == "diagram.native-svg"
    assert registry.get("presentation.ppt-master").fallback_renderer_id == "presentation.pptx"
    assert "video.ffmpeg" in registry.as_dict()

    svg = tmp_path / "preview.svg"
    svg.write_text('<svg width="10" height="10"><text>ok</text></svg>', encoding="utf-8")
    report = registry.inspect("diagram.native-svg", svg, required_text=("ok",))
    assert report.approved is True


def test_registry_rejects_duplicates_and_self_fallback():
    capability = RendererCapability("demo", "1", ("svg",), frozenset({"inspect"}))
    registry = RendererRegistry([capability])
    try:
        registry.register(capability)
        raise AssertionError("duplicate renderer was accepted")
    except ValueError as exc:
        assert "already registered" in str(exc)

    try:
        RendererCapability("loop", "1", ("svg",), frozenset({"inspect"}), "loop")
        raise AssertionError("self fallback was accepted")
    except ValueError as exc:
        assert "itself" in str(exc)
