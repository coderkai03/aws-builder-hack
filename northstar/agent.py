"""North Star: the autonomous growth PM loop.

OBSERVE -> DIAGNOSE -> DESIGN -> [human approval] -> LAUNCH -> MONITOR (auto-kill) -> DECIDE -> LEARN

Judgment calls (diagnosis, experiment design, decision memo) go to the smart model. Routine
monitoring notes go to the fast model. Hard safety rules (guardrail kills, significance, minimum
sample) are enforced in code, never left to the model.
"""
import json
import threading
import time
from typing import Literal

from pydantic import BaseModel, Field

from . import config, llm, product, stats
from .integrations import memory, statsig
from .store import store

_lock = threading.Lock()
state = {"baseline_params": dict(product.CONTROL), "ticks": 0}

DECIDE_USERS_PER_ARM = max(config.MIN_USERS_PER_ARM * 3, 1200)  # earliest possible decision
MAX_USERS_PER_ARM = 5000  # always decide by here
EARLY_STOP_ALPHA = 0.01   # stricter bar for stopping early (we peek every tick)


# ---------------------------------------------------------------- schemas -----------
class ParamChange(BaseModel):
    name: str = Field(description="Parameter name from the allowed list")
    value: str = Field(description="New value, written as text (e.g. '3', 'true', 'outcome')")


class Hypothesis(BaseModel):
    title: str
    rationale: str = Field(description="Why the data suggests this; cite numbers")
    changes: list[ParamChange]
    expected_lift_pct: float


class Diagnosis(BaseModel):
    leakiest_step: str
    segment_insight: str = Field(description="What differs between mobile and desktop")
    summary: str
    hypotheses: list[Hypothesis]


class VariantSpec(BaseModel):
    name: str = Field(description="Short snake_case name, not 'control'")
    description: str
    changes: list[ParamChange]


class ExperimentDesign(BaseModel):
    name: str
    hypothesis: str
    primary_metric: Literal["signup_start_rate", "signup_complete_rate", "purchase_rate"]
    variants: list[VariantSpec] = Field(description="2 or 3 treatment variants; control is added automatically")
    guardrail: str = Field(description="What would make you kill a variant early")


class MonitorNote(BaseModel):
    summary: str
    concern: bool


class DecisionMemo(BaseModel):
    headline: str
    memo: str = Field(description="Short decision memo for the team, plain text, cite the numbers")
    learnings: list[str] = Field(description="Durable lessons about our users, one sentence each")


SYSTEM = (
    "You are North Star, an autonomous growth PM for Acme Cloud, a developer SaaS product. "
    "You read funnel data, form hypotheses, and design A/B experiments using ONLY the parameters "
    "you are given. Be specific and quantitative: cite the numbers you were shown. Never invent data."
)


def _apply(changes: list[ParamChange], base: dict) -> dict:
    params = dict(base)
    params.update({c.name: c.value for c in changes if c.name in product.PARAMS})
    return product.normalize(params)


def live_experiment() -> dict | None:
    for e in store.list_experiments():
        if e["status"] == "running":
            return e
    return None


# ---------------------------------------------------------------- OBSERVE -----------
def observe() -> dict:
    overall = stats.arm_metrics(store.funnel("").get("control", {}))
    by_device = {d: stats.arm_metrics(store.funnel("", d).get("control", {})) for d in ("mobile", "desktop")}
    snapshot = {
        "overall": overall,
        "steps": stats.step_conversion(overall),
        "steps_by_device": {d: stats.step_conversion(m) for d, m in by_device.items()},
        "baseline_params": state["baseline_params"],
    }
    worst = min(snapshot["steps"], key=lambda s: s["rate"]) if overall["users"] else None
    store.audit("observe", f"Read baseline funnel: {overall['users']} users"
                + (f", weakest step {worst['from']} -> {worst['to']} at {worst['rate']:.0%}" if worst else ""),
                snapshot, actor="agent")
    return snapshot


