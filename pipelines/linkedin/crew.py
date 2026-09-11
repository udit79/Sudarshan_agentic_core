"""Deterministic LinkedIn generation Flow with frontend-owned publishing."""

from __future__ import annotations

import re
from typing import Any, Callable

from pipelines.advisory.schemas import QualityReview
from pipelines.common.text_generation import TextTransformationFlow
from pipelines.linkedin.agents import build_agents
from pipelines.linkedin.humanizer import audit_linkedin_text
from pipelines.linkedin.schemas import LinkedInImageSpec, LinkedInPostOutput
from pipelines.linkedin.tasks import build_tasks
from pipelines.linkedin.voice_profile import profile_from_metadata, voice_context


class LinkedInPostFlow(TextTransformationFlow):
    """Generate and validate a LinkedIn draft; never publish it directly."""

    pipeline_name = "linkedin_post"
    agent_factory = staticmethod(build_agents)
    task_factory = staticmethod(build_tasks)
    output_model = LinkedInPostOutput
    quality_model = QualityReview
    human_approval_required = True

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
        self._voice_profile = None

    def pipeline_options(self, request: Any) -> dict[str, Any]:
        """Resolve image intent from explicit user language before agent judgment."""

        configured = request.metadata.get("linkedin_image")
        self._voice_profile = profile_from_metadata(
            request.metadata,
            user_id=str(getattr(request, "user_id", None) or "anonymous"),
        )
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
            },
            "voice_profile": voice_context(self._voice_profile),
        }

    def enrich_output(self, output: Any) -> LinkedInPostOutput:
        """Attach deterministic humanizer state and optionally materialize an image."""
        from pipelines.orchestrator.cross_skill import build_child_plan, select_visual_child_skill


        if not isinstance(output, LinkedInPostOutput):
            return output

        def finalize(value: LinkedInPostOutput) -> LinkedInPostOutput:
            child_plan = build_child_plan(
                "linkedin.post",
                value,
                parent_run_id=self.state.run_id or self.state.task_id or "unbound-linkedin",
                parent_node_id="linkedin_post",
            )
            self.state.artifact = {
                "child_plan": [item.model_dump(mode="json") for item in child_plan],
            }
            return value

        updates: dict[str, Any] = {
            "humanizer_report": audit_linkedin_text(
                output.post_text,
                voice_profile=self._voice_profile.model_dump(mode="json") if self._voice_profile else None,
            ),
            "approval_required": "publish",
            "publish_status": "draft_only",
        }
        if output.image.requested and output.image.image_type in {"diagram", "infographic"}:
            updates["visual_child"] = output.visual_child.model_copy(update={
                "skill_id": select_visual_child_skill(output.image.model_dump(mode="json")),
                "status": "eligible",
            })

        if not output.image.requested:
            return finalize(output.model_copy(update=updates))
        image = output.image
        if self.image_generator is None:
            if image.strategy == "generate":
                updates["image"] = image.model_copy(update={"strategy": "prompt"})
                return finalize(output.model_copy(update=updates))
            return finalize(output.model_copy(update=updates))
        try:
            asset_uri = self.image_generator(image.generation_prompt)
            if not asset_uri:
                raise ValueError("image generator returned no asset URI")
            updates["image"] = image.model_copy(update={"strategy": "asset", "asset_uri": str(asset_uri)})
            return finalize(output.model_copy(update=updates))
        except Exception as exc:
            updates["image"] = image.model_copy(update={"strategy": "prompt", "asset_uri": None})
            from integrations.providers.receipts import classify_provider_error

            failure_class = classify_provider_error(exc)
            updates["caveats"] = [
                *output.caveats,
                f"Image asset generation was unavailable ({failure_class}); use the supplied prompt.",
            ]
            return finalize(output.model_copy(update=updates))

    def prepare_quality_output(self, output: Any) -> LinkedInPostOutput:
        """Run the deterministic humanizer before the model quality verdict."""

        if not isinstance(output, LinkedInPostOutput):
            return output
        return output.model_copy(update={
            "humanizer_report": audit_linkedin_text(
                output.post_text,
                voice_profile=self._voice_profile.model_dump(mode="json") if self._voice_profile else None,
            )
        })

    def quality_output_issues(self, output: Any) -> list[str]:
        """Enforce parent-skill release gates independently of model obedience."""

        if not isinstance(output, LinkedInPostOutput):
            return ["LinkedIn output is not a validated LinkedInPostOutput"]
        issues: list[str] = []
        if not output.claim_bindings:
            issues.append("claim_bindings must identify evidence for every material public claim")
        if not output.humanizer_report.approved:
            issues.extend(issue.message for issue in output.humanizer_report.issues if issue.severity == "block")
        if output.approval_required != "publish" or output.publish_status != "draft_only":
            issues.append("LinkedIn generation must remain draft_only and require separate publish approval")
        return issues
