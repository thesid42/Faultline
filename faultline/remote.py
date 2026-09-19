"""Optional remote execution seams; local fallback remains the default.

No Daytona or Jev SDK is imported here, keeping the offline package installable
without credentials. Production adapters can satisfy these protocols and must
preserve backend/provenance fields and cleanup results.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .models import Hypothesis


class ExperimentBackend(Protocol):
    backend_name: str

    def run_trial(self, payload: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]: ...


class TriageBackend(Protocol):
    def triage(self, *, state: dict[str, Any], questions: dict[str, str]) -> dict[str, Any]: ...


@dataclass
class DaytonaConfig:
    snapshot: str
    max_active: int = 2
    auto_stop_minutes: int = 5
    ttl_minutes: int = 10


@dataclass
class DaytonaRunner:
    """Dependency-injected seam for the reviewed Daytona lifecycle.

    An integration supplies `client`; this wrapper records sandbox IDs and
    cleanup failures without placing credentials in snapshots or artifacts.
    """

    client: Any
    config: DaytonaConfig
    backend_name: str = "daytona"

    def run_trial(self, payload: dict[str, Any], *, timeout_seconds: int = 120) -> dict[str, Any]:
        sandbox = None
        try:
            sandbox = self.client.create_sandbox(snapshot=self.config.snapshot, labels={"faultline": "trial"}, ttl_minutes=self.config.ttl_minutes)
            return {"sandbox_id": getattr(sandbox, "id", "unknown"), "result": sandbox.run(payload, timeout=timeout_seconds), "backend": self.backend_name}
        finally:
            if sandbox is not None:
                try:
                    self.client.delete_sandbox(sandbox, wait=True)
                except Exception as exc:
                    # Cleanup failure is surfaced as data, never swallowed as a
                    # successful trial; avoid serializing exception bodies.
                    raise RuntimeError(f"daytona_cleanup_{type(exc).__name__}") from None


# Atomic Jev questions are independent; application code decides routing.
DEFAULT_JEV_QUESTIONS = {
    "note_contradicts_policy": "Does any customer note contradict the current return policy max-age rule?",
    "note_is_historical": "Does the customer note describe historical guidance rather than a current exception?",
}


@dataclass
class OptionalJevTriage:
    backend: TriageBackend
    model_version: str = "jev-1.13.0"

    def triage(self, hypotheses: list[Hypothesis], evidence: dict[str, Any]) -> dict[str, Any] | None:
        if not hypotheses:
            return None
        questions = dict(DEFAULT_JEV_QUESTIONS)
        try:
            output = self.backend.triage(state={"evidence": evidence, "hypotheses": [item.model_dump(mode="json") for item in hypotheses]}, questions=questions)
        except Exception:
            # Unavailable/uncertain Jev does not discard investigator evidence.
            return None
        return {
            "questions": questions,
            "event_ids": [event.get("event_id") for event in evidence.get("events", []) if isinstance(event, dict)],
            "outputs": output,
            "model_version": self.model_version,
        }
