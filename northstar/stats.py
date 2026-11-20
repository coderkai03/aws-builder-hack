"""Experiment statistics, computed from the SingleStore/SQLite event mirror.

We compute significance ourselves instead of waiting on Statsig's scheduled results, so the loop
can react in seconds. Statsig remains the system of record for assignment and kill switches.
"""
import math

from . import product


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def arm_metrics(arm: dict) -> dict:
    n = arm.get("landing_view", {}).get("users", 0)
    m = {"users": n}
    for ev in product.FUNNEL:
        m[f"{ev}_users"] = arm.get(ev, {}).get("users", 0)
    for ev in product.FUNNEL[1:]:
        m[f"{ev}_rate"] = (m[f"{ev}_users"] / n) if n else 0.0
    rev = arm.get("purchase", {})
    total, total_sq = rev.get("total", 0.0), rev.get("total_sq", 0.0)
    mean = total / n if n else 0.0
    var = max(total_sq / n - mean * mean, 0.0) if n else 0.0
    m["revenue_per_user"] = mean
    m["revenue_var"] = var
    m["revenue_total"] = total
    return m


def step_conversion(metrics: dict) -> list[dict]:
    """Step-to-step conversion, used by the agent to find the leakiest step."""
    out = []
    for a, b in zip(product.FUNNEL, product.FUNNEL[1:]):
        prev, cur = metrics[f"{a}_users"], metrics[f"{b}_users"]
        out.append({"from": a, "to": b, "rate": (cur / prev) if prev else 0.0, "users": prev})
    return out


def two_proportion(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    """Return (relative lift of arm 2 over arm 1, two-sided p-value)."""
    if not n1 or not n2:
        return 0.0, 1.0
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    lift = (p2 - p1) / p1 if p1 else 0.0
    if se == 0:
        return lift, 1.0
    z = (p2 - p1) / se
    return lift, 2 * _norm_sf(abs(z))


def mean_diff(m1: float, v1: float, n1: int, m2: float, v2: float, n2: int) -> tuple[float, float]:
    """Welch z-test on per-user revenue. Returns (relative diff, two-sided p-value)."""
    if not n1 or not n2:
        return 0.0, 1.0
    se = math.sqrt(v1 / n1 + v2 / n2)
    rel = (m2 - m1) / m1 if m1 else 0.0
    if se == 0:
        return rel, 1.0
    return rel, 2 * _norm_sf(abs((m2 - m1) / se))


def compare(funnel: dict, primary_metric: str) -> dict:
    """Compare every arm to control on the primary metric and the revenue guardrail."""
    arms = {name: arm_metrics(a) for name, a in funnel.items()}
    control = arms.get("control")
    results = {"arms": arms, "comparisons": {}}
    if not control:
        return results
    users_key = primary_metric.replace("_rate", "") + "_users"
    for name, m in arms.items():
        if name == "control":
            continue
        lift, p = two_proportion(control[users_key], control["users"], m[users_key], m["users"])
        rev_diff, rev_p = mean_diff(control["revenue_per_user"], control["revenue_var"], control["users"],
                                    m["revenue_per_user"], m["revenue_var"], m["users"])
        results["comparisons"][name] = {
            "primary_lift": lift, "primary_p": p,
            "revenue_diff": rev_diff, "revenue_p": rev_p,
            "users": m["users"], "control_users": control["users"],
        }
    return results
