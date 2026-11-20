"""Experiment memory: "what we already know about our users".

Cognee Cloud when COGNEE_API_KEY and COGNEE_BASE_URL are set: every learning is added to a Cognee
dataset and "cognified" into a knowledge graph; before proposing hypotheses the agent asks the graph
what past experiments taught us. A local table always keeps a copy, so the loop never blocks on it.

Cognee Cloud HTTP API (docs.cognee.ai/cognee-cloud/http-api): X-Api-Key auth,
  POST /api/v1/add      multipart: datasetName, raw_data
  POST /api/v1/cognify  {"datasets": [...]}
  POST /api/v1/search   {"query", "search_type", "datasets"}
"""
import json
import threading

import httpx

from .. import config
from ..store import store

DATASET = "northstar_experiments"


def _headers() -> dict:
    return {"X-Api-Key": config.COGNEE_API_KEY}


def _url(path: str) -> str:
    return config.COGNEE_BASE_URL.rstrip("/") + path


def _push(texts: list[str]):
    try:
        r = httpx.post(_url("/api/v1/add"), headers=_headers(), timeout=60,
                       data={"datasetName": DATASET, "raw_data": texts})
        r.raise_for_status()
        r = httpx.post(_url("/api/v1/cognify"), headers=_headers(), timeout=300,
                       json={"datasets": [DATASET]})
        r.raise_for_status()
        store.audit("memory", f"Cognee: added {len(texts)} learnings and rebuilt the knowledge graph",
                    {"dataset": DATASET}, actor="system")
    except Exception as e:
        store.audit("memory", f"Cognee write failed, kept local copy: {str(e)[:200]}", actor="system")


def remember_many(texts: list[str]):
    for t in texts:
        store.remember(t)
    if config.COGNEE_ENABLED and texts:
        # cognify can take a while; never block the experiment loop on it
        threading.Thread(target=_push, args=(texts,), daemon=True).start()


def remember(text: str):
    remember_many([text])


def recall(query: str) -> list[str]:
    local = store.memories(10)
    if not config.COGNEE_ENABLED:
        return local
    try:
        r = httpx.post(_url("/api/v1/search"), headers=_headers(), timeout=45,
                       json={"query": query, "search_type": "GRAPH_COMPLETION", "datasets": [DATASET]})
        if r.status_code == 404:  # dataset/graph not created yet
            return local
        r.raise_for_status()
        data = r.json()
        items = data if isinstance(data, list) else [data]
        answers = []
        for it in items:
            if isinstance(it, dict):
                val = it.get("search_result", it.get("result", it))
                answers.extend(val if isinstance(val, list) else [val])
            else:
                answers.append(it)
        answers = [a if isinstance(a, str) else json.dumps(a, default=str) for a in answers if a]
        store.audit("memory", f"Cognee graph recall: {len(answers)} results", {"query": query, "results": answers[:5]},
                    actor="system")
        return (answers[:5] + local)[:10]
    except Exception as e:
        store.audit("memory", f"Cognee search failed, using local memory: {str(e)[:200]}", actor="system")
        return local
