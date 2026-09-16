from pipelines.ppt.presentation_quality import build_slide_jobs, inspect_presentation
from pipelines.ppt.schemas import DeckPlan, PresentationOutput, SlideContent, SlideSpec


def _output(bullets=None):
    return PresentationOutput(
        presentation_id="brief-1",
        title="Brief",
        classification_level="RESTRICTED",
        distribution="Authorized",
        slides=[
            SlideContent(slide_id="cover", order=1, title="Cover", bullets=[], layout="cover"),
            SlideContent(slide_id="agenda", order=2, title="Agenda", bullets=["Context", "Decision"], layout="agenda"),
            SlideContent(slide_id="s1", order=3, title="Context", bullets=bullets or ["One"], layout="content"),
            SlideContent(slide_id="s2", order=4, title="Decision", bullets=["Two"], layout="content"),
            SlideContent(slide_id="conclusion", order=5, title="Conclusion", bullets=["Takeaway"], layout="conclusion"),
            SlideContent(slide_id="closing", order=6, title="Closing", bullets=["High"], layout="closing"),
        ],
    )


def test_presentation_quality_builds_ordered_slide_jobs_and_checks_rendered_pptx(tmp_path):
    deck = DeckPlan(
        presentation_id="brief-1",
        title="Brief",
        theme_id="ntro",
        slides=[
            SlideSpec(slide_id="s1", sequence=1, intent="context", one_message="Context", content={"slide_id": "s1", "headline": "Context"}),
            SlideSpec(slide_id="s2", sequence=2, intent="decision", one_message="Decision", content={"slide_id": "s2", "headline": "Decision"}),
        ],
    )
    jobs = build_slide_jobs(deck)
    assert jobs[0].dependencies == []
    assert jobs[1].dependencies == [jobs[0].job_id]

    from pipelines.ppt.renderer import render_presentation
    artifact = render_presentation(_output())
    report = inspect_presentation(_output(), rendered_artifacts=[artifact.path])
    assert report.approved is True


def test_presentation_quality_reports_density_repairs():
    report = inspect_presentation(_output(["1", "2", "3", "4", "5", "6"]))
    assert report.approved is False
    assert report.repair_recommendations
