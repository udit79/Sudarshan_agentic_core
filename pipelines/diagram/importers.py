"""Bounded, non-executable diagram interchange importers."""

from __future__ import annotations

import json
import re
from html import unescape
from xml.etree import ElementTree

from pipelines.diagram.family import DiagramEdge, DiagramNode, DiagramSpec


MAX_SOURCE_CHARS = 200_000


def import_mermaid(source: str, *, diagram_id: str = "mermaid-import") -> DiagramSpec:
    text = _bounded(source)
    if re.search(r"<script|javascript:|data:text/html", text, re.IGNORECASE):
        raise ValueError("Mermaid source contains executable content")
    header = re.search(r"(?:flowchart|graph)\s+(LR|TD|TB)\b", text, re.IGNORECASE)
    if not header:
        raise ValueError("only Mermaid flowchart source is supported")
    direction = "left-to-right" if header.group(1).upper() == "LR" else "top-to-bottom"
    nodes: dict[str, DiagramNode] = {}
    edges: list[DiagramEdge] = []
    for match in re.finditer(r"([A-Za-z0-9_-]+)(?:\[\"?([^\]\"]+)\"?\])?\s*-->(?:\|([^|\n]{1,120})\|)?\s*([A-Za-z0-9_-]+)(?:\[\"?([^\]\"]+)\"?\])?", text):
        source_id, source_label, edge_label, target_id, target_label = match.groups()
        nodes.setdefault(source_id, DiagramNode(node_id=source_id, label=unescape(source_label or source_id)))
        nodes.setdefault(target_id, DiagramNode(node_id=target_id, label=unescape(target_label or target_id)))
        edges.append(DiagramEdge(source=source_id, target=target_id, label=unescape((edge_label or "").strip())))
    if not edges:
        raise ValueError("Mermaid source contains no supported edges")
    return DiagramSpec(
        diagram_id=diagram_id,
        kind="flowchart",
        title=diagram_id,
        nodes=list(nodes.values()),
        edges=edges,
        direction=direction,
    )


def import_drawio(source: str, *, diagram_id: str = "drawio-import") -> DiagramSpec:
    text = _bounded(source)
    if re.search(r"<script|javascript:|data:text/html|https?://", text, re.IGNORECASE):
        raise ValueError("Draw.io source contains unsafe content or remote references")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValueError("Draw.io source is not valid XML") from exc
    nodes: dict[str, DiagramNode] = {}
    edges: list[DiagramEdge] = []
    for cell in root.iter():
        if cell.tag.rsplit("}", 1)[-1] != "mxCell":
            continue
        cell_id = cell.attrib.get("id", "")
        value = unescape(re.sub(r"<br\s*/?>", " ", cell.attrib.get("value", ""), flags=re.IGNORECASE)).strip()
        if cell.attrib.get("edge") == "1":
            source_id, target_id = cell.attrib.get("source"), cell.attrib.get("target")
            if source_id and target_id:
                edges.append(DiagramEdge(source=source_id, target=target_id, label=value[:120]))
        elif cell.attrib.get("vertex") == "1" and cell_id:
            nodes[cell_id] = DiagramNode(node_id=cell_id, label=value or cell_id)
    if not nodes:
        raise ValueError("Draw.io source contains no vertex nodes")
    return DiagramSpec(diagram_id=diagram_id, kind="architecture", title=diagram_id, nodes=list(nodes.values()), edges=edges)


def import_excalidraw(source: str, *, diagram_id: str = "excalidraw-import") -> DiagramSpec:
    text = _bounded(source)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Excalidraw source is not valid JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ValueError("Excalidraw source must contain an elements list")
    nodes: dict[str, DiagramNode] = {}
    for element in payload["elements"]:
        if not isinstance(element, dict) or element.get("isDeleted"):
            continue
        if element.get("type") in {"rectangle", "diamond", "ellipse", "text"}:
            element_id = str(element.get("id", ""))
            label = str(element.get("text", "")).strip() or element_id
            if element_id:
                nodes[element_id] = DiagramNode(node_id=element_id, label=label)
    edges: list[DiagramEdge] = []
    for element in payload["elements"]:
        if not isinstance(element, dict) or element.get("type") not in {"arrow", "line"}:
            continue
        start = element.get("startBinding") or {}
        end = element.get("endBinding") or {}
        source_id, target_id = start.get("elementId"), end.get("elementId")
        if source_id in nodes and target_id in nodes and source_id != target_id:
            edges.append(DiagramEdge(source=source_id, target=target_id))
    if not nodes:
        raise ValueError("Excalidraw source contains no supported elements")
    return DiagramSpec(diagram_id=diagram_id, kind="flowchart", title=diagram_id, nodes=list(nodes.values()), edges=edges)


def _bounded(source: str) -> str:
    if not isinstance(source, str) or len(source) > MAX_SOURCE_CHARS:
        raise ValueError(f"diagram import is limited to {MAX_SOURCE_CHARS} characters")
    return source


__all__ = ["import_drawio", "import_excalidraw", "import_mermaid"]
