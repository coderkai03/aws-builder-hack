"""Traffic simulator. Real experiments need thousands of users and days; we have neither.

Synthetic users walk the Acme funnel. Each parameter has a HIDDEN true effect (below), so the demo
can show the agent discovering the truth. Say clearly in the demo that traffic is simulated:
assignment, event tracking and the agent loop are all real.

Built-in traps for the agent:
  * pricing_display="hidden" lifts signup completion but tanks purchases -> revenue guardrail breach
  * form_fields matters ~2.5x more on mobile -> rewards segment-aware diagnosis
"""
import random
import threading
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
    def __init__(self):
        self.running = False
        self.users_per_tick = 400
        self.tick_seconds = 1.0
        self.total_users = 0
        self._thread: threading.Thread | None = None
        self._rng = random.Random(42)

    def generate(self, n: int) -> int:
        """Send n synthetic users through whatever experiment is live right now."""
        from .agent import live_experiment, state  # avoid import cycle

        exp = live_experiment()
        batch = []
        now = time.time()
        for _ in range(n):
            user_id = "u_" + uuid.uuid4().hex[:10]
            device = "mobile" if self._rng.random() < 0.55 else "desktop"
            if exp:
                variant, params = statsig.assign(exp, user_id)
                exp_id = exp["id"]
            else:
                variant, params, exp_id = "control", state["baseline_params"], ""
            for event, value in walk(params, device, self._rng):
                batch.append({"ts": now, "user_id": user_id, "experiment_id": exp_id, "variant": variant,
                              "device": device, "event": event, "value": value})
        store.insert_events(batch)
        amplitude.track(batch)
        self.total_users += n
        return n

    def _loop(self):
        while self.running:
            try:
                self.generate(self.users_per_tick)
            except Exception as e:  # keep the demo alive
                print("simulator error:", e)
            time.sleep(self.tick_seconds)

    def start(self, users_per_tick: int | None = None):
        if users_per_tick:
            self.users_per_tick = users_per_tick
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False


simulator = Simulator()
