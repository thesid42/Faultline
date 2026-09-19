"""Explicit application adapter configuration."""
from __future__ import annotations

import os

from .live import OpenRouterProvider
from .models import BudgetState
from .return_desk import ReturnDesk


def load_configured_target(name: str | None = None) -> ReturnDesk:
    """Load a live target only when explicitly configured; never fake-fallback."""
    name = name or os.getenv("FAULTLINE_TARGET_MODEL")
    if not name:
        raise RuntimeError("FAULTLINE_TARGET_MODEL is not configured")
    if name == "fake":
        raise RuntimeError("fake target is available only through the explicit offline smoke path")
    price = os.getenv("FAULTLINE_TARGET_PRICE_USD")
    if price is None:
        raise RuntimeError("FAULTLINE_TARGET_PRICE_USD is required for a live target")
    return ReturnDesk(OpenRouterProvider(name, price_per_call=float(price), budget=BudgetState()))
