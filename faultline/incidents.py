"""Incident intake and deduplication."""
from __future__ import annotations

import hashlib
import json

from .models import Incident, RunRecord


class IncidentQueue:
    def __init__(self) -> None:
        self._by_digest: dict[str, Incident] = {}

    def enqueue(self, run: RunRecord) -> Incident | None:
        if run.checker_passed is not False or run.status.value != "completed":
            return None
        payload = {"scenario": run.scenario.model_dump(mode="json"), "ledger": run.actual_ledger, "checker": run.checker_status}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        existing = self._by_digest.get(digest)
        if existing:
            return existing
        incident = Incident(run_id=run.run_id, violation_digest=digest)
        self._by_digest[digest] = incident
        return incident

    def all(self) -> list[Incident]:
        return list(self._by_digest.values())
