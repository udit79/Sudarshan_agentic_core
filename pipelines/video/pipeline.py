"""Sudarshan native video skill composition with legacy adapter support."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from threading import Event
from typing import Mapping

from memory import KnowledgeUnit, MemoryType, ScopeType, Source, SourceType
from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines.common.memory_tools import MemoryManagerLike, MemoryRuntime, TaskMemoryWriter
from pipelines.orchestrator.constants import STAGE_RECALL_GROUNDING_TOKENS, truncate_to_token_budget
from pipelines.video.contracts import VideoPackage
from pipelines.video.native_generator import NativeVideoGenerator
from pipelines.video.planner import OpenAIVideoPlanner
from pipelines.video.skills import NativeVideoRenderSkill, NativeVideoStoryboardSkill
from pipelines.video.provider_jobs import VideoProviderJobStore
from integrations.providers.moneyprinterturbo import MoneyPrinterTurboClient


class VideoPipeline:
    pipeline_name = "video"

    def __init__(
        self,
        memory_manager: MemoryManagerLike,
        *,
        generator: NativeVideoGenerator | None = None,
        client: MoneyPrinterTurboClient | None = None,
        planner: OpenAIVideoPlanner | None = None,
        provider_job_store: VideoProviderJobStore | None = None,
    ) -> None:
        self.memory_manager = memory_manager
        self.generator = generator or NativeVideoGenerator()
        self.client = client
        self.provider_job_store = provider_job_store or (
            VideoProviderJobStore(os.getenv("SUDARSHAN_VIDEO_PROVIDER_JOBS_DB", "artifacts/.state/video_provider_jobs.db"))
            if client is not None
            else None
        )
        self.planner = planner or OpenAIVideoPlanner()
        self.storyboard_skill = NativeVideoStoryboardSkill(self.planner)
        self.render_skill = NativeVideoRenderSkill(self.generator)

    def _runtime(self, request: AdvisoryRequest) -> MemoryRuntime:
        return MemoryRuntime(
            manager=self.memory_manager,
            context=request.access_context,
            task_id=request.task_id,
            case_id=request.case_id,
            run_id=str(request.metadata.get("run_id", request.task_id)),
            pipeline_name=self.pipeline_name,
        )

    def run(self, request: AdvisoryRequest, *, cancel_event: Event | None = None) -> PipelineResponse:
        from pipelines.orchestrator.cross_skill import build_child_plan

        runtime = self._runtime(request)
        writer = TaskMemoryWriter(runtime)
        run_id = runtime.run_id
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("video generation cancelled cooperatively")
            writer.write("video_generation", "started", "Starting native video generation.")
            memory_context = truncate_to_token_budget(
                str(request.metadata.get("resolved_memory_context", "")),
                STAGE_RECALL_GROUNDING_TOKENS,
            )
            package_data = request.metadata.get("video_package")
            package = VideoPackage.model_validate(package_data) if isinstance(package_data, Mapping) else None
            
            subject = str(
                (package.subject if package is not None else request.metadata.get("video_subject"))
                or request.query
            ).strip()[:500]
            
            package, scenes = self.storyboard_skill.prepare(
                request,
                subject=subject,
                memory_context=memory_context,
                package_data=package.model_dump() if package is not None else None,
                prefer_query_script=self.client is not None,
                cancel_event=cancel_event,
            )
                
            # An explicitly selected native-compatible renderer must stay
            # inside Sudarshan even when an optional legacy client is
            # configured.  The default remains backward-compatible: a
            # configured external client handles the legacy path unless the
            # package opts into the native compatibility adapter.
            native_renderer_requested = (
                package is not None
                and package.provider_options.renderer_id == "video.moneyprinter-compatible"
            )
            if self.client is not None and not native_renderer_requested:
                provider_options = package.provider_payload() if package is not None else {}
                script = truncate_to_token_budget(
                    str(provider_options.pop("video_script", "") or "\n\n".join(
                        scene.narration for scene in scenes if scene.narration
                    ) or memory_context).strip(),
                    STAGE_RECALL_GROUNDING_TOKENS,
                )
                submit_fingerprint = hashlib.sha256(
                    json.dumps(
                        {"subject": subject, "script": script, "options": provider_options},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                if self.provider_job_store is not None:
                    self.provider_job_store.record_submit_start(
                        run_id, "moneyprinterturbo", submit_fingerprint
                    )
                try:
                    result = self.client.generate(
                        subject=subject,
                        script=script,
                        options=provider_options,
                        cancel_event=cancel_event,
                    )
                except Exception as exc:
                    if self.provider_job_store is not None:
                        self.provider_job_store.record_submit_unknown(run_id, str(exc))
                    raise
                artifact = {
                    "provider": "moneyprinterturbo",
                    "provider_task_id": result.provider_task_id,
                    **dict(result.data),
                }
                if self.provider_job_store is not None:
                    if result.status == "pending":
                        self.provider_job_store.record_submit_success(
                            run_id, result.provider_task_id, status="pending"
                        )
                    elif result.status in {"succeeded", "failed", "cancelled"}:
                        self.provider_job_store.record_submit_success(
                            run_id, result.provider_task_id, status="pending"
                        )
                        self.provider_job_store.record_terminal(
                            run_id,
                            status=result.status,
                            receipt=result.data,
                            error=result.error,
                        )
                if result.status == "failed":
                    writer.write("video_generation", "failed", result.error or "MoneyPrinterTurbo failed")
                    return PipelineResponse(
                        status="failed", pipeline=self.pipeline_name, task_id=request.task_id,
                        run_id=run_id, failure=result.error or "video provider failed",
                        artifact=artifact,
                        metadata={"provider": "moneyprinterturbo", "human_approval_required": False},
                    )
                if result.status == "pending":
                    writer.write("video_generation", "pending", json.dumps(artifact, ensure_ascii=False))
                    return PipelineResponse(
                        status="pending", pipeline=self.pipeline_name, task_id=request.task_id,
                        run_id=run_id, artifact=artifact,
                        metadata={"provider": "moneyprinterturbo", "human_approval_required": False},
                    )
                if result.status == "cancelled":
                    return PipelineResponse(
                        status="failed", pipeline=self.pipeline_name, task_id=request.task_id,
                        run_id=run_id, failure=result.error or "video generation cancelled",
                        artifact=artifact,
                        metadata={
                            "provider": "moneyprinterturbo",
                            "cancellation_requested": True,
                            "human_approval_required": False,
                        },
                    )
                output = {"provider": "moneyprinterturbo", "subject": subject, "status": "succeeded"}
            else:
                attempt_id = str(request.metadata.get("attempt_id") or "1")
                result = self.render_skill.render(
                    package,
                    scenes=scenes,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    cancel_event=cancel_event,
                    authorization_scope={
                        "user_id": request.user_id,
                        "case_id": request.case_id,
                        "classification_level": request.classification_level,
                        "distribution": request.distribution,
                    },
                )
                if result.status == "failed":
                    writer.write("video_generation", "failed", result.error or "Native video generation failed")
                    return PipelineResponse(
                        status="failed", pipeline=self.pipeline_name, task_id=request.task_id,
                        run_id=run_id, failure=result.error or "video generation failed",
                        metadata={"provider": "openai-native"},
                    )
                scene_records = list(result.metadata.get("scenes", []))
                package_payload = package.model_dump() if package is not None else {
                    "subject": subject,
                    "title": subject,
                    "script": "\n\n".join(scene.narration for scene in scenes),
                    "storyboard": [scene.model_dump() for scene in scenes],
                }
                package_payload["storyboard"] = scene_records or package_payload.get("storyboard", [])
                package_root = Path(
                    result.metadata.get("package_dir", Path("artifacts") / "videos" / str(run_id))
                )
                package_root.mkdir(parents=True, exist_ok=True)
                script_path = package_root / "script.txt"
                storyboard_path = package_root / "storyboard.json"
                manifest_path = package_root / "manifest.json"
                script_path.write_text(str(package_payload.get("script", "")), encoding="utf-8")
                storyboard_path.write_text(json.dumps(package_payload["storyboard"], ensure_ascii=False, indent=2), encoding="utf-8")
                manifest = {
                    "provider": "openai-native",
                    "subject": subject,
                    "title": package_payload.get("title", subject),
                    "script_path": str(script_path),
                    "storyboard_path": str(storyboard_path),
                    "video_path": result.video_path,
                    "duration_seconds": result.duration_seconds,
                    "scene_count": result.scene_count,
                    "scenes": scene_records,
                    "quality_report": result.metadata.get("quality_report"),
                    "subtitle_path": result.metadata.get("subtitle_path"),
                    "music_path": result.metadata.get("music_path"),
                }
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                artifact = {
                    "provider": "openai-native",
                    "package_dir": str(package_root),
                    "manifest_path": str(manifest_path),
                    "script_path": str(script_path),
                    "storyboard_path": str(storyboard_path),
                    "story": package_payload.get("script", ""),
                    "storyboard": package_payload["storyboard"],
                    "video_path": result.video_path,
                    "duration_seconds": result.duration_seconds,
                    "scene_count": result.scene_count,
                    "status_url": f"file://{Path(result.video_path).resolve()}" if result.video_path else None,
                    "quality_report": result.metadata.get("quality_report"),
                    "subtitle_path": result.metadata.get("subtitle_path"),
                    "music_path": result.metadata.get("music_path"),
                    "failed_scene_ids": result.metadata.get("failed_scene_ids", []),
                    "degraded": result.status == "partial" or bool(result.metadata.get("failed_scene_ids")),
                }
                quality_report = result.metadata.get("quality_report") or {}
                if quality_report.get("status") == "failed":
                    writer.write("video_generation", "failed", "Rendered video failed deterministic media QA.")
                    return PipelineResponse(
                        status="failed", pipeline=self.pipeline_name, task_id=request.task_id,
                        run_id=run_id, failure="Rendered video failed deterministic media QA.",
                        artifact=artifact,
                        metadata={"provider": "openai-native", "quality_report": quality_report},
                    )
                if result.status == "partial":
                    writer.write(
                        "video_generation",
                        "partial",
                        f"Video generated with partial scene failures: {result.metadata.get('failed_scene_ids')}",
                    )
                    return PipelineResponse(
                        status="partial",
                        pipeline=self.pipeline_name,
                        task_id=request.task_id,
                        run_id=run_id,
                        failure=f"Video generated partially; failed scenes: {result.metadata.get('failed_scene_ids')}",
                        output={"provider": "openai-native", "subject": subject, "status": "partial"},
                        artifact=artifact,
                        metadata={
                            **(dict(result.metadata) if self.client is None else {}),
                            "provider": "openai-native",
                            "human_approval_required": False,
                            "degraded": True,
                            "failed_scene_ids": result.metadata.get("failed_scene_ids", []),
                        },
                    )
                output = {"provider": "openai-native", "subject": subject, "status": "succeeded"}

            child_plan = build_child_plan(
                "video.storyboard",
                package,
                parent_run_id=run_id,
                parent_node_id="video.storyboard",
            )
            artifact["child_plan"] = [item.model_dump(mode="json") for item in child_plan]
            
            writer.write("video_generation", "succeeded", json.dumps(output, ensure_ascii=False))
            
            from pipelines.common.release_gate import can_release_to_case_memory
            allowed, _ = can_release_to_case_memory(
                pipeline=self.pipeline_name,
                output=output,
                quality_approved=True,
                status="succeeded",
                artifact=artifact,
                human_approval_required=False,
                human_approved=True,
            )
            if allowed:
                unit = KnowledgeUnit(
                    unit_id=f"video-{run_id}",
                    content=json.dumps({"output": output, "artifact": artifact}, ensure_ascii=False),
                    source=Source(source_id=run_id, source_type=SourceType.VIDEO,
                                  source_reference=f"pipeline://video/{run_id}"),
                    metadata={"pipeline": self.pipeline_name, "delivery_owner": "frontend", "artifact": artifact},
                    provenance={"task_id": request.task_id, "case_id": request.case_id, "run_id": run_id,
                                "memory_policy": "validated_output_case_write_back"},
                )
                self.memory_manager.remember(unit, request.access_context, scope_type=ScopeType.CASE,
                                             memory_type=MemoryType.SUMMARY)
            return PipelineResponse(
                status="succeeded", pipeline=self.pipeline_name, task_id=request.task_id,
                run_id=run_id, output=output, artifact=artifact,
                metadata={
                    **(dict(result.metadata) if self.client is None else {}),
                    "provider": "moneyprinterturbo" if self.client is not None else "openai-native",
                    "human_approval_required": False,
                    "stages": ["storyboard", "scene-media", "composition", "qa"],
                },
            )
        except Exception as exc:
            try:
                writer.write("video_generation", "failed", str(exc))
            except Exception:
                pass
            return PipelineResponse(
                status="failed", pipeline=self.pipeline_name, task_id=request.task_id,
                run_id=run_id, failure=str(exc), metadata={"provider": "openai-native"},
            )

    def reconcile_provider_job(self, run_id: str):
        """Reconcile one durable MoneyPrinterTurbo job after a retry/restart."""

        if self.client is None or self.provider_job_store is None:
            return None

        def check(_provider: str, provider_task_id: str):
            if not provider_task_id:
                return "submit_unknown", None, "provider task ID is not available"
            result = self.client.status(provider_task_id)
            return result.status, result.data, result.error

        return self.provider_job_store.reconcile_job(run_id, check)
