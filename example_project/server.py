"""Weather Dashboard API — CacheFlight Example Project.

A FastAPI server that simulates fetching weather data from a slow external API.
CacheFlight deduplicates concurrent requests so only ONE actual fetch happens
per city, no matter how many clients ask at the same time.

Run:
    cd example_project
    pip install -r requirements.txt
    pip install -e ..          # install cacheflight from local source
    uvicorn server:app --reload --port 8000

Then open http://localhost:8000/docs to explore the API,
or run `python load_test.py` to see deduplication in action.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass

from cacheflight import CacheFlight, CacheFlightEvent, CacheFlightOptions

try:
    from fastapi import FastAPI, HTTPException
except ImportError:
    raise ImportError("Install FastAPI first: pip install fastapi uvicorn")


# ── Metrics tracker ──────────────────────────────────────────────────────────

@dataclass
class Metrics:
    api_calls: int = 0          # actual external API calls made
    requests_served: int = 0    # total HTTP requests served
    deduplicated: int = 0       # requests that piggy-backed on existing calls
    total_latency_saved_ms: float = 0.0


metrics = Metrics()
SIMULATED_LATENCY_MS = 500  # pretend the external API takes 500ms


# ── CacheFlight setup with event logging ─────────────────────────────────────

def on_event(event: CacheFlightEvent) -> None:
    if event.type == "hit":
        metrics.deduplicated += 1
        metrics.total_latency_saved_ms += SIMULATED_LATENCY_MS
        print(f"  [HIT]  key={event.key} — reusing in-flight result (saved {SIMULATED_LATENCY_MS}ms)")
    elif event.type == "miss":
        print(f"  [MISS] key={event.key} — starting new fetch")
    elif event.type == "task_resolved":
        print(f"  [DONE] key={event.key} — completed in {event.duration_ms:.0f}ms")


flight = CacheFlight(CacheFlightOptions(
    max_keys=1_000,
    default_timeout_ms=10_000,
    on_event=on_event,
))

app = FastAPI(
    title="Weather Dashboard (CacheFlight Demo)",
    description="Demonstrates request deduplication under concurrent load.",
)


# ── Simulated external weather API ───────────────────────────────────────────

WEATHER_DATA: dict[str, dict[str, object]] = {
    "london":    {"city": "London",    "temp_c": 12, "condition": "Cloudy"},
    "tokyo":     {"city": "Tokyo",     "temp_c": 22, "condition": "Sunny"},
    "new-york":  {"city": "New York",  "temp_c": 18, "condition": "Partly Cloudy"},
    "paris":     {"city": "Paris",     "temp_c": 15, "condition": "Rainy"},
    "sydney":    {"city": "Sydney",    "temp_c": 26, "condition": "Clear"},
    "mumbai":    {"city": "Mumbai",    "temp_c": 33, "condition": "Humid"},
}


async def fetch_weather_from_api(city: str) -> dict[str, object]:
    """Simulate a slow external API call (500ms latency)."""
    metrics.api_calls += 1
    call_num = metrics.api_calls
    print(f"  >>> External API call #{call_num} for '{city}' (takes {SIMULATED_LATENCY_MS}ms)...")

    await asyncio.sleep(SIMULATED_LATENCY_MS / 1000)

    base = WEATHER_DATA.get(city)
    if base is None:
        raise ValueError(f"Unknown city: {city}")

    return {
        **base,
        "temp_c": base["temp_c"] + random.randint(-2, 2),  # slight variation
        "fetched_at": time.strftime("%H:%M:%S"),
        "api_call_number": call_num,
    }


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/weather/{city}")
async def get_weather(city: str) -> dict[str, object]:
    """Fetch weather for a city. Concurrent requests are deduplicated."""
    city = city.lower()
    if city not in WEATHER_DATA:
        raise HTTPException(404, f"Unknown city. Try: {', '.join(WEATHER_DATA)}")

    metrics.requests_served += 1
    key = f"weather:{city}"
    return await flight.run(key, lambda: fetch_weather_from_api(city))


@app.get("/metrics")
async def get_metrics() -> dict[str, object]:
    """Show how effective deduplication has been."""
    return {
        "total_requests_served": metrics.requests_served,
        "actual_api_calls": metrics.api_calls,
        "deduplicated_requests": metrics.deduplicated,
        "estimated_latency_saved_ms": metrics.total_latency_saved_ms,
        "current_in_flight": flight.size,
    }


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "message": "Weather Dashboard — CacheFlight Demo",
        "try": "GET /weather/london, GET /weather/tokyo, GET /metrics",
        "docs": "GET /docs",
    }
