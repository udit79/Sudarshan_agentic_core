"""Adapters between the real infographic output contract and semantic IR."""

from __future__ import annotations

from pipelines.infographic.schemas import (
    DiagramEdge,
    DiagramIR,
    DiagramNode,
    InfographicBlock,
    InfographicIR,
    InfographicOutput,
)
from pipelines.infographic.templates import select_infographic_template


def infographic_ir_from_output(output: InfographicOutput) -> InfographicIR:
    """Build semantic blocks from the final validated system output."""

    blocks = [
        InfographicBlock(
            block_id=item.evidence_id,
            label=item.claim[:180],
            description=item.evidence_summary[:500],
            kind="observation",
            evidence_ids=[item.evidence_id],
        )
        for item in output.evidence
    ]
    return InfographicIR(
        infographic_id=output.infographic_id,
        title=output.title,
        visual_type="list" if output.visual_type == "auto" else output.visual_type,
        alt_text=output.alt_text,
        blocks=blocks,
        evidence_ids=[item.evidence_id for item in output.evidence],
        caveats=list(output.caveats),
    )


def infographic_ir_to_syntax(ir: InfographicIR) -> str:
    """Compile semantic IR into the current renderer's stable AntV DSL."""

    selection = select_infographic_template(ir.visual_type)
    lines = [f"infographic {selection.template.directive}", "data", "  lists"]
    lines.extend(["    - label Brief", f"      desc {_safe(ir.title)}"])
    for block in ir.blocks:
        label = f"[{block.block_id}] {_safe(block.label)}"
        desc = _safe(block.description)
        lines.extend([f"    - label {label}", f"      desc {desc}"])
    for caveat in ir.caveats:
        lines.extend(["    - label Caveat", f"      desc {_safe(caveat)}"])
    return "\n".join(lines)


def diagram_ir_from_output(output: InfographicOutput) -> DiagramIR:
    """Create a graph IR only for process/flow outputs where order is meaningful."""

    if output.visual_type not in {"process", "flow", "timeline"}:
        raise ValueError("diagram IR requires process, flow, or timeline visual_type")
    nodes = [
        DiagramNode(
            node_id=item.evidence_id,
            label=item.claim[:180],
            kind="process",
            evidence_ids=[item.evidence_id],
        )
        for item in output.evidence
    ]
    edges = [
        DiagramEdge(source=nodes[index].node_id, target=nodes[index + 1].node_id)
        for index in range(len(nodes) - 1)
    ]
    return DiagramIR.model_validate(
        DiagramIR(diagram_id=output.infographic_id, title=output.title, nodes=nodes, edges=edges)
    )


def _safe(value: str) -> str:
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").replace("'", "").replace('"', "").split())[:220]


__all__ = ["diagram_ir_from_output", "infographic_ir_from_output", "infographic_ir_to_syntax"]
