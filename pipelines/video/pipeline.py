"""Sudarshan pipeline adapter for the isolated MoneyPrinterTurbo worker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from memory import KnowledgeUnit, MemoryType, ScopeType, Source, SourceType
from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines.common.memory_tools import MemoryManagerLike, MemoryRuntime, TaskMemoryWriter
from pipelines.video.contracts import VideoPackage
from pipelines.video.native_generator import (
    NativeVideoGenerator, 
    scenes_from_package, 
    scenes_from_script
)
from integrations.providers.moneyprinterturbo import MoneyPrinterTurboClient


class VideoPipeline:
    pipeline_name = "video"

    def __init__(
        self,
        memory_manager: MemoryManagerLike,
        *,
        generator: NativeVideoGenerator | None = None,
        client: MoneyPrinterTurboClient | None = None,
    ) -> None:
        self.memory_manager = memory_manager
        self.generator = generator or NativeVideoGenerator()
        self.client = client

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
            else:
                script = str(request.metadata.get("video_script") or memory_context).strip()[:20000]
                scenes = scenes_from_script(script, subject)
                
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
                result = self.generator.generate(subject=subject, scenes=scenes, artifact_name=f"video-{run_id}")
                if result.status == "failed":
                    writer.write("video_generation", "failed", result.error or "Native video generation failed")
                    return PipelineResponse(
                        status="failed", pipeline=self.pipeline_name, task_id=request.task_id,
                        run_id=run_id, failure=result.error or "video generation failed",
                        metadata={"provider": "native"},
                    )
                artifact = {
                    "provider": "native",
                    "video_path": result.video_path,
                    "duration_seconds": result.duration_seconds,
                    "scene_count": result.scene_count,
                    "status_url": f"file://{Path(result.video_path).resolve()}" if result.video_path else None,
                }
                output = {"provider": "native", "subject": subject, "status": "succeeded"}
            
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
                metadata={"provider": "moneyprinterturbo" if self.client is not None else "native",
                          "human_approval_required": False},
            )
        except Exception as exc:
            try:
                writer.write("video_generation", "failed", str(exc))
            except Exception:
                pass
            return PipelineResponse(
                status="failed", pipeline=self.pipeline_name, task_id=request.task_id,
                run_id=run_id, failure=str(exc), metadata={"provider": "native"},
            )
