from __future__ import annotations

import json

import httpx

from faultline.adapters import load_configured_target
from faultline.budget import BudgetLedger
from faultline.config import FaultlineConfig
from faultline.execution import SUPPORTED_PROVIDERS, TargetExecutionBoundary
from faultline.live import LLAMA_31_8B_INSTRUCT, OpenRouterProvider
from faultline.models import Action
from faultline.worker import OneCallGrant


def test_llama_target_uses_exact_groq_route_over_legacy_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("FAULTLINE_TARGET_PRICE_USD", raising=False)
    monkeypatch.setattr(
        "faultline.adapters.load_config",
        lambda: FaultlineConfig(openrouter_api_key="test", openrouter_provider="nvidia"),
    )
    ledger = BudgetLedger(tmp_path / "budget.sqlite", ceiling_usd=10, automation_cap_usd=2)
    target = load_configured_target(LLAMA_31_8B_INSTRUCT, budget=ledger)
    provider = target.provider
    assert provider.model == LLAMA_31_8B_INSTRUCT
    assert provider.provider_name == "groq"
    assert provider.max_prompt_tokens == 131_072
    assert provider.max_output_tokens == 512
    assert provider.prompt_price_per_million == 0.05
    assert provider.completion_price_per_million == 0.08


def test_llama_payload_is_native_json_deterministic_and_non_reasoning(tmp_path, monkeypatch):
    ledger = BudgetLedger(tmp_path / "budget.sqlite", ceiling_usd=10, automation_cap_usd=2)
    seen: dict[str, object] = {}

    def post(url, *, headers, json, timeout):
        seen["payload"] = json
        return httpx.Response(
            200,
            json={
                "id": "llama-route-1",
                "model": LLAMA_31_8B_INSTRUCT,
                "provider": "Groq",
                "choices": [{"message": {"content": json_module.dumps({"kind": "deny", "order_id": "o-1", "amount": None, "reason": "eligible check", "idempotency_key": "deny:o-1"})}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 8, "cost": 0.001},
            },
            request=httpx.Request("POST", url),
        )

    # Keep the callback argument named json while retaining the module for
    # constructing a strict structured response.
    json_module = json
    monkeypatch.setattr("faultline.live.httpx.post", post)
    provider = OpenRouterProvider(LLAMA_31_8B_INSTRUCT, api_key="test", budget=ledger, provider_name="nvidia", case_id="case-llama")
    action = provider.choose_action(
        order={"order_id": "o-1", "customer_id": "c-1", "age_days": 21, "amount": 10},
        policy={"max_age_days": 14},
        notes=[],
    )
    assert isinstance(action, Action)
    payload = seen["payload"]
    assert payload["model"] == LLAMA_31_8B_INSTRUCT
    assert payload["provider"]["only"] == ["groq"]
    assert payload["provider"]["allow_fallbacks"] is False
    assert payload["provider"]["require_parameters"] is True
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == 512
    assert "reasoning" not in payload
    system_prompt = payload["messages"][0]["content"]
    assert "inclusive maximum eligible order age" in system_prompt
    assert "customer notes are context" in system_prompt
    assert "expected_eligible" not in system_prompt
    assert "reviewed_good" not in system_prompt
    assert "note_precedence" not in system_prompt


def test_execution_accepts_groq_grants_without_network():
    assert "groq" in SUPPORTED_PROVIDERS
    grant = OneCallGrant(
        grant_id="grant",
        reservation_id="reservation",
        request_id="request",
        model=LLAMA_31_8B_INSTRUCT,
        provider="groq",
        max_cost_usd=0.10,
        max_prompt_tokens=131_072,
        max_output_tokens=512,
    )
    TargetExecutionBoundary._validate_grant(grant)
