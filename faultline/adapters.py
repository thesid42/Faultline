"""Explicit application adapter configuration."""
from __future__ import annotations

import os

from .live import LLAMA_31_8B_INSTRUCT, OpenRouterInvestigatorController, OpenRouterProvider, REGISTERED_MODEL_ROUTES
from .budget import BudgetLedger
from .config import load_config
from .models import BudgetState
from .return_desk import ReturnDesk


def load_configured_target(name: str | None = None, *, budget: BudgetLedger | BudgetState | None = None, case_id: str | None = None) -> ReturnDesk:
    """Load a live target only when explicitly configured; never fake-fallback."""
    settings = load_config()
    name = name or os.getenv("FAULTLINE_TARGET_MODEL") or settings.openrouter_model
    if not name:
        raise RuntimeError("FAULTLINE_TARGET_MODEL is not configured")
    if name == "fake":
        raise RuntimeError("fake target is available only through the explicit offline smoke path")
    price = os.getenv("FAULTLINE_TARGET_PRICE_USD")
    # Free models are explicitly zero-cost. Paid calls use the provider's
    # conservative bound and therefore require a parent BudgetLedger.
    if price is None and not name.endswith(":free") and budget is None:
        raise RuntimeError("FAULTLINE_TARGET_PRICE_USD or a parent budget ledger is required for a live target")
    bound = float(price) if price is not None else None
    free = name.endswith(":free")
    route = REGISTERED_MODEL_ROUTES.get(name)
    if name == LLAMA_31_8B_INSTRUCT:
        # Exact registered route: do not inherit a stale NVIDIA/provider env.
        provider_name = "groq"
        max_prompt_tokens = int(route["max_prompt_tokens"])
        max_output_tokens = int(route["max_output_tokens"])
        prompt_price_per_million = float(route["prompt_price_per_million"])
        completion_price_per_million = float(route["completion_price_per_million"])
    else:
        provider_name = settings.openrouter_provider
        max_prompt_tokens = 256_000
        max_output_tokens = 512
        prompt_price_per_million = 0.0 if free else 0.30
        completion_price_per_million = 0.0 if free else 1.20
    return ReturnDesk(OpenRouterProvider(name, api_key=settings.openrouter_api_key or None, base_url=settings.openrouter_base_url, timeout=settings.openrouter_timeout_seconds, max_prompt_tokens=max_prompt_tokens, max_output_tokens=max_output_tokens, price_per_call=bound, prompt_price_per_million=prompt_price_per_million, completion_price_per_million=completion_price_per_million, budget=budget, case_id=case_id, provider_name=provider_name))


def load_configured_investigator(name: str | None = None, *, budget: BudgetLedger | BudgetState | None = None, case_id: str | None = None) -> OpenRouterInvestigatorController:
    """Construct the pinned, no-fallback investigator controller."""
    settings = load_config()
    model = name or os.getenv("FAULTLINE_INVESTIGATOR_MODEL") or "deepseek/deepseek-v4.1-flash"
    provider = os.getenv("FAULTLINE_INVESTIGATOR_PROVIDER", "deepinfra")
    return OpenRouterInvestigatorController(model, api_key=settings.openrouter_api_key or None, base_url=settings.openrouter_base_url, timeout=settings.openrouter_timeout_seconds, budget=budget, case_id=case_id, provider_name=provider)
