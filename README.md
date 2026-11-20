# ★ North Star: an autonomous growth PM

North Star watches your product data, finds where users drop off, designs A/B experiments,
launches them in Statsig, **automatically kills variants that hurt revenue**, ships the winners and
writes up every decision in an audit trail.

```
OBSERVE → DIAGNOSE → DESIGN → [human approves] → LAUNCH → MONITOR (auto-kill) → DECIDE → LEARN
Amplitude   smart LLM   smart LLM                  Statsig    stats + fast LLM    smart LLM  Cognee
          (+ memory)                                         SingleStore mirror
```

## Quick start (runs offline, no keys needed)

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env   # fill in whatever keys you have; empty = local mock
```

```bash
uvicorn northstar.server:app --reload --port 8000
```

Open http://localhost:8000 (the agent control room) and http://localhost:8000/acme (the demo product).

**Models:** set `OPENROUTER_API_KEY` to send every model call through OpenRouter (pick models with
`OPENROUTER_SMART_MODEL` / `OPENROUTER_FAST_MODEL`; an `arcee-ai/*` model on the fast tier helps the
Arcee entry), or set `ANTHROPIC_API_KEY` to call Anthropic directly.
With neither key the agent runs in **scripted** mode (deterministic responses), so the
UI and loop can be built and demoed before keys arrive. The integration pills in the header show
what's live and what's mocked.

## Demo script (about 3 minutes)

1. **Reset**, then **Seed baseline (3k users)**. The funnel shows the weak step: *Started signup → Completed signup*.
2. **Run agent.** The audit trail fills: observe → diagnose (mobile vs. desktop insight, past learnings from memory) → design.
3. The experiment card shows 3 variants as parameter changes. Click **Approve launch** (human in the loop).
   Show the experiment in the Statsig console.
4. **Start traffic.** Variants separate on the live chart. Open `/acme` in a second tab: the page changes per variant with no deploy.
5. **The moment:** `hide_pricing_until_after_signup` gets more signups but tanks revenue, so the agent **auto-kills it** (red event in the audit trail).
6. The agent reaches significance, **ships the winner** and writes the decision memo. Learnings go into memory.
7. Click any audit event to expand the exact data and model output behind it. Point at the
   *agent economics* panel (smart vs. fast model calls, $ saved by routing).

> Say it out loud: the traffic is simulated (real experiments take weeks). Assignment, tracking,
> the stats and the agent's decisions are real.

## How the code is laid out

| File | What it does |
|---|---|
| `northstar/agent.py` | The loop. LLM does judgment (diagnose, design, memo); **code enforces safety** (guardrail kills, significance, min sample). |
| `northstar/llm.py` | Model router: smart tier vs. fast tier, via OpenRouter or Anthropic. Logs cost per call. Output validated against Pydantic schemas (one retry, then a safe fallback). |
| `northstar/stats.py` | Two-proportion z-test (primary metric), Welch test (revenue guardrail). |
| `northstar/simulator.py` | Synthetic users with **hidden ground truth** per parameter (incl. the hidden-pricing trap). |
| `northstar/product.py` | The parameters the agent may change. Variants are parameter sets, not code. |
| `northstar/store.py` | SingleStore (or SQLite): event mirror, experiment registry, audit log, memory. |
| `northstar/integrations/` | `statsig.py`, `amplitude.py`, `memory.py` (Cognee). All fall back to mocks. |
| `northstar/server.py` | FastAPI: dashboard, Acme page, agent + simulator endpoints. |
| `static/` | `dashboard.html` (control room) and `acme.html` (demo product). |

## Sponsor checklist

| Sponsor | Status | Next step |
|---|---|---|
| **Amplitude** | Events sent via HTTP V2 when `AMPLITUDE_API_KEY` is set | Build the funnel chart in Amplitude for the demo; optionally read the diagnosis from the Dashboard REST API (`integrations/amplitude.py` TODO) |
| **Statsig** | Console API create/start/kill/ship (best-effort) | **Verify endpoint paths and payloads** in `integrations/statsig.py` against the Console API docs. Optionally swap `assign()` for the server SDK |
| **SingleStore** | Set `SINGLESTORE_URL`, `pip install singlestoredb` | Create a Helios workspace; show a SQL query of the audit table in the demo. Stretch: vector search over past experiments |
| **Cognee** | Set `COGNEE_ENABLED=1`, `pip install cognee` | Confirm the add → cognify → search API in `integrations/memory.py` |
| **Arcee** | Hook in `llm._arcee()` | Route the fast tier to Arcee; the economics panel already shows the savings |
| **Persona** | Not started | Verify the approver's identity before **Approve launch** (`agent.approve`) |
| **Airbyte** | Not started | Bring in Stripe/CRM data so decisions use real revenue |
| **Senso** | Not started | Brand guidelines and product facts as trusted context for variant copy |

## Team split

| Person | Owns |
|---|---|
| A | Acme page + simulator realism, demo polish |
| B | Agent prompts (`agent.py`), LLM router, Arcee |
| C | Statsig + Amplitude + SingleStore + Cognee wiring |
| D | Dashboard UI, Persona approval, **record video by 3:45 PM**, submission |

## Submission (deadline 4:30 PM PT)

GitHub repo, demo video link, what we built and the tools used, team names and emails, plus a screenshot.
