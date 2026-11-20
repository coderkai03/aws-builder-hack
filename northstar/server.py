"""HTTP API + the two web pages (agent control room and the Acme demo product).

Run:  uvicorn northstar.server:app --reload --port 8000
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import agent, config, llm, product, stats
from .integrations import amplitude, statsig
from .simulator import simulator
from .store import store

STATIC = Path(__file__).resolve().parent.parent / "static"
app = FastAPI(title="North Star")


@app.on_event("startup")
def _startup():
    agent.autopilot.start()


@app.get("/")
def dashboard():
    return FileResponse(STATIC / "dashboard.html")


@app.get("/acme")
def acme():
    return FileResponse(STATIC / "acme.html")


# ---- demo product: the Acme page asks which params to render for a user ------------
@app.get("/api/acme/config")
def acme_config(user_id: str):
    exp = agent.live_experiment()
    if exp:
        variant, params = statsig.assign(exp, user_id)
        return {"experiment_id": exp["id"], "variant": variant, "params": params,
                "headline": product.HEADLINES[params["headline_style"]]}
    params = agent.state["baseline_params"]
    return {"experiment_id": "", "variant": "control", "params": params,
            "headline": product.HEADLINES[params["headline_style"]]}


# ---- simulator ---------------------------------------------------------------------
class SimStart(BaseModel):
    users_per_tick: int | None = None


@app.post("/api/simulator/start")
def sim_start(body: SimStart | None = None):
    simulator.start(body.users_per_tick if body else None)
    return {"running": True}


@app.post("/api/simulator/stop")
def sim_stop():
    simulator.stop()
    return {"running": False}


class Seed(BaseModel):
    users: int = 3000


@app.post("/api/simulator/seed")
def sim_seed(body: Seed):
    return {"generated": simulator.generate(body.users)}


# ---- agent -------------------------------------------------------------------------
@app.post("/api/agent/plan")
def agent_plan():
    try:
        return agent.plan()
    except RuntimeError as e:
        raise HTTPException(409, str(e))


class Approval(BaseModel):
    approver: str = "human"


@app.post("/api/experiments/{exp_id}/approve")
def approve(exp_id: str, body: Approval | None = None):
    try:
        return agent.approve(exp_id, body.approver if body else "human")
    except (ValueError, RuntimeError) as e:
        raise HTTPException(409, str(e))


@app.post("/api/experiments/{exp_id}/reject")
def reject(exp_id: str, body: Approval | None = None):
    return agent.reject(exp_id, body.approver if body else "human")


@app.post("/api/reset")
def reset():
    simulator.stop()
    store.reset()
    agent.state["baseline_params"] = dict(product.CONTROL)
    return {"ok": True}


# ---- state for the dashboard (polled) ---------------------------------------------
@app.get("/api/state")
def get_state():
    exps = store.list_experiments()
    current = next((e for e in exps if e["status"] in ("running", "pending_approval")), exps[0] if exps else None)
    results = agent.experiment_results(current) if current and current["status"] != "pending_approval" else None
    baseline = stats.arm_metrics(store.funnel("").get("control", {}))
    return {
        "integrations": config.integration_status(),
        "store_backend": store.backend,
        "simulator": {"running": simulator.running, "total_users": simulator.total_users},
        "amplitude": amplitude.sent,
        "llm": llm.totals,
        "baseline": baseline,
        "baseline_steps": stats.step_conversion(baseline),
        "baseline_params": agent.state["baseline_params"],
        "funnel_labels": product.FUNNEL_LABELS,
        "current": current,
        "results": results,
        "experiments": [{k: e[k] for k in ("id", "name", "status", "created_at")} for e in exps],
        "audit": store.audit_log(150),
        "decide_users_per_arm": agent.DECIDE_USERS_PER_ARM,
    }
