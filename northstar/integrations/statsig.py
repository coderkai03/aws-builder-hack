"""Statsig: the agent's "hands". Experiments are created, started, killed and shipped here.

Assignment: we bucket users deterministically (hash of user_id + experiment id) so the simulator is
fast. With a real Statsig server SDK you would replace `assign()` with `get_experiment()`; the
launch / kill / ship calls below already go through the Statsig Console API when a key is set.

Endpoints verified against Statsig's OpenAPI spec (version 20240601) and a live project:
create (POST /experiments), start (PUT /{id}/start), kill one group (POST /{id}/disable_groups),
ship (PUT /{id}/make_decision with the winning group's ID), abandon (PUT /{id}/abandon).
Every call is best-effort: failures are logged to the audit trail and the demo keeps running.
"""
import hashlib

import httpx

from .. import config, product

BASE = "https://statsigapi.net/console/v1"


def _headers():
    return {"STATSIG-API-KEY": config.STATSIG_CONSOLE_KEY, "STATSIG-API-VERSION": "20240601",
            "Content-Type": "application/json"}


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
    statsig_id = ((created.get("body") or {}).get("data") or {}).get("id") or body["name"]
    started = _call("PUT", f"/experiments/{statsig_id}/start")
    return {"statsig_id": statsig_id, "create": created, "start": started}


def _ref(exp: dict) -> str:
    return exp.get("statsig_ref") or exp["id"]


def kill_variant(exp: dict, variant: str) -> dict:
    """Stop assigning users to one group; its users fall back to control."""
    return _call("POST", f"/experiments/{_ref(exp)}/disable_groups", {"group_names": [variant]})


def ship(exp: dict, variant: str) -> dict:
    """Make the decision: launch the winning group (Statsig needs the group's ID, not its name)."""
    if not config.STATSIG_CONSOLE_KEY:
        return _call("PUT", f"/experiments/{_ref(exp)}/make_decision")
    got = _call("GET", f"/experiments/{_ref(exp)}")
    groups = ((got.get("body") or {}).get("data") or {}).get("groups") or []
    group_id = next((g["id"] for g in groups if g.get("name") == variant), None)
    if not group_id:
        return {"error": f"group {variant} not found in Statsig", "lookup": got}
    return _call("PUT", f"/experiments/{_ref(exp)}/make_decision",
                 {"id": group_id, "decisionReason": f"North Star: {variant} won with healthy guardrails"})


def abandon(exp: dict, reason: str) -> dict:
    return _call("PUT", f"/experiments/{_ref(exp)}/abandon", {"decisionReason": reason})


def assign(exp: dict, user_id: str) -> tuple[str, dict]:
    variants = exp["spec"]["variants"]
    h = int(hashlib.sha256(f"{exp['id']}:{user_id}".encode()).hexdigest(), 16)
    v = variants[h % len(variants)]
    if v["name"] in exp.get("killed", []):
        control = next((x for x in variants if x["name"] == "control"), None)
        return "control", product.normalize(control["params"] if control else product.CONTROL)
    return v["name"], product.normalize(v["params"])
