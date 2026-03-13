"""FastAPI integration example for CacheFlight.

Demonstrates how to use CacheFlight to deduplicate concurrent requests
in a FastAPI application.

Run:
    pip install fastapi uvicorn cacheflight
    uvicorn examples.fastapi_example:app --reload

Test:
    # Fire 50 concurrent requests — only 1 DB call will execute
    for i in $(seq 1 50); do curl -s http://localhost:8000/user/42 & done; wait
"""

from __future__ import annotations

import asyncio
import logging

from cacheflight import CacheFlight, CacheFlightEvent, CacheFlightOptions

try:
    from fastapi import FastAPI, HTTPException
except ImportError:
    raise ImportError("Install fastapi to run this example: pip install fastapi uvicorn")

logger = logging.getLogger("cacheflight.example")


# ── Observability hook ────────────────────────────────────────────────────────

def on_event(event: CacheFlightEvent) -> None:
    logger.info("cacheflight event=%s key=%s", event.type, event.key)


# ── CacheFlight instance ─────────────────────────────────────────────────────

flight = CacheFlight(CacheFlightOptions(
    max_keys=10_000,
    default_timeout_ms=5_000,
    on_event=on_event,
))

app = FastAPI(title="CacheFlight + FastAPI Example")


# ── Simulated database ───────────────────────────────────────────────────────

_call_count = 0


async def fake_db_get_user(user_id: str) -> dict[str, object]:
    """Simulate a slow database lookup."""
    global _call_count
    _call_count += 1
    await asyncio.sleep(0.2)  # 200ms simulated latency
    return {"id": user_id, "name": f"User {user_id}", "db_calls_total": _call_count}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/user/{user_id}")
async def get_user(user_id: str) -> dict[str, object]:
    """Fetch a user — concurrent requests for the same ID are deduplicated."""
    key = f"user:{user_id}"
    try:
        return await flight.run(key, lambda: fake_db_get_user(user_id))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/stats")
async def stats() -> dict[str, object]:
    """Return CacheFlight diagnostics."""
    return {
        "in_flight_keys": flight.size,
        "total_db_calls": _call_count,
    }

