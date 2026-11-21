"""Traffic simulator. Real experiments need thousands of users and days; we have neither.

Synthetic users walk the Acme funnel. Each parameter has a HIDDEN true effect (below), so the demo
can show the agent discovering the truth. Say clearly in the demo that traffic is simulated:
assignment, event tracking and the agent loop are all real.

Built-in traps for the agent:
  * pricing_display="hidden" lifts signup completion but tanks purchases -> revenue guardrail breach
  * form_fields matters ~2.5x more on mobile -> rewards segment-aware diagnosis
"""
import random
import time
import uuid

from . import product
from .integrations import amplitude, statsig
from .store import store

# ---- hidden ground truth (the agent never reads this) -------------------------------
HEADLINE = {"feature": 0.0, "outcome": 0.03, "social_proof": 0.05}
CTA = {"Sign up": 0.0, "Start free trial": 0.04, "Get started free": 0.05}
FIELDS = {5: 0.0, 3: 0.08, 2: 0.12}
PRICING_COMPLETE = {"monthly": 0.0, "annual_discount": 0.0, "hidden": 0.06}
PRICING_PURCHASE = {"monthly": 0.0, "annual_discount": 0.04, "hidden": -0.25}
TRIAL = {7: 0.03, 14: 0.0, 30: -0.04}


def _clamp(p: float) -> float:
    return max(0.01, min(0.95, p))


def walk(params: dict, device: str, rng: random.Random) -> list[tuple[str, float]]:
    """Return the funnel events (event, value) one synthetic user produces under `params`."""
    p = product.normalize(params)
    mobile = device == "mobile"
    events = [("landing_view", 0.0)]

    p_start = 0.42 + HEADLINE[p["headline_style"]] + CTA[p["cta_text"]] + 0.03 * p["show_testimonial"]
    if rng.random() > _clamp(p_start):
        return events
    events.append(("signup_start", 0.0))

    base = 0.25 if mobile else 0.45
    p_complete = (base + FIELDS[p["form_fields"]] * (1.5 if mobile else 0.6)
                  - 0.20 * p["require_credit_card"] + PRICING_COMPLETE[p["pricing_display"]]
                  + 0.02 * p["show_testimonial"])
    if rng.random() > _clamp(p_complete):
        return events
    events.append(("signup_complete", 0.0))

    p_purchase = (0.45 + PRICING_PURCHASE[p["pricing_display"]] + 0.25 * p["require_credit_card"]
                  + TRIAL[p["trial_days"]])
    if rng.random() > _clamp(p_purchase):
        return events
    value = 199.0 if (p["pricing_display"] == "annual_discount" and rng.random() < 0.45) else 39.0
    events.append(("purchase", value))
    return events


class Simulator:
    """Request-driven: every dashboard poll calls catch_up(), which generates the users that "arrived"
    since the last tick. No background threads, so it runs the same locally and on serverless hosts."""
    users_per_second = 400
    max_users_per_tick = 2000

    def __init__(self):
        self._rng = random.Random()

    @property
    def running(self) -> bool:
        return bool(store.get("sim_running", False))

    @property
    def total_users(self) -> int:
        return int(store.get("sim_total_users", 0) or 0)

    def generate(self, n: int) -> int:
        """Send n synthetic users through whatever experiment is live right now."""
        from .agent import live_experiment, state  # avoid import cycle

        exp = live_experiment()
        baseline = state["baseline_params"]
        batch = []
        now = time.time()
        for _ in range(n):
            user_id = "u_" + uuid.uuid4().hex[:10]
            device = "mobile" if self._rng.random() < 0.55 else "desktop"
            if exp:
                variant, params = statsig.assign(exp, user_id)
                exp_id = exp["id"]
            else:
                variant, params, exp_id = "control", baseline, ""
            for event, value in walk(params, device, self._rng):
                batch.append({"ts": now, "user_id": user_id, "experiment_id": exp_id, "variant": variant,
                              "device": device, "event": event, "value": value})
        store.insert_events(batch)
        amplitude.track(batch)
        store.incr("sim_total_users", n)
        return n

    def catch_up(self) -> int:
        if not self.running:
            return 0
        now = time.time()
        last = store.get("sim_last_tick", now)
        n = min(int((now - last) * self.users_per_second), self.max_users_per_tick)
        if n < 100:
            return 0
        store.set("sim_last_tick", now)
        return self.generate(n)

    def start(self):
        store.set("sim_last_tick", time.time())
        store.set("sim_running", True)

    def stop(self):
        store.set("sim_running", False)


simulator = Simulator()