# ---------------------------------------------------------------- DIAGNOSE ----------
def _scripted_diagnosis(snapshot: dict) -> Diagnosis:
    steps = snapshot["steps"]
    worst = min(steps, key=lambda s: s["rate"]) if steps else {"from": "signup_start", "to": "signup_complete", "rate": 0}
    mob = {s["to"]: s["rate"] for s in snapshot["steps_by_device"]["mobile"]}
    desk = {s["to"]: s["rate"] for s in snapshot["steps_by_device"]["desktop"]}
    return Diagnosis(
        leakiest_step=f"{worst['from']} -> {worst['to']}",
        segment_insight=(f"Signup completion is {mob.get('signup_complete', 0):.0%} on mobile vs "
                         f"{desk.get('signup_complete', 0):.0%} on desktop: the 5-field form hurts mobile most."),
        summary="Users start signup but abandon the form, especially on mobile.",
        hypotheses=[
            Hypothesis(title="Shorter form + social proof", rationale="Fewer fields reduce mobile friction.",
                       changes=[ParamChange(name="form_fields", value="3"),
                                ParamChange(name="show_testimonial", value="true")], expected_lift_pct=12),
            Hypothesis(title="Minimal 2-field form", rationale="Email + password only.",
                       changes=[ParamChange(name="form_fields", value="2")], expected_lift_pct=15),
            Hypothesis(title="Hide pricing until after signup", rationale="Remove sticker shock at signup.",
                       changes=[ParamChange(name="pricing_display", value="hidden")], expected_lift_pct=8),
        ],
    )


def diagnose(snapshot: dict) -> Diagnosis:
    past = memory.recall("What have past Acme experiments taught us?")
    prompt = (
        f"Baseline funnel data (JSON):\n{json.dumps(snapshot, default=str)}\n\n"
        f"Parameters you may change:\n{product.params_doc()}\n\n"
        f"Lessons from past experiments (do not repeat a losing idea):\n"
        + ("\n".join(f"- {m}" for m in past) if past else "- none yet")
        + "\n\nFind the leakiest funnel step, explain the mobile vs desktop difference, "
          "and propose 3 hypotheses expressed as parameter changes."
    )
    d = llm.structured("diagnose", "smart", SYSTEM, prompt, Diagnosis, lambda: _scripted_diagnosis(snapshot))
    store.audit("diagnose", d.summary, {"diagnosis": d.model_dump(), "memories_used": past})
    return d


# ---------------------------------------------------------------- DESIGN ------------
def _scripted_design(d: Diagnosis) -> ExperimentDesign:
    return ExperimentDesign(
        name="Signup form friction",
        hypothesis="Reducing signup friction lifts completed signups without hurting revenue.",
        primary_metric="signup_complete_rate",
        variants=[VariantSpec(name=h.title.lower().replace(" ", "_").replace("+", "and")[:40],
                              description=h.rationale, changes=h.changes) for h in d.hypotheses[:3]],
        guardrail=f"Kill any variant whose revenue per user drops more than "
                  f"{config.GUARDRAIL_MAX_REVENUE_DROP:.0%} vs control.",
    )


