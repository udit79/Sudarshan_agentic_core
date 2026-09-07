"""Sudarshan pipeline adapter for the isolated MoneyPrinterTurbo worker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from memory import KnowledgeUnit, MemoryType, ScopeType, Source, SourceType
from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines.common.memory_tools import MemoryManagerLike, MemoryRuntime, TaskMemoryWriter
from pipelines.video.contracts import VideoPackage, VideoScene as VideoContractScene
from pipelines.video.native_generator import (
    NativeVideoGenerator,
    VideoScene as NativeVideoScene,
    scenes_from_package,
    scenes_from_script,
)
from pipelines.video.planner import CrewAIVideoPlanner, OpenAIVideoPlanner
from integrations.providers.moneyprinterturbo import MoneyPrinterTurboClient


def _contract_scene(scene: NativeVideoScene) -> VideoContractScene:
    """Convert the native renderer scene into the validated package contract."""

    return VideoContractScene(
        scene_id=scene.scene_id,
        narration=scene.narration,
        visual_description=scene.visual_description,
        duration_seconds=scene.duration_seconds,
        on_screen_text=scene.on_screen_text,
        image_path=scene.image_path,
        audio_path=scene.audio_path,
        video_path=scene.video_path,
    )


def _scene_payload(scene: NativeVideoScene) -> dict[str, Any]:
    """Serialize a native scene without assuming it is a Pydantic model."""

    return _contract_scene(scene).model_dump(mode="json")


class VideoPipeline:
    pipeline_name = "video"

    def __init__(
        self,
        memory_manager: MemoryManagerLike,
        *,
        generator: NativeVideoGenerator | None = None,
        client: MoneyPrinterTurboClient | None = None,
        planner: CrewAIVideoPlanner | OpenAIVideoPlanner | None = None,
    ) -> None:
        self.memory_manager = memory_manager
        self.generator = generator or NativeVideoGenerator()
        self.client = client
        self.planner = planner or CrewAIVideoPlanner()

    def _runtime(self, request: AdvisoryRequest) -> MemoryRuntime:
        return MemoryRuntime(
            manager=self.memory_manager,
            context=request.access_context,
            task_id=request.task_id,
            case_id=request.case_id,
            run_id=str(request.metadata.get("run_id", request.task_id)),
            pipeline_name=self.pipeline_name,
        )

    def run(self, request: AdvisoryRequest) -> PipelineResponse:
        runtime = self._runtime(request)
        writer = TaskMemoryWriter(runtime)
        run_id = runtime.run_id
        try:
            writer.write("video_generation", "started", "Starting native video generation.")
            memory_context = str(request.metadata.get("resolved_memory_context", ""))[:30000]
            package_data = request.metadata.get("video_package")
            package = VideoPackage.model_validate(package_data) if isinstance(package_data, Mapping) else None
            
            subject = str(
                (package.subject if package is not None else request.metadata.get("video_subject"))
                or request.query
            ).strip()[:500]
            
            if package is not None:
                scenes = scenes_from_package(package.model_dump())
            elif self.client is not None:
                # Preserve the explicit legacy worker contract without
                # requiring the OpenAI planner for provider-owned jobs.
                supplied_script = str(
                    request.metadata.get("video_script") or memory_context or request.query
                ).strip()[:20000]
                scenes = scenes_from_script(supplied_script, subject)
                package = VideoPackage(
                    subject=subject,
                    title=subject,
                    script=supplied_script,
                    storyboard=[
                        _contract_scene(scene)
                        for scene in scenes
                    ],
                )
            else:
                supplied_script = str(request.metadata.get("video_script") or "").strip()[:20000]
                if supplied_script:
                    package = VideoPackage(
                        subject=subject,
                        title=subject,
                        script=supplied_script,
                        storyboard=[
                            _contract_scene(scene)
                            for scene in scenes_from_script(supplied_script, subject)
                        ],
                    )
                else:
                    package = self.planner.plan(
                        subject=subject,
                        query=request.query,
                        memory_context=memory_context,
                        prompt_plan=dict(request.metadata.get("prompt_plan") or {}),
                        task_writer=writer,
                    )
                scenes = scenes_from_package(package.model_dump())
                
            if self.client is not None:
                provider_options = package.provider_payload() if package is not None else {}
                script = str(provider_options.pop("video_script", "") or "\n\n".join(
                    scene.narration for scene in scenes if scene.narration
                ) or memory_context).strip()[:20000]
                result = self.client.generate(subject=subject, script=script, options=provider_options)
                artifact = {
                    "provider": "moneyprinterturbo",
                    "provider_task_id": result.provider_task_id,
                    **dict(result.data),
                }
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
                output = {"provider": "moneyprinterturbo", "subject": subject, "status": "succeeded"}
            else:
                package_dir = Path("artifacts") / "videos" / str(run_id)
                result = self.generator.generate(
                    subject=subject,
                    scenes=scenes,
                    artifact_name=f"video-{run_id}",
                    package_dir=package_dir,
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
                    "storyboard": [_scene_payload(scene) for scene in scenes],
                }
                package_payload["storyboard"] = scene_records or package_payload.get("storyboard", [])
                package_root = Path(result.metadata.get("package_dir", package_dir))
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
                }
                output = {"provider": "openai-native", "subject": subject, "status": "succeeded"}
            
            writer.write("video_generation", "succeeded", json.dumps(output, ensure_ascii=False))
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
                metadata={"provider": "moneyprinterturbo" if self.client is not None else "openai-native",
                          "human_approval_required": False},
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
