"""Statsig: the agent's "hands". Experiments are created, started, killed and shipped here.

Assignment: we bucket users deterministically (hash of user_id + experiment id) so the simulator is
fast. With a real Statsig server SDK you would replace `assign()` with `get_experiment()`; the
launch / kill / ship calls below already go through the Statsig Console API when a key is set.

TODO(teammate C): verify endpoint paths + payloads against https://docs.statsig.com/console-api
in the first 30 minutes. Every call is best-effort: failures are logged to the audit trail and the
local mock keeps the demo running.
"""
import hashlib

import httpx

from .. import config, product

BASE = "https://statsigapi.net/console/v1"


def _headers():
    return {"STATSIG-API-KEY": config.STATSIG_CONSOLE_KEY, "Content-Type": "application/json"}


def _call(method: str, path: str, json: dict | None = None) -> dict:
    if not config.STATSIG_CONSOLE_KEY:
        return {"mock": True, "method": method, "path": path}
    try:
        r = httpx.request(method, BASE + path, headers=_headers(), json=json, timeout=15)
        return {"status": r.status_code, "body": r.json() if r.content else {}}
    except Exception as e:  # never break the loop on a vendor hiccup
        return {"error": str(e)}


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower())[:60].strip("_")


def create_and_start(exp: dict) -> dict:
    spec = exp["spec"]
    variants = spec["variants"]
    size = round(100 / len(variants), 2)
    body = {
        "name": f"northstar_{_slug(exp['name'])}_{exp['id'][-4:]}",
        "description": spec.get("hypothesis", ""),
        "idType": "userID",
        "hypothesis": spec.get("hypothesis", ""),
        "groups": [{"name": v["name"], "size": size, "parameterValues": product.normalize(v["params"])}
                   for v in variants],
    }
    created = _call("POST", "/experiments", body)
    statsig_id = body["name"]
    started = _call("PUT", f"/experiments/{statsig_id}/start")
    return {"statsig_id": statsig_id, "create": created, "start": started}


def kill_variant(exp: dict, variant: str) -> dict:
    # Remove the group's allocation; its users fall back to control params.
    return _call("PATCH", f"/experiments/{exp.get('statsig_ref') or exp['id']}",
                 {"note": f"North Star auto-kill: {variant} breached guardrail"})


def ship(exp: dict, variant: str) -> dict:
    return _call("PUT", f"/experiments/{exp.get('statsig_ref') or exp['id']}/make_decision",
                 {"id": variant, "reason": "North Star: significant win, guardrails healthy"})


def assign(exp: dict, user_id: str) -> tuple[str, dict]:
    variants = exp["spec"]["variants"]
    h = int(hashlib.sha256(f"{exp['id']}:{user_id}".encode()).hexdigest(), 16)
    v = variants[h % len(variants)]
    if v["name"] in exp.get("killed", []):
        control = next((x for x in variants if x["name"] == "control"), None)
        return "control", product.normalize(control["params"] if control else product.CONTROL)
    return v["name"], product.normalize(v["params"])