def design(d: Diagnosis) -> dict:
    prompt = (
        f"Diagnosis (JSON):\n{d.model_dump_json()}\n\nParameters:\n{product.params_doc()}\n\n"
        f"Current control params: {json.dumps(state['baseline_params'])}\n\n"
        "Design ONE experiment with 2-3 treatment variants testing the strongest hypotheses. "
        f"Revenue per user is a guardrail: variants dropping it more than "
        f"{config.GUARDRAIL_MAX_REVENUE_DROP:.0%} are killed automatically."
    )
    spec = llm.structured("design", "smart", SYSTEM, prompt, ExperimentDesign, lambda: _scripted_design(d))
    variants = [{"name": "control", "description": "Current experience", "params": dict(state["baseline_params"])}]
    seen = {"control"}
    for v in spec.variants[:3]:
        name = v.name if v.name not in seen else f"{v.name}_{len(seen)}"
        seen.add(name)
        variants.append({"name": name, "description": v.description,
                         "params": _apply(v.changes, state["baseline_params"])})
    if config.DEMO_TRAP and not any(v["params"]["pricing_display"] == "hidden" for v in variants):
        # Demo: a stakeholder asks to test hiding pricing. It lifts signups but hurts revenue, so the
        # guardrail should catch it. Labeled honestly in the spec and the audit trail.
        variants.append({"name": "hide_pricing_stakeholder_request",
                         "description": "Requested by the sales team: hide pricing until after signup.",
                         "params": product.normalize({**state["baseline_params"], "pricing_display": "hidden"}),
                         "added_by": "stakeholder request"})
        store.audit("design", "Added stakeholder-requested variant 'hide_pricing_stakeholder_request' "
                    "(guardrail will protect revenue)", {"variant": variants[-1]}, actor="stakeholder")
    full = {"hypothesis": spec.hypothesis, "primary_metric": spec.primary_metric,
            "guardrail": spec.guardrail, "variants": variants, "diagnosis": d.model_dump()}
    exp_id = store.create_experiment(spec.name, full)
    store.audit("design", f"Designed '{spec.name}' with {len(variants) - 1} variants, awaiting human approval",
                {"experiment_id": exp_id, "spec": full})
    return store.get_experiment(exp_id)


def plan() -> dict:
    """OBSERVE -> DIAGNOSE -> DESIGN. Ends with an experiment waiting for approval."""
    with _lock:
        if live_experiment():
            raise RuntimeError("An experiment is already running")
        return design(diagnose(observe()))


# ---------------------------------------------------------------- LAUNCH ------------
def approve(exp_id: str, approver: str = "human") -> dict:
    exp = store.get_experiment(exp_id)
    if not exp or exp["status"] != "pending_approval":
        raise ValueError("Experiment is not awaiting approval")
    if live_experiment():
        raise RuntimeError("Another experiment is running")
    store.audit("approve", f"{approver} approved launch of '{exp['name']}'", {"experiment_id": exp_id},
                actor=approver)
    res = statsig.create_and_start(exp)
    store.update_experiment(exp_id, status="running", statsig_ref=res["statsig_id"])
    store.audit("launch", f"Launched in Statsig as {res['statsig_id']}", res)
    return store.get_experiment(exp_id)


def reject(exp_id: str, approver: str = "human") -> dict:
    store.update_experiment(exp_id, status="rejected")
    store.audit("approve", f"{approver} rejected the experiment", {"experiment_id": exp_id}, actor=approver)
    return store.get_experiment(exp_id)


# ---------------------------------------------------------------- MONITOR -----------
def experiment_results(exp: dict) -> dict:
    return stats.compare(store.funnel(exp["id"]), exp["spec"]["primary_metric"])


def monitor_tick() -> dict | None:
    with _lock:
        exp = live_experiment()
        if not exp:
            return None
        state["ticks"] += 1
        res = experiment_results(exp)
        for name, c in res["comparisons"].items():
            if name in exp["killed"]:
                continue
            breached = (c["users"] >= config.MIN_USERS_PER_ARM
                        and c["revenue_diff"] < -config.GUARDRAIL_MAX_REVENUE_DROP and c["revenue_p"] < 0.10)
            if breached:
                exp["killed"].append(name)
                store.update_experiment(exp["id"], killed=exp["killed"])
                vendor = statsig.kill_variant(exp, name)
                store.audit("guardrail_kill",
                            f"AUTO-KILLED '{name}': revenue/user {c['revenue_diff']:+.1%} vs control "
                            f"(p={c['revenue_p']:.3f}, n={c['users']})",
                            {"variant": name, "comparison": c, "statsig": vendor})

        if state["ticks"] % 10 == 0:
            _monitor_note(exp, res)

        live = [n for n in res["comparisons"] if n not in exp["killed"]]
        min_users = min((res["comparisons"][n]["users"] for n in live), default=0)
        clear_winner = any(res["comparisons"][n]["primary_p"] < EARLY_STOP_ALPHA
                           and res["comparisons"][n]["primary_lift"] > 0 for n in live)
        ready = live and min_users >= DECIDE_USERS_PER_ARM and (clear_winner or min_users >= MAX_USERS_PER_ARM)
        if ready or (not live and res["comparisons"]):
            return _decide(exp, res)
        return res


