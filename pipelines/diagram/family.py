"""Small semantic diagram family shared by PPT, infographic, and video skills."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pipelines.ppt.schemas import FlowchartEdge, FlowchartNode, FlowchartSpec


DiagramKind = Literal[
    "flowchart", "sequence", "swimlane", "architecture",
    "timeline", "state", "dependency", "mind-map",
]

DiagramAudience = Literal["executive", "mixed", "technical"]
DiagramDetail = Literal["simplified", "balanced", "faithful"]
DiagramFormat = Literal["html", "svg", "png", "pptx", "video-frame"]
DiagramMotion = Literal["none", "reveal", "step", "loop"]


_DETAIL_BUDGETS: dict[DiagramDetail, tuple[int, int]] = {
    "simplified": (7, 9),
    "balanced": (12, 16),
    "faithful": (24, 32),
}


_DIAGRAM_REGISTRY: dict[str, dict[str, Any]] = {
    "flowchart": {"purpose": "ordered decisions and processes", "direction": "left-to-right", "patterns": ("decision_logic", "paired_policy_traces")},
    "sequence": {"purpose": "ordered interactions between actors", "direction": "top-to-bottom", "patterns": ("interaction_trace",)},
    "swimlane": {"purpose": "responsibility across actors or teams", "direction": "left-to-right", "patterns": ("ownership_handoff",)},
    "architecture": {"purpose": "components and system boundaries", "direction": "left-to-right", "patterns": ("secure_paved_road", "governance_catalog")},
    "timeline": {"purpose": "events over time", "direction": "left-to-right", "patterns": ("temporal_sequence",)},
    "state": {"purpose": "state transitions", "direction": "left-to-right", "patterns": ("state_lifecycle",)},
    "dependency": {"purpose": "upstream and downstream dependencies", "direction": "left-to-right", "patterns": ("dependency_map", "fan_in_bottleneck")},
    "mind-map": {"purpose": "central concept and radial branches", "direction": "top-to-bottom", "patterns": ("concept_decomposition",)},
}


_PATTERN_KEYWORDS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("secure_paved_road", ("trust boundary", "secure path", "allowed ingress", "forbidden ingress"), "architecture"),
    ("fan_in_bottleneck", ("bottleneck", "queue depth", "fan-in", "capacity"), "dependency"),
    ("paired_policy_traces", ("policy trace", "pass/fail", "first divergence"), "flowchart"),
    ("ownership_handoff", ("ownership", "handoff", "responsibility"), "swimlane"),
    ("interaction_trace", ("sequence", "message flow", "actor interaction"), "sequence"),
    ("temporal_sequence", ("timeline", "over time", "milestone"), "timeline"),
    ("state_lifecycle", ("state transition", "lifecycle"), "state"),
    ("dependency_map", ("dependency", "dependencies", "depends on", "upstream"), "dependency"),
    ("concept_decomposition", ("mind map", "mindmap", "branches from"), "mind-map"),
    ("decision_logic", ("flowchart", "decision", "process"), "flowchart"),
)


class DiagramNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=180)
    role: str = Field(default="process", max_length=40)
    group: str | None = Field(default=None, max_length=120)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class DiagramEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)
    label: str = Field(default="", max_length=120)
    relation: str = Field(default="leads_to", max_length=40)


class DiagramGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=180)


class AccessibilitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=2000)


class FidelityEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["merged", "collapsed", "dropped", "kept"]
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    result: str = Field(min_length=1, max_length=240)


class DiagramSpec(BaseModel):
    """Renderer-neutral semantic graph; no SVG, PPTX, or provider payloads."""

    model_config = ConfigDict(extra="forbid")

    diagram_id: str = Field(min_length=1, max_length=120)
    kind: DiagramKind
    title: str = Field(default="", max_length=240)
    nodes: list[DiagramNode] = Field(min_length=1, max_length=80)
    edges: list[DiagramEdge] = Field(default_factory=list, max_length=160)
    visual_type: DiagramKind | None = None
    semantic_pattern: str | None = Field(default=None, max_length=80)
    audience: DiagramAudience = "mixed"
    detail: DiagramDetail = "balanced"
    format: DiagramFormat = "svg"
    size_preset: str = Field(default="doc-wide", max_length=40)
    motion: DiagramMotion = "none"
    direction: Literal["left-to-right", "top-to-bottom"] = "left-to-right"
    style_tokens: dict[str, str] = Field(default_factory=dict, max_length=24)
    style_profile: str = Field(default="ntro-default", max_length=80)
    groups: list[DiagramGroup] = Field(default_factory=list, max_length=20)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    accessibility: AccessibilitySpec | None = None
    fidelity_ledger: list[FidelityEntry] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_references(self) -> "DiagramSpec":
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("diagram node IDs must be unique")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError("diagram edges must reference existing nodes")
            if edge.source == edge.target:
                raise ValueError("diagram edges cannot point to the same node")
        if self.visual_type is not None and self.visual_type != self.kind:
            raise ValueError("visual_type must match kind when both are supplied")
        group_ids = {group.group_id for group in self.groups}
        if len(group_ids) != len(self.groups):
            raise ValueError("diagram group IDs must be unique")
        unknown_groups = {node.group for node in self.nodes if node.group and node.group not in group_ids}
        if unknown_groups:
            raise ValueError(f"diagram nodes reference unknown groups: {sorted(unknown_groups)}")
        if self.motion != "none" and self.format not in {"html", "svg"}:
            raise ValueError("motion is supported only for HTML or SVG targets")
        if self.accessibility is None:
            object.__setattr__(self, "accessibility", AccessibilitySpec(
                title=self.title or self.diagram_id,
                description=f"{self.kind} diagram {self.diagram_id}.",
            ))
        return self


_PATTERNS = _DIAGRAM_REGISTRY


def diagram_type_registry() -> dict[str, dict[str, Any]]:
    """Return a copy of the allow-listed semantic diagram registry."""

    return {name: dict(metadata) for name, metadata in _DIAGRAM_REGISTRY.items()}


def choose_semantic_pattern(query: str, requested: str | None = None) -> str | None:
    """Choose a bounded semantic pattern before a visual layout."""

    if requested:
        valid = {pattern for metadata in _DIAGRAM_REGISTRY.values() for pattern in metadata["patterns"]}
        if requested not in valid:
            raise ValueError(f"unsupported semantic diagram pattern: {requested}")
        return requested
    text = str(query).casefold()
    for pattern, phrases, _kind in _PATTERN_KEYWORDS:
        if any(phrase in text for phrase in phrases):
            return pattern
    return None


def pattern_for(kind: DiagramKind) -> dict[str, object]:
    try:
        return dict(_PATTERNS[kind])
    except KeyError as exc:
        raise ValueError(f"unsupported diagram kind: {kind}") from exc


def choose_diagram_kind(query: str, requested: str | None = None) -> DiagramKind:
    """Choose a semantic type before any visual layout is attempted."""

    if requested:
        normalized = requested.strip().lower().replace("_", "-")
        if normalized not in _PATTERNS:
            raise ValueError(f"unsupported diagram kind: {requested}")
        return normalized  # type: ignore[return-value]
    pattern = choose_semantic_pattern(query)
    if pattern:
        for kind, metadata in _DIAGRAM_REGISTRY.items():
            if pattern in metadata["patterns"]:
                return kind  # type: ignore[return-value]
    return "flowchart"


def inspect_diagram(spec: DiagramSpec) -> list[str]:
    """Return deterministic self-checker issues before a renderer is called."""

    issues: list[str] = []
    max_nodes, max_edges = _DETAIL_BUDGETS[spec.detail]
    if len(spec.nodes) > max_nodes:
        issues.append(f"diagram exceeds the {spec.detail} complexity budget of {max_nodes} nodes")
    if len(spec.edges) > max_edges:
        issues.append(f"diagram exceeds the {spec.detail} complexity budget of {max_edges} edges")
    connected = {edge.source for edge in spec.edges} | {edge.target for edge in spec.edges}
    if len(spec.nodes) > 1:
        issues.extend(f"node is disconnected: {node.node_id}" for node in spec.nodes if node.node_id not in connected)
    issues.extend(f"node has no accessible label: {node.node_id}" for node in spec.nodes if not node.label.strip())
    issues.extend(
        f"node label is too long for the selected audience: {node.node_id}"
        for node in spec.nodes
        if len(node.label) > (120 if spec.audience == "executive" else 180)
    )
    if spec.motion != "none":
        issues.append("motion requires an approved controller and is not enabled by the native static renderer")
    if not spec.style_profile.strip():
        issues.append("diagram style profile is empty")
    return issues


def compile_flowchart_spec(spec: DiagramSpec) -> FlowchartSpec:
    """Compile compatible diagram semantics to the existing native graph renderer."""

    issues = inspect_diagram(spec)
    if issues:
        raise ValueError("; ".join(issues))
    return FlowchartSpec(
        flowchart_id=spec.diagram_id,
        direction=spec.direction,
        nodes=[
            FlowchartNode(
                node_id=node.node_id,
                label=node.label,
                kind=_flowchart_role(node.role),
                group=node.group,
            )
            for node in spec.nodes
        ],
        edges=[FlowchartEdge(source=edge.source, target=edge.target, label=edge.label) for edge in spec.edges],
        style_tokens=dict(spec.style_tokens),
    )


def _flowchart_role(role: str) -> str:
    normalized = role.casefold()
    if normalized in {"start", "process", "decision", "review", "end"}:
        return normalized
    if normalized in {"condition", "question", "gate"}:
        return "decision"
    if normalized in {"actor", "component", "state", "event", "milestone"}:
        return "process"
    return "process"


__all__ = [
    "AccessibilitySpec", "DiagramAudience", "DiagramDetail", "DiagramEdge", "DiagramFormat",
    "DiagramGroup", "DiagramKind", "DiagramMotion", "DiagramNode", "DiagramSpec", "FidelityEntry",
    "choose_diagram_kind", "choose_semantic_pattern", "compile_flowchart_spec", "diagram_type_registry",
    "inspect_diagram", "pattern_for",
]
