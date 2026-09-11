from pathlib import Path

from integrations.deepseek_harness.mcp_server import MCP_TOOL_PROFILES


REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_ROOT = REPO_ROOT / "integrations" / "deepseek_harness"
PROFILE = HARNESS_ROOT / "sudarshan.cordis.yml"
PRESET_ROOT = HARNESS_ROOT / "agent-presets" / "sudarshan-artifact-agent"
BUNDLE_PATCH = REPO_ROOT / "deepseek-harness" / "packages" / "bundle" / "web-app" / "cordis.patch.yml"
OPERATIONS_README = REPO_ROOT / "deepseek-harness" / "packages" / "experimental" / "client-ui-sudarshan-operations" / "README.md"


def test_native_profile_mounts_one_governed_artifact_agent():
    profile = PROFILE.read_text(encoding="utf-8")
    preset = (PRESET_ROOT / "agent.cordis.yml").read_text(encoding="utf-8")
    metadata = (PRESET_ROOT / "preset.yml").read_text(encoding="utf-8")

    assert "name: Sudarshan Artifact Agent" in metadata
    assert "default: sudarshan-artifact-agent" in profile
    assert "path: integrations/deepseek_harness/agent-presets" in profile
    assert "includeShippedRoot: false" in profile
    assert "includeUserRoot: false" in profile
    assert "name: '@deepseek-ai/dsh-mcp-client'" in profile
    assert "args: [-m, integrations.deepseek_harness.mcp_server]" in profile
    assert "SUDARSHAN_MCP_TOOL_PROFILE: artifact" in profile
    assert "You are the Sudarshan Artifact Agent" in preset


def test_native_profile_does_not_mount_general_coding_capabilities():
    preset = (PRESET_ROOT / "agent.cordis.yml").read_text(encoding="utf-8")
    profile = PROFILE.read_text(encoding="utf-8")

    for forbidden in (
        "dsh-tool-bash",
        "dsh-tool-pwsh",
        "dsh-tool-fs",
        "dsh-tool-web",
        "dsh-tool-skill",
        "dsh-tool-subagent",
        "dsh-tool-workflow",
    ):
        assert forbidden not in preset

    for row in (
        "ui-agent-preset",
        "ui-settings-plugins",
        "ui-cordis",
        "ui-workflow-run",
        "ui-plan",
        "ui-goal",
        "ui-subagent",
        "ui-input-trigger",
        "ui-commands",
        "ui-skill",
        "ui-reference",
    ):
        assert f"- id: {row}\n  disabled: true" in profile


def test_native_mcp_profile_keeps_full_external_mode_and_bounds_native_schema():
    assert MCP_TOOL_PROFILES["full"] is None
    artifact = MCP_TOOL_PROFILES["artifact"]
    assert artifact is not None
    assert "list_sudarshan_skills" in artifact
    assert "start_sudarshan_run" in artifact
    assert "get_sudarshan_artifact" in artifact
    assert "search_sudarshan_text_evidence" not in artifact
    assert "remember_sudarshan_context" not in artifact


def test_native_harness_bundle_loads_live_operations_bridge():
    bundle = BUNDLE_PATCH.read_text(encoding="utf-8")
    readme = OPERATIONS_README.read_text(encoding="utf-8")

    assert "@deepseek-ai/dsh-experimental-client-ui-sudarshan-operations" in bundle
    assert "typed backend projection/SSE bridge" in bundle
    assert "automatically bound" in readme
    assert "start_sudarshan_run" in readme
