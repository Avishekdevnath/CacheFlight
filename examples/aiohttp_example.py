"""aiohttp integration example for CacheFlight.

Run:
    pip install aiohttp cacheflight
    python examples/aiohttp_example.py
"""

from __future__ import annotations

import asyncio
import logging

from cacheflight import CacheFlight, CacheFlightOptions

try:
    from aiohttp import web
except ImportError:
    raise ImportError("Install aiohttp to run this example: pip install aiohttp")

logger = logging.getLogger("cacheflight.example")

flight = CacheFlight(CacheFlightOptions(
    max_keys=10_000,
    default_timeout_ms=5_000,
    on_event=lambda e: logger.info("event=%s key=%s", e.type, e.key),
))

_call_count = 0


async def fake_db_get_user(user_id: str) -> dict[str, object]:
    global _call_count
    _call_count += 1
    await asyncio.sleep(0.2)
    return {"id": user_id, "name": f"User {user_id}", "db_calls_total": _call_count}


async def handle_user(request: web.Request) -> web.Response:
    user_id = request.match_info["user_id"]
    key = f"user:{user_id}"
    result = await flight.run(key, lambda: fake_db_get_user(user_id))
    return web.json_response(result)


app = web.Application()
app.router.add_get("/user/{user_id}", handle_user)

if __name__ == "__main__":
    web.run_app(app, port=8080)
