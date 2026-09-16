"""Shared control-plane lease and idempotency primitives.

SQLite remains the default local scheduler.  This module defines the narrow
shared-store seam needed by a multi-worker deployment.  The Redis adapter is
optional and accepts a redis-py compatible client so the core package does not
require Redis for local development.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from threading import Lock
import time
from typing import Any, Mapping, Protocol
from uuid import uuid4


class ControlPlaneConflict(ValueError):
    """Raised when an idempotency key is reused for different work."""


class StaleLeaseError(RuntimeError):
    """Raised when a fenced worker tries to mutate state after lease loss."""


@dataclass(frozen=True, slots=True)
class LeaseToken:
    resource_key: str
    owner: str
    fencing_token: int
    expires_at: float


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    resource_key: str
    request_hash: str
    status: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class QueueMessage:
    """A shared queue entry held until the local worker finishes the job."""

    queue: str
    message_id: str
    resource_key: str


class ControlPlane(Protocol):
    """Small contract shared by local and distributed control-plane stores."""

    def admit(
        self,
        resource_key: str,
        request_hash: str,
        payload: Mapping[str, Any],
        *,
        queue: str = "runs",
    ) -> AdmissionResult:
        ...

    def poll(
        self,
        queue: str,
        *,
        owner: str,
        block_ms: int = 250,
    ) -> QueueMessage | None:
        ...

    def ack(self, message: QueueMessage) -> None:
        ...

    def reclaim(
        self,
        queue: str,
        *,
        owner: str,
        min_idle_ms: int,
    ) -> QueueMessage | None:
        ...

    def publish_progress(self, resource_key: str, event: Mapping[str, Any]) -> int:
        ...

    def progress_events(
        self,
        resource_key: str,
        *,
        after_sequence: int = 0,
    ) -> tuple[dict[str, Any], ...]:
        ...

    def cache_get(self, fingerprint: str) -> dict[str, Any] | None:
        ...

    def cache_put(self, fingerprint: str, entry: Mapping[str, Any]) -> None:
        ...

    def cache_claim(self, fingerprint: str, *, owner: str, lease_seconds: float) -> str | None:
        ...

    def cache_release(self, fingerprint: str, owner: str) -> bool:
        ...

    def cache_invalidate(self, fingerprint: str) -> None:
        ...

    def budget_register(self, run_id: str, policy: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def budget_reserve(self, run_id: str, reservation: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def budget_commit(self, reservation_id: str, usage: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def budget_release(self, reservation_id: str) -> dict[str, Any]:
        ...

    def budget_snapshot(self, run_id: str) -> dict[str, Any] | None:
        ...

    def usage_record(self, record: Mapping[str, Any]) -> None:
        ...

    def usage_records(self, run_id: str) -> tuple[dict[str, Any], ...]:
        ...

    def observability_record(self, run_id: str, event: Mapping[str, Any]) -> None:
        ...

    def observability_events(self, run_id: str, *, limit: int = 500) -> tuple[dict[str, Any], ...]:
        ...

    def ingestion_budget_register(self, ingestion_id: str, budget: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def ingestion_budget_charge(
        self,
        ingestion_id: str,
        *,
        stage: str,
        units: int,
        tokens: int,
        fan_out: int,
    ) -> dict[str, Any]:
        ...

    def ingestion_budget_snapshot(self, ingestion_id: str) -> dict[str, Any] | None:
        ...

    def ingestion_usage_record(self, ingestion_id: str, record: Mapping[str, Any]) -> None:
        ...

    def ingestion_usage_snapshot(self, ingestion_id: str) -> dict[str, Any]:
        ...

    def dag_snapshot(self, run_id: str) -> dict[str, Any] | None:
        ...

    def dag_snapshot_put(self, run_id: str, snapshot: Mapping[str, Any]) -> int:
        ...

    def dag_snapshot_patch(
        self,
        run_id: str,
        nodes: Mapping[str, Mapping[str, Any]],
    ) -> int:
        ...

    def claim(self, resource_key: str, *, owner: str, lease_seconds: float) -> LeaseToken | None:
        ...

    def renew(self, lease: LeaseToken, *, lease_seconds: float) -> LeaseToken:
        ...

    def transition(
        self,
        lease: LeaseToken,
        *,
        status: str,
        result: Mapping[str, Any] | None = None,
    ) -> None:
        ...

    def schedule_retry(self, lease: LeaseToken, *, retry_at: float, error: str) -> None:
        ...

    def state(self, resource_key: str) -> dict[str, Any] | None:
        ...

    def preparation_create_if_absent(self, idempotency_key: str, fingerprint: str, record: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def preparation_get(self, idempotency_key: str) -> dict[str, Any] | None:
        ...

_ADMIT_SCRIPT = """
local existing = redis.call('HGET', KEYS[1], 'request_hash')
if existing then
  if existing ~= ARGV[1] then return {'conflict'} end
  return {'replay', redis.call('HGET', KEYS[1], 'status') or 'queued'}
end
redis.call('HSET', KEYS[1],
  'request_hash', ARGV[1], 'payload', ARGV[2], 'status', 'queued',
  'attempt', '0', 'created_at', ARGV[3], 'updated_at', ARGV[3])
redis.call('XADD', KEYS[2], '*', 'event_type', 'admitted', 'status', 'queued', 'message', 'admitted')
redis.call('XADD', KEYS[3], '*', 'resource_key', ARGV[4])
return {'created', 'queued'}
"""

_PREPARATION_CREATE_SCRIPT = """
local existing_fingerprint = redis.call('HGET', KEYS[1], 'request_fingerprint')
if existing_fingerprint then
  if existing_fingerprint ~= ARGV[1] then return {'conflict'} end
  return {'replay', redis.call('HGET', KEYS[1], 'payload')}
end
redis.call('HSET', KEYS[1], 'request_fingerprint', ARGV[1], 'payload', ARGV[2])
return {'created', ARGV[2]}
"""

_CLAIM_SCRIPT = """
local status = redis.call('HGET', KEYS[1], 'status')
if not status then return {'missing'} end
if status == 'succeeded' or status == 'partial' or status == 'failed' or status == 'cancelled' or status == 'completed' then
  return {'terminal', status}
