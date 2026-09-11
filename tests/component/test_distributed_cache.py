from __future__ import annotations

import threading

from pipelines.orchestrator.cache import CacheStore


class FakeCachePlane:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.entries: dict[str, dict[str, object]] = {}
        self.claims: dict[str, str] = {}

    def cache_get(self, fingerprint):
        with self._lock:
            entry = self.entries.get(fingerprint)
            return dict(entry) if entry else None

    def cache_put(self, fingerprint, entry):
        with self._lock:
            self.entries[fingerprint] = dict(entry)

    def cache_claim(self, fingerprint, *, owner, lease_seconds):
        del lease_seconds
        with self._lock:
            if fingerprint in self.claims:
                return None
            self.claims[fingerprint] = owner
            return owner

    def cache_release(self, fingerprint, owner):
        with self._lock:
            if self.claims.get(fingerprint) != owner:
                return False
            del self.claims[fingerprint]
            return True

    def cache_invalidate(self, fingerprint):
        with self._lock:
            self.entries.pop(fingerprint, None)


def test_cache_store_uses_shared_entry_and_stampede_claim(tmp_path):
    control = FakeCachePlane()
    first = CacheStore(str(tmp_path / "first.db"), control_plane=control)
    second = CacheStore(str(tmp_path / "second.db"), control_plane=control)
    try:
        first.put(
            fingerprint="fp-shared",
            skill_id="visual.flowchart",
            skill_version="1",
            artifact_ids=["artifact-1"],
            quality_report_id="quality-1",
            quality_status="passed",
            metadata={"renderer": "native", "prompt": "must not survive"},
        )
        hit = second.get("fp-shared")
        assert hit is not None
        assert hit.artifact_ids == ("artifact-1",)
        assert "prompt" not in hit.metadata

        assert first.try_claim("fp-missing", owner="worker-1") == "worker-1"
        assert second.try_claim("fp-missing", owner="worker-2") is None
        assert second.release_claim("fp-missing", "worker-2") is False
        assert first.release_claim("fp-missing", "worker-1") is True
        assert second.try_claim("fp-missing", owner="worker-2") == "worker-2"

        first.invalidate("fp-shared")
        assert second.get("fp-shared") is None
    finally:
        first.close()
        second.close()
