"""The demo product ("Acme Cloud") and the knobs the agent is allowed to turn.

Every variant is just a set of these parameters. The Acme signup page reads them at render time
(from Statsig experiment parameters), so the agent can create a new variant with zero code deploys.
"""

FUNNEL = ["landing_view", "signup_start", "signup_complete", "purchase"]

FUNNEL_LABELS = {
    "landing_view": "Landing page",
    "signup_start": "Started signup",
    "signup_complete": "Completed signup",
    "purchase": "Purchased plan",
}

PARAMS = {
    "headline_style": {"type": "enum", "values": ["feature", "outcome", "social_proof"],
                       "desc": "Landing headline angle"},
    "cta_text": {"type": "enum", "values": ["Sign up", "Start free trial", "Get started free"],
                 "desc": "Primary call-to-action button"},
    "form_fields": {"type": "enum", "values": [2, 3, 5],
                    "desc": "Number of fields on the signup form"},
    "show_testimonial": {"type": "bool", "desc": "Show a customer testimonial next to the form"},
    "pricing_display": {"type": "enum", "values": ["monthly", "annual_discount", "hidden"],
                        "desc": "How pricing is shown after signup"},
    "trial_days": {"type": "enum", "values": [7, 14, 30], "desc": "Free trial length"},
    "require_credit_card": {"type": "bool", "desc": "Require a card to start the trial"},
}

CONTROL = {
    "headline_style": "feature",
    "cta_text": "Sign up",
    "form_fields": 5,
    "show_testimonial": False,
    "pricing_display": "monthly",
    "trial_days": 14,
    "require_credit_card": False,
}

HEADLINES = {
    "feature": "Deploy containers in one click.",
    "outcome": "Ship your app today, not next sprint.",
    "social_proof": "Trusted by 12,000 engineering teams.",
}


def normalize(params: dict) -> dict:
    """Fill gaps from control and coerce values into the allowed set."""
    out = dict(CONTROL)
    for k, v in (params or {}).items():
        spec = PARAMS.get(k)
        if not spec:
            continue
        if spec["type"] == "bool":
            out[k] = bool(v) if not isinstance(v, str) else v.lower() in ("true", "1", "yes")
        elif v in spec["values"]:
            out[k] = v
        else:
            # tolerate "3" vs 3
            for allowed in spec["values"]:
                if str(allowed) == str(v):
                    out[k] = allowed
    return out


def params_doc() -> str:
    lines = []
    for k, s in PARAMS.items():
        allowed = "true | false" if s["type"] == "bool" else " | ".join(map(str, s["values"]))
        lines.append(f"- {k}: {s['desc']}. Allowed: {allowed}. Control: {CONTROL[k]}")
    return "\n".join(lines)