end
local now = tonumber(ARGV[2])
local current_expiry = tonumber(redis.call('HGET', KEYS[1], 'lease_until') or '0')
if current_expiry > now then return {'busy'} end
local fence = redis.call('INCR', KEYS[2])
local expiry = now + tonumber(ARGV[3])
redis.call('HSET', KEYS[1], 'status', 'running', 'owner', ARGV[1],
  'fencing_token', fence, 'lease_until', expiry, 'updated_at', now,
  'attempt', (tonumber(redis.call('HGET', KEYS[1], 'attempt') or '0') + 1))
redis.call('XADD', KEYS[3], '*', 'event_type', 'started', 'status', 'running', 'message', 'lease acquired')
return {'claimed', tostring(fence), tostring(expiry)}
"""

_RENEW_SCRIPT = """
local owner = redis.call('HGET', KEYS[1], 'owner')
local fence = tonumber(redis.call('HGET', KEYS[1], 'fencing_token') or '0')
if owner ~= ARGV[1] or fence ~= tonumber(ARGV[2]) or redis.call('HGET', KEYS[1], 'status') ~= 'running' then
  return {'stale'}
end
local expiry = tonumber(ARGV[3]) + tonumber(ARGV[4])
redis.call('HSET', KEYS[1], 'lease_until', expiry, 'updated_at', ARGV[3])
return {'renewed', tostring(expiry)}
"""

_TRANSITION_SCRIPT = """
local owner = redis.call('HGET', KEYS[1], 'owner')
local fence = tonumber(redis.call('HGET', KEYS[1], 'fencing_token') or '0')
if owner ~= ARGV[1] or fence ~= tonumber(ARGV[2]) or redis.call('HGET', KEYS[1], 'status') ~= 'running' then
  return {'stale'}
end
redis.call('HSET', KEYS[1], 'status', ARGV[3], 'result', ARGV[4],
  'owner', '', 'lease_until', '0', 'updated_at', ARGV[5])
redis.call('XADD', KEYS[2], '*', 'event_type', 'completed', 'status', ARGV[3], 'message', ARGV[3])
return {'ok'}
"""

_RETRY_SCRIPT = """
local owner = redis.call('HGET', KEYS[1], 'owner')
local fence = tonumber(redis.call('HGET', KEYS[1], 'fencing_token') or '0')
if owner ~= ARGV[1] or fence ~= tonumber(ARGV[2]) or redis.call('HGET', KEYS[1], 'status') ~= 'running' then
  return {'stale'}
end
redis.call('HSET', KEYS[1], 'status', 'retrying', 'error', ARGV[3],
  'retry_at', ARGV[4], 'owner', '', 'lease_until', '0', 'updated_at', ARGV[5])
redis.call('XADD', KEYS[2], '*', 'event_type', 'retrying', 'status', 'retrying', 'message', ARGV[3])
return {'ok'}
"""

_RELEASE_CACHE_CLAIM_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return {'not-released'} end
redis.call('DEL', KEYS[1])
return {'released'}
"""

_BUDGET_REGISTER_SCRIPT = """
local existing = redis.call('HGET', KEYS[1], 'max_model_tokens')
if existing then
  if redis.call('HGET', KEYS[1], 'max_model_tokens') ~= ARGV[1]
    or redis.call('HGET', KEYS[1], 'max_tool_calls') ~= ARGV[2]
    or redis.call('HGET', KEYS[1], 'max_wall_time_ms') ~= ARGV[3]
    or redis.call('HGET', KEYS[1], 'max_parallel_children') ~= ARGV[4]
    or redis.call('HGET', KEYS[1], 'max_cost') ~= ARGV[5] then
    return {'error', 'POLICY_CONFLICT'}
  end
  return {'ok'}
end
redis.call('HSET', KEYS[1],
  'max_model_tokens', ARGV[1], 'max_tool_calls', ARGV[2],
  'max_wall_time_ms', ARGV[3], 'max_parallel_children', ARGV[4],
  'max_cost', ARGV[5], 'used_model_tokens', '0',
  'reserved_model_tokens', '0', 'used_tool_calls', '0',
  'reserved_tool_calls', '0', 'used_wall_time_ms', '0',
  'reserved_wall_time_ms', '0', 'used_cost', '0',
  'reserved_cost', '0', 'active_concurrency', '0')
return {'ok'}
"""

