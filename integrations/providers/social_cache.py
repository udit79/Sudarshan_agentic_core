"""Scoped cache for provider-neutral social read responses."""

from __future__ import annotations

import json
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import time
from typing import Any, Mapping

_SECRET_MARKERS = (
    "access_token", "api_key", "authorization", "client_secret", "credential",
    "cookie", "password", "private_key", "refresh_token", "secret",
)


@dataclass(frozen=True, slots=True)
class SocialReadCacheEntry:
    fingerprint: str
    provider: str
    operation: str
    target_ref: str
    data: Mapping[str, Any]
    provenance: Mapping[str, Any]
    scope_hash: str
    skill_version: str
    policy_version: str
    created_at: float
    expires_at: float | None
    untrusted_data: bool = True


def build_social_read_fingerprint(
    *,
    provider: str,
    operation: str,
    target_ref: str,
    request_params: Mapping[str, Any] | None,
    skill_id: str,
    skill_version: str,
    authorization_scope: Mapping[str, Any],
    policy_version: str,
) -> str:
    """Build a read-cache key from provider, request, policy, and scope."""

    safe_scope = _safe_scope(authorization_scope)
    return _stable_hash({
        "provider": _bounded_text(provider, 80),
        "operation": _bounded_text(operation, 80),
        "target_ref": _safe_target_ref(target_ref),
        "request_params": _bounded_value(request_params or {}, depth=0),
        "skill_id": _bounded_text(skill_id, 120),
        "skill_version": _bounded_text(skill_version, 80),
        "authorization_scope": safe_scope,
        "policy_version": _bounded_text(policy_version, 80),
    })


