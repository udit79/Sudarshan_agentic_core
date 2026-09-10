"""Budget and cache primitives for bounded ingestion stages.

This module is independent from the scheduler and model clients. Adapters can
charge parser/OCR/vision/summary/embedding work before expensive work, while
the cache reuses a derived stage only when all result-affecting inputs match.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Mapping

from ingestion_pipelines.contracts import IngestionBudget


IngestionStage = Literal["parser", "ocr", "vision", "summary", "embedding"]
_STAGES: tuple[IngestionStage, ...] = ("parser", "ocr", "vision", "summary", "embedding")


class IngestionBudgetExceededError(RuntimeError):
    """Raised before a stage exceeds its declared ingestion envelope."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class IngestionBudgetSnapshot:
    ingestion_id: str
    budget: IngestionBudget
    stage_units: Mapping[str, int]
    stage_tokens: Mapping[str, int]
    fan_out_used: int
    total_tokens: int


class IngestionBudgetController:
    """Thread-safe per-ingestion accounting with a hard fan-out guard."""

    def __init__(self) -> None:
        self._budgets: dict[str, IngestionBudget] = {}
        self._stage_units: dict[str, dict[str, int]] = {}
        self._stage_tokens: dict[str, dict[str, int]] = {}
        self._fan_out: dict[str, int] = {}
        self._lock = Lock()

    def register(self, ingestion_id: str, budget: IngestionBudget) -> IngestionBudgetSnapshot:
        key = str(ingestion_id).strip()
        if not key:
            raise ValueError("ingestion_id must be non-empty")
        with self._lock:
            existing = self._budgets.get(key)
            if existing is not None and existing != budget:
                raise IngestionBudgetExceededError("BUDGET_CONFLICT", "ingestion already has a different budget")
            self._budgets[key] = budget
            self._stage_units.setdefault(key, {stage: 0 for stage in _STAGES})
            self._stage_tokens.setdefault(key, {stage: 0 for stage in _STAGES})
            self._fan_out.setdefault(key, 0)
            return self._snapshot_locked(key)

    def charge(
        self,
        ingestion_id: str,
        stage: IngestionStage,
        *,
        units: int = 1,
        tokens: int = 0,
        fan_out: int = 1,
    ) -> IngestionBudgetSnapshot:
        """Atomically charge work before invoking a parser or model."""

        if stage not in _STAGES:
            raise ValueError(f"unsupported ingestion stage: {stage}")
        if units < 0 or tokens < 0 or fan_out < 0:
            raise IngestionBudgetExceededError("INVALID_BUDGET", "charge values must be non-negative")
        with self._lock:
            key = str(ingestion_id).strip()
            budget = self._budgets.get(key)
            if budget is None:
                raise IngestionBudgetExceededError("NOT_REGISTERED", f"ingestion '{key}' is not registered")
            current_units = self._stage_units[key][stage]
            current_tokens = self._stage_tokens[key][stage]
            stage_limit = {
                "parser": budget.parser_units,
                "ocr": budget.ocr_calls,
                "vision": budget.vision_calls,
                "summary": budget.summary_tokens,
                "embedding": budget.embedding_tokens,
            }[stage]
            if stage in {"summary", "embedding"}:
                if current_tokens + tokens > stage_limit:
                    raise IngestionBudgetExceededError("STAGE_TOKEN_BUDGET", f"{stage} token budget is exhausted")
            elif current_units + units > stage_limit:
                raise IngestionBudgetExceededError("STAGE_CALL_BUDGET", f"{stage} call budget is exhausted")
            total_tokens = sum(self._stage_tokens[key].values()) + tokens
            if budget.token_budget and total_tokens > budget.token_budget:
                raise IngestionBudgetExceededError("TOKEN_BUDGET", "ingestion token budget is exhausted")
            if self._fan_out[key] + fan_out > budget.max_fan_out:
                raise IngestionBudgetExceededError("FAN_OUT_BUDGET", "ingestion fan-out limit is exhausted")
            self._stage_units[key][stage] += units
            self._stage_tokens[key][stage] += tokens
            self._fan_out[key] += fan_out
            return self._snapshot_locked(key)

    def snapshot(self, ingestion_id: str) -> IngestionBudgetSnapshot:
        with self._lock:
            key = str(ingestion_id).strip()
            if key not in self._budgets:
                raise IngestionBudgetExceededError("NOT_REGISTERED", f"ingestion '{key}' is not registered")
            return self._snapshot_locked(key)

    def _snapshot_locked(self, ingestion_id: str) -> IngestionBudgetSnapshot:
        return IngestionBudgetSnapshot(
            ingestion_id=ingestion_id,
            budget=self._budgets[ingestion_id],
            stage_units=dict(self._stage_units[ingestion_id]),
            stage_tokens=dict(self._stage_tokens[ingestion_id]),
            fan_out_used=self._fan_out[ingestion_id],
            total_tokens=sum(self._stage_tokens[ingestion_id].values()),
        )


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def build_ingestion_stage_fingerprint(
    *,
    source_hash: str,
    stage: IngestionStage,
    stage_version: str,
    configuration_hash: str,
    model_policy: Mapping[str, Any] | str,
    scope: Mapping[str, Any],
    input_fingerprints: list[str] | tuple[str, ...] = (),
) -> str:
    """Hash every input that can change a derived ingestion stage."""

    if stage not in _STAGES:
        raise ValueError(f"unsupported ingestion stage: {stage}")
    payload = _canonical(
        {
            "source_hash": source_hash,
            "stage": stage,
            "stage_version": stage_version,
            "configuration_hash": configuration_hash,
            "model_policy": model_policy,
            "scope": scope,
            "input_fingerprints": list(input_fingerprints),
        }
    )
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class IngestionStageCacheEntry:
    fingerprint: str
    source_hash: str
    stage: str
    stage_version: str
    user_id: str | None
    case_id: str | None
    task_id: str | None
    classification_level: str
    payload: Any
    created_at: float
    expires_at: float | None


