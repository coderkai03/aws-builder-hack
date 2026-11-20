"""Amplitude: the agent's "eyes" for the humans watching. Every simulated product event is sent
through the HTTP V2 ingestion API, so the Amplitude funnel chart fills up live during the demo.

The agent's real-time stats run on the SingleStore mirror (Amplitude ingestion can lag by minutes).
TODO(teammate C): add a Dashboard REST API funnel query in `funnel_snapshot()` so the initial
diagnosis is read straight out of Amplitude. https://amplitude.com/docs/apis/analytics/dashboard-rest
"""
import threading

import httpx

from .. import config

URL = "https://api2.amplitude.com/2/httpapi"
sent = {"events": 0, "errors": 0}


def _send(events: list[dict]):
    payload = {
        "api_key": config.AMPLITUDE_API_KEY,
        "events": [{
            "user_id": e["user_id"],
            "event_type": e["event"],
            "time": int(e["ts"] * 1000),
            "platform": e["device"],
            "event_properties": {"experiment_id": e["experiment_id"], "variant": e["variant"],
                                 "value": e["value"]},
            "user_properties": {f"ns_{e['experiment_id'] or 'baseline'}": e["variant"]},
            **({"revenue": e["value"]} if e["event"] == "purchase" else {}),
        } for e in events],
    }
    try:
        r = httpx.post(URL, json=payload, timeout=15)
        if r.status_code == 200:
            sent["events"] += len(events)
        else:
            sent["errors"] += 1
    except Exception:
        sent["errors"] += 1


def track(events: list[dict]):
    if not config.AMPLITUDE_API_KEY or not events:
        return
    for i in range(0, len(events), 1000):  # HTTP V2 batch limit headroom
        threading.Thread(target=_send, args=(events[i:i + 1000],), daemon=True).start()


def funnel_snapshot() -> dict | None:
    return None  # see TODO above
