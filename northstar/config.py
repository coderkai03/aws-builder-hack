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

STATSIG_CONSOLE_KEY = _env("STATSIG_CONSOLE_KEY")
AMPLITUDE_API_KEY = _env("AMPLITUDE_API_KEY")
SINGLESTORE_URL = _env("SINGLESTORE_URL")
COGNEE_ENABLED = _env("COGNEE_ENABLED") in ("1", "true", "yes")

SQLITE_PATH = _env("NORTHSTAR_SQLITE_PATH", "northstar.db")

# Guardrail: kill a variant if revenue/user drops more than this vs control (relative).
GUARDRAIL_MAX_REVENUE_DROP = float(_env("NORTHSTAR_GUARDRAIL_DROP", "0.05"))
# Minimum users per arm before the agent is allowed to kill or ship anything.
MIN_USERS_PER_ARM = int(_env("NORTHSTAR_MIN_USERS", "400"))
# Significance threshold for shipping a winner.
ALPHA = float(_env("NORTHSTAR_ALPHA", "0.05"))


def llm_mode() -> str:
    return "live" if ANTHROPIC_API_KEY else "scripted"


def integration_status() -> dict:
    return {
        "llm": llm_mode(),
        "arcee": "live" if ARCEE_API_KEY else "off",
        "statsig": "live" if STATSIG_CONSOLE_KEY else "mock",
        "amplitude": "live" if AMPLITUDE_API_KEY else "mock",
        "singlestore": "live" if SINGLESTORE_URL else "sqlite",
        "cognee": "live" if COGNEE_ENABLED else "local",
    }