class IngestionStageCache:
    """Local scoped cache for derived stage payloads, not run state."""

    def __init__(self, db_path: str | Path = "artifacts/.state/ingestion_stage_cache.db") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = Lock()
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ingestion_stage_cache (
                fingerprint TEXT PRIMARY KEY,
                source_hash TEXT NOT NULL,
                stage TEXT NOT NULL,
                stage_version TEXT NOT NULL,
                user_id TEXT,
                case_id TEXT,
                task_id TEXT,
                classification_level TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL
            )
            """
        )
        self._connection.commit()

    def put(
        self,
        *,
        fingerprint: str,
        source_hash: str,
        stage: IngestionStage,
        stage_version: str,
        scope: Mapping[str, Any],
        classification_level: str,
        payload: Any,
        ttl_seconds: float | None = None,
    ) -> IngestionStageCacheEntry:
        if stage not in _STAGES:
            raise ValueError(f"unsupported ingestion stage: {stage}")
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive when provided")
        encoded = json.dumps(_canonical(payload), ensure_ascii=False, separators=(",", ":"))
        now = time.time()
        expires_at = now + ttl_seconds if ttl_seconds is not None else None
        entry = IngestionStageCacheEntry(
            fingerprint=str(fingerprint),
            source_hash=str(source_hash),
            stage=stage,
            stage_version=str(stage_version),
            user_id=_scope_value(scope, "user_id"),
            case_id=_scope_value(scope, "case_id"),
            task_id=_scope_value(scope, "task_id"),
            classification_level=str(classification_level),
            payload=json.loads(encoded),
            created_at=now,
            expires_at=expires_at,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO ingestion_stage_cache
                    (fingerprint, source_hash, stage, stage_version, user_id,
                     case_id, task_id, classification_level, payload_json,
                     created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    source_hash=excluded.source_hash,
                    stage=excluded.stage,
                    stage_version=excluded.stage_version,
                    user_id=excluded.user_id,
                    case_id=excluded.case_id,
                    task_id=excluded.task_id,
                    classification_level=excluded.classification_level,
                    payload_json=excluded.payload_json,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at
                """,
                (
                    entry.fingerprint,
                    entry.source_hash,
                    entry.stage,
                    entry.stage_version,
                    entry.user_id,
                    entry.case_id,
                    entry.task_id,
                    entry.classification_level,
                    encoded,
                    entry.created_at,
                    entry.expires_at,
                ),
            )
            self._connection.commit()
        return entry

    def get(
        self,
        fingerprint: str,
        *,
        scope: Mapping[str, Any],
        classification_level: str,
        now: float | None = None,
    ) -> IngestionStageCacheEntry | None:
        current = time.time() if now is None else now
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM ingestion_stage_cache WHERE fingerprint = ?",
                (str(fingerprint),),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] is not None and float(row["expires_at"]) <= current:
                self._connection.execute("DELETE FROM ingestion_stage_cache WHERE fingerprint = ?", (str(fingerprint),))
                self._connection.commit()
                return None
            expected = {"user_id": row["user_id"], "case_id": row["case_id"], "task_id": row["task_id"]}
            if any(_scope_value(scope, key) != value for key, value in expected.items()):
                return None
            if str(classification_level) != str(row["classification_level"]):
                return None
            return IngestionStageCacheEntry(
                fingerprint=str(row["fingerprint"]),
                source_hash=str(row["source_hash"]),
                stage=str(row["stage"]),
                stage_version=str(row["stage_version"]),
                user_id=row["user_id"],
                case_id=row["case_id"],
                task_id=row["task_id"],
                classification_level=str(row["classification_level"]),
                payload=json.loads(str(row["payload_json"])),
                created_at=float(row["created_at"]),
                expires_at=(float(row["expires_at"]) if row["expires_at"] is not None else None),
            )

    def invalidate(self, fingerprint: str) -> None:
        with self._lock:
            self._connection.execute("DELETE FROM ingestion_stage_cache WHERE fingerprint = ?", (str(fingerprint),))
            self._connection.commit()

    def cleanup_expired(self, *, now: float | None = None) -> int:
        current = time.time() if now is None else now
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM ingestion_stage_cache WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (current,),
            )
            self._connection.commit()
            return int(cursor.rowcount)

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class IngestionUsageRecorder:
    """Thread-safe usage ledger separating preflight estimates from actuals."""

    def __init__(self) -> None:
        self._records: dict[str, list[dict[str, Any]]] = {}
        self._lock = Lock()

    def record(
        self,
        ingestion_id: str,
        *,
        stage: str,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        is_estimate: bool = False,
    ) -> None:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("usage token counts must be non-negative")
        record = {
            "stage": str(stage),
            "provider": str(provider),
            "model": str(model),
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "total_tokens": int(input_tokens + output_tokens),
            "is_estimate": bool(is_estimate),
        }
        with self._lock:
            self._records.setdefault(str(ingestion_id), []).append(record)

    def record_estimate(self, ingestion_id: str, *, stage: str, tokens: int) -> None:
        self.record(
            ingestion_id,
            stage=stage,
            provider="budget",
            model="preflight",
            output_tokens=tokens,
            is_estimate=True,
        )

    def snapshot(self, ingestion_id: str) -> dict[str, Any]:
        with self._lock:
            records = [dict(item) for item in self._records.get(str(ingestion_id), [])]
        estimates = [item for item in records if item["is_estimate"]]
        actuals = [item for item in records if not item["is_estimate"]]
        by_stage: dict[str, dict[str, int]] = {}
        for item in records:
            stage = str(item["stage"])
            bucket = by_stage.setdefault(stage, {"estimated_tokens": 0, "actual_tokens": 0, "calls": 0})
            bucket["calls"] += 1
            key = "estimated_tokens" if item["is_estimate"] else "actual_tokens"
            bucket[key] += int(item["total_tokens"])
        return {
            "records": records,
            "by_stage": by_stage,
            "estimated_tokens": sum(int(item["total_tokens"]) for item in estimates),
            "actual_tokens": sum(int(item["total_tokens"]) for item in actuals),
            "usage_is_estimate": bool(estimates),
        }


def _scope_value(scope: Mapping[str, Any], key: str) -> str | None:
    value = scope.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "IngestionBudgetController",
    "IngestionBudgetExceededError",
    "IngestionBudgetSnapshot",
    "IngestionStageCache",
    "IngestionStageCacheEntry",
    "IngestionUsageRecorder",
    "IngestionStage",
    "build_ingestion_stage_fingerprint",
]
