"""Slide jobs and deterministic presentation quality checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from pptx import Presentation
from pydantic import BaseModel, ConfigDict, Field

from pipelines.common.renderers import default_renderer_registry
from pipelines.ppt.schemas import (
    DeckPlan,
    PresentationOutput,
    PresentationTheme,
    resolve_presentation_theme,
)
from pipelines.ppt.issues import (
    PPTIssue,
    PPT_CONSTRAINT_SLIDE_COUNT,
    PPT_CONSTRAINT_COLOR_PALETTE,
    PPT_CONSTRAINT_FONT,
    PPT_CONSTRAINT_REQUIRED_SECTION,
    PPT_CONSTRAINT_EDITABILITY,
    PPT_CONSTRAINT_Z_ORDER,
)
from pipelines.orchestrator.contracts import RequestConstraints


class PresentationStyleProfile(PresentationTheme):
    """Backward-compatible quality profile built on the canonical theme."""

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
    issues: list[PPTIssue] = Field(default_factory=list)
    repair_recommendations: list[str] = Field(default_factory=list)
    rendered_reports: list[dict[str, object]] = Field(default_factory=list)


def build_slide_jobs(deck: DeckPlan) -> list[SlideJob]:
    """Create bounded dependency-aware slide jobs."""
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
    constraints: RequestConstraints | None = None,
) -> PresentationQualityReport:
    """Run content checks, enforce NP-05 deterministic constraints, then integrity gate."""

    style = style or PresentationStyleProfile()
    normalized_constraints = _normalize_constraints(constraints)
    theme = (
        resolve_presentation_theme(normalized_constraints)
        if normalized_constraints is not None
        else PresentationTheme.model_validate(style.model_dump(exclude={"max_body_items"}))
    )
    issues: list[PPTIssue] = []
    repairs: list[str] = []
    
    total_slide_count = len(output.slides)  # Every slide is explicit in the output

    if output.total_page_budget is not None and total_slide_count > output.total_page_budget:
        issues.append(PPTIssue(
            code="page_budget_exceeded",
            severity="error",
            message=f"Rendered {total_slide_count} slides; budget is {output.total_page_budget}",
            expected=output.total_page_budget,
            actual=total_slide_count,
            repairable=True,
        ))
    
    # 1. Evaluate explicit RequestConstraints
    if normalized_constraints:
        if normalized_constraints.slide_count is not None and total_slide_count != normalized_constraints.slide_count:
            issues.append(PPTIssue(
                code=PPT_CONSTRAINT_SLIDE_COUNT,
                severity="error",
                message=f"Expected {normalized_constraints.slide_count} slides but rendered {total_slide_count}",
                expected=normalized_constraints.slide_count,
                actual=total_slide_count,
                repairable=True
            ))

        if normalized_constraints.required_sections:
            actual_sections = [s.title.lower() for s in output.slides]
            for req in normalized_constraints.required_sections:
                if req.lower() not in actual_sections:
                    issues.append(PPTIssue(
                        code=PPT_CONSTRAINT_REQUIRED_SECTION,
                        severity="error",
                        message=f"Missing required section: {req}",
                        expected=req,
                        actual=None,
                        repairable=True
                    ))
                    
    # 2. Basic structural quality checks
    if total_slide_count > 20:
        issues.append(PPTIssue(
            code=PPT_CONSTRAINT_SLIDE_COUNT,
            severity="warning",
            message="presentation exceeds the maximum slide count limit of 19",
            expected="<= 19",
            actual=total_slide_count,
            repairable=True
        ))
    for slide in output.slides:
        if len(slide.bullets) > style.max_body_items:
            issues.append(PPTIssue(
                code="PPT_CONTENT_DENSITY",
                severity="error",
                message=f"slide {slide.order} exceeds body density budget",
                affected_slide_ids=[slide.slide_id],
                repairable=True
            ))
            repairs.append(f"condense slide {slide.order} to {style.max_body_items} bullets")
        if any(not bullet.strip() for bullet in slide.bullets):
            issues.append(PPTIssue(
                code="PPT_CONTENT_EMPTY",
                severity="error",
                message=f"slide {slide.order} contains an empty bullet",
                affected_slide_ids=[slide.slide_id],
                repairable=True
            ))
            repairs.append(f"remove empty bullets from slide {slide.order}")
            
    # 3. Artifact inspection
    rendered_reports: list[dict[str, object]] = []
    registry = default_renderer_registry()
    for artifact in rendered_artifacts:
        report = registry.inspect("presentation.pptx", artifact)
        rendered_reports.append(report.model_dump(mode="json"))
        for issue_msg in report.issues:
            issues.append(PPTIssue(
                code="PPT_RENDER_ISSUE",
                severity="error",
                message=f"{Path(artifact).name}: {issue_msg}",
                repairable=False
            ))
        contract_issues = _inspect_pptx_contract(artifact, normalized_constraints, theme)
        rendered_reports.append({"artifact": str(artifact), "contract_issues": contract_issues})
        for issue in contract_issues:
            issues.append(PPTIssue(
                code=issue["code"],
                severity="error",
                message=f"{Path(artifact).name}: {issue['message']}",
                expected=issue.get("expected"),
                actual=issue.get("actual"),
                affected_slide_ids=issue.get("affected_slide_ids", []),
                repairable=False,
            ))
            
    # 4. Determine final approval
    has_errors = any(issue.severity == "error" for issue in issues)
    
    return PresentationQualityReport(
        approved=not has_errors,
        slide_count=total_slide_count,
        issues=issues,
        repair_recommendations=repairs,
        rendered_reports=rendered_reports,
    )


def _normalize_constraints(constraints: RequestConstraints | Mapping[str, Any] | None) -> RequestConstraints | None:
    if constraints is None:
        return None
    return constraints if isinstance(constraints, RequestConstraints) else RequestConstraints.model_validate(constraints)


def _inspect_pptx_contract(
    artifact: str | Path,
    constraints: RequestConstraints | None,
    theme: PresentationTheme,
) -> list[dict[str, Any]]:
    """Inspect the actual editable PPTX, not only the pre-rendered IR."""

    issues: list[dict[str, Any]] = []
    try:
        presentation = Presentation(str(artifact))
    except Exception as exc:
        return [{"code": PPT_RENDER_INVALID, "message": f"PPTX cannot be opened: {exc}"}]

    actual_count = len(presentation.slides)
    expected_count = constraints.slide_count if constraints else None
    if expected_count is not None and actual_count != expected_count:
        issues.append({
            "code": PPT_CONSTRAINT_SLIDE_COUNT,
            "message": f"actual PPTX contains {actual_count} slides, expected {expected_count}",
            "expected": expected_count,
            "actual": actual_count,
        })

    accent_seen = False
    for index, slide in enumerate(presentation.slides, start=1):
        shape_names = [str(getattr(shape, "name", "")) for shape in slide.shapes]
        if "theme.accent" in shape_names:
            accent_seen = True
            accent_shape = slide.shapes[shape_names.index("theme.accent")]
            try:
                accent_rgb = accent_shape.fill.fore_color.rgb
            except (AttributeError, ValueError):
                accent_rgb = None
            if accent_rgb is None or f"#{accent_rgb}".upper() != theme.accent.upper():
                issues.append({
                    "code": PPT_CONSTRAINT_COLOR_PALETTE,
                    "message": f"slide {index} accent layer does not use {theme.accent}",
                    "expected": theme.accent,
                    "actual": f"#{accent_rgb}" if accent_rgb is not None else None,
                    "affected_slide_ids": [f"slide-{index}"],
                })
        try:
            background_rgb = slide.background.fill.fore_color.rgb
        except (AttributeError, ValueError):
            background_rgb = None
        if background_rgb is None or f"#{background_rgb}".upper() != theme.background.upper():
            issues.append({
                "code": PPT_CONSTRAINT_COLOR_PALETTE,
                "message": f"slide {index} background does not use {theme.background}",
                "expected": theme.background,
                "actual": f"#{background_rgb}" if background_rgb is not None else None,
                "affected_slide_ids": [f"slide-{index}"],
            })
        text_shapes = [shape for shape in slide.shapes if getattr(shape, "has_text_frame", False)]
        if not text_shapes:
            issues.append({
                "code": PPT_CONSTRAINT_EDITABILITY,
                "message": f"slide {index} has no editable text layer",
                "affected_slide_ids": [f"slide-{index}"],
            })

        title_positions = [pos for pos, shape in enumerate(slide.shapes) if getattr(shape, "is_placeholder", False) and getattr(shape, "placeholder_format", None) and shape.placeholder_format.idx == 0]
        body_positions = [pos for pos, shape in enumerate(slide.shapes) if getattr(shape, "is_placeholder", False) and getattr(shape, "placeholder_format", None) and shape.placeholder_format.idx == 1]
        if title_positions and body_positions and title_positions[0] > body_positions[0]:
            issues.append({
                "code": PPT_CONSTRAINT_Z_ORDER,
                "message": f"slide {index} title layer is behind the body layer",
                "affected_slide_ids": [f"slide-{index}"],
            })

        for shape in text_shapes:
            for paragraph in shape.text_frame.paragraphs:
                for run in paragraph.runs:
                    if run.font.name and run.font.name not in {theme.title_font, theme.body_font}:
                        issues.append({
                            "code": PPT_CONSTRAINT_FONT,
                            "message": f"slide {index} uses an unapproved font: {run.font.name}",
                            "affected_slide_ids": [f"slide-{index}"],
                        })
                    try:
                        rgb = run.font.color.rgb
                    except (AttributeError, ValueError):
                        rgb = None
                    if rgb is not None and f"#{rgb}".upper() not in {value.upper() for value in theme.palette()}:
                        issues.append({
                            "code": PPT_CONSTRAINT_COLOR_PALETTE,
                            "message": f"slide {index} contains a color outside the theme palette: #{rgb}",
                            "affected_slide_ids": [f"slide-{index}"],
                        })
                if len(paragraph.text) > 300:
                    issues.append({
                        "code": "PPT_CONTENT_OVERFLOW",
                        "message": f"slide {index} contains a text run exceeding the overflow budget",
                        "affected_slide_ids": [f"slide-{index}"],
                    })

    if not accent_seen:
        issues.append({
            "code": PPT_CONSTRAINT_COLOR_PALETTE,
            "message": "the selected accent token was not found in the rendered PPTX",
            "expected": theme.accent,
        })
    return issues


__all__ = ["PresentationQualityReport", "PresentationStyleProfile", "SlideJob", "build_slide_jobs", "inspect_presentation"]
