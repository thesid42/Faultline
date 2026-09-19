"""Fixed child entrypoint for one granted target execution.

This module accepts only serialized scenario/grant data on stdin or through
``main``. It reads the OpenRouter credential from the one-process environment,
never opens the parent's ledger, and emits one JSON result.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Mapping

from .execution import SUPPORTED_PROVIDERS
from .budget import BudgetExceeded, BudgetReservation
from .live import OpenRouterProvider
from .models import Scenario
from .return_desk import ReturnDesk
from .worker import OneCallGrant


class GrantedOpenRouterProvider(OpenRouterProvider):
    """OpenRouter adapter constrained entirely by a parent-issued grant."""

    def __init__(self, grant: OneCallGrant, *, api_key: str, timeout: float = 120.0) -> None:
        if grant.provider not in SUPPORTED_PROVIDERS:
            raise ValueError("unsupported target provider")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required in child process")
        paid = not grant.model.endswith(":free")
        prompt_price = grant.prompt_price_per_million or (0.30 if paid else 0.0)
        completion_price = grant.completion_price_per_million or (1.20 if paid else 0.0)
        super().__init__(
            grant.model,
            api_key=api_key,
            timeout=timeout,
            max_retries=0,
            price_per_call=grant.max_cost_usd,
            budget=None,
            max_prompt_tokens=grant.max_prompt_tokens,
            max_output_tokens=grant.max_output_tokens,
            prompt_price_per_million=prompt_price,
            completion_price_per_million=completion_price,
            provider_name=grant.provider,
            case_id=None,
        )
        self.grant = grant
        self._dispatched = False
        self.provider = grant.provider
        self.backend = "openrouter-child"
        self.version = "chat-completions-v1-granted"

    def _reserve(self):
        # The parent has already reserved and claimed this exact call.
        if self._dispatched:
            raise RuntimeError("granted target call already dispatched")
        self._dispatched = True
        return BudgetReservation(self.grant.reservation_id, self.grant.request_id, self.grant.max_cost_usd, "dispatched")

    def _settle(self, reservation, actual):
        # Receipt reconciliation is parent-only after this process exits.
        if actual is not None and actual > self.grant.max_cost_usd:
            raise BudgetExceeded("actual provider charge exceeded immutable child grant")
        return None


def _request_from_wrapped_daytona(request: Mapping[str, Any]) -> Mapping[str, Any]:
    candidate = request.get("input")
    if isinstance(candidate, Mapping) and "grant" in candidate and "scenario" in candidate:
        return candidate
    return request


def execute_request(request: Mapping[str, Any]) -> dict[str, Any]:
    request = _request_from_wrapped_daytona(request)
    grant_payload = request.get("grant")
    scenario_payload = request.get("scenario")
    if not isinstance(grant_payload, Mapping) or not isinstance(scenario_payload, Mapping):
        raise ValueError("worker request must contain grant and scenario")
    grant = OneCallGrant(**dict(grant_payload))
    scenario = Scenario.model_validate(scenario_payload)
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    provider = GrantedOpenRouterProvider(grant, api_key=api_key)
    target = ReturnDesk(provider=provider)
    run = target.run(
        scenario,
        configuration_id=str(request.get("configuration_id", "default")),
        fixture_partition=str(request.get("fixture_partition", "main")),
        source_run_id=request.get("source_run_id"),
    )
    receipt = provider.last_receipt.as_dict() if provider.last_receipt is not None else None
    return {"run_record": run.model_dump(mode="json"), "receipt": receipt}


def main(request: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if request is None:
        raw = sys.stdin.read()
        request = json.loads(raw)
    return execute_request(request)


if __name__ == "__main__":
    try:
        print(json.dumps(main(), sort_keys=True, separators=(",", ":")))
    except Exception as exc:
        print(json.dumps({"run_record": None, "receipt": None, "error": type(exc).__name__}, sort_keys=True, separators=(",", ":")))
        raise SystemExit(1)
