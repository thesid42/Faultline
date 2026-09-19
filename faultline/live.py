"""Explicit live OpenRouter adapters.

Live providers never fall back to fixtures. Errors record only safe error
classes/statuses so API keys and response bodies cannot enter artifacts.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any

import httpx

from .models import Action, BudgetState, ControllerAction


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"http_status_{exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.NetworkError):
        return "network_error"
    return type(exc).__name__


class OpenRouterProvider:
    evidence_origin = "live"
    provider = "openrouter"
    backend = "httpx"
    version = "chat-completions-v1"

    def __init__(self, model: str, *, api_key: str | None = None, timeout: float = 30.0, max_retries: int = 2, price_per_call: float | None = None, budget: BudgetState | None = None) -> None:
        if not model:
            raise ValueError("target model is required")
        if price_per_call is None or not math.isfinite(price_per_call) or price_per_call < 0:
            raise ValueError("finite non-negative price_per_call is required")
        if not model.endswith(":free") or price_per_call != 0:
            raise RuntimeError("paid live models are deferred until verified provider pricing and usage reconciliation are available")
        if budget is None:
            raise RuntimeError("live model calls require a parent-owned BudgetState")
        self.model = model
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for live model calls")
        self.timeout = timeout
        self.max_retries = max(0, min(max_retries, 3))
        self.price_per_call = price_per_call
        self.budget = budget

    def _request(self, messages: list[dict[str, Any]], response_format: dict[str, Any]) -> dict[str, Any]:
        request = {"model": self.model, "messages": messages, "response_format": response_format, "max_tokens": 300}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            # Reserve every attempt before dispatch, including retries and
            # ambiguous in-flight timeouts. Settlement is conservative.
            self.budget.reserve(self.price_per_call, paid=True)
            settled = False
            try:
                response = httpx.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=request, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                self.budget.settle(self.price_per_call, self.price_per_call, paid=True)
                settled = True
                if isinstance(content, str):
                    return json.loads(content)
                if isinstance(content, dict):
                    return content
                raise ValueError("structured content is not an object")
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, KeyError, ValueError, json.JSONDecodeError) as exc:
                if not settled:
                    self.budget.settle(self.price_per_call, self.price_per_call, paid=True)
                last = exc
                if attempt >= self.max_retries:
                    break
        raise RuntimeError(f"live structured call failed: {_safe_error(last or RuntimeError())}")

    def choose_action(self, *, order: dict[str, Any], policy: dict[str, Any], notes: list[str]) -> Action:
        data = self._request(
            [{"role": "system", "content": "Return JSON with kind (refund|escalate|deny), order_id, amount, reason, idempotency_key only."}, {"role": "user", "content": json.dumps({"order": order, "policy": policy, "notes": notes}, sort_keys=True)}],
            {"type": "json_object"},
        )
        return Action.model_validate(data)


class OpenRouterInvestigatorController(OpenRouterProvider):
    """Separate investigator model/configuration using typed commands."""

    version = "investigator-controller-v1"

    def next_action(self, observations: list[dict[str, Any]]) -> ControllerAction:
        data = self._request(
            [{"role": "system", "content": "Return one JSON command: kind is inspect_trace|triage_hypotheses|run_experiment|probe_case|check_suite|propose_tests|finish. For run_experiment include operator policy_notes|remove_note|order_age and value. Never emit code."}, {"role": "user", "content": json.dumps({"observations": observations[-8:]}, sort_keys=True)}],
            {"type": "json_object"},
        )
        return ControllerAction.model_validate(data)


def reserve_live_call(budget: BudgetState, provider: OpenRouterProvider) -> None:
    """Compatibility helper; providers reserve per attempt internally."""
    budget.reserve(provider.price_per_call, paid=True)
