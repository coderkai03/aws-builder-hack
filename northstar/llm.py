"""Model router: "smart" tier for judgment calls, "fast" tier for routine work.

Providers, first key found wins: Superlinked SIE Serverless (SUPERLINKED_API_KEY), OpenRouter
(OPENROUTER_API_KEY), Anthropic direct (ANTHROPIC_API_KEY), else offline "scripted" mode.

Every call is written to the audit trail with model, tokens and cost, so the demo can show how much
the routing saves (the Arcee "Pareto frontier" angle).

In "scripted" mode each call site passes a deterministic fallback, so the whole loop can be developed
and demoed offline. The same fallback is used if a live model fails twice.
"""
import json
import time
from typing import Callable, TypeVar

import anthropic
import httpx
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
          "cost_if_all_smart_usd": 0.0, "smart_tokens": 0, "smart_cost": 0.0}


def persisted_totals() -> dict:
    """Model-call totals read back from the audit trail (survives serverless restarts)."""
    rows = store.query("SELECT summary, cost_usd FROM audit WHERE actor = ? AND (summary LIKE ? OR summary LIKE ?)",
                       ("agent", "[smart]%", "[fast]%"))
    smart = sum(1 for r in rows if r["summary"].startswith("[smart]"))
    cost = sum(float(r["cost_usd"] or 0) for r in rows)
    return {"calls": len(rows), "smart_calls": smart, "fast_calls": len(rows) - smart, "cost_usd": cost,
            "cost_if_all_smart_usd": cost}


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


# OpenAI-compatible chat-completions providers. Cost comes from what each provider reports.
PROVIDERS = {
    "superlinked": {"url": "https://api.superlinked.com/v1/chat/completions", "label": "Superlinked SIE",
                    "key": lambda: config.SUPERLINKED_API_KEY,
                    "models": lambda: (config.SUPERLINKED_SMART_MODEL, config.SUPERLINKED_FAST_MODEL),
                    "max_tokens_field": "max_completion_tokens", "extra": {},
                    # SIE bills in credits; their credit pack is $50 for 5,000,000 credits.
                    "cost": lambda u: float(u.get("credits_charged_decimal") or u.get("credits_charged") or 0) / 100_000},
    "openrouter": {"url": "https://openrouter.ai/api/v1/chat/completions", "label": "OpenRouter",
                   "key": lambda: config.OPENROUTER_API_KEY,
                   "models": lambda: (config.OPENROUTER_SMART_MODEL, config.OPENROUTER_FAST_MODEL),
                   "max_tokens_field": "max_tokens", "extra": {"usage": {"include": True}},
                   "cost": lambda u: float(u.get("cost") or 0.0)},
}


def _strict_schema(schema: type[BaseModel]) -> dict:
    """Pydantic JSON schema -> strict structured-output schema (every object closed, every field required)."""
    def fix(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for v in node.values():
                fix(v)
        elif isinstance(node, list):
            for v in node:
                fix(v)
        return node
    return fix(schema.model_json_schema())


def _clean_json(text: str) -> str:
    text = (text or "").strip()
    if "</think>" in text:  # reasoning models may prepend a think block
        text = text.split("</think>", 1)[1].strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if not text.startswith("{") and "{" in text:
        text = text[text.index("{"): text.rindex("}") + 1]
    return text


def _post_with_cold_start_retry(url: str, body: dict, key: str) -> httpx.Response:
    """Serverless models scale to zero: a 503 'provisioning' means wait Retry-After and try again."""
    for _ in range(6):
        r = httpx.post(url, json=body, timeout=180, headers={"Authorization": f"Bearer {key}"})
        if r.status_code not in (429, 503):
            return r
        time.sleep(min(float(r.headers.get("retry-after") or 10), 30))
    return r


def _chat_completions(provider: str, step: str, tier: str, system: str, prompt: str, schema: type[T],
                      fallback: Callable[[], T]) -> T:
    """Ask an OpenAI-compatible provider for JSON matching the Pydantic schema, validate it, and retry
    once with the validation error before falling back to the scripted response."""
    p = PROVIDERS[provider]
    smart, fast = p["models"]()
    model = smart if tier == "smart" else fast
    json_schema = _strict_schema(schema)
    messages = [
        {"role": "system", "content": system + "\n\nRespond with a JSON object matching this schema:\n"
                                               + json.dumps(json_schema)},
        {"role": "user", "content": prompt},
    ]
    last_err = ""
    for attempt in range(2):
        body = {"model": model, "messages": messages, p["max_tokens_field"]: 4000,
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": schema.__name__, "strict": True, "schema": json_schema}}, **p["extra"]}
        try:
            r = _post_with_cold_start_retry(p["url"], body, p["key"]())
            r.raise_for_status()
            data = r.json()
            result = schema.model_validate_json(_clean_json(data["choices"][0]["message"]["content"]))
        except Exception as e:  # HTTP error, empty choice, or JSON that fails validation
            last_err = str(e)[:500]
            messages.append({"role": "user", "content": f"That failed: {last_err}. Return only valid JSON "
                                                        "with exactly the schema's field names."})
            continue
        usage = data.get("usage") or {}
        cost = p["cost"](usage)
        tokens = int(usage.get("total_tokens") or 0)
        totals["cost_usd"] += cost
        if tier == "smart":
            totals["smart_tokens"] += tokens
            totals["smart_cost"] += cost
            totals["cost_if_all_smart_usd"] += cost
        else:
            per_tok = totals["smart_cost"] / totals["smart_tokens"] if totals["smart_tokens"] else 0.0
            totals["cost_if_all_smart_usd"] += max(tokens * per_tok, cost)
        store.audit(step, f"[{tier}] {model} via {p['label']}", {"output": result.model_dump()},
                    model=model, cost_usd=cost, tokens=tokens)
        return result
    store.audit(step, f"[{tier}] {model} failed twice ({last_err}), using fallback", model=model, actor="system")
    return fallback()


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

    if config.llm_mode() in PROVIDERS:
        return _chat_completions(config.llm_mode(), step, tier, system, prompt, schema, fallback)

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