def _monitor_note(exp: dict, res: dict):
    brief = {n: {k: round(v, 4) if isinstance(v, float) else v for k, v in c.items()}
             for n, c in res["comparisons"].items()}
    prompt = (f"Experiment '{exp['name']}', primary metric {exp['spec']['primary_metric']}. "
              f"Killed so far: {exp['killed']}. Interim comparisons vs control: {json.dumps(brief)}. "
              "Write a one-sentence status update. Flag a concern only if something looks wrong.")
    note = llm.structured("monitor", "fast", SYSTEM, prompt, MonitorNote,
                          lambda: MonitorNote(summary=f"Interim check: {len(brief)} arms collecting data.",
                                              concern=False))
    store.audit("monitor", note.summary, {"comparisons": brief, "concern": note.concern})


# ---------------------------------------------------------------- DECIDE + LEARN -----
def _decide(exp: dict, res: dict) -> dict:
    winners = []
    for name, c in res["comparisons"].items():
        if name in exp["killed"]:
            continue
        if (c["primary_p"] < config.ALPHA and c["primary_lift"] > 0
                and c["revenue_diff"] > -config.GUARDRAIL_MAX_REVENUE_DROP):
            winners.append((c["revenue_diff"], c["primary_lift"], name))
    winner = max(winners)[2] if winners else None
    decision = "ship" if winner else "no_winner"

    def fallback() -> DecisionMemo:
        if winner:
            c = res["comparisons"][winner]
            return DecisionMemo(
                headline=f"Ship {winner}: {c['primary_lift']:+.1%} on {exp['spec']['primary_metric']}",
                memo=(f"{winner} beat control by {c['primary_lift']:+.1%} (p={c['primary_p']:.4f}) with "
                      f"revenue/user {c['revenue_diff']:+.1%}. Killed during the test: {exp['killed'] or 'none'}."),
                learnings=[f"{winner} lifted {exp['spec']['primary_metric']} by {c['primary_lift']:+.1%}."]
                + [f"Variant {k} hurt revenue and was killed." for k in exp["killed"]])
        return DecisionMemo(headline="No winner: keep control", memo="No variant was significant.",
                            learnings=[f"Experiment '{exp['name']}' showed no significant effect."])

    variants = {v["name"]: v for v in exp["spec"]["variants"]}
    prompt = (
        f"Experiment '{exp['name']}'. Hypothesis: {exp['spec']['hypothesis']}\n"
        f"Variants: {json.dumps(variants)}\nFinal comparisons vs control: {json.dumps(res['comparisons'])}\n"
        f"Variants killed by guardrail: {exp['killed']}\n"
        f"Decision already made by the statistics engine: {decision}"
        + (f" (winner: {winner})" if winner else "")
        + "\nWrite the decision memo and the durable learnings about our users."
    )
    memo = llm.structured("decide", "smart", SYSTEM, prompt, DecisionMemo, fallback)

    result = {"decision": decision, "winner": winner, "headline": memo.headline, "memo": memo.memo,
              "learnings": memo.learnings, "comparisons": res["comparisons"]}
    if winner:
        vendor = statsig.ship(exp, winner)
        state["baseline_params"] = dict(variants[winner]["params"])
        result["statsig"] = vendor
    store.update_experiment(exp["id"], status="shipped" if winner else "no_winner", result=result)
    store.audit("decide", memo.headline, result)
    for lesson in memo.learnings:
        memory.remember(lesson)
    store.audit("learn", f"Stored {len(memo.learnings)} learnings in memory", {"learnings": memo.learnings})
    return result


# ---------------------------------------------------------------- autopilot ---------
class Autopilot:
    def __init__(self):
        self.running = False

    def _loop(self):
        while self.running:
            try:
                monitor_tick()
            except Exception as e:
                print("monitor error:", e)
            time.sleep(2)

    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._loop, daemon=True).start()


autopilot = Autopilot()
