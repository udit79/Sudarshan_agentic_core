"""Central LangGraph orchestration for Sudarshan application pipelines."""

# Keep the graph module lazy. Pipeline implementations import ArtifactStore,
# while api.artifacts imports the transport-neutral contracts from this package;
# importing the graph eagerly here creates an api.artifacts <-> ppt.vertical
# cycle during API startup.
from pipelines.orchestrator.contracts import (
    ArtifactManifest,
    ChildTaskOutcome,
    ChildTaskSpec,
    ContextPack,
    HarnessCorrelation,
    NodeSpec,
    QualityReport,
    RunEvent,
    RunPolicy,
    RunSummary,
    SkillCall,
    SkillManifest,
    SkillResult,
    TelemetrySummary,
    TelemetryUsage,
    UsageRecord,
    project_progress_event,
)
from pipelines.orchestrator.progress import (
    InMemoryProgressSink,
    ProgressEvent,
    ProgressSink,
    RedisProgressSink,
    SQLiteProgressSink,
    event_dict,
)
from pipelines.orchestrator.observability import (
    CompositeObservabilityStore,
    JsonHttpObservabilityExporter,
    ObservableProgressSink,
    ObservabilityEvent,
    ObservabilityExporter,
    RedisObservabilityStore,
    SQLiteObservabilityStore,
)
from pipelines.orchestrator.skill_runtime import (
    RunContext,
    SkillRuntime,
    SkillRuntimeError,
)
from pipelines.orchestrator.child_tasks import reconcile_child_result, validate_child_plan
from pipelines.orchestrator.dag import (
    DAGError,
    DAGNodeState,
    DAGRunState,
    DependencyDAG,
)
from pipelines.orchestrator.budget import (
    BudgetController,
    BudgetExceededError,
    BudgetReservation,
    BudgetSnapshot,
)
from pipelines.orchestrator.cache import (
    CacheEntry,
    CacheStore,
    build_cache_fingerprint,
    stable_hash,
)
from pipelines.orchestrator.types import (
    OrchestrationResult,
    PipelineAdapter,
    PipelineName,
    PipelineRegistry,
    load_pipeline_plugins,
    orchestration_result_to_dict,
)
from pipelines.orchestrator.understanding import (
    PromptCrafterAgent,
    PromptPlan,
    RequestUnderstanding,
    RequestUnderstandingAgent,
    default_intent_resolver,
    resolve_requested_pipelines,
)


def __getattr__(name: str):
    """Load graph exports only when an orchestration caller requests them."""

    if name in {"PipelineOrchestrator", "build_default_pipeline_registry", "create_sqlite_checkpointer"}:
        from pipelines.orchestrator.graph import (
            PipelineOrchestrator,
            build_default_pipeline_registry,
            create_sqlite_checkpointer,
        )

        return {
            "PipelineOrchestrator": PipelineOrchestrator,
            "build_default_pipeline_registry": build_default_pipeline_registry,
            "create_sqlite_checkpointer": create_sqlite_checkpointer,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "ArtifactManifest",
    "ChildTaskOutcome",
    "ChildTaskSpec",
    "ContextPack",
    "HarnessCorrelation",
    "InMemoryProgressSink",
    "OrchestrationResult",
    "orchestration_result_to_dict",
    "PipelineAdapter",
    "PipelineName",
    "PipelineRegistry",
    "NodeSpec",
    "QualityReport",
    "RunEvent",
    "RunPolicy",
    "RunSummary",
    "TelemetrySummary",
    "TelemetryUsage",
    "SkillCall",
    "SkillManifest",
    "SkillResult",
    "RunContext",
    "SkillRuntime",
    "SkillRuntimeError",
    "reconcile_child_result",
    "validate_child_plan",
    "DAGError",
    "DAGNodeState",
    "DAGRunState",
    "DependencyDAG",
    "BudgetController",
    "BudgetExceededError",
    "BudgetReservation",
    "BudgetSnapshot",
    "CacheEntry",
    "CacheStore",
    "build_cache_fingerprint",
    "stable_hash",
    "UsageRecord",
    "load_pipeline_plugins",
    "PipelineOrchestrator",
    "PromptCrafterAgent",
    "PromptPlan",
    "ProgressEvent",
    "ProgressSink",
    "RedisProgressSink",
    "SQLiteProgressSink",
    "event_dict",
    "ObservableProgressSink",
    "ObservabilityEvent",
    "ObservabilityExporter",
    "CompositeObservabilityStore",
    "JsonHttpObservabilityExporter",
    "RedisObservabilityStore",
    "SQLiteObservabilityStore",
    "project_progress_event",
    "RequestUnderstanding",
    "RequestUnderstandingAgent",
    "build_default_pipeline_registry",
    "create_sqlite_checkpointer",
    "default_intent_resolver",
    "resolve_requested_pipelines",
]


def __getattr__(name: str):
    """Load the application graph only when orchestration is requested.

    Contract consumers such as the artifact store should not need the optional
    CrewAI-backed pipeline graph merely to import manifest types.
    """
    if name in {"PipelineOrchestrator", "build_default_pipeline_registry", "create_sqlite_checkpointer"}:
        from pipelines.orchestrator.graph import (
            PipelineOrchestrator,
            build_default_pipeline_registry,
            create_sqlite_checkpointer,
        )

        return {
            "PipelineOrchestrator": PipelineOrchestrator,
            "build_default_pipeline_registry": build_default_pipeline_registry,
            "create_sqlite_checkpointer": create_sqlite_checkpointer,
        }[name]
    raise AttributeError(name)
