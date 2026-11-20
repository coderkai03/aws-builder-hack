"""Experiment memory: "what we already know about our users".

Cognee when COGNEE_ENABLED=1 (knowledge graph over every past experiment result), otherwise a
local table. The agent reads memory before proposing hypotheses so it never re-runs a losing test.
TODO(teammate C): confirm the cognee API (add -> cognify -> search) at https://docs.cognee.ai/
"""
import asyncio

from .. import config
from ..store import store


def remember(text: str):
    store.remember(text)
    if config.COGNEE_ENABLED:
        try:
            import cognee

            async def _go():
                await cognee.add(text, dataset_name="northstar")
                await cognee.cognify(["northstar"])

            asyncio.run(_go())
        except Exception as e:
            store.audit("memory", f"Cognee write failed, kept local copy: {e}", actor="system")


def recall(query: str) -> list[str]:
    if config.COGNEE_ENABLED:
        try:
            import cognee

            results = asyncio.run(cognee.search(query_text=query))
            return [str(r) for r in results][:10]
        except Exception as e:
            store.audit("memory", f"Cognee search failed, using local memory: {e}", actor="system")
    return store.memories(10)
