"""One-call grants and receipts used by parent/child execution."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import inspect
import json
import math
import uuid
from typing import Any, Callable, Mapping

from .budget import BudgetExceeded, BudgetLedger, conservative_cost_usd


def conservative_prompt_tokens(prompt: str) -> int:
    """A deliberately conservative token estimate (one token per character)."""
    return max(1, len(prompt))


@dataclass(frozen=True, slots=True)
class OneCallGrant:
    grant_id: str
    reservation_id: str
    request_id: str
    model: str
    provider: str
    max_cost_usd: float
    max_prompt_tokens: int
    max_output_tokens: int
    prompt_price_per_million: float = 0.0
    completion_price_per_million: float = 0.0

    # Camel-case aliases make serialized receipts/grants match provider APIs.
    @property
    def requestID(self) -> str:
        return self.request_id


@dataclass(frozen=True, slots=True)
class WorkerReceipt:
    request_id: str | None
    model: str
    provider: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    reservation_id: str
    parsed_json: Any = None
    parse_error: str | None = None

    @property
    def tokens(self) -> dict[str, int | None]:
        return {"prompt": self.prompt_tokens, "completion": self.completion_tokens}

    def as_dict(self) -> dict[str, Any]:
        return {
            "requestID": self.request_id,
            "request_id": self.request_id,
            "model": self.model,
            "provider": self.provider,
            "tokens": self.tokens,
            "cost": self.cost_usd,
            "cost_usd": self.cost_usd,
            "reservation_id": self.reservation_id,
            "parsed_json": self.parsed_json,
            "parse_error": self.parse_error,
        }


class GrantLimitError(ValueError):
    pass


class OneCallWorker:
    """Issue a parent-owned grant and execute exactly one backend call."""

    def __init__(self, ledger: BudgetLedger) -> None:
        self.ledger = ledger

    def issue_grant(
        self,
        *,
        model: str,
        provider: str,
        max_cost_usd: float,
        max_prompt_tokens: int,
        max_output_tokens: int,
        request_id: str | None = None,
        case_id: str | None = None,
        prompt_price_per_million: float = 0.0,
        completion_price_per_million: float = 0.0,
        approved: bool = False,
    ) -> OneCallGrant:
        if not model or not provider:
            raise GrantLimitError("model and provider are required")
        if max_prompt_tokens <= 0 or max_output_tokens <= 0:
            raise GrantLimitError("token limits must be positive")
        if not math.isfinite(max_cost_usd) or max_cost_usd < 0:
            raise GrantLimitError("max_cost_usd must be finite and non-negative")
        if max_cost_usd > 0.50:
            raise GrantLimitError("per-call grant exceeds $0.50")
        # A zero-priced target (for example an explicit ``:free`` route) has
        # no paid exposure to bound. Some compatibility callers still pass
        # paid catalog defaults alongside a zero grant; applying that paid
        # estimate would reject an otherwise valid free dispatch. Positive
        # grants remain subject to the conservative immutable bound.
        if max_cost_usd > 0:
            estimated_cost = conservative_cost_usd(
                max_prompt_tokens,
                max_output_tokens,
                prompt_per_million=prompt_price_per_million,
                completion_per_million=completion_price_per_million,
            )
            if estimated_cost > max_cost_usd:
                raise GrantLimitError("grant cost is below its immutable token/price bound")
        request_id = request_id or uuid.uuid4().hex
        reservation = self.ledger.reserve(max_cost_usd, request_id=request_id, category="worker", case_id=case_id, approved=approved)
        if reservation.status != "pending":
            raise GrantLimitError("request already dispatched or settled; retries are disabled")
        return OneCallGrant(
            grant_id=uuid.uuid4().hex,
            reservation_id=reservation.reservation_id,
            request_id=reservation.request_id,
            model=model,
            provider=provider,
            max_cost_usd=reservation.max_cost_usd,
            max_prompt_tokens=max_prompt_tokens,
            max_output_tokens=max_output_tokens,
            prompt_price_per_million=prompt_price_per_million,
            completion_price_per_million=completion_price_per_million,
        )

    def execute(
        self,
        grant: OneCallGrant,
        prompt: str,
        call: Callable[..., Mapping[str, Any]],
        *,
        parse_json: bool = True,
    ) -> WorkerReceipt:
        estimated = conservative_prompt_tokens(prompt)
        if estimated > grant.max_prompt_tokens:
            raise GrantLimitError("prompt exceeds immutable grant token ceiling")
        response: Mapping[str, Any] | None = None
        try:
            self.ledger.claim(grant.reservation_id, grant.grant_id)
            # Select a compatible calling convention from the signature before
            # dispatch; never retry after a backend TypeError (it may have
            # already accepted and charged the request).
            try:
                signature = inspect.signature(call)
                accepts_keywords = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()) or "model" in signature.parameters
            except (TypeError, ValueError):
                accepts_keywords = True
            if accepts_keywords:
                response = call(model=grant.model, provider=grant.provider, prompt=prompt, max_tokens=grant.max_output_tokens)
            else:
                response = call(prompt, grant.model, grant.max_output_tokens)
            usage = response.get("usage") if isinstance(response, Mapping) else None
            usage = usage if isinstance(usage, Mapping) else {}
            cost = usage.get("cost")
            try:
                cost = float(cost) if cost is not None else None
            except (TypeError, ValueError):
                cost = None
            if cost is not None and (not math.isfinite(cost) or cost < 0):
                cost = None
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            receipt = WorkerReceipt(
                str(response.get("id")) if response.get("id") is not None else None,
                str(response.get("model", grant.model)),
                str(response.get("provider", grant.provider)),
                int(prompt_tokens) if isinstance(prompt_tokens, (int, float)) else None,
                int(completion_tokens) if isinstance(completion_tokens, (int, float)) else None,
                cost,
                grant.reservation_id,
            )
            self.ledger.reconcile(grant.reservation_id, cost, usage_available=cost is not None, dispatch_token=grant.grant_id)
            if cost is not None and cost > grant.max_cost_usd:
                raise BudgetExceeded("actual provider charge exceeded immutable grant")
            if not parse_json:
                return receipt
            content = response.get("content")
            if content is None:
                choices = response.get("choices")
                if isinstance(choices, list) and choices:
                    content = choices[0].get("message", {}).get("content")
            if isinstance(content, Mapping):
                parsed = dict(content)
            elif isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    return replace(receipt, parse_error="model_json_parse_failure")
            else:
                parsed = None
            return replace(receipt, parsed_json=parsed)
        except (TimeoutError, OSError):
            # No usage means the reservation remains pending across restarts.
            self.ledger.reconcile(grant.reservation_id, None, usage_available=False, dispatch_token=grant.grant_id)
            raise


def execute_one_call(grant: OneCallGrant, prompt: str, call: Callable[..., Mapping[str, Any]], ledger: BudgetLedger) -> WorkerReceipt:
    """Functional compatibility wrapper around :class:`OneCallWorker`."""
    return OneCallWorker(ledger).execute(grant, prompt, call)
