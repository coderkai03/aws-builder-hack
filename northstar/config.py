"""Central config. Every sponsor integration falls back to a local mock when its key is unset,
so the whole loop runs on a laptop with zero credentials."""
import os

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
SMART_MODEL = _env("NORTHSTAR_SMART_MODEL", "claude-opus-5-5")
FAST_MODEL = _env("NORTHSTAR_FAST_MODEL", "claude-haiku-5-5")
ARCEE_API_KEY = _env("ARCEE_API_KEY")

# Superlinked SIE Serverless (OpenAI-style chat). Highest priority provider when set.
SUPERLINKED_API_KEY = _env("SUPERLINKED_API_KEY")
SUPERLINKED_SMART_MODEL = _env("SUPERLINKED_SMART_MODEL", "Qwen/Qwen3.8-27B-FP8")
SUPERLINKED_FAST_MODEL = _env("SUPERLINKED_FAST_MODEL", "Qwen/Qwen3.8-27B-FP8")

# OpenRouter: if set, ALL model calls go through OpenRouter (any provider's models).
# Model slugs: https://openrouter.ai/models  (Arcee models are not on OpenRouter as of Nov 2026)
OPENROUTER_API_KEY = _env("OPENROUTER_API_KEY")
OPENROUTER_SMART_MODEL = _env("OPENROUTER_SMART_MODEL", "anthropic/claude-opus-5.5")
OPENROUTER_FAST_MODEL = _env("OPENROUTER_FAST_MODEL", "anthropic/claude-haiku-5.5")

STATSIG_CONSOLE_KEY = _env("STATSIG_CONSOLE_KEY")
AMPLITUDE_API_KEY = _env("AMPLITUDE_API_KEY")
SINGLESTORE_URL = _env("SINGLESTORE_URL")
COGNEE_ENABLED = _env("COGNEE_ENABLED") in ("1", "true", "yes")

# Demo: add a stakeholder-requested "hide pricing" variant to every design so the revenue guardrail
# visibly fires on stage. Set NORTHSTAR_DEMO_TRAP=1.
DEMO_TRAP = _env("NORTHSTAR_DEMO_TRAP") in ("1", "true", "yes")

SQLITE_PATH = _env("NORTHSTAR_SQLITE_PATH", "northstar.db")

# Guardrail: kill a variant if revenue/user drops more than this vs control (relative).
GUARDRAIL_MAX_REVENUE_DROP = float(_env("NORTHSTAR_GUARDRAIL_DROP", "0.05"))
# Minimum users per arm before the agent is allowed to kill or ship anything.
MIN_USERS_PER_ARM = int(_env("NORTHSTAR_MIN_USERS", "400"))
# Significance threshold for shipping a winner.
ALPHA = float(_env("NORTHSTAR_ALPHA", "0.05"))


def llm_mode() -> str:
    if SUPERLINKED_API_KEY:
        return "superlinked"
    if OPENROUTER_API_KEY:
        return "openrouter"
    return "anthropic" if ANTHROPIC_API_KEY else "scripted"


def integration_status() -> dict:
    return {
        "llm": llm_mode(),
        "arcee": "live" if ARCEE_API_KEY else "off",
        "statsig": "live" if STATSIG_CONSOLE_KEY else "mock",
        "amplitude": "live" if AMPLITUDE_API_KEY else "mock",
        "singlestore": "live" if SINGLESTORE_URL else "sqlite",
        "cognee": "live" if COGNEE_ENABLED else "local",
    }