_BUDGET_RESERVE_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then return {'error', 'RUN_NOT_REGISTERED'} end
local model = tonumber(ARGV[2])
local tools = tonumber(ARGV[3])
local wall = tonumber(ARGV[4])
local cost = tonumber(ARGV[5])
local concurrency = tonumber(ARGV[6])
if tonumber(redis.call('HGET', KEYS[1], 'used_model_tokens')) + tonumber(redis.call('HGET', KEYS[1], 'reserved_model_tokens')) + model > tonumber(redis.call('HGET', KEYS[1], 'max_model_tokens')) then return {'error', 'TOKEN_BUDGET'} end
if tonumber(redis.call('HGET', KEYS[1], 'used_tool_calls')) + tonumber(redis.call('HGET', KEYS[1], 'reserved_tool_calls')) + tools > tonumber(redis.call('HGET', KEYS[1], 'max_tool_calls')) then return {'error', 'TOOL_BUDGET'} end
if tonumber(redis.call('HGET', KEYS[1], 'used_wall_time_ms')) + tonumber(redis.call('HGET', KEYS[1], 'reserved_wall_time_ms')) + wall > tonumber(redis.call('HGET', KEYS[1], 'max_wall_time_ms')) then return {'error', 'WALL_TIME_BUDGET'} end
local max_cost = redis.call('HGET', KEYS[1], 'max_cost')
if max_cost ~= '' and tonumber(redis.call('HGET', KEYS[1], 'used_cost')) + tonumber(redis.call('HGET', KEYS[1], 'reserved_cost')) + cost > tonumber(max_cost) then return {'error', 'COST_BUDGET'} end
if tonumber(redis.call('HGET', KEYS[1], 'active_concurrency')) + concurrency > tonumber(redis.call('HGET', KEYS[1], 'max_parallel_children')) then return {'error', 'CONCURRENCY_BUDGET'} end
redis.call('HINCRBY', KEYS[1], 'reserved_model_tokens', model)
redis.call('HINCRBY', KEYS[1], 'reserved_tool_calls', tools)
redis.call('HINCRBY', KEYS[1], 'reserved_wall_time_ms', wall)
redis.call('HINCRBYFLOAT', KEYS[1], 'reserved_cost', cost)
redis.call('HINCRBY', KEYS[1], 'active_concurrency', concurrency)
redis.call('HSET', KEYS[2], 'run_id', ARGV[1], 'node_id', ARGV[7], 'model_tokens', ARGV[2], 'tool_calls', ARGV[3], 'wall_time_ms', ARGV[4], 'cost', ARGV[5], 'concurrency', ARGV[6])
return {'ok'}
"""

_BUDGET_COMMIT_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 0 then return {'error', 'RESERVATION_NOT_FOUND'} end
if redis.call('HGET', KEYS[2], 'run_id') ~= ARGV[1] then return {'error', 'RUN_MISMATCH'} end
local model = tonumber(ARGV[2])
local tools = tonumber(ARGV[3])
local wall = tonumber(ARGV[4])
local cost = tonumber(ARGV[5])
if model > tonumber(redis.call('HGET', KEYS[2], 'model_tokens')) then return {'error', 'TOKEN_RESERVATION_EXCEEDED'} end
if tools > tonumber(redis.call('HGET', KEYS[2], 'tool_calls')) then return {'error', 'TOOL_RESERVATION_EXCEEDED'} end
if wall > tonumber(redis.call('HGET', KEYS[2], 'wall_time_ms')) then return {'error', 'WALL_TIME_RESERVATION_EXCEEDED'} end
if tonumber(redis.call('HGET', KEYS[2], 'cost')) > 0 and cost > tonumber(redis.call('HGET', KEYS[2], 'cost')) then return {'error', 'COST_RESERVATION_EXCEEDED'} end
redis.call('HINCRBY', KEYS[1], 'reserved_model_tokens', -tonumber(redis.call('HGET', KEYS[2], 'model_tokens')))
redis.call('HINCRBY', KEYS[1], 'reserved_tool_calls', -tonumber(redis.call('HGET', KEYS[2], 'tool_calls')))
redis.call('HINCRBY', KEYS[1], 'reserved_wall_time_ms', -tonumber(redis.call('HGET', KEYS[2], 'wall_time_ms')))
redis.call('HINCRBYFLOAT', KEYS[1], 'reserved_cost', -tonumber(redis.call('HGET', KEYS[2], 'cost')))
redis.call('HINCRBY', KEYS[1], 'active_concurrency', -tonumber(redis.call('HGET', KEYS[2], 'concurrency')))
redis.call('HINCRBY', KEYS[1], 'used_model_tokens', model)
redis.call('HINCRBY', KEYS[1], 'used_tool_calls', tools)
redis.call('HINCRBY', KEYS[1], 'used_wall_time_ms', wall)
redis.call('HINCRBYFLOAT', KEYS[1], 'used_cost', cost)
redis.call('DEL', KEYS[2])
return {'ok'}
"""

_BUDGET_RELEASE_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 0 then return {'error', 'RESERVATION_NOT_FOUND'} end
redis.call('HINCRBY', KEYS[1], 'reserved_model_tokens', -tonumber(redis.call('HGET', KEYS[2], 'model_tokens')))
redis.call('HINCRBY', KEYS[1], 'reserved_tool_calls', -tonumber(redis.call('HGET', KEYS[2], 'tool_calls')))
redis.call('HINCRBY', KEYS[1], 'reserved_wall_time_ms', -tonumber(redis.call('HGET', KEYS[2], 'wall_time_ms')))
redis.call('HINCRBYFLOAT', KEYS[1], 'reserved_cost', -tonumber(redis.call('HGET', KEYS[2], 'cost')))
redis.call('HINCRBY', KEYS[1], 'active_concurrency', -tonumber(redis.call('HGET', KEYS[2], 'concurrency')))
redis.call('DEL', KEYS[2])
return {'ok'}
"""

_INGESTION_BUDGET_REGISTER_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 1 then
  if redis.call('HGET', KEYS[1], 'token_budget') ~= ARGV[1] or
     redis.call('HGET', KEYS[1], 'parser_units') ~= ARGV[2] or
     redis.call('HGET', KEYS[1], 'ocr_calls') ~= ARGV[3] or
     redis.call('HGET', KEYS[1], 'vision_calls') ~= ARGV[4] or
     redis.call('HGET', KEYS[1], 'summary_tokens') ~= ARGV[5] or
     redis.call('HGET', KEYS[1], 'embedding_tokens') ~= ARGV[6] or
     redis.call('HGET', KEYS[1], 'max_fan_out') ~= ARGV[7] or
     redis.call('HGET', KEYS[1], 'wall_time_seconds') ~= ARGV[9] then
    return {'error', 'BUDGET_CONFLICT'}
  end
  return {'ok'}
end
redis.call('HSET', KEYS[1],
  'ingestion_id', ARGV[8], 'token_budget', ARGV[1],
  'parser_units', ARGV[2], 'ocr_calls', ARGV[3], 'vision_calls', ARGV[4],
  'summary_tokens', ARGV[5], 'embedding_tokens', ARGV[6],
  'max_fan_out', ARGV[7], 'wall_time_seconds', ARGV[9],
  'units_parser', '0', 'units_ocr', '0', 'units_vision', '0',
  'units_summary', '0', 'units_embedding', '0',
  'tokens_parser', '0', 'tokens_ocr', '0', 'tokens_vision', '0',
  'tokens_summary', '0', 'tokens_embedding', '0',
  'fan_out_used', '0', 'total_tokens', '0')
return {'ok'}
"""

