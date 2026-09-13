"""Typed deterministic structure compilers for infographic IR."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pipelines.infographic.schemas import InfographicIR


StructureKind = Literal["chart", "hierarchy", "comparison", "timeline", "mind-map"]


class StructureNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=180)
    value: int = Field(ge=0)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class StructureEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)
    relation: Literal["ordered", "contains", "compares"] = "ordered"


class InfographicStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: StructureKind
    nodes: list[StructureNode] = Field(min_length=1, max_length=30)
    edges: list[StructureEdge] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def validate_edges(self) -> "InfographicStructure":
        known = {node.node_id for node in self.nodes}
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError("structure edge references an unknown node")
            if edge.source == edge.target:
                raise ValueError("structure edge cannot reference itself")
        return self


def compile_infographic_structure(ir: InfographicIR, kind: StructureKind | None = None) -> InfographicStructure:
    """Compile bounded semantic blocks without exposing renderer syntax."""

    selected = kind or _kind_for_ir(ir.visual_type)
    nodes = [
        StructureNode(
            node_id=block.block_id,
            label=block.label,
            value=index,
            evidence_ids=list(block.evidence_ids),
        )
        for index, block in enumerate(ir.blocks, start=1)
    ]
    edges: list[StructureEdge] = []
    if selected in {"timeline", "comparison"}:
        relation = "compares" if selected == "comparison" else "ordered"
        edges = [StructureEdge(source=left.node_id, target=right.node_id, relation=relation) for left, right in zip(nodes, nodes[1:])]
    elif selected in {"hierarchy", "mind-map"} and len(nodes) > 1:
        edges = [StructureEdge(source=nodes[0].node_id, target=node.node_id, relation="contains") for node in nodes[1:]]
    elif selected == "chart":
        edges = [StructureEdge(source=left.node_id, target=right.node_id, relation="ordered") for left, right in zip(nodes, nodes[1:])]
    return InfographicStructure(kind=selected, nodes=nodes, edges=edges)


def _kind_for_ir(visual_type: str) -> StructureKind:
    if visual_type in {"timeline", "comparison", "hierarchy", "mind-map"}:
        return visual_type  # type: ignore[return-value]
    return "timeline" if visual_type in {"process", "flow"} else "chart"


__all__ = ["InfographicStructure", "StructureEdge", "StructureKind", "StructureNode", "compile_infographic_structure"]
