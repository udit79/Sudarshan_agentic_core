"""Slide jobs and deterministic presentation quality checks."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from pipelines.common.renderers import default_renderer_registry
from pipelines.ppt.schemas import DeckPlan, PresentationOutput


class PresentationStyleProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_id: str = Field(default="ntro-briefing", min_length=1)
    background: str = "#0B1220"
    foreground: str = "#F8FAFC"
    accent: str = "#38BDF8"
    body_font: str = "Aptos"
    max_body_items: int = Field(default=5, ge=1, le=8)


class SlideJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    slide_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    dependencies: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class PresentationQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    slide_count: int = Field(ge=0)
    issues: list[str] = Field(default_factory=list)
    repair_recommendations: list[str] = Field(default_factory=list)
    rendered_reports: list[dict[str, object]] = Field(default_factory=list)


def build_slide_jobs(deck: DeckPlan) -> list[SlideJob]:
    """Create bounded dependency-aware slide jobs.

    Explicit plan dependencies are preserved. The legacy sequential chain is
    retained only when a slide has no declared dependencies.
    """

    task_by_slide = {task.slide_id: task for task in deck.tasks}
    jobs: list[SlideJob] = []
    job_ids = {
        slide.slide_id: (
            task_by_slide[slide.slide_id].task_id
            if slide.slide_id in task_by_slide
            else f"slide:{slide.slide_id}"
        )
        for slide in deck.slides
    }
    previous: str | None = None
    for slide in sorted(deck.slides, key=lambda item: item.sequence):
        task = task_by_slide.get(slide.slide_id)
        job_id = job_ids[slide.slide_id]
        dependencies = list(slide.dependencies)
        if slide.slide_id in deck.slide_dependencies:
            dependencies = list(deck.slide_dependencies[slide.slide_id])
        if task and task.dependencies:
            dependencies.extend(task.dependencies)
        if not dependencies and previous:
            dependencies = [previous]
        jobs.append(SlideJob(
            job_id=job_id,
            slide_id=slide.slide_id,
            sequence=slide.sequence,
            dependencies=[job_ids.get(item, item) for item in dict.fromkeys(dependencies)],
            required_skills=list(task.required_skills) if task else [],
            evidence_ids=[binding.evidence_id for binding in [*slide.evidence, *slide.content.evidence]],
        ))
        previous = job_id
    return jobs


def inspect_presentation(
    output: PresentationOutput,
    *,
    style: PresentationStyleProfile | None = None,
    rendered_artifacts: Iterable[str | Path] = (),
) -> PresentationQualityReport:
    """Run content checks, then the shared integrity gate on rendered files."""

    style = style or PresentationStyleProfile()
    issues: list[str] = []
    repairs: list[str] = []
    if len(output.slides) > 15:
        issues.append("presentation exceeds the maximum slide count")
    for slide in output.slides:
        if len(slide.bullets) > style.max_body_items:
            issues.append(f"slide {slide.slide_number} exceeds body density budget")
            repairs.append(f"condense slide {slide.slide_number} to {style.max_body_items} bullets")
        if any(not bullet.strip() for bullet in slide.bullets):
            issues.append(f"slide {slide.slide_number} contains an empty bullet")
            repairs.append(f"remove empty bullets from slide {slide.slide_number}")
    rendered_reports: list[dict[str, object]] = []
    registry = default_renderer_registry()
    for artifact in rendered_artifacts:
        report = registry.inspect("presentation.pptx", artifact)
        rendered_reports.append(report.model_dump(mode="json"))
        issues.extend(f"{Path(artifact).name}: {issue}" for issue in report.issues)
    return PresentationQualityReport(
        approved=not issues,
        slide_count=len(output.slides) + 4,
        issues=issues,
        repair_recommendations=repairs,
        rendered_reports=rendered_reports,
    )


__all__ = ["PresentationQualityReport", "PresentationStyleProfile", "SlideJob", "build_slide_jobs", "inspect_presentation"]
