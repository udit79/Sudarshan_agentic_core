"""CrewAI tasks for NTRO briefing presentation generation."""

from __future__ import annotations

import os

from crewai import Agent, Task

from pipelines.advisory.schemas import IntelligenceBrief
from pipelines.common.memory_tools import TaskMemoryWriter
from pipelines.ppt.schemas import DeckPlan, PresentationOutput, PresentationQualityReview


def build_tasks(agents: dict[str, Agent], writer: TaskMemoryWriter) -> dict[str, Task]:
    """Build a sequential, typed crew with deterministic task callbacks."""

    if os.getenv("SUDARSHAN_PPT_FLOW", "staged").strip().lower() == "staged":
        return build_staged_tasks(agents, writer)

    analysis = Task(
        description=(
            "Analyze the NTRO briefing operation {query}. Use only the injected permitted "
            "memory context and the recall_sudarshan_memory tool. Return confirmed facts, "
            "explicitly labeled assessments, entities, evidence with source references and "
            "confidence scores, and intelligence gaps. This analysis will drive the slides.\n"
            "Permitted memory context:\n{memory_context}\n"
            "Central prompt plan:\n{prompt_plan}"
        ),
        expected_output="A validated IntelligenceBrief JSON object.",
        agent=agents["content_analyst"],
        output_pydantic=IntelligenceBrief,
        callback=writer.callback("ppt_content_analyst"),
    )

    output = Task(
        description=(
            "Write a complete NTRO briefing presentation from the intelligence analysis. "
            "The classification is {classification_level}; distribution is {distribution}. "
            "Use the exact PresentationOutput schema. Generate only the number of slides required by the supplied constraints. "
            "Set template_id to `native-default` unless the request explicitly supplies a validated template contract; "
            "do not invent a custom template ID. "
            "A requested exact slide count includes any cover, agenda, conclusion, or closing slide; never add those slides "
            "when they would exceed the requested count. Use the appropriate `layout` field for slides that are actually planned. "
            "Keep slides focused: one topic per slide. Bullets must be complete sentences or "
            "clear noun phrases — no fragments, no filler. Speaker notes must add context not "
            "visible on the slide. Never invent NTRO policy, response authority, or contacts. "
            "Write like a formal NTRO briefing: direct, neutral, precise. "
            "Follow the central prompt plan where compatible with these rules:\n{prompt_plan}\n"
            "Constraints to strictly enforce (e.g. target slide count, colors):\n{constraints}"
        ),
        expected_output="A complete validated PresentationOutput JSON object.",
        agent=agents["presentation_writer"],
        context=[analysis],
        output_pydantic=PresentationOutput,
        callback=writer.callback("ppt_presentation_writer"),
    )

    quality = Task(
        description=(
            "Critically review the PresentationOutput. Check every slide for a clear title, "
            "focused and evidence-linked bullets, and informative speaker notes. "
            "Treat the supplied constraints, especially an exact slide count, as authoritative. "
            "Do not reject a concise deck merely because it has no separate agenda, conclusion, "
            "or key-takeaway slide when adding those slides would violate the requested count; "
            "evaluate those requirements within the available slides instead. "
            "Verify any agenda, conclusion, or key-takeaway content that is actually requested. "
            "Reject placeholder text, unsupported claims, invented organizational authority, "
            "AI self-reference, meta-commentary, vague or unfocused slides, unresolved evidence "
            "labels, and missing gaps. "
            "Return PresentationQualityReview with approved=true only if release-ready. "
            "If false, list precise slide-level and constraint-aware structural issues for retry. "
            "Constraints to apply: {constraints}"
        ),
        expected_output="A validated PresentationQualityReview JSON object.",
        agent=agents["quality_critic"],
        context=[output],
        output_pydantic=PresentationQualityReview,
        callback=writer.callback("ppt_quality_critic"),
    )

    return {"analysis": analysis, "output": output, "quality": quality}


def build_staged_tasks(agents: dict[str, Agent], writer: TaskMemoryWriter) -> dict[str, Task]:
    """Build the staged PPT path behind an explicit feature flag.

    The final output remains ``PresentationOutput`` for compatibility with the
    existing flow. The plan and visual-routing tasks produce typed IR before
    the writer converts it into that legacy delivery model.
    """

    grounding = Task(
        description=(
            "Ground the briefing in permitted memory for {query}. Return confirmed facts, "
            "assessments, evidence IDs, confidence, and gaps. Never invent unsupported claims.\n"
            "Permitted memory context:\n{memory_context}\nCentral prompt plan:\n{prompt_plan}"
        ),
        expected_output="A validated IntelligenceBrief JSON object.",
        agent=agents["content_analyst"],
        output_pydantic=IntelligenceBrief,
        callback=writer.callback("ppt_grounding"),
    )
    plan = Task(
        description=(
            "Create a DeckPlan from the grounded intelligence. Give every slide one message, "
            "choose a layout archetype, include evidence bindings, and create a SlideTask for "
            "visual.flowchart when process/dependency structure is central. Do not emit PPTX XML."
        ),
        expected_output="A validated DeckPlan JSON object.",
        agent=agents["deck_planner"],
        context=[grounding],
        output_pydantic=DeckPlan,
        callback=writer.callback("ppt_deck_planner"),
    )
    visual_routing = Task(
        description=(
            "Review the DeckPlan and return the same typed plan with explicit visual routing. "
            "Use visual.flowchart only for meaningful graph structure; keep the child input and "
            "output references typed and bounded. Do not create renderer-specific markup."
        ),
        expected_output="A validated DeckPlan with deterministic visual task references.",
        agent=agents["visual_router"],
        context=[plan],
        output_pydantic=DeckPlan,
        callback=writer.callback("ppt_visual_router"),
    )
    output = Task(
        description=(
            "Convert the grounded intelligence and routed DeckPlan into a complete validated "
            "PresentationOutput. Preserve evidence bindings, one message per slide, speaker "
            "notes, uncertainty, and gaps. Use only typed child artifact references for visuals. "
            "The classification is {classification_level}; distribution is {distribution}. "
            "Set template_id to `native-default` unless a validated template contract is explicitly supplied. "
            "The constraints are authoritative: {constraints}. If an exact slide count is supplied, "
            "the `slides` array must contain exactly that many slides, including any cover or closing slide."
        ),
        expected_output="A complete validated PresentationOutput JSON object.",
        agent=agents["presentation_writer"],
        context=[grounding, plan, visual_routing],
        output_pydantic=PresentationOutput,
        callback=writer.callback("ppt_slide_content"),
    )
    quality = Task(
        description=(
            "Review the staged PresentationOutput and its plan. Check evidence bindings, one "
            "message per slide, visual routing, placeholders, overflow risks, agenda alignment, "
            "gaps, unsupported claims, and exact slide/page-count constraints. Return precise slide-level repair IDs."
        ),
        expected_output="A validated PresentationQualityReview JSON object.",
        agent=agents["quality_critic"],
        context=[plan, visual_routing, output],
        output_pydantic=PresentationQualityReview,
        callback=writer.callback("ppt_staged_quality_critic"),
    )
    return {
        "grounding": grounding,
        "plan": plan,
        "visual_routing": visual_routing,
        "output": output,
        "quality": quality,
    }
