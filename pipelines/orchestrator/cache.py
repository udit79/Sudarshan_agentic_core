"""Verified, fingerprinted cache for deterministic skill artifacts.

The cache stores references to already-produced artifacts, never prompts,
retrieved records, or raw model output. A cache hit is therefore an
optimization of a validated execution, not a second source of truth for run
state or permissions.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import time
from typing import Any, Mapping
from uuid import uuid4


def _canonical(value: Any) -> Any:
    """Convert supported values to deterministic JSON-safe structures."""

    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def stable_hash(value: Any) -> str:
    """Return a SHA-256 digest without persisting the value itself."""

    encoded = json.dumps(
        _canonical(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_cache_fingerprint(
    *,
    skill_id: str,
    skill_version: str,
    stage_contract: Mapping[str, Any] | str,
    input_artifact_hashes: list[str] | tuple[str, ...],
    input_payload_hash: str,
    tool_provider_versions: Mapping[str, Any] | None = None,
    model_policy: Mapping[str, Any] | None = None,
    authorization_scope: Mapping[str, Any] | None = None,
) -> str:
    """Build a cache key from all inputs that can change the result.

    Callers should pass a digest for raw input payloads. This function is
    intentionally explicit about skill/version, policy, tools, and auth scope
    so a policy or renderer change cannot silently reuse an old artifact.
    """

    return stable_hash(
        {
            "skill_id": skill_id,
            "skill_version": skill_version,
            "stage_contract": stage_contract,
            "input_artifact_hashes": list(input_artifact_hashes),
            "input_payload_hash": input_payload_hash,
            "tool_provider_versions": tool_provider_versions or {},
            "model_policy": model_policy or {},
            "authorization_scope": authorization_scope or {},
        }
    )


@dataclass(frozen=True, slots=True)
class CacheEntry:
    fingerprint: str
    skill_id: str
    skill_version: str
    artifact_ids: tuple[str, ...]
    quality_report_id: str | None
    quality_status: str
    created_at: float
    expires_at: float | None
    metadata: Mapping[str, Any]


class CacheStore:
    """Small SQLite cache with verified entries and stampede leases."""

    def __init__(self, db_path: str = "artifacts/.state/skill_cache.db") -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = Lock()
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                fingerprint TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                skill_version TEXT NOT NULL,
                artifact_ids_json TEXT NOT NULL,
                quality_report_id TEXT,
                quality_status TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL,
                metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cache_claims (
                fingerprint TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                expires_at REAL NOT NULL
            );
            """
        )
        self._connection.commit()

    def put(
        self,
        *,
        fingerprint: str,
        skill_id: str,
        skill_version: str,
        artifact_ids: list[str] | tuple[str, ...],
        quality_report_id: str | None,
        quality_status: str,
        ttl_seconds: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> CacheEntry:
        """Store only a quality-passed artifact reference."""

        refs = tuple(str(item).strip() for item in artifact_ids if str(item).strip())
        if quality_status != "passed":
            raise ValueError("only quality-passed artifacts may be cached")
        if not refs:
            raise ValueError("cached entries require at least one artifact reference")
        now = time()
        expires_at = now + ttl_seconds if ttl_seconds is not None else None
        safe_metadata = _safe_metadata(metadata or {})
        entry = CacheEntry(
            fingerprint=fingerprint,
            skill_id=skill_id,
            skill_version=skill_version,
            artifact_ids=refs,
            quality_report_id=quality_report_id,
            quality_status=quality_status,
            created_at=now,
            expires_at=expires_at,
            metadata=safe_metadata,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO cache_entries
                    (fingerprint, skill_id, skill_version, artifact_ids_json,
                     quality_report_id, quality_status, created_at, expires_at,
                     metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    skill_id=excluded.skill_id,
                    skill_version=excluded.skill_version,
                    artifact_ids_json=excluded.artifact_ids_json,
                    quality_report_id=excluded.quality_report_id,
                    quality_status=excluded.quality_status,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    entry.fingerprint,
                    entry.skill_id,
                    entry.skill_version,
                    json.dumps(entry.artifact_ids),
                    entry.quality_report_id,
                    entry.quality_status,
                    entry.created_at,
                    entry.expires_at,
                    json.dumps(entry.metadata, sort_keys=True),
                ),
            )
            self._connection.commit()
        return entry

    def get(self, fingerprint: str, *, now: float | None = None) -> CacheEntry | None:
        current = time() if now is None else now
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM cache_entries WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] is not None and float(row["expires_at"]) <= current:
                self._connection.execute("DELETE FROM cache_entries WHERE fingerprint = ?", (fingerprint,))
                self._connection.commit()
                return None
            if row["quality_status"] != "passed":
                return None
            return CacheEntry(
                fingerprint=row["fingerprint"],
                skill_id=row["skill_id"],
                skill_version=row["skill_version"],
                artifact_ids=tuple(json.loads(row["artifact_ids_json"])),
                quality_report_id=row["quality_report_id"],
                quality_status=row["quality_status"],
                created_at=float(row["created_at"]),
                expires_at=(float(row["expires_at"]) if row["expires_at"] is not None else None),
                metadata=json.loads(row["metadata_json"]),
            )

    def invalidate(self, fingerprint: str) -> None:
        with self._lock:
            self._connection.execute("DELETE FROM cache_entries WHERE fingerprint = ?", (fingerprint,))
            self._connection.commit()

    def try_claim(self, fingerprint: str, *, owner: str | None = None, lease_seconds: float = 300) -> str | None:
        """Claim a missing key to avoid duplicate expensive generation."""

        claim_owner = owner or f"claim-{uuid4().hex}"
        now = time()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute("DELETE FROM cache_claims WHERE expires_at <= ?", (now,))
                existing = self._connection.execute(
                    "SELECT owner FROM cache_claims WHERE fingerprint = ?", (fingerprint,)
                ).fetchone()
                if existing is not None:
                    self._connection.commit()
                    return None
                self._connection.execute(
                    "INSERT INTO cache_claims (fingerprint, owner, expires_at) VALUES (?, ?, ?)",
                    (fingerprint, claim_owner, now + lease_seconds),
                )
                self._connection.commit()
                return claim_owner
            except sqlite3.IntegrityError:
                # Another process may win the race after SQLite releases its
                # write lock. Treat that as an ordinary in-flight claim.
                self._connection.rollback()
                return None

    def release_claim(self, fingerprint: str, owner: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM cache_claims WHERE fingerprint = ? AND owner = ?",
                (fingerprint, owner),
            )
            self._connection.commit()
            return cursor.rowcount == 1

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def _safe_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Keep cache metadata small and explicit; raw content is not metadata."""

    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        name = str(key).lower()
        if any(marker in name for marker in (
            "prompt", "query", "content", "input", "secret", "memory",
            "api_key", "access_token", "refresh_token", "authorization",
            "credential", "password", "private_key",
        )):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)[:80]] = value
        elif isinstance(value, (list, tuple)) and all(isinstance(item, (str, int, float, bool)) for item in value):
            safe[str(key)[:80]] = list(value)[:32]
    return safe


__all__ = ["CacheEntry", "CacheStore", "build_cache_fingerprint", "stable_hash"]
