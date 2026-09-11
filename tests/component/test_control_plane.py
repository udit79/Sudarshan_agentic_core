from __future__ import annotations

import json
import os
import time

import pytest

from api.control_plane import ControlPlaneConflict, RedisControlPlane, StaleLeaseError
from pipelines.orchestrator.progress import ProgressEvent, RedisProgressSink


class RecordingRedis:
    """Small command recorder for adapter-contract tests without Redis installed."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.hashes = {}
        self.values = {}
        self.lists = {}
        self.streams = {}
        self.counters = {}

    def get(self, key):
        return self.values.get(key)

    def pipeline(self):
        return RecordingPipeline(self)

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(str(value).encode())
        return len(self.lists[key])

    def lrange(self, key, start, stop):
        values = self.lists.get(key, [])
        if stop == -1:
            stop = len(values) - 1
        return values[start : stop + 1]

    def ltrim(self, key, start, stop):
        self.lists[key] = self.lrange(key, start, stop)

    def eval(self, script, numkeys, *args):
        self.calls.append((script, numkeys, args))
        if "not-released" in script:
            key, owner = args[0], str(args[1]).encode()
            if self.hashes.get(key) != owner:
                return [b"not-released"]
            self.hashes.pop(key, None)
            return [b"released"]
        return self.responses.pop(0)

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def xrange(self, key, *, min, max):
        return self.streams.get(key, [])

    def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def xadd(self, key, values):
        sequence = values["sequence"]
        event_id = f"{sequence}-0".encode()
        encoded = {str(k).encode(): str(v).encode() for k, v in values.items()}
        self.streams.setdefault(key, []).append((event_id, encoded))
        return event_id

    def hset(self, key, *, mapping):
        self.hashes[key] = {
            str(name).encode(): str(value).encode() for name, value in mapping.items()
        }

    def expire(self, key, seconds):
        del key, seconds

    def set(self, key, value, *, nx=False, px=None):
        if px is not None:
            if not nx or key not in self.hashes:
                self.hashes[key] = str(value).encode()
                return True
            return False
        if not nx or key not in self.values:
            self.values[key] = str(value).encode()
            return True
        return False

    def delete(self, key):
        self.hashes.pop(key, None)
        self.values.pop(key, None)
        self.streams.pop(key, None)
        self.lists.pop(key, None)

    def xgroup_create(self, key, group, *, id, mkstream):
        self.calls.append(("xgroup_create", key, group, id, mkstream))

    def xreadgroup(self, group, consumer, *, streams, count, block):
        self.calls.append(("xreadgroup", group, consumer, streams, count, block))
        return []

    def xack(self, key, group, message_id):
        self.calls.append(("xack", key, group, message_id))

    def xautoclaim(self, key, group, consumer, min_idle_ms, *, start_id, count):
        self.calls.append(("xautoclaim", key, group, consumer, min_idle_ms, start_id, count))
        return (b"0-0", [])


class RecordingPipeline:
    def __init__(self, redis):
        self.redis = redis

    def watch(self, key):
        del key

    def get(self, key):
        return self.redis.get(key)

    def multi(self):
        return None

    def set(self, key, value):
        return self.redis.set(key, value)

    def execute(self):
        return [True]

    def reset(self):
        return None


def test_redis_adapter_admission_is_idempotent_and_conflicts_are_explicit():
    redis = RecordingRedis([[b"created", b"queued"], [b"replay", b"queued"], [b"conflict"]])
    control = RedisControlPlane(redis)

    first = control.admit("run-1", "hash-1", {"case_id": "case-1"})
    replay = control.admit("run-1", "hash-1", {"case_id": "case-1"})

    assert first.replayed is False
    assert replay.replayed is True
    assert json.loads(redis.calls[0][2][4]) == {"case_id": "case-1"}
    with pytest.raises(ControlPlaneConflict):
        control.admit("run-1", "hash-2", {"case_id": "case-1"})


def test_redis_adapter_fences_claims_and_rejects_stale_terminal_writes():
    redis = RecordingRedis([
        [b"claimed", b"7", str(time.time() + 30).encode()],
        [b"renewed", str(time.time() + 60).encode()],
        [b"stale"],
    ])
    control = RedisControlPlane(redis)
    lease = control.claim("run-1", owner="worker-1", lease_seconds=30)

    assert lease is not None
    assert lease.fencing_token == 7
    renewed = control.renew(lease, lease_seconds=60)
    assert renewed.fencing_token == lease.fencing_token
    with pytest.raises(StaleLeaseError):
        control.transition(lease, status="succeeded", result={"artifact_id": "artifact-1"})


def test_redis_adapter_state_and_events_are_safe_projections():
    redis = RecordingRedis([])
    redis.hashes["sudarshan:control:resource:run-1"] = {
        b"status": b"running",
        b"payload": b"{\"case_id\": \"case-1\"}",
    }
    redis.streams["sudarshan:control:resource:run-1:events"] = [
        (b"1-0", {b"event_type": b"admitted", b"status": b"queued"}),
    ]
    control = RedisControlPlane(redis)

    assert control.state("run-1") == {"status": "running", "payload": '{"case_id": "case-1"}'}
    assert control.events("run-1")[0]["event_id"] == "1-0"


def test_redis_adapter_discovers_and_acknowledges_queue_entries():
    redis = RecordingRedis([])
    redis.queue_rows = [[(b"sudarshan:control:queue:runs", [(b"42-0", {b"resource_key": b"run-42"})])]]

    def read_group(group, consumer, *, streams, count, block):
        redis.calls.append(("xreadgroup", group, consumer, streams, count, block))
        return redis.queue_rows.pop(0)

    redis.xreadgroup = read_group
    control = RedisControlPlane(redis)

    message = control.poll("runs", owner="worker-1", block_ms=10)
    assert message is not None
    assert message.resource_key == "run-42"
    control.ack(message)
    assert redis.calls[-1][0] == "xack"


def test_redis_adapter_reclaims_idle_queue_entries():
    redis = RecordingRedis([])
    redis.xautoclaim = lambda *args, **kwargs: (
        b"0-0",
        [(b"43-0", {b"resource_key": b"run-43"})],
        [],
    )
    control = RedisControlPlane(redis)

    message = control.reclaim("runs", owner="worker-2", min_idle_ms=1000)
    assert message is not None
    assert message.resource_key == "run-43"
    assert message.message_id == "43-0"


def test_redis_progress_sink_replays_monotonic_safe_events():
    redis = RecordingRedis([])
    control = RedisControlPlane(redis)
    sink = RedisProgressSink(control)
    event = ProgressEvent(
        run_id="run-progress",
        task_id="task-progress",
        stage="planning",
        status="running",
        progress=25,
        message="planning",
    )

    sink.publish(event)
    sink.publish(event.model_copy(update={"stage": "rendering", "progress": 50}))

    events = sink.events("run-progress")
    assert [item.sequence for item in events] == [1, 2]
    assert [item.stage for item in events] == ["planning", "rendering"]
    assert sink.events("run-progress", after_sequence=1)[0].stage == "rendering"


def test_redis_cache_entry_and_claim_contract():
    redis = RecordingRedis([])
    control = RedisControlPlane(redis)
    entry = {
        "fingerprint": "fp-1",
        "skill_id": "visual.flowchart",
        "skill_version": "1",
        "artifact_ids": ["artifact-1"],
        "quality_report_id": "quality-1",
        "quality_status": "passed",
        "created_at": 1.0,
        "expires_at": None,
        "metadata": {"renderer": "native"},
    }

    control.cache_put("fp-1", entry)
    assert control.cache_get("fp-1")["artifact_ids"] == ["artifact-1"]
    assert control.cache_claim("fp-1", owner="worker-1", lease_seconds=10) == "worker-1"
    assert control.cache_claim("fp-1", owner="worker-2", lease_seconds=10) is None
    assert control.cache_release("fp-1", "worker-2") is False
    assert control.cache_release("fp-1", "worker-1") is True
    control.cache_invalidate("fp-1")
    assert control.cache_get("fp-1") is None


def test_redis_dag_snapshot_put_and_patch_contract():
    redis = RecordingRedis([])
    control = RedisControlPlane(redis)
    initial = {
        "run_id": "dag-1",
        "status": "queued",
        "created_at": "now",
        "updated_at": "now",
        "nodes": {
            "source": {"status": "ready"},
            "assemble": {"status": "pending"},
        },
    }

    assert control.dag_snapshot_put("dag-1", initial) == 1
    assert control.dag_snapshot("dag-1")["revision"] == 1
    assert control.dag_snapshot_patch("dag-1", {"source": {"status": "succeeded"}}) == 2
    snapshot = control.dag_snapshot("dag-1")
    assert snapshot["status"] == "queued"
    assert snapshot["nodes"]["source"]["status"] == "succeeded"
    with pytest.raises(ControlPlaneConflict):
        control.dag_snapshot_put("dag-1", initial)


def test_redis_shared_usage_and_observability_projections():
    redis = RecordingRedis([])
    control = RedisControlPlane(redis)
    control.usage_record({"run_id": "run-1", "usage_id": "usage-1", "is_estimate": True})
    control.observability_record(
        "run-1",
        {"event_id": "event-1", "run_id": "run-1", "status": "running"},
    )

    assert control.usage_records("run-1")[0]["usage_id"] == "usage-1"
    assert control.observability_events("run-1")[0]["event_id"] == "event-1"


@pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="requires a running Redis instance")
def test_live_redis_control_plane_contract():
    control = RedisControlPlane.from_url(os.environ["REDIS_URL"], prefix="sudarshan:test")
    resource = f"contract-{time.time_ns()}"
    first = control.admit(resource, "hash-1", {"case_id": "case-1"})
    replay = control.admit(resource, "hash-1", {"case_id": "case-1"})
    assert first.replayed is False
    assert replay.replayed is True

    lease = control.claim(resource, owner="worker-1", lease_seconds=2)
    assert lease is not None
    assert control.claim(resource, owner="worker-2", lease_seconds=2) is None
    control.transition(lease, status="succeeded", result={"artifact_id": "artifact-1"})
    assert control.state(resource)["status"] == "succeeded"
