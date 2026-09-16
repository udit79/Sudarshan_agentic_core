from __future__ import annotations

import threading
import time
from pathlib import Path

from api.dag_scheduler import DAGSchedulerBridge
from pipelines import ProgressEvent
from pipelines.infographic.renderer import AntVInfographicRenderer
from pipelines.infographic.renderer import MINIMUM_TIMEOUT_SECONDS
from pipelines.orchestrator.contracts import NodeSpec
from pipelines.orchestrator.dag import DependencyDAG
from pipelines.orchestrator.progress import SQLiteProgressSink
from pipelines.video.native_generator import NativeVideoGenerator, VideoScene


def _node(node_id: str, *dependencies: str) -> NodeSpec:
    return NodeSpec(
        node_id=node_id,
        skill_id=f"skill.{node_id}",
        output_schema="ArtifactManifest",
        dependencies=list(dependencies),
    )


def _wait_for_bridge(bridge: DAGSchedulerBridge, run_id: str, expected: set[str]):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        state = bridge.status(run_id)
        if state["status"] in expected:
            return state
        time.sleep(0.01)
    raise AssertionError(bridge.status(run_id))


def test_restarted_dag_bridge_admits_dependents_from_durable_job_payload(tmp_path) -> None:
    dag_db = tmp_path / "dag.db"
    queue_db = tmp_path / "queue.db"
    dag = DependencyDAG(dag_db)
    dag.create_run("restart-run", [_node("source"), _node("assemble", "source")])
    source = dag.claim_ready_nodes("restart-run", limit=1)[0]

    completed: list[str] = []

    def execute(node, payload, cancel_event):
        del payload, cancel_event
        completed.append(node.node_id)
        return {"status": "succeeded", "output_ref": f"artifact-{node.node_id}"}

    bridge = DAGSchedulerBridge(
        dag,
        execute,
        queue_db_path=str(queue_db),
        max_workers=1,
    )
    try:
        bridge.scheduler.submit(
            "restart-run::node::source::repair-0",
            {
                "query": "restart",
                "user_id": "operator-1",
                "case_id": "case-1",
                "task_id": "task-restart:source",
                "classification_level": "RESTRICTED",
                "distribution": "Authorized NTRO personnel",
                "requested_pipelines": [source.skill_id],
                "metadata": {
                    "dag_run_id": "restart-run",
                    "dag_node_id": "source",
                    "dag_base_task_id": "task-restart",
                },
            },
            operator_id="operator-1",
        )
        state = _wait_for_bridge(bridge, "restart-run", {"succeeded"})
        assert completed == ["source", "assemble"]
        assert [node["status"] for node in state["nodes"]] == ["succeeded", "succeeded"]
    finally:
        bridge.close()


def test_progress_reconnect_replays_only_events_after_cursor(tmp_path) -> None:
    db_path = tmp_path / "progress.db"
    first = SQLiteProgressSink(str(db_path))
    first.publish(ProgressEvent(run_id="reconnect-run", task_id="task-1", stage="planning", status="running"))
    first.publish(ProgressEvent(run_id="reconnect-run", task_id="task-1", stage="rendering", status="running"))

    reconnected = SQLiteProgressSink(str(db_path))
    reconnected.publish(ProgressEvent(run_id="reconnect-run", task_id="task-1", stage="completed", status="completed"))

    replay = reconnected.events("reconnect-run", after_sequence=2)
    assert [event.stage for event in replay] == ["completed"]
    assert replay[0].sequence == 3


def test_renderer_failure_is_explicit_and_does_not_return_a_fake_artifact(tmp_path) -> None:
    renderer = AntVInfographicRenderer(
        node_binary="definitely-missing-node",
        output_dir=tmp_path,
        timeout_seconds=MINIMUM_TIMEOUT_SECONDS,
    )

    try:
        renderer("infographic { title: 'x' }", artifact_name="failed")
    except RuntimeError as error:
        assert "renderer unavailable" in str(error).lower()
    else:
        raise AssertionError("renderer failure must not be reported as an artifact")
    assert not (tmp_path / "failed.svg").exists()


def test_video_partial_package_retries_only_failed_scene(tmp_path) -> None:
    calls: list[str] = []
    failed_once = {"scene-1"}
    generator = NativeVideoGenerator(output_dir=tmp_path / "videos", max_parallel_scenes=2)

    def fake_scene(scene, work_dir, index, ffmpeg, subject, package_root, cancel_event):
        del work_dir, ffmpeg, subject, cancel_event
        calls.append(scene.scene_id)
        if scene.scene_id in failed_once:
            failed_once.remove(scene.scene_id)
            raise RuntimeError("injected scene failure")
        output = Path(package_root) / "segments" / f"scene_{index:03d}.mp4"
        output.write_bytes(scene.scene_id.encode("utf-8"))
        scene.video_path = str(output)
        return str(output)

    generator._generate_scene = fake_scene
    generator._concatenate = lambda paths, output, work, ffmpeg, cancel_event: Path(output).write_bytes(
        "|".join(paths).encode("utf-8")
    )
    generator._probe_duration = lambda _path: 10.0
    scenes = [
        VideoScene(scene_id="scene-0", narration="first"),
        VideoScene(scene_id="scene-1", narration="second"),
    ]

    first = generator.generate(subject="Recovery test", scenes=scenes, artifact_name="partial")
    assert first.status == "partial"
    assert first.metadata["degraded"] is True
    assert first.metadata["failed_scene_ids"] == ["scene-1"]
    assert calls == ["scene-0", "scene-1"]

    second = generator.generate(
        subject="Recovery test",
        scenes=[VideoScene(scene_id="scene-0", narration="first"), VideoScene(scene_id="scene-1", narration="second")],
        artifact_name="partial",
    )
    assert second.status == "succeeded"
    assert second.metadata["degraded"] is False
    assert second.metadata["cache_hits"] == 1
    assert calls == ["scene-0", "scene-1", "scene-1"]
