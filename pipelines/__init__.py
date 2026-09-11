"""Controlled, application-specific pipelines built on Sudarshan memory.

Pipeline modules are loaded lazily so storage, contracts, and ingestion can be
used without importing every CrewAI flow at package-import time.
"""

from __future__ import annotations

from importlib import import_module

from pipelines.common.contracts import AdvisoryRequest, PipelineResponse


_LAZY_EXPORTS = {
    "AdvisoryFlow": ("pipelines.advisory.crew", "AdvisoryFlow"),
    "ExecutiveSummaryFlow": ("pipelines.executive_summary.crew", "ExecutiveSummaryFlow"),
    "InfographicFlow": ("pipelines.infographic.crew", "InfographicFlow"),
    "LinkedInPostFlow": ("pipelines.linkedin.crew", "LinkedInPostFlow"),
    "PresentationFlow": ("pipelines.ppt.crew", "PresentationFlow"),
    "MoneyPrinterTurboClient": ("pipelines.video", "MoneyPrinterTurboClient"),
    "VideoPipeline": ("pipelines.video", "VideoPipeline"),
    "InMemoryProgressSink": ("pipelines.orchestrator", "InMemoryProgressSink"),
    "OrchestrationResult": ("pipelines.orchestrator", "OrchestrationResult"),
    "orchestration_result_to_dict": ("pipelines.orchestrator", "orchestration_result_to_dict"),
    "PipelineAdapter": ("pipelines.orchestrator", "PipelineAdapter"),
    "PipelineOrchestrator": ("pipelines.orchestrator", "PipelineOrchestrator"),
    "PipelineRegistry": ("pipelines.orchestrator", "PipelineRegistry"),
    "load_pipeline_plugins": ("pipelines.orchestrator", "load_pipeline_plugins"),
    "PromptCrafterAgent": ("pipelines.orchestrator", "PromptCrafterAgent"),
    "PromptPlan": ("pipelines.orchestrator", "PromptPlan"),
    "ProgressEvent": ("pipelines.orchestrator", "ProgressEvent"),
    "ProgressSink": ("pipelines.orchestrator", "ProgressSink"),
    "RequestUnderstanding": ("pipelines.orchestrator", "RequestUnderstanding"),
    "RequestUnderstandingAgent": ("pipelines.orchestrator", "RequestUnderstandingAgent"),
    "build_default_pipeline_registry": ("pipelines.orchestrator", "build_default_pipeline_registry"),
    "create_sqlite_checkpointer": ("pipelines.orchestrator", "create_sqlite_checkpointer"),
    "default_intent_resolver": ("pipelines.orchestrator", "default_intent_resolver"),
    "resolve_requested_pipelines": ("pipelines.orchestrator", "resolve_requested_pipelines"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module = import_module(target[0])
    value = getattr(module, target[1])
    globals()[name] = value
    return value


__all__ = ["AdvisoryRequest", "PipelineResponse", *_LAZY_EXPORTS]