class SocialReadCache:
    """SQLite-backed, TTL-bound cache for scoped social reads."""

    def __init__(self, db_path: str = "artifacts/.state/linkedin_read_cache.db") -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = Lock()
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS social_read_cache (
                fingerprint TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                target_ref TEXT NOT NULL,
                data_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                scope_hash TEXT NOT NULL,
                skill_version TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL,
                untrusted_data INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_social_read_target
                ON social_read_cache(provider, operation, target_ref, scope_hash);
            """
        )
        self._connection.commit()

    def get(self, fingerprint: str, *, now: float | None = None) -> SocialReadCacheEntry | None:
        current = time() if now is None else float(now)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM social_read_cache WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] is not None and float(row["expires_at"]) <= current:
                self._connection.execute("DELETE FROM social_read_cache WHERE fingerprint = ?", (fingerprint,))
                self._connection.commit()
                return None
            try:
                data = json.loads(row["data_json"])
                provenance = json.loads(row["provenance_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                self._connection.execute("DELETE FROM social_read_cache WHERE fingerprint = ?", (fingerprint,))
                self._connection.commit()
                return None
            if not isinstance(data, Mapping) or not isinstance(provenance, Mapping):
                return None
            return SocialReadCacheEntry(
                fingerprint=str(row["fingerprint"]), provider=str(row["provider"]),
                operation=str(row["operation"]), target_ref=str(row["target_ref"]),
                data=dict(data), provenance=dict(provenance), scope_hash=str(row["scope_hash"]),
                skill_version=str(row["skill_version"]), policy_version=str(row["policy_version"]),
                created_at=float(row["created_at"]),
                expires_at=float(row["expires_at"]) if row["expires_at"] is not None else None,
                untrusted_data=bool(row["untrusted_data"]),
            )

    def put(
        self,
        *,
        fingerprint: str,
        provider: str,
        operation: str,
        target_ref: str,
        data: Mapping[str, Any],
        provenance: Mapping[str, Any] | None,
        authorization_scope: Mapping[str, Any],
        skill_version: str,
        policy_version: str,
        ttl_seconds: float,
    ) -> SocialReadCacheEntry:
        if ttl_seconds < 0:
            raise ValueError("social read cache ttl must be non-negative")
        safe_scope = _safe_scope(authorization_scope)
        safe_data = sanitize_social_mapping(data)
        safe_provenance = sanitize_social_mapping(provenance or {})
        now = time()
        entry = SocialReadCacheEntry(
            fingerprint=_bounded_text(fingerprint, 128), provider=_bounded_text(provider, 80),
            operation=_bounded_text(operation, 80), target_ref=_safe_target_ref(target_ref),
            data=dict(safe_data), provenance=dict(safe_provenance), scope_hash=_stable_hash(safe_scope),
            skill_version=_bounded_text(skill_version, 80), policy_version=_bounded_text(policy_version, 80),
            created_at=now, expires_at=now + ttl_seconds if ttl_seconds > 0 else now,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO social_read_cache
                    (fingerprint, provider, operation, target_ref, data_json,
                     provenance_json, scope_hash, skill_version, policy_version,
                     created_at, expires_at, untrusted_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    provider=excluded.provider, operation=excluded.operation,
                    target_ref=excluded.target_ref, data_json=excluded.data_json,
                    provenance_json=excluded.provenance_json, scope_hash=excluded.scope_hash,
                    skill_version=excluded.skill_version, policy_version=excluded.policy_version,
                    created_at=excluded.created_at, expires_at=excluded.expires_at,
                    untrusted_data=excluded.untrusted_data
                """,
                (
                    entry.fingerprint, entry.provider, entry.operation, entry.target_ref,
                    json.dumps(entry.data, ensure_ascii=False, sort_keys=True),
                    json.dumps(entry.provenance, ensure_ascii=False, sort_keys=True),
                    entry.scope_hash, entry.skill_version, entry.policy_version,
                    entry.created_at, entry.expires_at,
                ),
            )
            self._connection.commit()
        return entry

    def invalidate(self, *, provider: str, target_ref: str, authorization_scope: Mapping[str, Any]) -> int:
        """Invalidate all cached reads for one scoped target.

        The return value is the number of logical targets invalidated rather
        than the number of operation-specific cache rows removed. A target
        may have separate post, comments, and thread rows, but callers should
        observe one invalidation event for that target.
        """
        scope_hash = _stable_hash(_safe_scope(authorization_scope))
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM social_read_cache WHERE provider = ? AND target_ref = ? AND scope_hash = ?",
                (_bounded_text(provider, 80), _safe_target_ref(target_ref), scope_hash),
            )
            self._connection.commit()
            return 1 if cursor.rowcount > 0 else 0

    def cleanup_expired(self, *, now: float | None = None) -> int:
        current = time() if now is None else float(now)
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM social_read_cache WHERE expires_at IS NOT NULL AND expires_at <= ?", (current,)
            )
            self._connection.commit()
            return int(cursor.rowcount)

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def _safe_scope(scope: Mapping[str, Any]) -> dict[str, Any]:
    if not scope:
        raise ValueError("authorization scope is required for social reads")
    safe: dict[str, Any] = {}
    for key, value in scope.items():
        name = str(key).strip().lower()
        if not name or any(marker in name for marker in _SECRET_MARKERS):
            raise ValueError("authorization scope contains a secret-shaped field")
        safe[name[:80]] = _bounded_value(value, depth=0)
    return safe


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def sanitize_social_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Bound a provider response and remove credential-shaped fields."""

    sanitized = _bounded_value(value, depth=0)
    if not isinstance(sanitized, Mapping):
        raise ValueError("social read data must be a mapping")
    return dict(sanitized)


def _bounded_text(value: Any, maximum: int) -> str:
    text = str(value).strip()
    if not text or len(text) > maximum:
        raise ValueError(f"social read value must be 1-{maximum} characters")
    return text


def _safe_target_ref(value: Any) -> str:
    target_ref = _bounded_text(value, 2048)
    if any(marker in target_ref.lower() for marker in _SECRET_MARKERS):
        raise ValueError("target_ref contains a secret-shaped field")
    return target_ref


def _bounded_value(value: Any, *, depth: int) -> Any:
    if depth > 4:
        raise ValueError("social read data is too deeply nested")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:16000]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:100]:
            name = str(key).strip()
            if any(marker in name.lower() for marker in _SECRET_MARKERS):
                continue
            result[name[:120]] = _bounded_value(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_bounded_value(item, depth=depth + 1) for item in list(value)[:100]]
    return str(value)[:16000]


__all__ = [
    "SocialReadCache",
    "SocialReadCacheEntry",
    "build_social_read_fingerprint",
    "sanitize_social_mapping",
]
