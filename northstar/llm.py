"""Model router: "smart" tier for judgment calls, "fast" tier for routine work.

Every call is written to the audit trail with model, tokens and cost, so the demo can show how much
the routing saves (the Arcee "Pareto frontier" angle).

With no ANTHROPIC_API_KEY the router runs in "scripted" mode: each call site passes a deterministic
fallback, so the whole loop can be developed and demoed offline.
"""
from typing import Callable, TypeVar

import anthropic
from pydantic import BaseModel

from . import config
from .store import store

T = TypeVar("T", bound=BaseModel)

# $ per million tokens (input, output)
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}

_client: anthropic.Anthropic | None = None
totals = {"calls": 0, "cost_usd": 0.0, "smart_calls": 0, "fast_calls": 0,
          "cost_if_all_smart_usd": 0.0}


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _cost(model: str, usage) -> tuple[float, int]:
    pin, pout = PRICES.get(model, (4.0, 20.0))
    tin, tout = usage.input_tokens, usage.output_tokens
    return (tin * pin + tout * pout) / 1e6, tin + tout


def _arcee(system: str, prompt: str, schema: type[T]) -> T:
    # TODO(teammate B): route the fast tier to Arcee here (https://docs.arcee.ai/).
    raise NotImplementedError


def structured(step: str, tier: str, system: str, prompt: str, schema: type[T],
               fallback: Callable[[], T]) -> T:
    """Ask the tier's model for a `schema` object. Logs the call to the audit trail."""
    model = config.SMART_MODEL if tier == "smart" else config.FAST_MODEL
    totals["calls"] += 1
    totals[f"{tier}_calls"] += 1

    if config.llm_mode() == "scripted":
        result = fallback()
        store.audit(step, f"[{tier}] scripted response", {"output": result.model_dump()},
                    model="scripted")
        return result

    if tier == "fast" and config.ARCEE_API_KEY:
        try:
            return _arcee(system, prompt, schema)
        except NotImplementedError:
            pass

    effort = "high" if tier == "smart" else "low"
    kwargs = dict(model=model, max_tokens=16000, system=system, output_config={"effort": effort},
                  messages=[{"role": "user", "content": prompt}], output_format=schema)
    try:
        if model in ("claude-opus-5-5", "claude-sonnet-5-5"):
            # Server-side refusal fallback: if the model declines, the API re-runs on a fallback model.
            resp = client().beta.messages.parse(betas=["server-side-fallback-2026-07-01"],
                                                fallbacks="default", **kwargs)
        else:
            resp = client().messages.parse(**kwargs)
    except anthropic.APIError as e:
        store.audit(step, f"[{tier}] model call failed, using fallback: {e}", model=model, actor="system")
        return fallback()

    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        store.audit(step, f"[{tier}] no parsed output ({resp.stop_reason}), using fallback", model=model,
                    actor="system")
        return fallback()

    cost, tokens = _cost(model, resp.usage)
    smart_cost, _ = _cost(config.SMART_MODEL, resp.usage)
    totals["cost_usd"] += cost
    totals["cost_if_all_smart_usd"] += smart_cost
    store.audit(step, f"[{tier}] {model}", {"output": resp.parsed_output.model_dump()},
                model=model, cost_usd=cost, tokens=tokens)
    return resp.parsed_output
