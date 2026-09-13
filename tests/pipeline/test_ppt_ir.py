from __future__ import annotations

import pytest
from pydantic import ValidationError

from pipelines.ppt.schemas import (
    DeckPlan,
    EvidenceBinding,
    LayoutBox,
    SlideContentIR,
    SlideSpec,
    SlideTask,
    VisualIR,
)


def flowchart_slide() -> SlideSpec:
    evidence = [EvidenceBinding(evidence_id="claim-1")]
    visual = VisualIR(
        visual_id="process-1",
        kind="flowchart",
        bounds=LayoutBox(x=0.1, y=0.25, width=0.8, height=0.55),
        alt_text="Three-stage process",
        evidence=evidence,
        data={"nodes": [{"id": "a"}], "edges": []},
    )
    return SlideSpec(
        slide_id="slide-1",
        sequence=1,
        intent="Explain the process",
        one_message="Evidence moves through three stages",
        layout="flowchart",
        content=SlideContentIR(
            slide_id="slide-1",
            headline="How the process works",
            visuals=[visual],
            evidence=evidence,
        ),
        evidence=evidence,
    )


def test_deck_plan_accepts_typed_visual_and_child_task() -> None:
    deck = DeckPlan(
        presentation_id="deck-1",
        title="Case brief",
        theme_id="ntro-dark",
        slides=[flowchart_slide()],
        tasks=[
            SlideTask(
                task_id="task-flowchart",
                slide_id="slide-1",
                required_skills=["visual.flowchart"],
                output_type="visual-ir",
            )
        ],
    )
    assert deck.slides[0].content.visuals[0].kind == "flowchart"
    assert deck.tasks[0].required_skills == ["visual.flowchart"]


def test_ir_rejects_overflow_placeholders_and_renderer_payloads() -> None:
    with pytest.raises(ValidationError):
        LayoutBox(x=0.9, y=0, width=0.2, height=0.2)
    with pytest.raises(ValidationError):
        SlideContentIR(slide_id="s", headline="TBD: fill later")
    with pytest.raises(ValidationError):
        VisualIR(
            visual_id="bad",
            kind="shape",
            bounds=LayoutBox(x=0, y=0, width=0.2, height=0.2),
            alt_text="bad",
            data={"pptx_xml": "<xml>"},
        )


def test_deck_plan_validates_template_tokens_and_declared_dependencies() -> None:
    first = flowchart_slide()
    second = first.model_copy(update={
        "slide_id": "slide-2",
        "sequence": 2,
        "content": first.content.model_copy(update={"slide_id": "slide-2"}),
        "dependencies": ["slide-1"],
    })
    deck = DeckPlan(
        presentation_id="deck-2",
        title="Case brief",
        theme_id="ntro-dark",
        template_id="ntro-master",
        design_tokens={"accent": "#38BDF8"},
        renderer_capabilities=["svg", "pptx"],
        slides=[first, second],
    )
    assert deck.slides[1].dependencies == ["slide-1"]

    with pytest.raises(ValidationError, match="acyclic"):
        DeckPlan(
            presentation_id="cycle",
            title="Cycle",
            theme_id="theme",
            slides=[
                first.model_copy(update={"dependencies": ["slide-2"]}),
                second,
            ],
        )

