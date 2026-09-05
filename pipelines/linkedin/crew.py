"""Deterministic LinkedIn generation Flow with frontend-owned publishing."""

from __future__ import annotations

import re
from typing import Any, Callable

from pipelines.advisory.schemas import QualityReview
from pipelines.common.text_generation import TextTransformationFlow
from pipelines.linkedin.agents import build_agents
from pipelines.linkedin.schemas import LinkedInImageSpec, LinkedInPostOutput
from pipelines.linkedin.tasks import build_tasks


class LinkedInPostFlow(TextTransformationFlow):
    """Generate and validate a LinkedIn draft; never publish it directly."""

    pipeline_name = "linkedin_post"
    agent_factory = staticmethod(build_agents)
    task_factory = staticmethod(build_tasks)
    output_model = LinkedInPostOutput
    quality_model = QualityReview

    # CrewAI's Flow definition builder scans the concrete class namespace;
    # explicitly project the decorated methods onto each public Flow class.
    prepare_context = TextTransformationFlow.prepare_context
    run_crew = TextTransformationFlow.run_crew
    retry_crew = TextTransformationFlow.retry_crew
    validate_crew = TextTransformationFlow.validate_crew
    route_validation = TextTransformationFlow.route_validation
    persist_output = TextTransformationFlow.persist_output
    persist_failure = TextTransformationFlow.persist_failure

    def __init__(
        self,
        memory_manager: Any,
        *,
        max_attempts: int = 2,
        llm: Any = None,
        image_generator: Callable[[str], str] | None = None,
        progress_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(
            memory_manager,
            max_attempts=max_attempts,
            llm=llm,
            progress_callback=progress_callback,
        )
        self.image_generator = image_generator

    def pipeline_options(self, request: Any) -> dict[str, Any]:
        """Resolve image intent from explicit user language before agent judgment."""

        configured = request.metadata.get("linkedin_image")
        if isinstance(configured, bool):
            configured = {"requested": configured}
        if not isinstance(configured, dict):
            configured = {}
        if "requested" in configured:
            policy = "always" if bool(configured["requested"]) else "never"
        else:
            query = request.query.lower()
            explicit_negative = re.search(
                r"\b(no|without|don't|do not|dont)\s+(?:an?\s+)?(?:image|images|visual|infographic)s?\b",
                query,
            )
            explicit_positive = re.search(
                r"\b(?:image|images|visual|visuals|infographic|infographics)\b",
                query,
            )
            if explicit_negative:
                policy = "never"
            elif explicit_positive:
                policy = "always"
            else:
                policy = "auto"
        return {
            "linkedin_image": {
                "policy": policy,
                "image_type": str(configured.get("image_type", "auto")),
                "generator_available": self.image_generator is not None,
            }
        }

    def enrich_output(self, output: Any) -> LinkedInPostOutput:
        """Optionally turn the generated image prompt into an asset URI."""

        if not isinstance(output, LinkedInPostOutput) or not output.image.requested:
            return output
        image = output.image
        if self.image_generator is None:
            if image.strategy == "generate":
                return output.model_copy(update={
                    "image": image.model_copy(update={"strategy": "prompt"}),
                })
            return output
        try:
            asset_uri = self.image_generator(image.generation_prompt)
            if not asset_uri:
                raise ValueError("image generator returned no asset URI")
            return output.model_copy(update={
                "image": image.model_copy(update={"strategy": "asset", "asset_uri": str(asset_uri)}),
            })
        except Exception:
            return output.model_copy(update={
                "image": image.model_copy(update={"strategy": "prompt", "asset_uri": None}),
                "caveats": [*output.caveats, "Image asset generation was unavailable; use the supplied prompt."],
            })