_INGESTION_BUDGET_CHARGE_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then return {'error', 'NOT_REGISTERED'} end
local stage = ARGV[1]
local units = tonumber(ARGV[2])
local tokens = tonumber(ARGV[3])
local fanout = tonumber(ARGV[4])
local unit_field = 'units_' .. stage
local token_field = 'tokens_' .. stage
local limit_field = ''
if stage == 'parser' then limit_field = 'parser_units'
elseif stage == 'ocr' then limit_field = 'ocr_calls'
elseif stage == 'vision' then limit_field = 'vision_calls'
elseif stage == 'summary' then limit_field = 'summary_tokens'
elseif stage == 'embedding' then limit_field = 'embedding_tokens'
else return {'error', 'INVALID_STAGE'} end
local current_units = tonumber(redis.call('HGET', KEYS[1], unit_field) or '0')
local current_tokens = tonumber(redis.call('HGET', KEYS[1], token_field) or '0')
local stage_limit = tonumber(redis.call('HGET', KEYS[1], limit_field) or '0')
if stage == 'summary' or stage == 'embedding' then
  if current_tokens + tokens > stage_limit then return {'error', 'STAGE_TOKEN_BUDGET'} end
else
  if current_units + units > stage_limit then return {'error', 'STAGE_CALL_BUDGET'} end
