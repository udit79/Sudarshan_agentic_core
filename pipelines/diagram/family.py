"""Small semantic diagram family shared by PPT, infographic, and video skills."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pipelines.ppt.schemas import FlowchartEdge, FlowchartNode, FlowchartSpec


DiagramKind = Literal[
    "flowchart", "sequence", "swimlane", "architecture",
    "timeline", "state", "dependency", "mind-map",
]


class DiagramNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=180)
    role: str = Field(default="process", max_length=40)
    group: str | None = Field(default=None, max_length=120)


class DiagramEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)
    label: str = Field(default="", max_length=120)


class DiagramSpec(BaseModel):
    """Renderer-neutral semantic graph; no SVG, PPTX, or provider payloads."""

    model_config = ConfigDict(extra="forbid")

    diagram_id: str = Field(min_length=1, max_length=120)
    kind: DiagramKind
    title: str = Field(default="", max_length=240)
    nodes: list[DiagramNode] = Field(min_length=1, max_length=80)
    edges: list[DiagramEdge] = Field(default_factory=list, max_length=160)
    direction: Literal["left-to-right", "top-to-bottom"] = "left-to-right"
    style_tokens: dict[str, str] = Field(default_factory=dict, max_length=24)

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
        return self


_PATTERNS: dict[str, dict[str, object]] = {
    "flowchart": {"purpose": "ordered decisions and processes", "direction": "left-to-right"},
    "sequence": {"purpose": "ordered interactions between actors", "direction": "top-to-bottom"},
    "swimlane": {"purpose": "responsibility across actors or teams", "direction": "left-to-right"},
    "architecture": {"purpose": "components and system boundaries", "direction": "left-to-right"},
    "timeline": {"purpose": "events over time", "direction": "left-to-right"},
    "state": {"purpose": "state transitions", "direction": "left-to-right"},
    "dependency": {"purpose": "upstream and downstream dependencies", "direction": "left-to-right"},
    "mind-map": {"purpose": "central concept and radial branches", "direction": "top-to-bottom"},
}


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
    text = str(query).casefold()
    keywords = (
        ("mind-map", ("mind map", "mindmap", "branches")),
        ("swimlane", ("swimlane", "responsibility", "owner")),
        ("sequence", ("sequence", "interaction", "message flow")),
        ("timeline", ("timeline", "over time", "milestone")),
        ("architecture", ("architecture", "components", "system boundary")),
        ("state", ("state transition", "lifecycle state")),
        ("dependency", ("dependency", "dependencies", "depends on", "upstream")),
        ("flowchart", ("flowchart", "decision", "process")),
    )
    for kind, phrases in keywords:
        if any(phrase in text for phrase in phrases):
            return kind  # type: ignore[return-value]
    return "flowchart"


def inspect_diagram(spec: DiagramSpec) -> list[str]:
    """Return deterministic self-checker issues before a renderer is called."""

    issues: list[str] = []
    if len(spec.nodes) > 40:
        issues.append("diagram exceeds the default complexity budget of 40 nodes")
    if len(spec.edges) > 80:
        issues.append("diagram exceeds the default complexity budget of 80 edges")
    connected = {edge.source for edge in spec.edges} | {edge.target for edge in spec.edges}
    if len(spec.nodes) > 1:
        issues.extend(f"node is disconnected: {node.node_id}" for node in spec.nodes if node.node_id not in connected)
    issues.extend(f"node has no accessible label: {node.node_id}" for node in spec.nodes if not node.label.strip())
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
    "DiagramEdge", "DiagramKind", "DiagramNode", "DiagramSpec",
    "choose_diagram_kind", "compile_flowchart_spec", "inspect_diagram", "pattern_for",
]