end
local total = tonumber(redis.call('HGET', KEYS[1], 'total_tokens') or '0')
local token_limit = tonumber(redis.call('HGET', KEYS[1], 'token_budget') or '0')
if token_limit > 0 and total + tokens > token_limit then return {'error', 'TOKEN_BUDGET'} end
local fanout_used = tonumber(redis.call('HGET', KEYS[1], 'fan_out_used') or '0')
local fanout_limit = tonumber(redis.call('HGET', KEYS[1], 'max_fan_out') or '0')
if fanout_used + fanout > fanout_limit then return {'error', 'FAN_OUT_BUDGET'} end
redis.call('HINCRBY', KEYS[1], unit_field, units)
redis.call('HINCRBY', KEYS[1], token_field, tokens)
redis.call('HINCRBY', KEYS[1], 'total_tokens', tokens)
redis.call('HINCRBY', KEYS[1], 'fan_out_used', fanout)
return {'ok'}
"""


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _dag_status(nodes: Mapping[str, Mapping[str, Any]]) -> str:
    statuses = [str(node.get("status", "pending")) for node in nodes.values()]
    if not statuses:
        return "succeeded"
    if any(item == "waiting" for item in statuses):
        return "waiting"
    if any(item in {"failed", "blocked"} for item in statuses):
        return "failed"
    if all(item in {"succeeded", "cancelled"} for item in statuses):
        return "succeeded" if all(item == "succeeded" for item in statuses) else "cancelled"
    if any(item == "running" for item in statuses):
        return "running"
    return "queued"


class RedisControlPlane:
    """Redis-backed shared lease/idempotency state.

    The supplied client must implement the Redis lease/stream methods plus
    ``get``, ``set``, and ``pipeline`` for atomic DAG snapshot replication.
    The supplied client must implement ``eval``, ``hgetall``, ``xrange``,
    ``xgroup_create``, ``xreadgroup``, and ``xack``
    like redis-py.  Redis is intentionally optional so local SQLite remains
    the default and test dependency.
    """

    def __init__(self, client: Any, *, prefix: str = "sudarshan:control", event_stream_length: int = 1000) -> None:
        if not prefix.strip():
            raise ValueError("prefix must not be empty")
        if event_stream_length < 1:
            raise ValueError("event_stream_length must be positive")
        self.client = client
        self.prefix = prefix.rstrip(":")
        self.event_stream_length = event_stream_length
        self._group_lock = Lock()
        self._ready_groups: set[str] = set()

    @classmethod
    def from_url(cls, url: str, *, prefix: str = "sudarshan:control") -> "RedisControlPlane":
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Redis control plane requires the optional 'redis' package") from exc
        return cls(redis.Redis.from_url(url, decode_responses=False), prefix=prefix)

    def _keys(self, resource_key: str) -> tuple[str, str, str]:
        key = str(resource_key).strip()
        if not key:
            raise ValueError("resource_key must not be empty")
        root = f"{self.prefix}:resource:{key}"
        return root, f"{root}:fence", f"{root}:events"

    def _queue_key(self, queue: str) -> str:
        value = str(queue).strip()
        if not value or ":" in value:
            raise ValueError("queue must be a non-empty name without ':'")
        return f"{self.prefix}:queue:{value}"

    def _progress_keys(self, resource_key: str) -> tuple[str, str]:
        state_key, _, _ = self._keys(resource_key)
        return f"{state_key}:progress", f"{state_key}:progress:sequence"

    def _cache_key(self, fingerprint: str) -> str:
        value = str(fingerprint).strip()
        if not value:
            raise ValueError("fingerprint must not be empty")
        return f"{self.prefix}:cache:{value}"

    def _cache_claim_key(self, fingerprint: str) -> str:
        return f"{self._cache_key(fingerprint)}:claim"

    def _budget_key(self, run_id: str) -> str:
        value = str(run_id).strip()
        if not value:
            raise ValueError("run_id must not be empty")
        return f"{self.prefix}:budget:{value}"

    def _budget_reservation_key(self, reservation_id: str) -> str:
        value = str(reservation_id).strip()
        if not value:
            raise ValueError("reservation_id must not be empty")
        return f"{self.prefix}:budget:reservation:{value}"

    def _usage_key(self, run_id: str) -> str:
        value = str(run_id).strip()
        if not value:
            raise ValueError("run_id must not be empty")
        return f"{self.prefix}:usage:{value}"

    def _observability_key(self, run_id: str) -> str:
        value = str(run_id).strip()
        if not value:
            raise ValueError("run_id must not be empty")
        return f"{self.prefix}:observability:{value}"

    def _ingestion_budget_key(self, ingestion_id: str) -> str:
        value = str(ingestion_id).strip()
        if not value:
            raise ValueError("ingestion_id must not be empty")
        return f"{self.prefix}:ingestion:budget:{value}"

    def _ingestion_usage_key(self, ingestion_id: str) -> str:
        value = str(ingestion_id).strip()
        if not value:
            raise ValueError("ingestion_id must not be empty")
        return f"{self.prefix}:ingestion:usage:{value}"

    def _dag_key(self, run_id: str) -> str:
        value = str(run_id).strip()
        if not value:
            raise ValueError("run_id must not be empty")
        return f"{self.prefix}:dag:{value}"

    def _preparation_key(self, idempotency_key: str) -> str:
        value = str(idempotency_key).strip()
        if not value:
            raise ValueError("idempotency_key must not be empty")
        return f"{self.prefix}:preparation:{value}"

    def preparation_create_if_absent(self, idempotency_key: str, fingerprint: str, record: Mapping[str, Any]) -> dict[str, Any]:
        prep_key = self._preparation_key(idempotency_key)
        result = self.client.eval(
            _PREPARATION_CREATE_SCRIPT,
            1,
            prep_key,
            str(fingerprint),
            json.dumps(dict(record), sort_keys=True, ensure_ascii=False, default=str),
        )
        marker = _text(result[0])
        if marker == "conflict":
            raise ControlPlaneConflict("preparation key was already admitted with a different request fingerprint")
        payload = _text(result[1])
        return json.loads(payload)

    def preparation_get(self, idempotency_key: str) -> dict[str, Any] | None:
        prep_key = self._preparation_key(idempotency_key)
        payload = self.client.hget(prep_key, "payload")
        if not payload:
            return None
        return json.loads(_text(payload))

    def _group_name(self, queue: str) -> str:
        return f"{self.prefix}:workers:{queue}"

    def _ensure_group(self, queue_key: str, group: str) -> None:
        marker = f"{queue_key}:{group}"
        with self._group_lock:
            if marker in self._ready_groups:
                return
            try:
                self.client.xgroup_create(queue_key, group, id="0-0", mkstream=True)
            except Exception as exc:  # redis-py uses ResponseError for BUSYGROUP.
                if "BUSYGROUP" not in str(exc).upper():
                    raise
            self._ready_groups.add(marker)

    def _trim_events(self, events_key: str) -> None:
        # Keep tests and compatible Redis clients that omit xtrim usable while
        # bounding the stream in real deployments.
        xtrim = getattr(self.client, "xtrim", None)
        if xtrim is not None:
            xtrim(events_key, maxlen=self.event_stream_length, approximate=True)

    def admit(
        self,
        resource_key: str,
        request_hash: str,
        payload: Mapping[str, Any],
        *,
        queue: str = "runs",
    ) -> AdmissionResult:
        state_key, _, events_key = self._keys(resource_key)
        queue_key = self._queue_key(queue)
        result = self.client.eval(
            _ADMIT_SCRIPT,
            3,
            state_key,
            events_key,
            queue_key,
            str(request_hash),
            json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str),
            str(time.time()),
            str(resource_key),
        )
        marker = _text(result[0])
        if marker == "conflict":
            raise ControlPlaneConflict("resource key was already admitted with a different request")
        self._trim_events(events_key)
        return AdmissionResult(str(resource_key), str(request_hash), _text(result[1]), marker == "replay")

    def poll(
        self,
        queue: str,
        *,
        owner: str,
        block_ms: int = 250,
    ) -> QueueMessage | None:
        if block_ms < 0:
            raise ValueError("block_ms must not be negative")
        queue_key = self._queue_key(queue)
        group = self._group_name(queue)
        self._ensure_group(queue_key, group)
        rows = self.client.xreadgroup(
            group,
            str(owner),
            streams={queue_key: ">"},
            count=1,
            block=block_ms,
        )
        if not rows:
            return None
        _, entries = rows[0]
        if not entries:
            return None
        message_id, values = entries[0]
        resource_key = values.get("resource_key") or values.get(b"resource_key")
        if resource_key is None:
            raise ValueError("shared queue entry is missing resource_key")
        return QueueMessage(queue, _text(message_id), _text(resource_key))

    def ack(self, message: QueueMessage) -> None:
        self.client.xack(self._queue_key(message.queue), self._group_name(message.queue), message.message_id)

    def publish_progress(self, resource_key: str, event: Mapping[str, Any]) -> int:
        progress_key, sequence_key = self._progress_keys(resource_key)
        sequence = int(self.client.incr(sequence_key))
        self.client.xadd(
            progress_key,
            {
                "sequence": str(sequence),
                "payload": json.dumps(dict(event), sort_keys=True, ensure_ascii=False, default=str),
            },
        )
        self._trim_events(progress_key)
        return sequence

    def progress_events(
        self,
        resource_key: str,
        *,
        after_sequence: int = 0,
    ) -> tuple[dict[str, Any], ...]:
        progress_key, _ = self._progress_keys(resource_key)
        rows = self.client.xrange(progress_key, min="-", max="+")
        events: list[dict[str, Any]] = []
        for _, values in rows:
            raw_sequence = values.get("sequence") or values.get(b"sequence") or "0"
            sequence = int(_text(raw_sequence))
            if sequence <= after_sequence:
                continue
            raw_payload = values.get("payload") or values.get(b"payload") or "{}"
            try:
                payload = json.loads(_text(raw_payload))
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                payload["sequence"] = sequence
                events.append(payload)
        return tuple(events)

    def cache_get(self, fingerprint: str) -> dict[str, Any] | None:
        key = self._cache_key(fingerprint)
        raw = self.client.hgetall(key)
        if not raw:
            return None
        result = {_text(name): _text(value) for name, value in raw.items()}
        if result.get("quality_status") != "passed":
            return None
        try:
            expires_at = result.get("expires_at")
            if expires_at and float(expires_at) <= time.time():
                self.client.delete(key)
                return None
            result["artifact_ids"] = json.loads(result.get("artifact_ids", "[]"))
            result["metadata"] = json.loads(result.get("metadata", "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return result

    def cache_put(self, fingerprint: str, entry: Mapping[str, Any]) -> None:
        key = self._cache_key(fingerprint)
        expires_at = entry.get("expires_at")
        self.client.hset(
            key,
            mapping={
                "fingerprint": str(entry.get("fingerprint", fingerprint)),
                "skill_id": str(entry.get("skill_id", "")),
                "skill_version": str(entry.get("skill_version", "")),
                "artifact_ids": json.dumps(list(entry.get("artifact_ids", ())), sort_keys=True),
                "quality_report_id": str(entry.get("quality_report_id") or ""),
                "quality_status": str(entry.get("quality_status", "")),
                "created_at": str(entry.get("created_at", time.time())),
                "expires_at": str(expires_at or ""),
                "metadata": json.dumps(dict(entry.get("metadata") or {}), sort_keys=True),
            },
        )
        if expires_at is not None:
            ttl = max(1, int(float(expires_at) - time.time()))
            self.client.expire(key, ttl)

    def cache_claim(self, fingerprint: str, *, owner: str, lease_seconds: float) -> str | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        claimed = self.client.set(
            self._cache_claim_key(fingerprint),
            str(owner),
            nx=True,
            px=max(1, int(lease_seconds * 1000)),
        )
        return str(owner) if claimed else None

    def cache_release(self, fingerprint: str, owner: str) -> bool:
        response = self.client.eval(
            _RELEASE_CACHE_CLAIM_SCRIPT,
            1,
            self._cache_claim_key(fingerprint),
            str(owner),
        )
        return _text(response[0]) == "released"

    def cache_invalidate(self, fingerprint: str) -> None:
        self.client.delete(self._cache_key(fingerprint))

    def budget_register(self, run_id: str, policy: Mapping[str, Any]) -> dict[str, Any]:
        max_cost = policy.get("max_cost")
        result = self.client.eval(
            _BUDGET_REGISTER_SCRIPT,
            1,
            self._budget_key(run_id),
            str(policy["max_model_tokens"]),
            str(policy["max_tool_calls"]),
            str(policy["max_wall_time_ms"]),
            str(policy["max_parallel_children"]),
            "" if max_cost is None else str(max_cost),
        )
        if _text(result[0]) == "error":
            return {"error": _text(result[1])}
        return self.budget_snapshot(run_id) or {}

    def budget_reserve(self, run_id: str, reservation: Mapping[str, Any]) -> dict[str, Any]:
        reservation_id = str(reservation["reservation_id"])
        result = self.client.eval(
            _BUDGET_RESERVE_SCRIPT,
            2,
            self._budget_key(run_id),
            self._budget_reservation_key(reservation_id),
            str(run_id),
            str(reservation["model_tokens"]),
            str(reservation["tool_calls"]),
            str(reservation["wall_time_ms"]),
            str(reservation["cost"]),
            str(reservation["concurrency"]),
            str(reservation.get("node_id") or ""),
        )
        if _text(result[0]) == "error":
            return {"error": _text(result[1])}
        return self.budget_snapshot(run_id) or {}

    def budget_commit(self, reservation_id: str, usage: Mapping[str, Any]) -> dict[str, Any]:
        run_id = str(usage["run_id"])
        model_tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)) + int(usage.get("reasoning_tokens") or 0)
        result = self.client.eval(
            _BUDGET_COMMIT_SCRIPT,
            2,
            self._budget_key(run_id),
            self._budget_reservation_key(reservation_id),
            run_id,
            str(model_tokens),
            str(usage.get("tool_calls", 0)),
            str(usage.get("latency_ms", 0)),
            str(usage.get("estimated_cost") or 0.0),
        )
        if _text(result[0]) == "error":
            return {"error": _text(result[1])}
        return self.budget_snapshot(run_id) or {}

    def budget_release(self, reservation_id: str) -> dict[str, Any]:
        reservation_key = self._budget_reservation_key(reservation_id)
        raw = self.client.hgetall(reservation_key)
        if not raw:
            return {"error": "RESERVATION_NOT_FOUND"}
        fields = {_text(key): _text(value) for key, value in raw.items()}
        result = self.client.eval(
            _BUDGET_RELEASE_SCRIPT,
            2,
            self._budget_key(fields["run_id"]),
            reservation_key,
        )
        if _text(result[0]) == "error":
            return {"error": _text(result[1])}
        return self.budget_snapshot(fields["run_id"]) or {}

    def budget_snapshot(self, run_id: str) -> dict[str, Any] | None:
        raw = self.client.hgetall(self._budget_key(run_id))
        if not raw:
            return None
        result = {_text(key): _text(value) for key, value in raw.items()}
        for key in {
            "max_model_tokens", "used_model_tokens", "reserved_model_tokens",
            "max_tool_calls", "used_tool_calls", "reserved_tool_calls",
            "max_wall_time_ms", "used_wall_time_ms", "reserved_wall_time_ms",
            "max_parallel_children", "active_concurrency",
        }:
            result[key] = int(float(result.get(key, 0)))
        result["max_cost"] = None if result.get("max_cost", "") == "" else float(result["max_cost"])
        result["used_cost"] = float(result.get("used_cost", 0))
        result["reserved_cost"] = float(result.get("reserved_cost", 0))
        result["run_id"] = str(run_id)
        return result

    def usage_record(self, record: Mapping[str, Any]) -> None:
        run_id = str(record.get("run_id", "")).strip()
        if not run_id:
            raise ValueError("usage record requires run_id")
        self.client.rpush(
            self._usage_key(run_id),
            json.dumps(dict(record), sort_keys=True, ensure_ascii=False, default=str),
        )

    def usage_records(self, run_id: str) -> tuple[dict[str, Any], ...]:
        rows = self.client.lrange(self._usage_key(run_id), 0, -1)
        records: list[dict[str, Any]] = []
        for raw in rows:
            try:
                value = json.loads(_text(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                records.append(value)
        return tuple(records)

    def observability_record(self, run_id: str, event: Mapping[str, Any]) -> None:
        key = self._observability_key(run_id)
        self.client.rpush(
            key,
            json.dumps(dict(event), sort_keys=True, ensure_ascii=False, default=str),
        )
        # Bound the shared projection. The local SQLite collector remains the
        # tamper-evident audit source; Redis is the cross-worker dashboard view.
        self.client.ltrim(key, -5000, -1)

    def observability_events(self, run_id: str, *, limit: int = 500) -> tuple[dict[str, Any], ...]:
        rows = self.client.lrange(self._observability_key(run_id), -max(1, min(int(limit), 5000)), -1)
        events: list[dict[str, Any]] = []
        for raw in rows:
            try:
                value = json.loads(_text(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                events.append(value)
        return tuple(events)

    def ingestion_budget_register(self, ingestion_id: str, budget: Mapping[str, Any]) -> dict[str, Any]:
        result = self.client.eval(
            _INGESTION_BUDGET_REGISTER_SCRIPT,
            1,
            self._ingestion_budget_key(ingestion_id),
            str(budget.get("token_budget", 0)),
            str(budget.get("parser_units", 0)),
            str(budget.get("ocr_calls", 0)),
            str(budget.get("vision_calls", 0)),
            str(budget.get("summary_tokens", 0)),
            str(budget.get("embedding_tokens", 0)),
            str(budget.get("max_fan_out", 0)),
            str(ingestion_id),
            str(budget.get("wall_time_seconds", 0)),
        )
        if _text(result[0]) == "error":
            return {"error": _text(result[1])}
        return self.ingestion_budget_snapshot(ingestion_id) or {}

    def ingestion_budget_charge(
        self,
        ingestion_id: str,
        *,
        stage: str,
        units: int,
        tokens: int,
        fan_out: int,
    ) -> dict[str, Any]:
        result = self.client.eval(
            _INGESTION_BUDGET_CHARGE_SCRIPT,
            1,
            self._ingestion_budget_key(ingestion_id),
            str(stage),
            str(units),
            str(tokens),
            str(fan_out),
        )
        if _text(result[0]) == "error":
            return {"error": _text(result[1])}
        return self.ingestion_budget_snapshot(ingestion_id) or {}

    def ingestion_budget_snapshot(self, ingestion_id: str) -> dict[str, Any] | None:
        raw = self.client.hgetall(self._ingestion_budget_key(ingestion_id))
        if not raw:
            return None
        result = {_text(key): _text(value) for key, value in raw.items()}
        for key in (
            "token_budget", "parser_units", "ocr_calls", "vision_calls",
            "summary_tokens", "embedding_tokens", "max_fan_out", "wall_time_seconds",
            "fan_out_used", "total_tokens", "units_parser", "units_ocr",
            "units_vision", "units_summary", "units_embedding", "tokens_parser",
            "tokens_ocr", "tokens_vision", "tokens_summary", "tokens_embedding",
        ):
            result[key] = int(float(result.get(key, 0)))
        result["ingestion_id"] = str(ingestion_id)
        result["budget"] = {
            key: result[key]
            for key in (
                "token_budget", "parser_units", "ocr_calls", "vision_calls",
                "summary_tokens", "embedding_tokens", "max_fan_out", "wall_time_seconds",
            )
        }
        result["stage_units"] = {
            stage: result[f"units_{stage}"] for stage in ("parser", "ocr", "vision", "summary", "embedding")
        }
        result["stage_tokens"] = {
            stage: result[f"tokens_{stage}"] for stage in ("parser", "ocr", "vision", "summary", "embedding")
        }
        return result

    def ingestion_usage_record(self, ingestion_id: str, record: Mapping[str, Any]) -> None:
        self.client.rpush(
            self._ingestion_usage_key(ingestion_id),
            json.dumps(dict(record), sort_keys=True, ensure_ascii=False, default=str),
        )

    def ingestion_usage_snapshot(self, ingestion_id: str) -> dict[str, Any]:
        rows = self.client.lrange(self._ingestion_usage_key(ingestion_id), 0, -1)
        records: list[dict[str, Any]] = []
        for raw in rows:
            try:
                value = json.loads(_text(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                records.append(value)
        estimates = [item for item in records if bool(item.get("is_estimate", False))]
        actuals = [item for item in records if not bool(item.get("is_estimate", False))]
        by_stage: dict[str, dict[str, int]] = {}
        for item in records:
            stage = str(item.get("stage", ""))
            bucket = by_stage.setdefault(stage, {"estimated_tokens": 0, "actual_tokens": 0, "calls": 0})
            bucket["calls"] += 1
            bucket["estimated_tokens" if bool(item.get("is_estimate", False)) else "actual_tokens"] += int(item.get("total_tokens", 0) or 0)
        return {
            "records": records,
            "by_stage": by_stage,
            "estimated_tokens": sum(int(item.get("total_tokens", 0) or 0) for item in estimates),
            "actual_tokens": sum(int(item.get("total_tokens", 0) or 0) for item in actuals),
            "usage_is_estimate": bool(estimates),
        }

    def dag_snapshot(self, run_id: str) -> dict[str, Any] | None:
        raw = self.client.get(self._dag_key(run_id))
        if raw is None:
            return None
        try:
            snapshot = json.loads(_text(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return snapshot if isinstance(snapshot, dict) else None

    def dag_snapshot_put(self, run_id: str, snapshot: Mapping[str, Any]) -> int:
        """Create an immutable initial DAG snapshot exactly once."""

        payload = dict(snapshot)
        payload["run_id"] = str(run_id)
        payload["revision"] = 1
        nodes = payload.get("nodes")
        if not isinstance(nodes, dict):
            raise ValueError("DAG snapshot nodes must be a mapping")
        payload["status"] = _dag_status(nodes)
        created = self.client.set(
            self._dag_key(run_id),
            json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str),
            nx=True,
        )
        if not created:
            raise ControlPlaneConflict("DAG snapshot already exists")
        return 1

    def dag_snapshot_patch(
        self,
        run_id: str,
        nodes: Mapping[str, Mapping[str, Any]],
    ) -> int:
        """Atomically merge changed node state into a shared DAG snapshot."""

        if not nodes:
            current = self.dag_snapshot(run_id)
            if current is None:
                raise ControlPlaneConflict("DAG snapshot does not exist")
            return int(current.get("revision", 0))
        key = self._dag_key(run_id)
        try:
            from redis.exceptions import WatchError  # type: ignore[import-not-found]
        except ImportError:  # pragma: no cover - only used with a real Redis client
            WatchError = RuntimeError  # type: ignore[assignment,misc]
        for _ in range(8):
            pipe = self.client.pipeline()
            try:
                pipe.watch(key)
                raw = pipe.get(key)
                if raw is None:
                    raise ControlPlaneConflict("DAG snapshot does not exist")
                snapshot = json.loads(_text(raw))
                if not isinstance(snapshot, dict):
                    raise ControlPlaneConflict("DAG snapshot is invalid")
                current_nodes = snapshot.get("nodes")
                if not isinstance(current_nodes, dict):
                    raise ControlPlaneConflict("DAG snapshot nodes are invalid")
                merged_nodes = dict(current_nodes)
                merged_nodes.update({str(node_id): dict(value) for node_id, value in nodes.items()})
                snapshot["nodes"] = merged_nodes
                snapshot["status"] = _dag_status(merged_nodes)
                revision = int(snapshot.get("revision", 0)) + 1
                snapshot["revision"] = revision
                snapshot["updated_at"] = datetime.now(timezone.utc).isoformat()
                pipe.multi()
                pipe.set(key, json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str))
                pipe.execute()
                return revision
            except WatchError:
                continue
            finally:
                reset = getattr(pipe, "reset", None)
                if reset is not None:
                    reset()
        raise ControlPlaneConflict("DAG snapshot update conflicted repeatedly")

    def reclaim(
        self,
        queue: str,
        *,
        owner: str,
        min_idle_ms: int,
    ) -> QueueMessage | None:
        if min_idle_ms < 1:
            raise ValueError("min_idle_ms must be positive")
        queue_key = self._queue_key(queue)
        group = self._group_name(queue)
        self._ensure_group(queue_key, group)
        response = self.client.xautoclaim(
            queue_key,
            group,
            str(owner),
            min_idle_ms,
            start_id="0-0",
            count=1,
        )
        if not response:
            return None
        entries = response[1] if len(response) > 1 else []
        if not entries:
            return None
        message_id, values = entries[0]
        resource_key = values.get("resource_key") or values.get(b"resource_key")
        if resource_key is None:
            raise ValueError("reclaimed queue entry is missing resource_key")
        return QueueMessage(queue, _text(message_id), _text(resource_key))

    def claim(self, resource_key: str, *, owner: str, lease_seconds: float) -> LeaseToken | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        state_key, fence_key, events_key = self._keys(resource_key)
        now = time.time()
        result = self.client.eval(
            _CLAIM_SCRIPT,
            3,
            state_key,
            fence_key,
            events_key,
            str(owner),
            str(now),
            str(lease_seconds),
        )
        marker = _text(result[0])
        if marker != "claimed":
            return None
        self._trim_events(events_key)
        return LeaseToken(str(resource_key), str(owner), int(_text(result[1])), float(_text(result[2])))

    def renew(self, lease: LeaseToken, *, lease_seconds: float) -> LeaseToken:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        state_key, _, _ = self._keys(lease.resource_key)
        result = self.client.eval(
            _RENEW_SCRIPT,
            1,
            state_key,
            lease.owner,
            str(lease.fencing_token),
            str(time.time()),
            str(lease_seconds),
        )
        if _text(result[0]) != "renewed":
            raise StaleLeaseError("lease is no longer owned by this worker")
        return LeaseToken(lease.resource_key, lease.owner, lease.fencing_token, float(_text(result[1])))

    def transition(
        self,
        lease: LeaseToken,
        *,
        status: str,
        result: Mapping[str, Any] | None = None,
    ) -> None:
        state_key, _, events_key = self._keys(lease.resource_key)
        response = self.client.eval(
            _TRANSITION_SCRIPT,
            2,
            state_key,
            events_key,
            lease.owner,
            str(lease.fencing_token),
            str(status),
            json.dumps(dict(result or {}), sort_keys=True, ensure_ascii=False, default=str),
            str(time.time()),
        )
        if _text(response[0]) != "ok":
            raise StaleLeaseError("stale worker cannot write terminal state")
        self._trim_events(events_key)

    def schedule_retry(self, lease: LeaseToken, *, retry_at: float, error: str) -> None:
        state_key, _, events_key = self._keys(lease.resource_key)
        response = self.client.eval(
            _RETRY_SCRIPT,
            2,
            state_key,
            events_key,
            lease.owner,
            str(lease.fencing_token),
            str(error)[:2000],
            str(retry_at),
            str(time.time()),
        )
        if _text(response[0]) != "ok":
            raise StaleLeaseError("stale worker cannot schedule a retry")
        self._trim_events(events_key)

    def state(self, resource_key: str) -> dict[str, Any] | None:
        state_key, _, _ = self._keys(resource_key)
        raw = self.client.hgetall(state_key)
        if not raw:
            return None
        return {_text(key): _text(value) for key, value in raw.items()}

    def events(self, resource_key: str, *, after_id: str = "-") -> tuple[dict[str, str], ...]:
        _, _, events_key = self._keys(resource_key)
        rows = self.client.xrange(events_key, min=after_id, max="+")
        events: list[dict[str, str]] = []
        for event_id, values in rows:
            event = {"event_id": _text(event_id)}
            event.update({_text(key): _text(value) for key, value in values.items()})
            events.append(event)
        return tuple(events)


def new_worker_id(prefix: str = "worker") -> str:
    """Create a non-secret owner ID for lease diagnostics."""

    return f"{prefix}-{uuid4().hex}"


__all__ = [
    "AdmissionResult",
    "ControlPlane",
    "ControlPlaneConflict",
    "LeaseToken",
    "QueueMessage",
    "RedisControlPlane",
    "StaleLeaseError",
    "new_worker_id",
]
